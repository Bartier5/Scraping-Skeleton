# ── config/config.py ─────────────────────────────────────────────────────────
# Central configuration hub for the entire scraper skeleton.
# Every other module imports settings from here.
# Values are read from the .env file — nothing is hardcoded.

from dotenv import load_dotenv  # reads key=value pairs from .env into os.environ
import os                       # standard library — access environment variables

# Call load_dotenv() once here so every module that imports Config
# automatically gets the .env values loaded into the environment
load_dotenv()


class Config:
    # ── Request Behavior ─────────────────────────────────────────────────────
    # How long (seconds) before we give up waiting for a response
    TIMEOUT: int = int(os.getenv("TIMEOUT", 30))

    # How many times to retry a failed request before giving up
    MAX_RETRIES: int = int(os.getenv("MAX_RETRIES", 3))

    # Max number of simultaneous async requests (used in batch_fetcher)
    CONCURRENCY: int = int(os.getenv("CONCURRENCY", 10))

    # Seconds to wait between requests to the same domain (polite scraping)
    DELAY_BETWEEN_REQUESTS: float = float(os.getenv("DELAY_BETWEEN_REQUESTS", 1.5))

    # ── Logging ──────────────────────────────────────────────────────────────
    # Minimum log level to display: DEBUG, INFO, WARNING, ERROR, CRITICAL
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "DEBUG")

    # Path to the log file — loguru will create it if it doesn't exist
    LOG_FILE: str = os.getenv("LOG_FILE", "logs/scraper.log")

    # ── Storage ──────────────────────────────────────────────────────────────
    # Which storage backend to use: "csv", "sqlite", or "postgres"
    STORAGE_BACKEND: str = os.getenv("STORAGE_BACKEND", "sqlite")

    # SQLite connection string (used by sqlite_storage and checkpoint_manager)
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///data/scraper.db")

    # PostgreSQL connection string (used on Day 11)
    POSTGRES_URL: str = os.getenv("POSTGRES_URL", "")

    # ── Anti-Bot ─────────────────────────────────────────────────────────────
    # Path to a text file containing one proxy per line (used on Day 12)
    PROXY_LIST: str = os.getenv("PROXY_LIST", "proxies.txt")

    # ── Paths ────────────────────────────────────────────────────────────────
    # Where scraped output files go (CSV, Excel, JSON exports)
    OUTPUT_DIR: str = os.getenv("OUTPUT_DIR", "data/")

    # Where log files are written
    LOG_DIR: str = os.getenv("LOG_DIR", "logs/")
