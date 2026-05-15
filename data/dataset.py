import argparse
import calendar
import os
import time
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = Path(__file__).resolve().parent / "raw"
BASE_URL = "https://data4library.kr/api"

RAW_DIR.mkdir(parents=True, exist_ok=True)
load_dotenv(PROJECT_ROOT / ".env")

API_KEY = os.getenv("LIBRARY_API_KEY")


_RATE_LIMIT_MSG = "500"  # 응답 에러 메시지 식별자


def get_json(endpoint: str, params: dict, retries: int = 5, sleep_sec: float = 1.0) -> dict:
    if not API_KEY:
        raise ValueError("LIBRARY_API_KEY가 없습니다. 프로젝트 .env 파일에 추가해주세요.")

    request_params = {
        **params,
        "authKey": API_KEY,
        "format": "json",
    }

    url = f"{BASE_URL}/{endpoint}"
    last_error = None

    for attempt in range(1, retries + 1):
        try:
            response = requests.get(url, params=request_params, timeout=20)
            response.raise_for_status()
            data = response.json()

            if "error" in data:
                raise RuntimeError(f"{endpoint} API 오류: {data['error']}")

            # 중첩된 response.error 감지 (rate limit 등)
            nested_error = data.get("response", {}).get("error")
            if nested_error:
                if _RATE_LIMIT_MSG in str(nested_error):
                    wait = min(60 * attempt, 300)
                    print(f"[rate-limit] {wait}초 대기 후 재시도 (attempt {attempt}/{retries})...")
                    time.sleep(wait)
                    continue
                raise RuntimeError(f"{endpoint} 응답 오류: {nested_error}")

            return data

        except (requests.RequestException, ValueError, RuntimeError) as exc:
            last_error = exc
            if attempt == retries:
                break
            time.sleep(sleep_sec * attempt)

    raise RuntimeError(f"API 요청 실패: {endpoint}, params={params}") from last_error


def normalize_list(value):
    if value is None:
        return []

    if isinstance(value, list):
        return value

    return [value]


def month_ranges(year: int):
    for month in range(1, 13):
        last_day = calendar.monthrange(year, month)[1]
        start = date(year, month, 1)
        end = date(year, month, last_day)

        yield start.isoformat(), end.isoformat(), f"{year}-{month:02d}"


def date_range(start: date, end: date, step_days: int = 1):
    current = start

    while current <= end:
        yield current
        current += timedelta(days=step_days)


def read_existing_csv(path: Path) -> pd.DataFrame:
    if path.exists():
        return pd.read_csv(path, dtype={"isbn13": "string"})

    return pd.DataFrame()


def append_csv(rows: list[dict], path: Path):
    if not rows:
        return

    df = pd.DataFrame(rows)
    write_header = not path.exists()

    df.to_csv(
        path,
        mode="a",
        header=write_header,
        index=False,
        encoding="utf-8-sig",
    )


def fetch_popular_books_month(start_dt: str, end_dt: str, page_size: int = 200) -> pd.DataFrame:
    rows = []

    for page_no in range(1, 26):
        data = get_json(
            "loanItemSrch",
            {
                "startDt": start_dt,
                "endDt": end_dt,
                "pageNo": page_no,
                "pageSize": page_size,
            },
        )

        response = data.get("response", {})
        docs = normalize_list(response.get("docs", []))

        if not docs:
            break

        for item in docs:
            doc = item.get("doc", item)

            rows.append(
                {
                    "period_start": start_dt,
                    "period_end": end_dt,
                    "ranking": doc.get("ranking"),
                    "bookname": doc.get("bookname"),
                    "authors": doc.get("authors"),
                    "publisher": doc.get("publisher"),
                    "publication_year": doc.get("publication_year"),
                    "isbn13": doc.get("isbn13"),
                    "addition_symbol": doc.get("addition_symbol"),
                    "vol": doc.get("vol"),
                    "class_no": doc.get("class_no"),
                    "class_nm": doc.get("class_nm"),
                    "loan_count": doc.get("loan_count"),
                    "bookImageURL": doc.get("bookImageURL"),
                    "bookDtlUrl": doc.get("bookDtlUrl"),
                }
            )

        print(f"[popular] {start_dt}~{end_dt} page={page_no} rows={len(rows)}")
        time.sleep(0.2)

    return pd.DataFrame(rows)


