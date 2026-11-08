"""Run every invoice document through the pipeline and store the results.

Usage: python scripts/process_all.py
"""
from invoicedesk.pipeline import list_inbox_documents, process_inbox

if __name__ == "__main__":
    route_counts = process_inbox()
    print(f"Processed {len(list_inbox_documents())} invoices: {dict(route_counts)}")