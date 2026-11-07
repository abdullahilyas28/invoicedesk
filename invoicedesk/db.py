"""SQLite storage for InvoiceDesk. One file, created automatically on first use."""
import sqlite3
from contextlib import closing
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "invoicedesk.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS extraction_cache (
    cache_key TEXT PRIMARY KEY,
    response_text TEXT NOT NULL,
    model TEXT NOT NULL,
    input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    latency_seconds REAL NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


def get_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.executescript(SCHEMA)
    return connection


def get_cached_response(cache_key: str) -> sqlite3.Row | None:
    with closing(get_connection()) as connection:
        return connection.execute(
            "SELECT * FROM extraction_cache WHERE cache_key = ?", (cache_key,)
        ).fetchone()


def save_cached_response(
    cache_key: str,
    response_text: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    latency_seconds: float,
) -> None:
    with closing(get_connection()) as connection, connection:
        connection.execute(
            """
            INSERT OR REPLACE INTO extraction_cache
                (cache_key, response_text, model, input_tokens, output_tokens, latency_seconds)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (cache_key, response_text, model, input_tokens, output_tokens, latency_seconds),
        )