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

CREATE TABLE IF NOT EXISTS processed_invoices (
    file_id TEXT PRIMARY KEY,
    document_filename TEXT NOT NULL,
    supplier_name TEXT NOT NULL,
    extracted_json TEXT NOT NULL,
    confidence_json TEXT NOT NULL,
    review_reasons_json TEXT NOT NULL,
    route TEXT NOT NULL,
    status TEXT NOT NULL,
    reviewed_json TEXT,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS corrections (
    correction_id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id TEXT NOT NULL,
    supplier_key TEXT NOT NULL,
    field_name TEXT NOT NULL,
    wrong_value TEXT,
    correct_value TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS ticket_resolutions (
    ticket_id TEXT PRIMARY KEY,
    resolution_json TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

UNREVIEWED_STATUSES = ("auto_approved", "needs_review")


def get_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.executescript(SCHEMA)
    return connection


# ---------------------------------------------------------------------------
# Extraction cache
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Processed invoices
# ---------------------------------------------------------------------------


def save_processed_invoice(
    file_id: str,
    document_filename: str,
    supplier_name: str,
    extracted_json: str,
    confidence_json: str,
    review_reasons_json: str,
    route: str,
    status: str,
) -> None:
    """
    Insert or update an invoice's pipeline result, but never overwrite one a human has reviewed.
    """
    with closing(get_connection()) as connection, connection:
        connection.execute(
            f"""
            INSERT INTO processed_invoices
                (file_id, document_filename, supplier_name, extracted_json, confidence_json,
                 review_reasons_json, route, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(file_id) DO UPDATE SET
                document_filename = excluded.document_filename,
                supplier_name = excluded.supplier_name,
                extracted_json = excluded.extracted_json,
                confidence_json = excluded.confidence_json,
                review_reasons_json = excluded.review_reasons_json,
                route = excluded.route,
                status = excluded.status,
                updated_at = CURRENT_TIMESTAMP
            WHERE processed_invoices.status IN {UNREVIEWED_STATUSES}
            """,
            (file_id, document_filename, supplier_name, extracted_json, confidence_json,
             review_reasons_json, route, status),
        )


def list_processed_invoices(status: str | None = None) -> list[sqlite3.Row]:
    with closing(get_connection()) as connection:
        if status is None:
            return connection.execute("SELECT * FROM processed_invoices ORDER BY file_id").fetchall()
        return connection.execute(
            "SELECT * FROM processed_invoices WHERE status = ? ORDER BY file_id", (status,)
        ).fetchall()


def get_processed_invoice(file_id: str) -> sqlite3.Row | None:
    with closing(get_connection()) as connection:
        return connection.execute(
            "SELECT * FROM processed_invoices WHERE file_id = ?", (file_id,)
        ).fetchone()


def save_review(file_id: str, reviewed_json: str, status: str) -> None:
    with closing(get_connection()) as connection, connection:
        connection.execute(
            """
            UPDATE processed_invoices
            SET reviewed_json = ?, status = ?, updated_at = CURRENT_TIMESTAMP
            WHERE file_id = ?
            """,
            (reviewed_json, status, file_id),
        )


def clear_processed_invoices() -> None:
    """
    Full reset, including human reviews. Not used by the batch job.
    """
    with closing(get_connection()) as connection, connection:
        connection.execute("DELETE FROM processed_invoices")


# ---------------------------------------------------------------------------
# Corrections
# ---------------------------------------------------------------------------


def save_corrections(
    file_id: str, supplier_key: str, corrections: list[tuple[str, str | None, str | None]]
) -> None:
    with closing(get_connection()) as connection, connection:
        connection.executemany(
            """
            INSERT INTO corrections (file_id, supplier_key, field_name, wrong_value, correct_value)
            VALUES (?, ?, ?, ?, ?)
            """,
            [(file_id, supplier_key, field_name, wrong_value, correct_value)
             for field_name, wrong_value, correct_value in corrections],
        )


def get_corrections_for_supplier(supplier_key: str, limit: int = 10) -> list[tuple[str, str | None, str | None]]:
    """
    Most recent corrections first, as (field_name, wrong_value, correct_value).
    """
    with closing(get_connection()) as connection:
        rows = connection.execute(
            """
            SELECT field_name, wrong_value, correct_value FROM corrections
            WHERE supplier_key = ?
            ORDER BY correction_id DESC
            LIMIT ?
            """,
            (supplier_key, limit),
        ).fetchall()
    return [tuple(row) for row in rows]

def list_corrections() -> list[sqlite3.Row]:
    with closing(get_connection()) as connection:
        return connection.execute("SELECT * FROM corrections ORDER BY correction_id").fetchall()
    

# ---------------------------------------------------------------------------
# Ticket resolutions
# ---------------------------------------------------------------------------


def save_ticket_resolution(ticket_id: str, resolution_json: str) -> None:
    with closing(get_connection()) as connection, connection:
        connection.execute(
            "INSERT OR REPLACE INTO ticket_resolutions (ticket_id, resolution_json) VALUES (?, ?)",
            (ticket_id, resolution_json),
        )


def list_ticket_resolutions() -> dict[str, str]:
    """
    ticket_id -> resolution_json for every stored resolution.
    """
    with closing(get_connection()) as connection:
        rows = connection.execute("SELECT ticket_id, resolution_json FROM ticket_resolutions").fetchall()
    return {row["ticket_id"]: row["resolution_json"] for row in rows}