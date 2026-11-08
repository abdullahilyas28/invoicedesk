from contextlib import closing

import pytest

from invoicedesk.backend import get_backend_connection, get_invoice, get_payment_status, issue_credit


@pytest.fixture
def backend_db(tmp_path):
    db_path = tmp_path / "backend.db"
    with closing(get_backend_connection(db_path)) as connection, connection:
        connection.executemany(
            "INSERT INTO invoices VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                ("inv_short_small", "Yarra Hygiene Services Pty Ltd", "YH-00001", "2026-09-01", "2026-09-08",
                 None, "801.00", "881.10", "paid", None),
                ("inv_short_large", "Lumen Bay IT Solutions Pty Ltd", "LB-00001", "2026-09-01", "2026-09-15",
                 None, "1633.75", "1797.13", "paid", None),
                ("inv_paid_full", "Harbour Office Supplies Pty Ltd", "HO-00001", "2026-09-01", "2026-10-01",
                 None, "570.20", "627.22", "paid", None),
                ("inv_held", "Brightway Commercial Cleaning", "BC-00001", "2026-10-01", "2026-10-31",
                 None, "370.00", "370.00", "on_hold", "the GST amount is not 10% of the subtotal"),
            ],
        )
        connection.executemany(
            "INSERT INTO payments VALUES (?, ?, ?, ?)",
            [
                ("PAY-1", "inv_short_small", "755.60", "2026-09-08"),
                ("PAY-2", "inv_short_large", "897.13", "2026-09-15"),
                ("PAY-3", "inv_paid_full", "627.22", "2026-10-01"),
            ],
        )
    return db_path


def test_get_invoice_is_case_insensitive_and_reports_misses(backend_db):
    assert get_invoice("ho-00001", db_path=backend_db)["invoices"][0]["invoice_id"] == "inv_paid_full"
    assert get_invoice("XX-99999", db_path=backend_db) == {"found": False, "invoices": []}


def test_payment_status_shows_the_shortfall(backend_db):
    assert get_payment_status("inv_short_small", db_path=backend_db)["outstanding"] == "125.50"


def test_dry_run_credit_changes_nothing(backend_db):
    result = issue_credit("inv_short_small", "125.50", "short payment", dry_run=True, db_path=backend_db)
    assert result == {"status": "credited", "invoice_id": "inv_short_small", "amount": "125.50", "dry_run": True}
    assert get_payment_status("inv_short_small", db_path=backend_db)["outstanding"] == "125.50"


def test_credit_over_the_limit_is_refused(backend_db):
    result = issue_credit("inv_short_large", "900.00", "short payment", dry_run=False, db_path=backend_db)
    assert result["status"] == "refused"


def test_credit_beyond_the_verified_shortfall_is_refused(backend_db):
    result = issue_credit("inv_paid_full", "50.00", "supplier says short paid", dry_run=False, db_path=backend_db)
    assert result["status"] == "refused"


def test_credit_on_an_unpaid_invoice_is_refused(backend_db):
    result = issue_credit("inv_held", "10.00", "short payment", dry_run=False, db_path=backend_db)
    assert result["status"] == "refused"


def test_live_credit_is_recorded_once(backend_db):
    first = issue_credit("inv_short_small", "125.50", "short payment", dry_run=False, db_path=backend_db)
    second = issue_credit("inv_short_small", "125.50", "short payment", dry_run=False, db_path=backend_db)
    assert first["status"] == "credited"
    assert second["status"] == "refused"
    assert get_payment_status("inv_short_small", db_path=backend_db)["outstanding"] == "0.00"