from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.preprocessing import LabelEncoder

RAW_DIR       = Path(__file__).resolve().parent / "raw"
PROCESSED_DIR = Path(__file__).resolve().parent / "processed"
PROCESSED_DIR.mkdir(exist_ok=True)

YEARS     = [2023, 2024, 2025]
TRAIN_END = 202506
VAL_END   = 202509

RANK_FILL = 5001 # 인기 목록에 없는 경우 대체값

SEASON_MAP = {
    1: "winter", 2: "winter",  3: "spring",
    4: "spring",  5: "spring",  6: "summer",
    7: "summer",  8: "summer",  9: "fall",
    10: "fall",  11: "fall",   12: "winter",
}
VACATION_MONTHS       = {1, 2, 7, 8}
SEMESTER_START_MONTHS = {3, 9}


# YYYYMM 유틸

def prev_yyyymm(yyyymm: int) -> int:
    y, m = divmod(int(yyyymm), 100)
    return (y - 1) * 100 + 12 if m == 1 else yyyymm - 1


def next_yyyymm(yyyymm: int) -> int:
    y, m = divmod(int(yyyymm), 100)
    return (y + 1) * 100 + 1 if m == 12 else yyyymm + 1


def month_of(yyyymm: int) -> int:
    return int(yyyymm) % 100


def split_label(yyyymm: int) -> str:
    yyyymm = int(yyyymm)
    if yyyymm <= TRAIN_END:
        return "train"
    elif yyyymm <= VAL_END:
        return "val"
    return "test"


# 데이터 로더