def fetch_popular_books_year(year: int) -> pd.DataFrame:
    out_path = RAW_DIR / f"popular_books_{year}.csv"
    frames = []

    for start_dt, end_dt, month in month_ranges(year):
        month_path = RAW_DIR / f"popular_books_{month}.csv"

        loaded = False
        if month_path.exists() and month_path.stat().st_size > 100:
            try:
                df = pd.read_csv(month_path, dtype={"isbn13": "string"})
                if not df.empty:
                    print(f"[popular] 기존 파일 사용: {month_path.name} rows={len(df)}")
                    loaded = True
            except Exception:
                print(f"[popular] 손상된 파일 재수집: {month_path.name}")
                month_path.unlink(missing_ok=True)

        if not loaded:
            df = fetch_popular_books_month(start_dt, end_dt)
            df.to_csv(month_path, index=False, encoding="utf-8-sig")

        frames.append(df)

    year_df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    year_df.to_csv(out_path, index=False, encoding="utf-8-sig")

    print(f"[popular] 저장 완료: {out_path} rows={len(year_df)}")

    return year_df


def fetch_monthly_keywords(month: str) -> pd.DataFrame:
    data = get_json("monthlyKeywords", {"month": month})
    response = data.get("response", {})
    rows = []

    for item in normalize_list(response.get("keywords", [])):
        keyword = item.get("keyword", item)

        rows.append(
            {
                "month": month,
                "word": keyword.get("word"),
                "weight": keyword.get("weight"),
            }
        )

    return pd.DataFrame(rows)


def fetch_monthly_keywords_year(year: int) -> pd.DataFrame:
    out_path = RAW_DIR / f"monthly_keywords_{year}.csv"
    frames = []

    for _, _, month in month_ranges(year):
        month_path = RAW_DIR / f"monthly_keywords_{month}.csv"

        loaded = False
        if month_path.exists() and month_path.stat().st_size > 10:
            try:
                df = pd.read_csv(month_path)
                if not df.empty:
                    print(f"[keywords] 기존 파일 사용: {month_path.name} rows={len(df)}")
                    loaded = True
            except Exception:
                print(f"[keywords] 손상된 파일 재수집: {month_path.name}")
                month_path.unlink(missing_ok=True)

        if not loaded:
            df = fetch_monthly_keywords(month)
            df.to_csv(month_path, index=False, encoding="utf-8-sig")
            print(f"[keywords] 저장 완료: {month_path.name} rows={len(df)}")
            time.sleep(0.2)

        frames.append(df)

    year_df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    year_df.to_csv(out_path, index=False, encoding="utf-8-sig")

    print(f"[keywords] 저장 완료: {out_path} rows={len(year_df)}")

    return year_df


def fetch_hot_trend(search_dt: str) -> pd.DataFrame:
    data = get_json("hotTrend", {"searchDt": search_dt})
    response = data.get("response", data)
    rows = []

    for result_item in normalize_list(response.get("results", [])):
        result = result_item.get("result", result_item)
        result_date = result.get("date")
        docs = normalize_list(result.get("docs", []))

        for item in docs:
            doc = item.get("doc", item)

            rows.append(
                {
                    "search_date": search_dt,
                    "result_date": result_date,
                    "no": doc.get("no"),
                    "difference": doc.get("difference"),
                    "baseWeekRank": doc.get("baseWeekRank"),
                    "pastWeekRank": doc.get("pastWeekRank"),
                    "bookname": doc.get("bookname"),
                    "authors": doc.get("authors"),
                    "publisher": doc.get("publisher"),
                    "publication_year": doc.get("publication_year"),
                    "isbn13": doc.get("isbn13"),
                    "addition_symbol": doc.get("addition_symbol"),
                    "vol": doc.get("vol"),
                    "class_no": doc.get("class_no"),
                    "class_nm": doc.get("class_nm"),
                    "bookImageURL": doc.get("bookImageURL"),
                    "bookDtlUrl": doc.get("bookDtlUrl"),
                }
            )

    return pd.DataFrame(rows)


def fetch_hot_trends_year(year: int, step_days: int = 3) -> pd.DataFrame:
    out_path = RAW_DIR / f"hot_trends_{year}.csv"
    frames = []

    start = date(year, 1, 1)
    end = date(year, 12, 31)

    for current in date_range(start, end, step_days=step_days):
        search_dt = current.isoformat()
        day_path = RAW_DIR / f"hot_trends_{search_dt}.csv"

        loaded = False
        if day_path.exists() and day_path.stat().st_size > 10:
            try:
                df = pd.read_csv(day_path, dtype={"isbn13": "string"})
                if not df.empty:
                    print(f"[hotTrend] 기존 파일 사용: {day_path.name} rows={len(df)}")
                    loaded = True
            except Exception:
                print(f"[hotTrend] 손상된 파일 재수집: {day_path.name}")
                day_path.unlink(missing_ok=True)

        if not loaded:
            df = fetch_hot_trend(search_dt)
            df.to_csv(day_path, index=False, encoding="utf-8-sig")
            print(f"[hotTrend] 저장 완료: {day_path.name} rows={len(df)}")
            time.sleep(0.2)

        frames.append(df)

    year_df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    if not year_df.empty:
        year_df = year_df.drop_duplicates(
            subset=["result_date", "isbn13", "baseWeekRank", "pastWeekRank"],
            keep="first",
        )

    year_df.to_csv(out_path, index=False, encoding="utf-8-sig")

    print(f"[hotTrend] 저장 완료: {out_path} rows={len(year_df)}")

    return year_df


