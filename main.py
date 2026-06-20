# ======================== imports ========================
#           !!! Using only built-in libraries !!!
# =========================================================
import json
import os
import shutil
import sys
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any
from urllib.parse import urlparse, parse_qs


# ======================== Constants ========================
HOST: str = "0.0.0.0"
PORT: int = 8574

MIN_YEAR: int = 1940
MAX_YEAR: int = 2100

VALID_GENRES: set[str] = {
    "SCI_FI",
    "NOVEL",
    "HISTORY",
    "MANGA",
    "ROMANCE",
    "PROFESSIONAL",
}

JSON_CONTENT_TYPE: str = "application/json"
TEXT_CONTENT_TYPE: str = "text/plain"

LOGS_DIR: str = "logs"
REQUESTS_LOG_FILE: str = os.path.join(LOGS_DIR, "requests.log")
BOOKS_LOG_FILE: str = os.path.join(LOGS_DIR, "books.log")

REQUEST_LOGGER_NAME: str = "request-logger"
BOOKS_LOGGER_NAME: str = "books-logger"

ERROR_LEVEL: str = "ERROR"
INFO_LEVEL: str = "INFO"
DEBUG_LEVEL: str = "DEBUG"

VALID_LOG_LEVELS: set[str] = {ERROR_LEVEL, INFO_LEVEL, DEBUG_LEVEL}

LOG_LEVEL_PRIORITY: dict[str, int] = {
    ERROR_LEVEL: 40,
    INFO_LEVEL: 20,
    DEBUG_LEVEL: 10,
}


# ======================== data storage ========================
books: dict[int, dict[str, Any]] = {}
next_book_id: int = 1

# First incoming request receives number 1.
request_counter: int = 0


# ======================== logging facility ========================
class ExerciseLogger:
    """
    A small custom logger for the exercise because the automation expects a very specific line format.
    """

    def __init__(self, name: str, file_path: str, level: str, write_to_console: bool = False) -> None:
        self.name = name
        self.file_path = file_path
        self.level = level
        self.write_to_console = write_to_console

    def set_level(self, level: str) -> None:
        self.level = level

    def get_level(self) -> str:
        return self.level

    def should_log(self, message_level: str) -> bool:
        """
        Level behavior:
        - ERROR logger level logs only ERROR.
        - INFO logger level logs INFO and ERROR.
        - DEBUG logger level logs DEBUG, INFO and ERROR.
        """
        return LOG_LEVEL_PRIORITY[message_level] >= LOG_LEVEL_PRIORITY[self.level]

    def log(self, message_level: str, message: str, request_number: int) -> None:
        if not self.should_log(message_level):
            return

        timestamp = datetime.now().strftime("%d-%m-%Y %H:%M:%S.%f")[:-3]
        line = f"{timestamp} {message_level}: {message} | request #{request_number}"

        with open(self.file_path, "a", encoding="utf-8") as log_file:
            log_file.write(line + "\n")

        if self.write_to_console:
            print(line, flush=True)

    def error(self, message: str, request_number: int) -> None:
        self.log(ERROR_LEVEL, message, request_number)

    def info(self, message: str, request_number: int) -> None:
        self.log(INFO_LEVEL, message, request_number)

    def debug(self, message: str, request_number: int) -> None:
        self.log(DEBUG_LEVEL, message, request_number)


request_logger: ExerciseLogger
books_logger: ExerciseLogger


def setup_logs_folder() -> None:
    """
    Creates a fresh logs folder for every server run.
    The folder is not deleted when the server exits, so the automation can inspect it.
    """
    if os.path.exists(LOGS_DIR):
        shutil.rmtree(LOGS_DIR)

    os.makedirs(LOGS_DIR, exist_ok=True)

    open(REQUESTS_LOG_FILE, "w", encoding="utf-8").close()
    open(BOOKS_LOG_FILE, "w", encoding="utf-8").close()


def setup_loggers() -> None:
    """
    Initializes the two required loggers:
    - request-logger: writes to requests.log and console, default INFO.
    - books-logger: writes to books.log, default INFO.
    """
    global request_logger, books_logger

    request_logger = ExerciseLogger(
        name=REQUEST_LOGGER_NAME,
        file_path=REQUESTS_LOG_FILE,
        level=INFO_LEVEL,
        write_to_console=True,
    )

    books_logger = ExerciseLogger(
        name=BOOKS_LOGGER_NAME,
        file_path=BOOKS_LOG_FILE,
        level=INFO_LEVEL,
        write_to_console=False,
    )