def load_popular_books(
    years: list[int],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    frames: list[pd.DataFrame] = []
    for year in years:
        fpath = RAW_DIR / f"popular_books_{year}.csv"
        if not fpath.exists():
            print(f"[load] 파일 없음, 스킵: {fpath.name}")
            continue
        df = pd.read_csv(fpath, dtype={"isbn13": "string"})
        df["period_start"] = pd.to_datetime(df["period_start"])
        df["yyyymm"]       = df["period_start"].dt.year * 100 + df["period_start"].dt.month
        df["loan_count"]   = pd.to_numeric(df["loan_count"], errors="coerce")
        df["ranking"]      = pd.to_numeric(df["ranking"],    errors="coerce")
        df = df.dropna(subset=["isbn13", "loan_count"])
        df = df[df["isbn13"].str.match(r"^\d{13}$", na=False)]
        df = df.drop_duplicates(subset=["isbn13", "yyyymm"])
        frames.append(df)

    if not frames:
        raise FileNotFoundError("popular_books_*.csv 파일이 하나도 없습니다.")

    all_df = pd.concat(frames, ignore_index=True).drop_duplicates(subset=["isbn13", "yyyymm"])

    # 도서 메타 (가장 최근 yyyymm 기준 1행)
    meta = (
        all_df.sort_values("yyyymm")
        .drop_duplicates(subset="isbn13", keep="last")
        [["isbn13", "bookname", "publication_year", "class_no", "publisher", "vol"]]
        .copy()
    )
    meta["bookname_length"]  = meta["bookname"].str.len().fillna(0).astype(int)
    meta["publication_year"] = pd.to_numeric(meta["publication_year"], errors="coerce")
    meta["book_age"]         = (max(years) - meta["publication_year"]).clip(0, 200)
    class_no_str = meta["class_no"].astype("string").fillna("").str.strip()
    meta["kdc_class"]     = class_no_str.str[:1].replace("", "unknown")
    meta["kdc_class_mid"] = class_no_str.str[:2].replace("", "unknown")

    # 출판사별 인기 도서 등재 빈도 (관심도 프록시)
    pub_counts = all_df.groupby("isbn13").first()["publisher"].value_counts()
    meta["publisher_pop_count"] = (
        meta["publisher"].map(pub_counts).fillna(1).astype(int)
    )

    # 시리즈 피처 기반 컬럼
    # 상/중/하 -> 1/2/3 매핑 먼저 적용
    KO_VOL_MAP = {"상": 1, "중": 2, "하": 3, "上": 1, "下": 3}
    vol_mapped = meta["vol"].map(KO_VOL_MAP)
    vol_numeric = vol_mapped.fillna(pd.to_numeric(meta["vol"], errors="coerce")).fillna(0)
    # 연도처럼 보이는 값(1900~2099) 제거 (예: "트렌드코리아 2025"의 vol=2025)
    is_year_like = (vol_numeric >= 1900) & (vol_numeric <= 2099)
    meta["vol_num"] = vol_numeric.where(~is_year_like, 0).astype(int)
    meta["has_vol"] = (meta["vol_num"] > 0).astype(int)

    loan_matrix = all_df.pivot(index="isbn13", columns="yyyymm", values="loan_count")
    rank_matrix = all_df.pivot(index="isbn13", columns="yyyymm", values="ranking")

    return meta, loan_matrix, rank_matrix


def load_usage_books() -> pd.DataFrame:
    fpath = RAW_DIR / "usage_books_raw.csv"
    if not fpath.exists():
        return pd.DataFrame(columns=["isbn13", "loanCnt_total"])
    df = pd.read_csv(fpath, dtype={"isbn13": "string"})
    df["loanCnt_total"] = pd.to_numeric(df["loanCnt_total"], errors="coerce").fillna(0)
    return df[["isbn13", "loanCnt_total"]].copy()


def load_loan_groups() -> pd.DataFrame:
    fpath = RAW_DIR / "loan_groups_raw.csv"
    if not fpath.exists():
        return pd.DataFrame(columns=["isbn13", "main_age_group", "female_ratio"])
    df = pd.read_csv(fpath, dtype={"isbn13": "string"})
    records = []
    for isbn, grp in df.groupby("isbn13"):
        top_idx    = grp["loanCnt"].idxmax()
        main_age   = grp.loc[top_idx, "age"]
        female_cnt = float(grp.loc[grp["gender"] == "여성", "loanCnt"].sum())
        total_cnt  = float(grp["loanCnt"].sum())
        records.append({
            "isbn13":         isbn,
            "main_age_group": main_age,
            "female_ratio":   round(female_cnt / total_cnt, 4) if total_cnt > 0 else 0.5,
        })
    return pd.DataFrame(records)


def load_hot_trends(years: list[int]) -> pd.DataFrame:
    """연도별 hot_trends CSV 로드. result_yyyymm 컬럼 추가."""
    frames: list[pd.DataFrame] = []
    for year in years:
        fpath = RAW_DIR / f"hot_trends_{year}.csv"
        if not fpath.exists():
            print(f"[load] 파일 없음, 스킵: {fpath.name}")
            continue
        df = pd.read_csv(fpath, dtype={"isbn13": "string"})
        frames.append(df)

    if not frames:
        return pd.DataFrame(columns=["isbn13", "result_yyyymm", "difference", "baseWeekRank"])

    hot = pd.concat(frames, ignore_index=True)
    hot = hot.dropna(subset=["isbn13"])
    hot = hot[hot["isbn13"].str.match(r"^\d{13}$", na=False)]
    rd = pd.to_datetime(hot["result_date"])
    hot["result_yyyymm"] = (rd.dt.year * 100 + rd.dt.month).astype(int)
    hot["difference"]    = pd.to_numeric(hot["difference"],    errors="coerce").fillna(0)
    hot["baseWeekRank"]  = pd.to_numeric(hot["baseWeekRank"],  errors="coerce")
    return hot[["isbn13", "result_yyyymm", "difference", "baseWeekRank"]].copy()


def build_hot_monthly(hot_df: pd.DataFrame) -> pd.DataFrame:
    """hot_trends 일별 데이터를 월별로 집계."""
    if hot_df.empty:
        return pd.DataFrame(columns=[
            "isbn13", "result_yyyymm",
            "ht_count", "ht_gain_max", "ht_rank_best",
        ])
    agg = (
        hot_df
        .groupby(["isbn13", "result_yyyymm"])
        .agg(
            ht_count    =("difference",   "count"),
            ht_gain_max =("difference",   "max"),
            ht_rank_best=("baseWeekRank", "min"),
        )
        .reset_index()
    )
    return agg


def load_co_loan_books() -> pd.DataFrame:
    fpath = RAW_DIR / "co_loan_books_raw.csv"
    if not fpath.exists():
        return pd.DataFrame(columns=["isbn13", "co_loan_count"])
    df = pd.read_csv(fpath, dtype={"isbn13": "string"})
    return df.groupby("isbn13").size().reset_index(name="co_loan_count")


def load_loan_history_ranking() -> pd.DataFrame:
    # [PoC 허용] loan_history_raw 는 API 호출 시점 기준 최근 12개월치이므로
    # target_yyyymm 이후 순위 정보가 포함될 수 있음.
    # 정식 구현 시 per-sample 기준으로 target 이전 월만 필터링 필요.
    fpath = RAW_DIR / "loan_history_raw.csv"
    if not fpath.exists():
        return pd.DataFrame(columns=["isbn13", "ranking_trend", "ranking_mean"])
    df = pd.read_csv(fpath, dtype={"isbn13": "string"})
    records = []
    for isbn, grp in df.groupby("isbn13"):
        ranks = pd.to_numeric(grp["monthly_ranking"], errors="coerce").dropna().tolist()
        slope = (
            round(float(np.polyfit(range(len(ranks)), ranks, 1)[0]), 4)
            if len(ranks) >= 2
            else 0.0
        )
        records.append({
            "isbn13":        isbn,
            "ranking_trend": slope,
            "ranking_mean":  round(float(np.mean(ranks)), 2) if ranks else 0.0,
        })
    return pd.DataFrame(records)


# 슬라이딩 윈도우 샘플 생성

def build_windows(
    loan_matrix: pd.DataFrame,
    rank_matrix: pd.DataFrame,
    window_size: int,
) -> pd.DataFrame:
    """YYYYMM 기반 슬라이딩 윈도우 샘플 생성.

    연도 경계를 포함한 연속 구간만 유효 샘플로 처리.
    각 샘플: feat_months(=window_size 개월) -> target_yyyymm(다음 달)
    """
    all_months  = sorted(int(c) for c in loan_matrix.columns)
    rank_months = set(rank_matrix.columns)
    rows: list[dict] = []

    for isbn, loan_row in loan_matrix.iterrows():
        valid_months = [m for m in all_months if not pd.isna(loan_row[m])]

        for i in range(len(valid_months) - window_size):
            seq = valid_months[i : i + window_size + 1]
            # 연속 월 여부 확인 (연도 경계 포함)
            if any(next_yyyymm(seq[k]) != seq[k + 1] for k in range(len(seq) - 1)):
                continue

            feat_months = seq[:window_size]
            tgt_yyyymm  = seq[window_size]
            vals = [float(loan_row[m]) for m in feat_months]
            x    = np.arange(len(vals), dtype=float)
            mean_v = float(np.mean(vals))
            std_v  = float(np.std(vals))

            sample: dict = {"isbn13": isbn, "target_yyyymm": tgt_yyyymm}

            # 대출 lag 피처 (lag1 = 가장 최근 달)
            for j, v in enumerate(reversed(vals)):
                sample[f"loan_lag{j + 1}"] = v

            # 이동평균 (가능한 경우만)
            loan_ma_3 = round(float(np.mean(vals[-3:])), 2) if len(vals) >= 3 else round(mean_v, 2)
            loan_ma_6 = round(float(np.mean(vals[-6:])), 2) if len(vals) >= 6 else round(mean_v, 2)

            # 직전월 대비 증가율
            if len(vals) >= 2 and vals[-2] > 0:
                loan_growth_1m = round((vals[-1] - vals[-2]) / vals[-2], 4)
            else:
                loan_growth_1m = 0.0

            sample.update({
                "loan_mean":         round(mean_v, 2),
                "loan_max":          float(max(vals)),
                "loan_min":          float(min(vals)),
                "loan_recent":       vals[-1],
                "loan_trend":        round(float(np.polyfit(x, vals, 1)[0]), 4),
                "loan_cv":           round(std_v / (mean_v + 1e-8), 4),
                "loan_recent_ratio": round(vals[-1] / (mean_v + 1e-8), 4),
                "loan_accel":        round(vals[-1] - vals[-2], 2) if window_size >= 2 else 0.0,
                "loan_ma_3":         loan_ma_3,
                "loan_ma_6":         loan_ma_6,
                "loan_growth_1m":    loan_growth_1m,
                "raw_loan_count":    float(loan_row[tgt_yyyymm]),
            })

            # 랭킹 lag 피처 (낮을수록 순위 높음)
            if isbn in rank_matrix.index:
                rank_row = rank_matrix.loc[isbn]
                for j, m in enumerate(reversed(feat_months)):
                    v = rank_row[m] if m in rank_months and not pd.isna(rank_row[m]) else RANK_FILL
                    sample[f"rank_lag{j + 1}"] = float(v)
            else:
                for j in range(window_size):
                    sample[f"rank_lag{j + 1}"] = float(RANK_FILL)

            rank_vals  = [sample[f"rank_lag{j + 1}"] for j in range(window_size)]
            rank_valid_with_idx = [
                (j, v) for j, v in enumerate(rank_vals) if v < RANK_FILL
            ]
            sample["rank_mean"]  = round(float(np.mean(rank_vals)), 2)
            sample["rank_trend"] = (
                round(float(np.polyfit(
                    [p[0] for p in rank_valid_with_idx],
                    [p[1] for p in rank_valid_with_idx],
                    1
                )[0]), 4)
                if len(rank_valid_with_idx) >= 2
                else 0.0
            )
            # 순위 변동폭 (안정성 지표)
            rank_only_vals = [p[1] for p in rank_valid_with_idx]
            sample["rank_std"] = (
                round(float(np.std(rank_only_vals)), 2)
                if len(rank_only_vals) >= 2
                else 0.0
            )

            rows.append(sample)

    return pd.DataFrame(rows)


# 핫트렌드 구조 피처

def compute_hot_features(
    windows_df: pd.DataFrame,
    hot_monthly: pd.DataFrame,
) -> pd.DataFrame:
    """핫트렌드 구조 피처. 누수 없음: result_yyyymm < target_yyyymm만 사용.

    lag1 피처:
      hot_trend_recency  — lag1 달에 핫트렌드 등장 여부
      rank_gain_lag1     — lag1 달의 순위 상승폭 (없으면 0)

    누적 이력 피처 (target 이전 전체):
      hot_trend_count_hist — 총 등장 횟수
      rank_gain_max_hist   — 최대 순위 상승폭
      ht_rank_best_hist    — 최고 순위 (최솟값)
    """
    base = windows_df[["isbn13", "target_yyyymm"]].copy()
    base["lag1_yyyymm"] = base["target_yyyymm"].apply(lambda t: prev_yyyymm(int(t)))

    if hot_monthly.empty:
        return base[["isbn13", "target_yyyymm"]].assign(
            hot_trend_recency=0,
            rank_gain_lag1=0.0,
            hot_trend_count_hist=0,
            rank_gain_max_hist=0.0,
            ht_rank_best_hist=float(RANK_FILL),
        )

    # lag1 합류
    lag1_feat = hot_monthly.rename(columns={
        "result_yyyymm": "lag1_yyyymm",
        "ht_gain_max":  "rank_gain_lag1",
    })[["isbn13", "lag1_yyyymm", "ht_count", "rank_gain_lag1"]]

    base = base.merge(lag1_feat, on=["isbn13", "lag1_yyyymm"], how="left")
    base["hot_trend_recency"] = base["ht_count"].notna().astype(int)
    base["rank_gain_lag1"]    = base["rank_gain_lag1"].fillna(0.0)

    # 전체 이력 집계 (target 이전)
    merged = (
        base[["isbn13", "target_yyyymm"]]
        .merge(hot_monthly, on="isbn13", how="left")
    )
    pre = merged[merged["result_yyyymm"] < merged["target_yyyymm"]]
    hist = (
        pre.groupby(["isbn13", "target_yyyymm"])
        .agg(
            hot_trend_count_hist=("ht_count",     "sum"),
            rank_gain_max_hist  =("ht_gain_max",  "max"),
            ht_rank_best_hist   =("ht_rank_best", "min"),
        )
        .reset_index()
    )

    result = base.merge(hist, on=["isbn13", "target_yyyymm"], how="left")
    result["hot_trend_count_hist"] = result["hot_trend_count_hist"].fillna(0).astype(int)
    result["rank_gain_max_hist"]   = result["rank_gain_max_hist"].fillna(0.0)
    result["ht_rank_best_hist"]    = result["ht_rank_best_hist"].fillna(float(RANK_FILL))

    return result[[
        "isbn13", "target_yyyymm",
        "hot_trend_recency", "rank_gain_lag1",
        "hot_trend_count_hist", "rank_gain_max_hist", "ht_rank_best_hist",
    ]]


def _rank_gain_for_target(
    windows_df: pd.DataFrame,
    hot_monthly: pd.DataFrame,
) -> pd.DataFrame:
    """타겟 구성 전용: target_yyyymm 당월 rank gain. 입력 피처 사용 금지."""
    if hot_monthly.empty:
        return windows_df[["isbn13", "target_yyyymm"]].assign(rank_gain_for_target=0.0)
    target_hot = hot_monthly.rename(columns={
        "result_yyyymm": "target_yyyymm",
        "ht_gain_max":  "rank_gain_for_target",
    })[["isbn13", "target_yyyymm", "rank_gain_for_target"]]
    return (
        windows_df[["isbn13", "target_yyyymm"]]
        .merge(target_hot, on=["isbn13", "target_yyyymm"], how="left")
        .assign(rank_gain_for_target=lambda d: d["rank_gain_for_target"].fillna(0.0))
    )


# 키워드 로더 (타겟 구성 전용 — 입력 피처 X에 포함되지 않음)

def load_keywords(years: list[int]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """도서 키워드 + 월별 키워드 로드. 타겟의 trend_score 계산에만 사용."""
    book_kw_path = RAW_DIR / "book_keywords_raw.csv"
    book_kw = (
        pd.read_csv(book_kw_path, dtype={"isbn13": "string"})
        if book_kw_path.exists()
        else pd.DataFrame(columns=["isbn13", "word", "weight"])
    )

    kw_frames: list[pd.DataFrame] = []
    for year in years:
        fpath = RAW_DIR / f"monthly_keywords_{year}.csv"
        if fpath.exists():
            kw_frames.append(pd.read_csv(fpath))
    monthly_kw = (
        pd.concat(kw_frames, ignore_index=True)
        if kw_frames
        else pd.DataFrame(columns=["month", "word", "weight"])
    )
    monthly_kw["yyyymm"] = monthly_kw["month"].str.replace("-", "").astype(int)
    return book_kw, monthly_kw


def build_isbn_kw_map(book_kw_df: pd.DataFrame) -> dict[str, dict[str, float]]:
    """{isbn13: {word: weight}} 도서 키워드 사전."""
    result: dict[str, dict[str, float]] = {}
    for isbn, grp in book_kw_df.groupby("isbn13"):
        result[isbn] = dict(zip(
            grp["word"].dropna().str.strip(),
            pd.to_numeric(grp["weight"], errors="coerce").fillna(0).tolist(),
        ))
    return result


def build_month_kw_map(monthly_kw_df: pd.DataFrame) -> dict[int, dict[str, float]]:
    """{yyyymm: {word: weight}} 월별 키워드 사전."""
    result: dict[int, dict[str, float]] = {}
    for yyyymm, grp in monthly_kw_df.groupby("yyyymm"):
        result[int(yyyymm)] = dict(zip(
            grp["word"].dropna().str.strip(),
            pd.to_numeric(grp["weight"], errors="coerce").fillna(0).tolist(),
        ))
    return result


def _trend_nlp_row(
    isbn: str,
    query_yyyymm: int,
    isbn_kw_map: dict[str, dict[str, float]],
    month_kw_map: dict[int, dict[str, float]],
) -> float:
    """도서 키워드 × 월별 키워드 유사도 (keyword_trend_similarity).

    타겟 구성 전용: query_yyyymm = target_yyyymm (ground truth, 누수 아님).
    반환값 0~1 스케일.
    """
    bw = isbn_kw_map.get(isbn, {})
    mw = month_kw_map.get(int(query_yyyymm), {})
    if not bw or not mw:
        return 0.0
    # 월별 키워드를 [0,1]로 정규화 → trend_score를 설계상 0~1에 바운딩
    max_mw = max(mw.values())
    mw_norm = {w: v / max_mw for w, v in mw.items()}
    overlap_scores = [bw[w] * mw_norm[w] for w in bw if w in mw_norm]
    total_bw = sum(bw.values())
    return round(sum(overlap_scores) / total_bw, 6) if total_bw > 0 else 0.0


# 시리즈 피처

def compute_series_features(
    meta: pd.DataFrame,
    loan_matrix: pd.DataFrame,
    windows_df: pd.DataFrame,
) -> pd.DataFrame:
    """시리즈 구조 피처 (merge 기반 벡터화).

    데이터4라이브러리 API에서 bookname = 시리즈 제목, vol = 권번호.
    같은 bookname 내 다른 vol을 가진 isbn들을 동일 시리즈로 간주.

    추가 컬럼:
      series_size            — 같은 시리즈(bookname) 내 isbn 수
      prev_vol_loan_lag1     — 이전 권(vol_num-1)의 lag1 대출 수
      series_total_loan_lag1 — 같은 시리즈 전체 lag1 대출 합계
    """
    series_meta = meta[meta["has_vol"] == 1][["isbn13", "bookname", "vol_num"]].copy()

    if series_meta.empty:
        windows_df = windows_df.copy()
        windows_df["series_size"]            = 1
        windows_df["prev_vol_loan_lag1"]     = 0.0
        windows_df["series_total_loan_lag1"] = 0.0
        return windows_df

    # 시리즈 크기
    series_size_map = (
        series_meta.groupby("bookname")["isbn13"]
        .nunique()
        .rename("series_size")
        .reset_index()
    )
    series_meta = series_meta.merge(series_size_map, on="bookname", how="left")
    series_meta["series_size"] = series_meta["series_size"].fillna(1).astype(int)

    # loan_matrix를 long 형태로 변환
    loan_long = (
        loan_matrix.stack()
        .reset_index()
        .rename(columns={"isbn13": "isbn13", "level_1": "yyyymm", 0: "loan_count"})
    )
    loan_long["yyyymm"] = loan_long["yyyymm"].astype(int)

    # windows_df 에 lag1_yyyymm 추가
    out = windows_df.copy()
    out["lag1_yyyymm"] = out["target_yyyymm"].apply(lambda t: prev_yyyymm(int(t)))

    # isbn → (bookname, vol_num, series_size) 매핑
    out = out.merge(
        series_meta[["isbn13", "bookname", "vol_num", "series_size"]],
        on="isbn13", how="left"
    )
    out["series_size"] = out["series_size"].fillna(1).astype(int)

    # 시리즈 전체 lag1 합계: 같은 bookname 의 모든 isbn 의 lag1 대출 합산
    series_loan = (
        series_meta[["isbn13", "bookname"]]
        .merge(loan_long, on="isbn13", how="left")
    )
    series_loan = series_loan.rename(columns={"yyyymm": "lag1_yyyymm", "loan_count": "series_loan"})
    series_total = (
        series_loan.groupby(["bookname", "lag1_yyyymm"])["series_loan"]
        .sum()
        .reset_index()
        .rename(columns={"series_loan": "series_total_loan_lag1"})
    )
    out = out.merge(series_total, on=["bookname", "lag1_yyyymm"], how="left")
    out["series_total_loan_lag1"] = out["series_total_loan_lag1"].fillna(0.0)

    # 이전 권(vol_num - 1) lag1 대출
    prev_vol = series_meta[["isbn13", "bookname", "vol_num"]].copy()
    prev_vol["vol_num"] = prev_vol["vol_num"] + 1  # 다음 권이 이전 권을 참조
    prev_vol = prev_vol.rename(columns={"isbn13": "prev_isbn13", "vol_num": "vol_num"})
    out = out.merge(
        prev_vol[["bookname", "vol_num", "prev_isbn13"]],
        on=["bookname", "vol_num"], how="left"
    )
    prev_loan = loan_long.rename(columns={"isbn13": "prev_isbn13", "loan_count": "prev_vol_loan_lag1"})
    out = out.merge(
        prev_loan[["prev_isbn13", "yyyymm", "prev_vol_loan_lag1"]].rename(columns={"yyyymm": "lag1_yyyymm"}),
        on=["prev_isbn13", "lag1_yyyymm"], how="left"
    )
    out["prev_vol_loan_lag1"] = out["prev_vol_loan_lag1"].fillna(0.0)

    # 불필요 임시 컬럼 제거
    drop_cols = ["bookname", "vol_num", "prev_isbn13", "lag1_yyyymm"]
    out = out.drop(columns=[c for c in drop_cols if c in out.columns])

    return out


# DemandScore 타겟

def compute_demand_score(
    windows_df: pd.DataFrame,
    hot_monthly: pd.DataFrame,
    isbn_kw_map: dict[str, dict[str, float]],
    month_kw_map: dict[int, dict[str, float]],
) -> pd.DataFrame:
    """DemandScore = 0.5 * norm_loan + 0.3 * norm_gain + 0.2 * trend_score.

    원래 공식 그대로 유지. train 집합 통계로 min-max 정규화.

    - norm_loan  : raw_loan_count 정규화
    - norm_gain  : target_yyyymm 당월 hotTrend rank gain 정규화
    - trend_score: keyword_trend_similarity (0~1) — ground truth label, 누수 아님
    rank_gain_for_target, trend_score_target 모두 out_cols 에서 제외.
    """
    df = windows_df.copy()

    # rank gain (target 월 내, 타겟 구성 전용)
    rg = _rank_gain_for_target(df, hot_monthly)
    df = df.merge(rg, on=["isbn13", "target_yyyymm"], how="left")
    df["rank_gain_for_target"] = df["rank_gain_for_target"].fillna(0.0)

    # trend score (target 월 키워드 유사도, 타겟 구성 전용)
    print("[process] Computing trend_score for DemandScore target ...")
    df["trend_score_target"] = df.apply(
        lambda r: _trend_nlp_row(
            r["isbn13"], int(r["target_yyyymm"]), isbn_kw_map, month_kw_map
        ),
        axis=1,
    )

    df["split"] = df["target_yyyymm"].apply(split_label)
    train_mask = df["split"] == "train"

    def _minmax(s: pd.Series) -> pd.Series:
        mn = s[train_mask].min()
        mx = s[train_mask].max()
        return (s - mn) / (mx - mn + 1e-8)

    norm_loan  = _minmax(df["raw_loan_count"])
    norm_gain  = _minmax(df["rank_gain_for_target"])
    norm_trend = df["trend_score_target"]   # 이미 0~1 비율값, 정규화 불필요
    df["aux_target_log1p"] = np.log1p(df["raw_loan_count"])
    df["target"] = (0.5 * norm_loan + 0.3 * norm_gain + 0.2 * norm_trend).round(6)
    return df


# 인코더/피처 정보 저장

def save_feature_info(
    le_kdc: LabelEncoder,
    le_kdc_mid: LabelEncoder,
    le_age: LabelEncoder,
    le_season: LabelEncoder,
    window_size: int,
    norm_stats: dict,
    years: list[int] | None = None,
) -> None:
    def _mapping(le: LabelEncoder) -> dict:
        return dict(zip(le.classes_.tolist(), le.transform(le.classes_).tolist()))

    info = {
        "version": "v4",
        "description": "Structural features only (no NLP)",
        "years": years if years is not None else YEARS,
        "window_size": window_size,
        "split_boundaries": {"train_end": TRAIN_END, "val_end": VAL_END},
        "kdc_class":      _mapping(le_kdc),
        "kdc_class_mid":  _mapping(le_kdc_mid),
        "main_age_group": _mapping(le_age),
        "season":         _mapping(le_season),
        "demand_score_weights": {"norm_loan": 0.5, "norm_gain": 0.3, "trend_score": 0.2},
        "demand_score_norm_stats": norm_stats,
    }
    path = PROCESSED_DIR / "feature_info.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(info, f, ensure_ascii=False, indent=2)
    print(f"[process] Feature info → {path}")

def main(years: list[int] | None = None, window_size: int = 6) -> None:
    active_years = years if years else YEARS

    print(f"[process] v4 | years={active_years}  window_size={window_size}")

    # 1. 로드
    book_meta, loan_matrix, rank_matrix = load_popular_books(active_years)
    usage_books = load_usage_books()
    loan_groups = load_loan_groups()
    hot_df      = load_hot_trends(active_years)
    co_loan     = load_co_loan_books()
    loan_hist   = load_loan_history_ranking()
    hot_monthly = build_hot_monthly(hot_df)

    # 키워드 맵 (타겟 trend_score 계산 전용)
    book_kw, monthly_kw = load_keywords(active_years)
    isbn_kw_map  = build_isbn_kw_map(book_kw)
    month_kw_map = build_month_kw_map(monthly_kw)

    print(
        f"[process] ISBNs={len(book_meta):,}  "
        f"loan_matrix={loan_matrix.shape}  "
        f"hot_monthly={len(hot_monthly):,}  "
        f"isbn_kw={len(isbn_kw_map):,}  month_kw={len(month_kw_map):,}"
    )

    # 2. 슬라이딩 윈도우
    windows = build_windows(loan_matrix, rank_matrix, window_size)
    print(f"[process] Window samples: {len(windows):,}")

    # 3. DemandScore 타겟 + split
    windows = compute_demand_score(windows, hot_monthly, isbn_kw_map, month_kw_map)
    print(f"[process] Split: {windows['split'].value_counts().to_dict()}")

    # 4. 핫트렌드 구조 피처
    print("[process] Computing hot trend structural features ...")
    hot_feats = compute_hot_features(windows, hot_monthly)

    # 5. 시리즈 피처
    print("[process] Computing series features ...")
    windows = compute_series_features(book_meta, loan_matrix, windows)

    # 6. 시간 피처
    windows["month_num"]         = windows["target_yyyymm"].apply(month_of)
    windows["season"]            = windows["month_num"].map(SEASON_MAP)
    windows["is_vacation"]       = windows["month_num"].isin(VACATION_MONTHS).astype(int)
    windows["is_semester_start"] = windows["month_num"].isin(SEMESTER_START_MONTHS).astype(int)

    # 7. 피처 JOIN
    meta_cols = [
        "isbn13", "bookname_length", "book_age", "kdc_class", "kdc_class_mid",
        "vol_num", "has_vol", "publisher_pop_count",
    ]
    df = (
        windows
        .merge(book_meta[meta_cols],                       on="isbn13", how="left")
        .merge(usage_books,                                on="isbn13", how="left")
        .merge(loan_groups,                                on="isbn13", how="left")
        .merge(hot_feats,       on=["isbn13", "target_yyyymm"], how="left")
        .merge(co_loan,                                    on="isbn13", how="left")
        .merge(loan_hist,                                  on="isbn13", how="left")
    )

    # 8. 결측 처리
    fill_zero = [
        "loanCnt_total", "co_loan_count",
        "ranking_trend", "ranking_mean",
        "hot_trend_recency", "rank_gain_lag1",
        "hot_trend_count_hist", "rank_gain_max_hist",
        "prev_vol_loan_lag1", "series_total_loan_lag1",
    ]
    for col in fill_zero:
        if col in df.columns:
            df[col] = df[col].fillna(0)

    df["female_ratio"]      = df["female_ratio"].fillna(0.5)
    df["ht_rank_best_hist"] = df["ht_rank_best_hist"].fillna(float(RANK_FILL))
    df["book_age"]          = df["book_age"].fillna(df["book_age"].median())

    # 9. 범주형 인코딩 (train 카테고리로만 fit)
    le_kdc     = LabelEncoder()
    le_kdc_mid = LabelEncoder()
    le_age     = LabelEncoder()
    le_season  = LabelEncoder()

    train_df = df[df["split"] == "train"]
    le_kdc.fit(train_df["kdc_class"].fillna("unknown"))
    le_kdc_mid.fit(train_df["kdc_class_mid"].fillna("unknown"))
    le_age.fit(train_df["main_age_group"].fillna("unknown"))
    le_season.fit(train_df["season"])

    def _safe_enc(le: LabelEncoder, s: pd.Series) -> pd.Series:
        mapping = {cls: int(i) for i, cls in enumerate(le.classes_)}
        return s.map(lambda x: mapping.get(x, -1))

    df["kdc_class_enc"]      = _safe_enc(le_kdc,     df["kdc_class"].fillna("unknown"))
    df["kdc_class_mid_enc"]  = _safe_enc(le_kdc_mid, df["kdc_class_mid"].fillna("unknown"))
    df["main_age_group_enc"] = _safe_enc(le_age,     df["main_age_group"].fillna("unknown"))
    df["season_enc"]         = _safe_enc(le_season,  df["season"])

    # 10. 피처 정보 저장
    train_mask = df["split"] == "train"
    norm_stats = {
        "loan_min": float(df.loc[train_mask, "raw_loan_count"].min()),
        "loan_max": float(df.loc[train_mask, "raw_loan_count"].max()),
        "gain_min": float(df.loc[train_mask, "rank_gain_for_target"].min()),
        "gain_max": float(df.loc[train_mask, "rank_gain_for_target"].max()),
    }
    save_feature_info(le_kdc, le_kdc_mid, le_age, le_season, window_size, norm_stats, active_years)

    # 11. 출력 컬럼 선택
    lag_cols  = [f"loan_lag{i + 1}"  for i in range(window_size)]
    rank_cols = [f"rank_lag{i + 1}"  for i in range(window_size)]

    out_cols = (
        ["isbn13", "target_yyyymm", "split"]
        # 대출 시계열
        + lag_cols
        + ["loan_mean", "loan_max", "loan_min", "loan_recent",
           "loan_trend", "loan_cv", "loan_recent_ratio", "loan_accel",
           "loan_ma_3", "loan_ma_6", "loan_growth_1m"]
        # 랭킹
        + rank_cols
        + ["rank_mean", "rank_trend", "rank_std"]
        # 핫트렌드 구조
        + ["hot_trend_recency", "rank_gain_lag1",
           "hot_trend_count_hist", "rank_gain_max_hist", "ht_rank_best_hist"]
        # 도서 메타
        + ["bookname_length", "book_age", "kdc_class_enc", "kdc_class_mid_enc",
           "publisher_pop_count", "loanCnt_total", "co_loan_count"]
        # 시리즈
        + ["has_vol", "vol_num", "series_size",
           "prev_vol_loan_lag1", "series_total_loan_lag1"]
        # 독자 인구통계
        + ["female_ratio", "main_age_group_enc"]
        # 순위 이력
        + ["ranking_trend", "ranking_mean"]
        # 시간
        + ["month_num", "season_enc", "is_vacation", "is_semester_start"]
        # aux_target_log1p : log1p(raw_loan_count) — 타겟 보조 실험용, 피처(X)로 사용 금지
        # 타겟 (aux_ 컬럼은 모델 입력 X에 포함 금지)
        + ["aux_target_log1p", "target"]
    )
    out_cols = [c for c in out_cols if c in df.columns]
    out = df[out_cols].dropna(subset=["target"])

    path = PROCESSED_DIR / "features_book.csv"
    out.to_csv(path, index=False, encoding="utf-8-sig")

    n_feat = len(out_cols) - 3  # isbn13, target_yyyymm, split 제외
    print(f"\n[process] Saved -> {path}")
    print(f"[process] Shape : {len(out):,} rows × {n_feat} features + target")
    print(f"[process] Split : {out['split'].value_counts().to_dict()}")

    nan_report = out.isna().sum()
    nan_report = nan_report[nan_report > 0]
    if not nan_report.empty:
        print(f"[process] NaN cols:\n{nan_report}")
    else:
        print("[process] NaN: 없음")

    print(
        f"[process] Target | "
        f"mean={out['target'].mean():.4f}  "
        f"std={out['target'].std():.4f}  "
        f"min={out['target'].min():.4f}  "
        f"max={out['target'].max():.4f}"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Feature engineering v4 (structural-only)")
    parser.add_argument("--window-size", type=int, default=6,
                        help="슬라이딩 윈도우 크기 (기본: 6개월, 5rd 회의 권장)")
    parser.add_argument("--years", type=int, nargs="+", default=None,
                        help="수집 연도 (기본: 2023 2024 2025)")
    args = parser.parse_args()
    main(years=args.years, window_size=args.window_size)