def fetch_usage_analysis(isbn13: str) -> dict[str, list[dict]]:
    data = get_json("usageAnalysisList", {"isbn13": str(isbn13)})
    response = data.get("response", {})

    rows = {
        "books": [],
        "history": [],
        "keywords": [],
        "groups": [],
        "co_loan_books": [],
        "mania_rec_books": [],
        "reader_rec_books": [],
    }

    book = response.get("book", {})

    rows["books"].append(
        {
            "isbn13": isbn13,
            "bookname": book.get("bookname"),
            "authors": book.get("authors"),
            "publisher": book.get("publisher"),
            "publication_year": book.get("publication_year"),
            "addition_symbol": book.get("addition_symbol"),
            "vol": book.get("vol"),
            "class_no": book.get("class_no"),
            "class_nm": book.get("class_nm"),
            "loanCnt_total": book.get("loanCnt"),
            "description": book.get("description"),
            "bookImageURL": book.get("bookImageURL"),
        }
    )

    for item in normalize_list(response.get("loanHistory", [])):
        loan = item.get("loan", item)

        rows["history"].append(
            {
                "isbn13": isbn13,
                "month": loan.get("month"),
                "monthly_loanCnt": loan.get("loanCnt"),
                "monthly_ranking": loan.get("ranking"),
            }
        )

    for item in normalize_list(response.get("keywords", [])):
        keyword = item.get("keyword", item)

        rows["keywords"].append(
            {
                "isbn13": isbn13,
                "word": keyword.get("word"),
                "weight": keyword.get("weight"),
            }
        )

    for item in normalize_list(response.get("loanGrps", [])):
        group = item.get("loanGrp", item)

        rows["groups"].append(
            {
                "isbn13": isbn13,
                "age": group.get("age"),
                "gender": group.get("gender"),
                "loanCnt": group.get("loanCnt"),
                "ranking": group.get("ranking"),
            }
        )

    related_sources = {
        "co_loan_books": "coLoanBooks",
        "mania_rec_books": "maniaRecBooks",
        "reader_rec_books": "readerRecBooks",
    }

    for output_name, response_name in related_sources.items():
        for item in normalize_list(response.get(response_name, [])):
            related_book = item.get("book", item)

            rows[output_name].append(
                {
                    "isbn13": isbn13,
                    "related_bookname": related_book.get("bookname"),
                    "related_authors": related_book.get("authors"),
                    "related_publisher": related_book.get("publisher"),
                    "related_publication_year": related_book.get("publication_year"),
                    "related_isbn13": related_book.get("isbn13"),
                    "related_vol": related_book.get("vol"),
                }
            )

    return rows


def collect_isbns(popular_df: pd.DataFrame, hot_trend_df: pd.DataFrame) -> list[str]:
    isbn_series = []

    if not popular_df.empty and "isbn13" in popular_df.columns:
        isbn_series.append(popular_df["isbn13"])

    if not hot_trend_df.empty and "isbn13" in hot_trend_df.columns:
        isbn_series.append(hot_trend_df["isbn13"])

    if not isbn_series:
        return []

    isbn_df = pd.concat(isbn_series, ignore_index=True).dropna().astype(str).str.strip()
    isbn_df = isbn_df[isbn_df.ne("")]

    return isbn_df.drop_duplicates().tolist()


def fetch_usage_analysis_many(isbn_list: list[str], usage_limit: int | None = 1000):
    if usage_limit is not None:
        isbn_list = isbn_list[:usage_limit]

    outputs = {
        "books": RAW_DIR / "usage_books_raw.csv",
        "history": RAW_DIR / "loan_history_raw.csv",
        "keywords": RAW_DIR / "book_keywords_raw.csv",
        "groups": RAW_DIR / "loan_groups_raw.csv",
        "co_loan_books": RAW_DIR / "co_loan_books_raw.csv",
        "mania_rec_books": RAW_DIR / "mania_rec_books_raw.csv",
        "reader_rec_books": RAW_DIR / "reader_rec_books_raw.csv",
    }

    existing = read_existing_csv(outputs["books"])

    done_isbns = (
        set(existing["isbn13"].dropna().astype(str))
        if not existing.empty
        else set()
    )

    target_isbns = [isbn for isbn in isbn_list if isbn not in done_isbns]

    print(
        f"[usage] 전체={len(isbn_list)} 완료={len(done_isbns)} 남은 작업={len(target_isbns)}"
    )

    for idx, isbn13 in enumerate(target_isbns, start=1):
        rows = fetch_usage_analysis(isbn13)

        for name, path in outputs.items():
            append_csv(rows[name], path)

        print(f"[usage] {idx}/{len(target_isbns)} isbn={isbn13}")
        time.sleep(0.3)


