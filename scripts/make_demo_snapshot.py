"""Create data/demo/invoicedesk.db: cached extractions and agent runs, with no review state.

Run after any change that affects extractions or agent runs, then commit the snapshot.
Usage: python scripts/make_demo_snapshot.py
"""
import shutil
import sqlite3
from contextlib import closing

from invoicedesk.db import DB_PATH, DEMO_DB_PATH
from invoicedesk.extract import PROMPT_VERSION

if __name__ == "__main__":
    DEMO_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(DB_PATH, DEMO_DB_PATH)
    with closing(sqlite3.connect(DEMO_DB_PATH)) as connection:
        with connection:
            connection.execute("DELETE FROM corrections")
            connection.execute("DELETE FROM processed_invoices")
            connection.execute(
                "DELETE FROM extraction_cache WHERE cache_key NOT LIKE ?", (f"%:{PROMPT_VERSION}:%",)
            )
        connection.execute("VACUUM")
        cached_count = connection.execute("SELECT COUNT(*) FROM extraction_cache").fetchone()[0]
        resolution_count = connection.execute("SELECT COUNT(*) FROM ticket_resolutions").fetchone()[0]
    size_kb = DEMO_DB_PATH.stat().st_size // 1024
    print(f"Wrote {DEMO_DB_PATH}: {cached_count} cached extractions, {resolution_count} agent runs, {size_kb} KB")