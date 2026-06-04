# ── utils/helpers.py ─────────────────────────────────────────────────────────
# General purpose utility functions used across the entire skeleton.
# These are small, focused helpers that don't belong to any single layer —
# think of this as the miscellaneous toolkit every module can pull from.

import os                           # file system operations
import hashlib                      # generate content hashes for deduplication
import re                           # regular expressions for text cleaning
from datetime import datetime       # timestamp generation
from pathlib import Path            # modern, OS-agnostic file path handling
from urllib.parse import (
    urlparse,                       # break a URL into its components
    urljoin,                        # safely join a base URL with a relative path
    urlencode,                      # encode a dict into a URL query string
)
from utils.logger import log        # consistent logging across all helpers


# ── Directory Helpers ─────────────────────────────────────────────────────────

def ensure_dir(path: str) -> str:
    """
    Creates a directory (and any missing parent directories) if it doesn't exist.
    Returns the path so it can be used inline.

    Example:
        filepath = ensure_dir("data/outputs") + "/results.csv"
    """
    Path(path).mkdir(parents=True, exist_ok=True)  # parents=True creates nested dirs
    return path


# ── Timestamp Helpers ─────────────────────────────────────────────────────────

def timestamp(fmt: str = "%Y%m%d_%H%M%S") -> str:
    """
    Returns the current datetime as a formatted string.
    Default format is sortable and safe for use in filenames.

    Example:
        filename = f"scrape_{timestamp()}.csv"  →  "scrape_20250604_143022.csv"
    """
    return datetime.now().strftime(fmt)


def readable_timestamp() -> str:
    """
    Returns a human-readable timestamp for logging and display purposes.

    Example output: "2025-06-04 14:30:22"
    """
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ── URL Helpers ───────────────────────────────────────────────────────────────

def get_domain(url: str) -> str:
    """
    Extracts the domain (netloc) from a full URL.
    Used by the rate limiter to group requests by domain.

    Example:
        get_domain("https://books.toscrape.com/catalogue/page-2.html")
        → "books.toscrape.com"
    """
    return urlparse(url).netloc


def build_url(base: str, path: str = "", params: dict = None) -> str:
    """
    Safely constructs a full URL from a base URL, optional path, and
    optional query parameters.

    Example:
        build_url("https://api.example.com", "/search", {"q": "python", "page": 1})
        → "https://api.example.com/search?q=python&page=1"
    """
    # urljoin handles trailing/leading slashes correctly
    full = urljoin(base, path) if path else base

    if params:
        # urlencode converts {"key": "val"} → "key=val" query string
        full += "?" + urlencode(params)

    return full


def is_valid_url(url: str) -> bool:
    """
    Returns True if the string is a properly formed HTTP/HTTPS URL.
    Used in url_utils.py to filter bad URLs before batch runs.

    Example:
        is_valid_url("https://example.com")  → True
        is_valid_url("not-a-url")            → False
    """
    try:
        parsed = urlparse(url)
        # A valid URL must have both a scheme (http/https) and a netloc (domain)
        return parsed.scheme in ("http", "https") and bool(parsed.netloc)
    except Exception:
        return False


# ── Hashing Helpers ───────────────────────────────────────────────────────────

def hash_content(content: str) -> str:
    """
    Returns an MD5 hash of a string. Used by checkpoint_manager to detect
    whether a page's content has changed since the last scrape (delta scraping).

    MD5 is fast and collision-resistant enough for this use case.

    Example:
        hash_content("<html>...</html>")  → "d41d8cd98f00b204e9800998ecf8427e"
    """
    return hashlib.md5(content.encode("utf-8")).hexdigest()


def hash_url(url: str) -> str:
    """
    Returns a short hash of a URL. Used as a unique key for storing
    checkpoints without saving the full URL string everywhere.

    Example:
        hash_url("https://example.com/page-1")  → "a1b2c3d4..."
    """
    return hashlib.md5(url.encode("utf-8")).hexdigest()


# ── Text Cleaning Helpers ─────────────────────────────────────────────────────

def clean_text(text: str) -> str:
    """
    Strips leading/trailing whitespace and collapses internal whitespace
    (multiple spaces, tabs, newlines) into a single space.

    Used in the cleaner pipeline to normalize raw scraped text.

    Example:
        clean_text("  Hello   \n  World  ")  → "Hello World"
    """
    if not text:
        return ""
    # \s+ matches any whitespace sequence (spaces, tabs, newlines)
    return re.sub(r"\s+", " ", text).strip()


def slugify(text: str) -> str:
    """
    Converts a string into a lowercase, hyphen-separated slug.
    Safe for use in filenames and URL paths.

    Example:
        slugify("Latest Products 2025!")  → "latest-products-2025"
    """
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)      # remove non-alphanumeric characters
    text = re.sub(r"[\s_]+", "-", text)        # replace spaces/underscores with hyphens
    text = re.sub(r"-+", "-", text)            # collapse multiple hyphens
    return text


# ── File Helpers ──────────────────────────────────────────────────────────────

def get_output_path(filename: str, output_dir: str = "data/") -> str:
    """
    Builds a full output file path, ensuring the output directory exists.

    Example:
        get_output_path("results.csv")  → "data/results.csv"
        get_output_path("report.xlsx", "exports/")  → "exports/report.xlsx"
    """
    ensure_dir(output_dir)
    return os.path.join(output_dir, filename)


def file_exists(path: str) -> bool:
    """
    Simple check — returns True if a file exists at the given path.
    Used in checkpoint_manager and storage layers.
    """
    return Path(path).is_file()
