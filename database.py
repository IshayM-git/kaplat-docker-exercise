# ======================== imports ========================
import ast
import json
import os
import time
from typing import Any

from mongoengine import Document, IntField, StringField, connect
from mongoengine.connection import get_db
from sqlalchemy import Integer, String, create_engine, func, select, text
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column


# ======================== Database configuration ========================
POSTGRES_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://postgres:docker@postgres:5432/books",
)
MONGO_URL = os.getenv("MONGO_URL", "mongodb://mongo:27017/books")

engine = create_engine(POSTGRES_URL, pool_pre_ping=True)


# ======================== Database models ========================
class Base(DeclarativeBase):
    pass


class PostgresBook(Base):
    __tablename__ = "books"

    rawid: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    title: Mapped[str] = mapped_column(String)
    author: Mapped[str] = mapped_column(String)
    year: Mapped[int] = mapped_column(Integer)
    price: Mapped[int] = mapped_column(Integer)
    genres: Mapped[str] = mapped_column(String)


class MongoBook(Document):
    rawid = IntField(required=True)
    title = StringField(required=True)
    author = StringField(required=True)
    year = IntField(required=True)
    price = IntField(required=True)
    genres = StringField(required=True)

    meta = {"collection": "books", "strict": False, "auto_create_index": False}


# ======================== Connection setup ========================
def connect_databases() -> None:
    connect(db="books", host=MONGO_URL, serverSelectionTimeoutMS=1000)

    # The database containers may have started before they are ready for queries.
    for attempt in range(40):
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            get_db().command("ping")
            return
        except Exception:
            if attempt == 39:
                raise
            time.sleep(1)


# ======================== Data conversion ========================
def parse_stored_genres(stored_genres: Any) -> list[str]:
    if isinstance(stored_genres, list):
        return stored_genres

    for parser in (json.loads, ast.literal_eval):
        try:
            genres = parser(stored_genres)
            if isinstance(genres, list):
                return genres
        except (ValueError, SyntaxError, TypeError):
            pass

    return [genre.strip() for genre in stored_genres.strip("[]").split(",") if genre.strip()]


def book_to_dict(book: PostgresBook | MongoBook) -> dict[str, Any]:
    return {
        "id": book.rawid,
        "title": book.title,
        "author": book.author,
        "price": book.price,
        "year": book.year,
        "genres": parse_stored_genres(book.genres),
    }


# ======================== Read operations ========================
def get_all_books(persistence_method: str) -> list[dict[str, Any]]:
    if persistence_method == "POSTGRES":
        with Session(engine) as session:
            return [book_to_dict(book) for book in session.scalars(select(PostgresBook))]

    return [book_to_dict(book) for book in MongoBook.objects]


def get_book_by_id(book_id: int, persistence_method: str = "POSTGRES") -> dict[str, Any] | None:
    if persistence_method == "POSTGRES":
        with Session(engine) as session:
            book = session.get(PostgresBook, book_id)
            return book_to_dict(book) if book is not None else None

    book = MongoBook.objects(rawid=book_id).first()
    return book_to_dict(book) if book is not None else None


def get_books_count(persistence_method: str = "POSTGRES") -> int:
    if persistence_method == "POSTGRES":
        with Session(engine) as session:
            return session.scalar(select(func.count()).select_from(PostgresBook)) or 0

    return MongoBook.objects.count()


def get_highest_book_id() -> int:
    with Session(engine) as session:
        postgres_id = session.scalar(select(func.max(PostgresBook.rawid))) or 0

    mongo_book = MongoBook.objects.order_by("-rawid").only("rawid").first()
    mongo_id = mongo_book.rawid if mongo_book is not None else 0
    return max(postgres_id, mongo_id)


# ======================== Write operations ========================
def create_book(book: dict[str, Any]) -> None:
    stored_genres = json.dumps(book["genres"])
    book_fields = {
        "rawid": book["id"],
        "title": book["title"],
        "author": book["author"],
        "year": book["year"],
        "price": book["price"],
        "genres": stored_genres,
    }

    with Session(engine) as session:
        postgres_book = PostgresBook(**book_fields)
        mongo_book = MongoBook(**book_fields)
        session.add(postgres_book)
        session.flush()
        mongo_book.save(force_insert=True)

        try:
            session.commit()
        except Exception:
            # If PostgreSQL could not commit, undo the MongoDB insertion.
            mongo_book.delete()
            raise


def update_book_price(book_id: int, new_price: int) -> None:
    with Session(engine) as session:
        postgres_book = session.get(PostgresBook, book_id)
        if postgres_book is None:
            raise RuntimeError(f"Book [{book_id}] not found in PostgreSQL")

        old_price = postgres_book.price
        postgres_book.price = new_price
        session.flush()

        modified = MongoBook.objects(rawid=book_id).update_one(set__price=new_price)
        if modified != 1:
            raise RuntimeError(f"Book [{book_id}] not found in MongoDB")

        try:
            session.commit()
        except Exception:
            MongoBook.objects(rawid=book_id).update_one(set__price=old_price)
            raise


def delete_book(book_id: int) -> int:
    with Session(engine) as session:
        postgres_book = session.get(PostgresBook, book_id)
        mongo_book = MongoBook.objects(rawid=book_id).first()
        if postgres_book is None or mongo_book is None:
            raise RuntimeError(f"Book [{book_id}] not found in both databases")

        session.delete(postgres_book)
        session.flush()
        mongo_book.delete()

        try:
            session.commit()
        except Exception:
            mongo_book.save(force_insert=True)
            raise

    return get_books_count("POSTGRES")
