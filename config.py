import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

META_API_KEY = os.getenv("META_API_KEY", "")
META_BASE_URL = os.getenv("META_BASE_URL", "https://api.meta.ai/v1")
META_CACHE = os.getenv("META_CACHE", "off")  # off | record | replay
MAX_SPEND_USD = float(os.getenv("MAX_SPEND_USD", "100"))

DATA_DIR = ROOT / "data"
CASSETTE_DIR = DATA_DIR / "cassettes"
COST_LEDGER = DATA_DIR / "costs.jsonl"
RUNS_DIR = DATA_DIR / "runs"
CHROMIUM_PATH = os.getenv("CHROMIUM_PATH") or None

PORTAL_URL = os.getenv("PORTAL_URL", "http://127.0.0.1:8000")
PORTAL_USER = os.getenv("PORTAL_USER", "operator")
PORTAL_PASSWORD = os.getenv("PORTAL_PASSWORD", "demo123")