def parse_usage_limit(value: str) -> int | None:
    if value.lower() == "all":
        return None

    limit = int(value)

    if limit < 0:
        raise argparse.ArgumentTypeError(
            "usage-limit 값은 0 이상의 정수 또는 'all' 이어야 합니다."
        )

    return limit


def main():
    parser = argparse.ArgumentParser(
        description="도서관 빅데이터 API 원천 데이터를 수집합니다. (단일 연도 또는 범위 지원)"
    )

    # 단일 연도 (하위 호환)
    parser.add_argument("--year", type=int, default=None, help="단일 연도 수집 (예: 2025)")

    # 멀티 연도 범위
    parser.add_argument("--year-start", type=int, default=None, help="수집 시작 연도 (예: 2023)")
    parser.add_argument("--year-end", type=int, default=None, help="수집 종료 연도 (예: 2025)")

    parser.add_argument(
        "--usage-limit",
        type=parse_usage_limit,
        default=1000,
        help="usageAnalysisList를 호출할 ISBN 개수. 전체 수집은 'all' 사용.",
    )

    parser.add_argument(
        "--skip-usage",
        action="store_true",
        help="월별 인기 도서, 월별 키워드, 인기 급상승 데이터만 수집합니다.",
    )

    parser.add_argument(
        "--hot-trend-step-days",
        type=int,
        default=3,
        help="hotTrend는 최근 3일 데이터를 포함하므로 기본값 3으로 중복 호출을 줄입니다.",
    )

    args = parser.parse_args()

    # 수집 연도 목록 결정
    if args.year is not None:
        years = [args.year]
    elif args.year_start is not None and args.year_end is not None:
        if args.year_start > args.year_end:
            parser.error("--year-start는 --year-end보다 작거나 같아야 합니다.")
        years = list(range(args.year_start, args.year_end + 1))
    else:
        years = [2025]

    print(f"[config] 수집 연도: {years}")

    all_popular_dfs: list[pd.DataFrame] = []
    all_hot_trend_dfs: list[pd.DataFrame] = []

    for year in years:
        print(f"\n{'='*50}")
        print(f"[year={year}] 수집 시작")
        print(f"{'='*50}")

        popular_df = fetch_popular_books_year(year)
        monthly_keywords_df = fetch_monthly_keywords_year(year)
        hot_trend_df = fetch_hot_trends_year(year, step_days=args.hot_trend_step_days)

        all_popular_dfs.append(popular_df)
        all_hot_trend_dfs.append(hot_trend_df)

        # 연도별 isbn_candidates 저장 (skip-usage 여부 무관)
        isbn_list_year = collect_isbns(popular_df, hot_trend_df)
        isbn_path = RAW_DIR / f"isbn_candidates_{year}.csv"
        pd.DataFrame({"isbn13": isbn_list_year}).to_csv(
            isbn_path, index=False, encoding="utf-8-sig"
        )
        print(f"[isbn] 저장 완료: {isbn_path} rows={len(isbn_list_year)}")

        print(
            f"[summary year={year}] "
            f"popular_rows={len(popular_df)}, "
            f"monthly_keyword_rows={len(monthly_keywords_df)}, "
            f"hot_trend_rows={len(hot_trend_df)}, "
            f"isbn_candidates={len(isbn_list_year)}"
        )

    if args.skip_usage:
        print("\n[config] --skip-usage: usageAnalysisList 수집을 건너뜁니다.")
        return

    # 전체 연도 ISBN 통합 → 중복 제거 후 usage 수집
    all_popular = pd.concat(all_popular_dfs, ignore_index=True) if all_popular_dfs else pd.DataFrame()
    all_hot = pd.concat(all_hot_trend_dfs, ignore_index=True) if all_hot_trend_dfs else pd.DataFrame()
    all_isbns = collect_isbns(all_popular, all_hot)

    print(f"\n[isbn] 전체 연도 통합 ISBN 수: {len(all_isbns)}")

    fetch_usage_analysis_many(all_isbns, usage_limit=args.usage_limit)


if __name__ == "__main__":
    main()