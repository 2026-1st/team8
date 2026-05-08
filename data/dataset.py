import os
import time
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv


load_dotenv()

API_KEY = os.getenv("LIBRARY_API_KEY")
BASE_URL = "https://data4library.kr/api"

RAW_DIR = Path("data/raw")
RAW_DIR.mkdir(parents=True, exist_ok=True)


def get_json(endpoint: str, params: dict) -> dict:
    if not API_KEY:
        raise ValueError("LIBRARY_API_KEY가 .env에 없습니다.")

    params = {
        **params,
        "authKey": API_KEY,
        "format": "json",
    }

    url = f"{BASE_URL}/{endpoint}"
    response = requests.get(url, params=params, timeout=10)
    response.raise_for_status()
    return response.json()


def normalize_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def fetch_popular_books(start_dt: str, end_dt: str, page_size: int = 200):
    rows = []

    for page_no in range(1, 26):  # 200 * 25 = 최대 5000건
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
        docs = response.get("docs", [])
        docs = normalize_list(docs)

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
                    "class_no": doc.get("class_no"),
                    "class_nm": doc.get("class_nm"),
                    "loan_count": doc.get("loan_count"),
                    "bookImageURL": doc.get("bookImageURL"),
                    "bookDtlUrl": doc.get("bookDtlUrl"),
                }
            )

        print(f"[인기대출] page={page_no}, rows={len(rows)}")
        time.sleep(0.2)

    df = pd.DataFrame(rows)
    df.to_csv(RAW_DIR / "popular_books_raw.csv", index=False, encoding="utf-8-sig")
    return df


def fetch_usage_analysis(isbn_list):
    book_rows = []
    history_rows = []
    keyword_rows = []
    group_rows = []
    coloans_rows = []

    for idx, isbn13 in enumerate(isbn_list, start=1):
        if pd.isna(isbn13):
            continue

        data = get_json(
            "usageAnalysisList",
            {
                "isbn13": str(isbn13),
            },
        )

        response = data.get("response", {})

        book = response.get("book", {})
        book_rows.append(
            {
                "isbn13": isbn13,
                "bookname": book.get("bookname"),
                "authors": book.get("authors"),
                "publisher": book.get("publisher"),
                "publication_year": book.get("publication_year"),
                "class_no": book.get("class_no"),
                "class_nm": book.get("class_nm"),
                "loanCnt_total": book.get("loanCnt"),
                "description": book.get("description"),
            }
        )

        loan_history = response.get("loanHistory", [])
        for item in normalize_list(loan_history):
            loan = item.get("loan", item)
            history_rows.append(
                {
                    "isbn13": isbn13,
                    "month": loan.get("month"),
                    "monthly_loanCnt": loan.get("loanCnt"),
                    "monthly_ranking": loan.get("ranking"),
                }
            )

        keywords = response.get("keywords", [])
        for item in normalize_list(keywords):
            keyword = item.get("keyword", item)
            keyword_rows.append(
                {
                    "isbn13": isbn13,
                    "word": keyword.get("word"),
                    "weight": keyword.get("weight"),
                }
            )

        loan_grps = response.get("loanGrps", [])
        for item in normalize_list(loan_grps):
            group = item.get("loanGrp", item)
            group_rows.append(
                {
                    "isbn13": isbn13,
                    "age": group.get("age"),
                    "gender": group.get("gender"),
                    "loanCnt": group.get("loanCnt"),
                    "ranking": group.get("ranking"),
                }
            )

        co_books = response.get("coLoanBooks", [])
        for item in normalize_list(co_books):
            co_book = item.get("book", item)
            coloans_rows.append(
                {
                    "isbn13": isbn13,
                    "co_bookname": co_book.get("bookname"),
                    "co_authors": co_book.get("authors"),
                    "co_publisher": co_book.get("publisher"),
                    "co_publication_year": co_book.get("publication_year"),
                    "co_isbn13": co_book.get("isbn13"),
                }
            )

        print(f"[이용분석] {idx}/{len(isbn_list)} isbn={isbn13}")
        time.sleep(0.3)

    pd.DataFrame(book_rows).to_csv(RAW_DIR / "usage_books_raw.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(history_rows).to_csv(RAW_DIR / "loan_history_raw.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(keyword_rows).to_csv(RAW_DIR / "book_keywords_raw.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(group_rows).to_csv(RAW_DIR / "loan_groups_raw.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(coloans_rows).to_csv(RAW_DIR / "co_loan_books_raw.csv", index=False, encoding="utf-8-sig")


def fetch_monthly_keywords(month: str):
    data = get_json(
        "monthlyKeywords",
        {
            "month": month,
        },
    )

    response = data.get("response", {})
    keywords = response.get("keywords", [])
    rows = []

    for item in normalize_list(keywords):
        keyword = item.get("keyword", item)
        rows.append(
            {
                "month": month,
                "word": keyword.get("word"),
                "weight": keyword.get("weight"),
            }
        )

    df = pd.DataFrame(rows)
    df.to_csv(RAW_DIR / f"monthly_keywords_{month}.csv", index=False, encoding="utf-8-sig")
    return df


def main():
    popular_df = fetch_popular_books(
        start_dt="2025-01-01",
        end_dt="2025-01-31",
    )

    isbn_list = (
        popular_df["isbn13"]
        .dropna()
        .astype(str)
        .drop_duplicates()
        .head(100)
        .tolist()
    )

    fetch_usage_analysis(isbn_list)
    fetch_monthly_keywords("2025-01")

    print("raw 데이터 수집 완료")


if __name__ == "__main__":
    main()