def get_logger_by_name(logger_name: str) -> ExerciseLogger | None:
    if logger_name == REQUEST_LOGGER_NAME:
        return request_logger

    if logger_name == BOOKS_LOGGER_NAME:
        return books_logger

    return None


# ======================== helper functions ========================
def build_success_response(result: Any) -> dict[str, Any]:
    return {"result": result}


def build_error_response(error_message: str) -> dict[str, str]:
    return {"errorMessage": error_message}


def normalize_book_title(title: str) -> str:
    return title.lower()


def parse_request_path_and_query(request_path: str) -> tuple[str, dict[str, list[str]]]:
    parsed_url = urlparse(request_path)
    path = parsed_url.path
    query_params = parse_qs(parsed_url.query, keep_blank_values=True)
    return path, query_params


def get_first_query_param(query_params: dict[str, list[str]], param_name: str) -> str | None:
    values = query_params.get(param_name)

    if values is None or len(values) == 0:
        return None

    return values[0]


def parse_required_int_query_param(query_params: dict[str, list[str]], param_name: str) -> int:
    raw_value = get_first_query_param(query_params, param_name)

    if raw_value is None or raw_value == "":
        raise ValueError(f"Missing required numeric query parameter: {param_name}")

    try:
        return int(raw_value)
    except ValueError as error:
        raise ValueError(f"Query parameter [{param_name}] must be numeric") from error


def parse_optional_int_query_param(query_params: dict[str, list[str]], param_name: str) -> int | None:
    raw_value = get_first_query_param(query_params, param_name)

    if raw_value is None:
        return None

    if raw_value == "":
        raise ValueError(f"Query parameter [{param_name}] must be numeric")

    try:
        return int(raw_value)
    except ValueError as error:
        raise ValueError(f"Query parameter [{param_name}] must be numeric") from error


