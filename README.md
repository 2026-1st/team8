# 도서관 빅데이터 기반 미래 대출 수요 예측 프로젝트

## 프로젝트 개요

본 프로젝트는 도서관정보나루(Library BigData) 공개 API를 활용하여 도서 대출 관련 데이터를 수집하고, 미래 도서 대출 수요 예측 모델 구축을 위한 기반을 마련하는 프로젝트이다.

최종 목표는 도서 정보, 대출 이력, 급상승 도서, 월별 키워드 등의 데이터를 활용하여 미래 도서 대출 수요를 예측하고, 도서관 운영 의사결정에 도움을 줄 수 있는 분석 및 예측 시스템을 구축하는 것이다.

현재 단계에서는 모델 학습 및 피처 엔지니어링은 진행하지 않았으며, 도서관정보나루 API 기반 raw 데이터 수집 기능 구현까지 완료하였다.
123
---

## 현재 구현 범위

현재 구현된 기능은 다음과 같다.

- 도서관정보나루 API 키 로드
- 1년치 월별 인기 대출 도서 수집
- 1년치 월별 이달의 키워드 수집
- 1년치 대출 급상승 도서 수집
- ISBN별 도서 이용 분석 데이터 수집
- 수집 데이터 CSV 저장

상세 구현 내용은 아래 문서에서 확인할 수 있다.

```text
data/README.md
```

---

## 사용 데이터

현재 수집 대상 데이터는 다음과 같다.

- 인기 대출 도서
- 이달의 키워드
- 대출 급상승 도서
- ISBN별 도서 이용 분석

  - 도서 기본 정보
  - 최근 12개월 대출 이력
  - 도서별 키워드
  - 연령 및 성별 이용 그룹
  - 함께 대출된 도서
  - 추천 도서 정보

---

## 프로젝트 구조

```text
team8/
├── README.md
├── .env
├── .gitignore
└── data/
    ├── README.md
    ├── dataset.py
    └── raw/
        ├── popular_books_YYYY-MM.csv
        ├── popular_books_YYYY.csv
        ├── monthly_keywords_YYYY-MM.csv
        ├── monthly_keywords_YYYY.csv
        ├── hot_trends_YYYY-MM-DD.csv
        ├── hot_trends_YYYY.csv
        ├── isbn_candidates_YYYY.csv
        ├── usage_books_raw.csv
        ├── loan_history_raw.csv
        ├── book_keywords_raw.csv
        ├── loan_groups_raw.csv
        ├── co_loan_books_raw.csv
        ├── mania_rec_books_raw.csv
        └── reader_rec_books_raw.csv
```

---

## 실행 전 준비

프로젝트 루트에 `.env` 파일을 생성하고 도서관정보나루 API 키를 설정한다.

```env
LIBRARY_API_KEY=발급받은_API_KEY
```

필요한 Python 패키지는 다음과 같다.

```text
pandas
requests
python-dotenv
```

---

## 실행 방법

프로젝트 루트에서 다음 명령어를 실행한다.

```bash
python data\dataset.py --year 2025
```

위 명령은 지정한 연도에 대해 다음 데이터를 수집한다.

- 월별 인기 대출 도서
- 월별 이달의 키워드
- 대출 급상승 도서
- ISBN 후보 기반 도서 이용 분석 데이터

---

## 실행 옵션

### 기본 raw 데이터만 수집

```bash
python data\dataset.py --year 2025 --skip-usage
```

### 도서 이용 분석 ISBN 개수 지정

```bash
python data\dataset.py --year 2025 --usage-limit 1000
```

### 전체 ISBN 대상 분석

```bash
python data\dataset.py --year 2025 --usage-limit all
```

### 대출 급상승 도서 API 호출 간격 지정

```bash
python data\dataset.py --year 2025 --hot-trend-step-days 3
```

---

## 현재 단계에서 제외된 항목

현재 구현은 raw 데이터 수집 단계까지만 포함한다.

아직 구현하지 않은 항목은 다음과 같다.

- 데이터 정제
- 결측치 처리
- 중복 데이터 처리
- 피처 엔지니어링
- 학습용 데이터셋 생성
- 머신러닝 모델 학습
- 모델 평가
- 데이터 시각화

---

## 상세 문서

데이터 수집 API, 저장 파일, 컬럼 구성, 실행 옵션에 대한 상세 내용은 아래 문서를 참고한다.

```text
data/README.md
```

---

## 데이터 출처

본 프로젝트는 도서관정보나루(Library BigData) 공개 API를 활용한다.

[도서관정보나루](https://www.data4library.kr?utm_source=chatgpt.com)

---

## License

본 프로젝트의 소스코드는 MIT License를 따른다.

단, 도서관정보나루 API를 통해 수집한 데이터의 이용 조건은 도서관정보나루 및 해당 데이터 제공 기관의 정책을 따른다.