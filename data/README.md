# data 디렉터리 문서

## 개요

`data` 디렉터리는 도서관정보나루 API 기반 raw 데이터 수집 코드를 포함한다.

현재 단계에서는 머신러닝 학습용 데이터셋 생성이나 전처리는 수행하지 않으며,
API 응답 기반 원천 데이터를 CSV 형태로 저장하는 역할만 담당한다.

또한 기존 수집하는 data는 `github 릴리즈`로 관리한다.
`vx.x.x-raw`의 버전을 참고

---

## 디렉터리 구조

```text
data/
├── README.md
├── dataset.py
└── raw/
```

---

## 수집 데이터 구성

현재 수집하는 데이터는 다음과 같다.

| 데이터 | 설명 |
|---|---|
| 인기대출도서 | 월별 인기 대출 도서 목록 |
| 이달의 키워드 | 월별 트렌드 키워드 |
| 대출 급상승 도서 | 단기간 대출량 급상승 도서 |
| 도서 이용 분석 | ISBN 기반 상세 이용 분석 |

---

## 사용 API

### 인기대출도서 조회

- API: `loanItemSrch`
- 함수:
  - `fetch_popular_books_month()`
  - `fetch_popular_books_year()`

#### 저장 파일

```text
data/raw/popular_books_YYYY-MM.csv
data/raw/popular_books_YYYY.csv
```

#### 주요 컬럼

| 컬럼 | 설명 |
|---|---|
| ranking | 대출 순위 |
| bookname | 도서명 |
| authors | 저자 |
| publisher | 출판사 |
| isbn13 | ISBN |
| loan_count | 대출 횟수 |

---

## 도서별 이용 분석

### 사용 API

```text
usageAnalysisList
```

### 수집 내용

- 최근 12개월 대출 이력
- 월별 대출 순위
- 연령/성별 이용 그룹
- 함께 대출된 도서
- 추천 도서

---

## 실행 방법

```bash
python data\dataset.py --year 2025
```

---

## 실행 옵션

### 기본 raw 데이터만 수집

```bash
python data\dataset.py --year 2025 --skip-usage
```

### ISBN 수집 개수 제한

```bash
python data\dataset.py --year 2025 --usage-limit 1000
```

---

## raw 데이터 주의사항

`data/raw/`의 CSV는 API 원천 데이터를 그대로 저장한 결과이다.

현재 단계에서는 다음 작업을 수행하지 않는다.

- 결측치 처리
- 이상치 제거
- 중복 정리
- 피처 엔지니어링
- 학습용 target 생성

해당 작업은 이후 전처리 및 모델링 단계에서 수행한다.