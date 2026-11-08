"""Runtime settings, read from environment variables (.env locally, Streamlit secrets when deployed)."""
import os

from dotenv import load_dotenv

load_dotenv()

DEMO_MODE = os.environ.get("INVOICEDESK_DEMO_MODE") == "1"