def read_json_body(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    content_length_text = handler.headers.get("Content-Length")

    if content_length_text is None:
        raise ValueError("Missing Content-Length header")

    try:
        content_length = int(content_length_text)
    except ValueError as error:
        raise ValueError("Invalid Content-Length header") from error

    body_bytes = handler.rfile.read(content_length)
    body_text = body_bytes.decode("utf-8")

    try:
        parsed_body = json.loads(body_text)
    except json.JSONDecodeError as error:
        raise ValueError(f"Request body is not valid JSON: {body_text}") from error

    if not isinstance(parsed_body, dict):
        raise ValueError("Request body must be a JSON object")

    return parsed_body


def is_valid_genre_list(genres: Any) -> bool:
    if not isinstance(genres, list):
        return False

    for genre in genres:
        if not isinstance(genre, str):
            return False

        if genre not in VALID_GENRES:
            return False

    return True


def parse_genres_filter(query_params: dict[str, list[str]]) -> set[str] | None:
    raw_genres = get_first_query_param(query_params, "genres")

    if raw_genres is None:
        return None

    if raw_genres == "":
        raise ValueError("Genres filter cannot be empty")

    genres = set(raw_genres.split(","))

    for genre in genres:
        if genre not in VALID_GENRES:
            raise ValueError(f"Invalid genre: {genre}")

    return genres


def find_book_by_title(title: str) -> dict[str, Any] | None:
    normalized_title = normalize_book_title(title)

    for book in books.values():
        if normalize_book_title(book["title"]) == normalized_title:
            return book

    return None


def get_book_by_id(book_id: int) -> dict[str, Any] | None:
    return books.get(book_id)


def apply_book_filters(query_params: dict[str, list[str]]) -> list[dict[str, Any]]:
    author_filter = get_first_query_param(query_params, "author")

    price_bigger_than = parse_optional_int_query_param(query_params, "price-bigger-than")
    price_less_than = parse_optional_int_query_param(query_params, "price-less-than")
    year_bigger_than = parse_optional_int_query_param(query_params, "year-bigger-than")
    year_less_than = parse_optional_int_query_param(query_params, "year-less-than")

    genres_filter = parse_genres_filter(query_params)

    filtered_books: list[dict[str, Any]] = []

    for book in books.values():
        if author_filter is not None:
            if book["author"].lower() != author_filter.lower():
                continue

        if price_bigger_than is not None:
            if book["price"] < price_bigger_than:
                continue

        if price_less_than is not None:
            if book["price"] > price_less_than:
                continue

        if year_bigger_than is not None:
            if book["year"] < year_bigger_than:
                continue

        if year_less_than is not None:
            if book["year"] > year_less_than:
                continue

        if genres_filter is not None:
            book_genres = set(book["genres"])

            if book_genres.isdisjoint(genres_filter):
                continue

        filtered_books.append(book)

    return filtered_books


def sort_books_by_title(book_list: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(book_list, key=lambda book: book["title"].lower())


def validate_new_book_data(book_data: dict[str, Any]) -> tuple[str, str, int, int, list[str]]:
    title = book_data.get("title")
    author = book_data.get("author")
    year = book_data.get("year")
    price = book_data.get("price")
    genres = book_data.get("genres")

    if not isinstance(title, str):
        raise ValueError("Bad request: title must be a string")

    if not isinstance(author, str):
        raise ValueError("Bad request: author must be a string")

    if not isinstance(year, int):
        raise ValueError("Bad request: year must be an integer")

    if not isinstance(price, int):
        raise ValueError("Bad request: price must be an integer")

    if not is_valid_genre_list(genres):
        raise ValueError("Bad request: genres must be a list of valid genres")

    return title, author, year, price, genres


def create_book(book_data: dict[str, Any]) -> int:
    global next_book_id

    title, author, year, price, genres = validate_new_book_data(book_data)

    existing_book = find_book_by_title(title)

    if existing_book is not None:
        raise RuntimeError(
            f"Error: Book with the title [{title}] already exists in the system"
        )

    if year < MIN_YEAR or year > MAX_YEAR:
        raise RuntimeError(
            f"Error: Can’t create new Book that its year [{year}] "
            f"is not in the accepted range [{MIN_YEAR} -> {MAX_YEAR}]"
        )

    if price <= 0:
        raise RuntimeError("Error: Can’t create new Book with negative price")

    new_book_id = next_book_id

    new_book = {
        "id": new_book_id,
        "title": title,
        "author": author,
        "price": price,
        "year": year,
        "genres": genres,
    }

    books[new_book_id] = new_book
    next_book_id += 1

    return new_book_id


def update_book_price(book_id: int, new_price: int) -> int | None:
    book = get_book_by_id(book_id)

    if book is None:
        return None

    old_price = book["price"]
    book["price"] = new_price

    return old_price


def delete_book(book_id: int) -> int | None:
    if book_id not in books:
        return None

    del books[book_id]

    return len(books)


# ======================== Request Handler ========================
class BookStoreRequestHandler(BaseHTTPRequestHandler):
    """
    Handles HTTP requests for the Book Store server.
    """

    # ------------------------ low-level response helpers ------------------------
    def send_json_response(self, status_code: int, response_body: dict[str, Any]) -> None:
        """
        Sends a JSON response.
        Also stores the final HTTP status code for the central logging wrapper.
        """
        self.last_status_code = status_code
        response_text = json.dumps(response_body, ensure_ascii=False)
        response_bytes = response_text.encode("utf-8")

        self.send_response(status_code)
        self.send_header("Content-Type", JSON_CONTENT_TYPE)
        self.send_header("Content-Length", str(len(response_bytes)))
        self.end_headers()

        self.wfile.write(response_bytes)

    def send_text_response(self, status_code: int, response_text: str) -> None:
        """
        Sends a plain text response.
        Used by /books/health and /logs/level.
        Also stores the final HTTP status code for the central logging wrapper.
        """
        self.last_status_code = status_code
        response_bytes = response_text.encode("utf-8")

        self.send_response(status_code)
        self.send_header("Content-Type", TEXT_CONTENT_TYPE)
        self.send_header("Content-Length", str(len(response_bytes)))
        self.end_headers()

        self.wfile.write(response_bytes)

    def send_bad_request_response(self, error_details: str = "Bad request") -> None:
        """
        Sends a 400 Bad Request response.
        For 400, no logs should be written whatsoever.
        """
        self.send_json_response(
            400,
            build_error_response(f"Error: {error_details}"),
        )

    # ------------------------ central request wrapper ------------------------
    def handle_request_with_logging(self, http_verb: str) -> None:
        """
        Central wrapper for every HTTP method.

        For Bad Request 400, no logs should be written whatsoever.
        Therefore, request-logger lines are written only after we know the final status code.
        """
        global request_counter

        request_counter += 1
        current_request_number = request_counter

        path, query_params = parse_request_path_and_query(self.path)
        start_time = time.perf_counter()
        self.last_status_code = None

        try:
            self.dispatch_request(http_verb, path, query_params, current_request_number)

        except Exception as error:
            error_message = f"Error: internal server error: {error}"
            books_logger.error(error_message, current_request_number)
            self.send_json_response(500, build_error_response(error_message))

        finally:
            if self.last_status_code == 400:
                return

            request_logger.info(
                f"Incoming request | #{current_request_number} | resource: {path} | HTTP Verb {http_verb}",
                current_request_number,
            )

            duration_ms = int((time.perf_counter() - start_time) * 1000)
            request_logger.debug(
                f"request #{current_request_number} duration: {duration_ms}ms",
                current_request_number,
            )

    def dispatch_request(
        self,
        http_verb: str,
        path: str,
        query_params: dict[str, list[str]],
        request_number: int,
    ) -> None:
        if path == "/logs/level":
            self.handle_logs_level_endpoint(http_verb, query_params)
            return

        if http_verb == "GET":
            self.handle_get_request(path, query_params, request_number)
            return

        if http_verb == "POST":
            self.handle_post_request(path, request_number)
            return

        if http_verb == "PUT":
            self.handle_put_request(path, query_params, request_number)
            return

        if http_verb == "DELETE":
            self.handle_delete_request(path, query_params, request_number)
            return

        error_message = "Error: endpoint not found"
        self.send_json_response(404, build_error_response(error_message))

    # ------------------------ HTTP verb entry points ------------------------
    def do_GET(self) -> None:
        self.handle_request_with_logging("GET")

    def do_POST(self) -> None:
        self.handle_request_with_logging("POST")

    def do_PUT(self) -> None:
        self.handle_request_with_logging("PUT")

    def do_DELETE(self) -> None:
        self.handle_request_with_logging("DELETE")

    # ------------------------ /logs/level endpoint ------------------------
    def handle_logs_level_endpoint(self, http_verb: str, query_params: dict[str, list[str]]) -> None:
        if http_verb not in {"GET", "PUT"}:
            self.send_text_response(404, "Error: endpoint not found")
            return

        logger_name = get_first_query_param(query_params, "logger-name")

        if logger_name is None or logger_name == "":
            self.send_text_response(400, "Error: missing logger-name")
            return

        selected_logger = get_logger_by_name(logger_name)

        if selected_logger is None:
            self.send_text_response(400, f"Error: logger [{logger_name}] does not exist")
            return

        if http_verb == "GET":
            self.send_text_response(200, selected_logger.get_level())
            return

        requested_level = get_first_query_param(query_params, "logger-level")

        if requested_level is None or requested_level == "":
            self.send_text_response(400, "Error: missing logger-level")
            return

        if requested_level not in VALID_LOG_LEVELS:
            self.send_text_response(400, f"Error: logger level [{requested_level}] is invalid")
            return

        selected_logger.set_level(requested_level)
        self.send_text_response(200, selected_logger.get_level())

    # ------------------------ books endpoints routing ------------------------
    def handle_get_request(
        self,
        path: str,
        query_params: dict[str, list[str]],
        request_number: int,
    ) -> None:
        if path == "/books/health":
            self.send_text_response(200, "OK")
            return

        if path == "/books/total":
            self.handle_get_books_total(query_params, request_number)
            return

        if path == "/books":
            self.handle_get_books(query_params, request_number)
            return

        if path == "/book":
            self.handle_get_single_book(query_params, request_number)
            return

        error_message = "Error: endpoint not found"
        self.send_json_response(404, build_error_response(error_message))

    def handle_post_request(self, path: str, request_number: int) -> None:
        if path != "/book":
            error_message = "Error: endpoint not found"
            self.send_json_response(404, build_error_response(error_message))
            return

        try:
            book_data = read_json_body(self)

            new_book_title = book_data.get("title")
            existing_books_count = len(books)
            new_book_id = next_book_id

            created_book_id = create_book(book_data)

            books_logger.info(
                f"Creating new Book with Title [{new_book_title}]",
                request_number,
            )
            books_logger.debug(
                f"Currently there are {existing_books_count} Books in the system. "
                f"New Book will be assigned with id {new_book_id}",
                request_number,
            )

            self.send_json_response(200, build_success_response(created_book_id))

        except RuntimeError as error:
            error_message = str(error)
            books_logger.error(error_message, request_number)
            self.send_json_response(409, build_error_response(error_message))

        except ValueError as error:
            self.send_bad_request_response(str(error))

    def handle_put_request(
        self,
        path: str,
        query_params: dict[str, list[str]],
        request_number: int,
    ) -> None:
        if path != "/book":
            error_message = "Error: endpoint not found"
            self.send_json_response(404, build_error_response(error_message))
            return

        try:
            book_id = parse_required_int_query_param(query_params, "id")
            new_price = parse_required_int_query_param(query_params, "price")

        except ValueError as error:
            self.send_bad_request_response(str(error))
            return

        book = get_book_by_id(book_id)

        if book is None:
            error_message = f"Error: no such Book with id {book_id}"
            books_logger.error(error_message, request_number)
            self.send_json_response(404, build_error_response(error_message))
            return

        if new_price <= 0:
            error_message = f"Error: price update for Book [{book_id}] must be a positive integer"
            books_logger.error(error_message, request_number)
            self.send_json_response(409, build_error_response(error_message))
            return

        book_title = book["title"]
        old_price = book["price"]
        update_book_price(book_id, new_price)

        books_logger.info(
            f"Update Book id [{book_id}] price to {new_price}",
            request_number,
        )
        books_logger.debug(
            f"Book [{book_title}] price change: {old_price} --> {new_price}",
            request_number,
        )

        self.send_json_response(200, build_success_response(old_price))

    def handle_delete_request(
        self,
        path: str,
        query_params: dict[str, list[str]],
        request_number: int,
    ) -> None:
        if path != "/book":
            error_message = "Error: endpoint not found"
            self.send_json_response(404, build_error_response(error_message))
            return

        try:
            book_id = parse_required_int_query_param(query_params, "id")

        except ValueError as error:
            self.send_bad_request_response(str(error))
            return

        book = get_book_by_id(book_id)

        if book is None:
            error_message = f"Error: no such book with id {book_id}"
            books_logger.error(error_message, request_number)
            self.send_json_response(404, build_error_response(error_message))
            return

        book_title = book["title"]
        remaining_books_count = delete_book(book_id)

        assert remaining_books_count is not None

        books_logger.info(
            f"Removing book [{book_title}]",
            request_number,
        )
        books_logger.debug(
            f"After removing book [{book_title}] id: [{book_id}] "
            f"there are {remaining_books_count} books in the system",
            request_number,
        )

        self.send_json_response(200, build_success_response(remaining_books_count))

    # ------------------------ concrete GET handlers ------------------------
    def handle_get_books_total(self, query_params: dict[str, list[str]], request_number: int) -> None:
        try:
            filtered_books = apply_book_filters(query_params)

        except ValueError as error:
            self.send_bad_request_response(str(error))
            return

        total_books_found = len(filtered_books)

        books_logger.info(
            f"Total Books found for requested filters is {total_books_found}",
            request_number,
        )

        self.send_json_response(200, build_success_response(total_books_found))

    def handle_get_books(self, query_params: dict[str, list[str]], request_number: int) -> None:
        try:
            filtered_books = apply_book_filters(query_params)

        except ValueError as error:
            self.send_bad_request_response(str(error))
            return

        total_books_found = len(filtered_books)
        sorted_books = sort_books_by_title(filtered_books)

        books_logger.info(
            f"Total Books found for requested filters is {total_books_found}",
            request_number,
        )

        self.send_json_response(200, build_success_response(sorted_books))

    def handle_get_single_book(self, query_params: dict[str, list[str]], request_number: int) -> None:
        try:
            book_id = parse_required_int_query_param(query_params, "id")

        except ValueError as error:
            self.send_bad_request_response(str(error))
            return

        book = get_book_by_id(book_id)

        if book is None:
            error_message = f"Error: no such Book with id {book_id}"
            books_logger.error(error_message, request_number)
            self.send_json_response(404, build_error_response(error_message))
            return

        books_logger.debug(
            f"Fetching book id {book_id} details",
            request_number,
        )

        self.send_json_response(200, build_success_response(book))

    def log_message(self, format: str, *args: Any) -> None:
        return


# ======================== Server runner ========================
def run_server() -> None:
    setup_logs_folder()
    setup_loggers()

    server = HTTPServer((HOST, PORT), BookStoreRequestHandler)

    print(f"Server listening on port {PORT}...", flush=True)

    server.serve_forever()


# ======================== main ========================
def main() -> int:
    try:
        run_server()
        return 0

    except KeyboardInterrupt:
        print("Server stopped by user.", flush=True)
        return 0

    except Exception as error:
        print(f"Error: {error}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())