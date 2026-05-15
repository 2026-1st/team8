# Data Pipeline Report — chore/#10/data-2023-2025

**작성일:** 2026-05-16  
**브랜치:** chore/#10/data-2023-2025  
**담당:** Data Pipeline Agent

---

## 1. 작업 요약

`data/dataset.py`를 멀티 연도(`--year-start / --year-end`) 지원으로 확장하고,
2023~2025 전체 raw 데이터를 data4library.kr API에서 수집하여 CSV로 저장했다.

---

## 2. 수집 결과

| 연도 | popular_books | monthly_keywords | hot_trends | isbn_candidates |
|------|:---:|:---:|:---:|:---:|
| 2023 | 12개월 (17.7 MB) | 12개월 | 122개 날짜 | 8,010 |
| 2024 | 12개월 (17.6 MB) | 12개월 | 122개 날짜 | 7,861 |
| 2025 | 12개월 (17.6 MB) | 12개월 | 122개 날짜 | 7,786 |

- **ISBN 통합 마스터 (중복 제거):** 12,821개 → `data/raw/isbn_candidates_all.csv`
- **Usage 분석 (2025 기수집):** 1,000 도서 → `data/raw/usage_books_raw.csv`

### 월별 인기 도서 (popular_books)
- 월별 최대 5,000행 (25페이지 × 200행)
- 파일 당 ~1.47 MB
- 연도별 합계 ~60,000행

### 트렌드 (hot_trends)
- 3일 간격 수집 → 연도별 122개 날짜 파일
- 날짜별 15~20행 (TOP 15 도서)

### 월별 키워드 (monthly_keywords)
- 연도별 12개 파일, 월별 ~100행

---

## 3. 코드 변경 사항

### `data/dataset.py` 수정 내용

1. **`--year-start / --year-end` 인자 추가** (기존 `--year` 하위 호환 유지)
   ```
   python data/dataset.py --year-start 2023 --year-end 2025 --skip-usage
   ```

2. **멀티 연도 루프 (`main()`)**: 연도별 수집 후 isbn_candidates 통합

3. **빈 파일 방어 처리** (`fetch_popular_books_year`, `fetch_monthly_keywords_year`, `fetch_hot_trends_year`):
   - 파일 크기 100 bytes 미만이면 재수집
   - `pandas.errors.EmptyDataError` try/except 추가

4. **rate-limit 자동 대기** (`get_json()`):
   - 응답 내 중첩 `response.error` 감지
   - "500건" 메시지 검출 시 최대 300초 대기 후 재시도 (최대 5회)

---

## 4. raw 데이터 구조

```
data/raw/
├── popular_books_2023-01.csv ~ popular_books_2023-12.csv   (2023 월별)
├── popular_books_2023.csv                                  (2023 연간 통합)
├── popular_books_2024-01.csv ~ popular_books_2024-12.csv   (2024 월별)
├── popular_books_2024.csv
├── popular_books_2025-01.csv ~ popular_books_2025-12.csv   (2025, 기수집)
├── popular_books_2025.csv
├── monthly_keywords_2023-01.csv ~ 12.csv
├── monthly_keywords_2024-01.csv ~ 12.csv
├── monthly_keywords_2025-01.csv ~ 12.csv
├── hot_trends_2023-YYYY-MM-DD.csv (122개)
├── hot_trends_2024-YYYY-MM-DD.csv (122개)
├── hot_trends_2025-YYYY-MM-DD.csv (122개)
├── isbn_candidates_2023.csv  (8,010개)
├── isbn_candidates_2024.csv  (7,861개)
├── isbn_candidates_2025.csv  (7,786개)
├── isbn_candidates_all.csv   (12,821개, 중복 제거)
├── usage_books_raw.csv       (1,000행, 2025 기수집)
├── loan_history_raw.csv
├── book_keywords_raw.csv
├── loan_groups_raw.csv
└── ...
```

---

## 5. 실행 방법

```bash
# 전체 3개년 목록 API 수집 (usageAnalysis 제외)
python data/dataset.py --year-start 2023 --year-end 2025 --skip-usage

# usage 포함 전체 수집 (시간 소요)
python data/dataset.py --year-start 2023 --year-end 2025 --usage-limit all

# 단일 연도 (하위 호환)
python data/dataset.py --year 2024
```

---

## 6. 블로커 및 주의사항

### API Rate Limit
- data4library.kr는 세션당 약 500건 제한 (`1회 500건 이상 요청 시 IP 차단`)
- **병렬 실행 금지** — 반드시 단일 프로세스로 순차 실행
- 코드에 자동 대기 로직 추가 완료 (rate limit 감지 시 60~300초 대기)

### usage_books_raw.csv 추가 수집 필요 시
```bash
python data/dataset.py --year-start 2023 --year-end 2025 --usage-limit 1000
```
2023/2024의 신규 ISBN이 추가로 처리됨. 단, 500건 rate limit 주의.

### monthly_keywords API 과거 데이터
- 2023~2024 데이터는 API에서 정상 반환됨 (연도별 월 100행)

---

## 7. Lead에게 전달 사항

- `dataset.py`: `--year-start / --year-end` 인자로 2023~2025 한 번에 수집 가능
- 2025 데이터는 기수집 파일이 있으므로 스킵 (skip 로직 정상 작동)
- `isbn_candidates_all.csv` 신규 생성 — process.py에서 전체 연도 ISBN 참조 가능
- usage 분석은 2025 기준 1,000건 완료. 2023/2024 신규 ISBN 추가 수집은 별도 실행 필요
- `process.py`의 `YEARS = [2025]` → `YEARS = [2023, 2024, 2025]` 변경 및 split 경계 조정 필요 (Modeling Agent 또는 다음 PR)
