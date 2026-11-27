# ======================== imports ========================
import json
import os
import urllib.error
import urllib.parse
import urllib.request

from database import connect_databases, get_all_books, get_books_count


# ======================== Test helpers ========================
BASE_URL = "http://localhost:4785"


def request(method: str, path: str, body: dict | None = None) -> tuple[int, dict | str]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        BASE_URL + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"} if data is not None else {},
    )

    try:
        response = urllib.request.urlopen(req, timeout=15)
    except urllib.error.HTTPError as error:
        response = error

    with response:
        text = response.read().decode("utf-8")
        try:
            result = json.loads(text)
        except json.JSONDecodeError:
            result = text
        return response.status, result


def assert_both_databases_equal() -> None:
    postgres_books = sorted(get_all_books("POSTGRES"), key=lambda book: book["id"])
    mongo_books = sorted(get_all_books("MONGO"), key=lambda book: book["id"])
    assert postgres_books == mongo_books, (postgres_books, mongo_books)


# ======================== Postman follow-up tests ========================
def main() -> None:
    os.environ["DATABASE_URL"] = "postgresql+psycopg://postgres:docker@localhost:5432/books"
    os.environ["MONGO_URL"] = "mongodb://localhost:27017/books"

    connect_databases()

    # Postman flow leaves books 1 and 3 in both databases.
    assert get_books_count("POSTGRES") == 2
    assert get_books_count("MONGO") == 2
    assert_both_databases_equal()

    status, result = request("GET", "/books?genres=NOVEL&persistenceMethod=POSTGRES")
    assert status == 200 and len(result["result"]) == 1
    assert result["result"][0]["genres"] == ["ROMANCE", "NOVEL"]

    status, result = request("GET", "/books/total?persistenceMethod=invalid")
    assert status == 400 and "errorMessage" in result

    status, result = request("GET", "/book?id=9999&persistenceMethod=MONGO")
    assert status == 404 and "errorMessage" in result

    status, result = request("POST", "/book", {
        "title": "Temporary validation test",
        "author": "Test",
        "year": 2010,
        "price": -2,
        "genres": ["NOVEL"],
    })
    assert status == 409
    assert get_books_count("POSTGRES") == 2
    assert_both_databases_equal()

    status, result = request("POST", "/book", {
        "title": "Restart verification",
        "author": "Test",
        "year": 2020,
        "price": 60,
        "genres": ["NOVEL", "HISTORY"],
    })
    assert status == 200 and result["result"] == 4
    assert_both_databases_equal()

    status, result = request("DELETE", "/book?id=4")
    assert status == 200 and result["result"] == 2
    assert_both_databases_equal()

    print("All extended consistency and validation tests passed.")


if __name__ == "__main__":
    main()
