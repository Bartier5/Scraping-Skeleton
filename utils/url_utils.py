# ── utils/url_utils.py ───────────────────────────────────────────────────────
# Everything related to working with lists of URLs before a scrape begins.
# Think of this as the URL pre-processor — it takes raw URL inputs and
# cleans, validates, deduplicates, and organizes them so the fetcher
# always receives a clean, ready-to-use list.
#
# Used by: batch_fetcher.py, batch_spider.py, scheduler
#
# Usage:
#   from utils.url_utils import prepare_urls, chunk_urls, group_by_domain

import re                               # regular expressions for URL pattern matching
from urllib.parse import (
    urlparse,                           # break URL into components (scheme, domain, path...)
    urljoin,                            # safely join base URL + relative path
    urlunparse,                         # rebuild a URL from its components
    urlencode,                          # convert dict → "key=value&key2=value2"
)
from typing import Generator            # type hint for generator functions
from utils.logger import log            # consistent logging
from utils.helpers import is_valid_url, get_domain   # reuse Day 1 helpers


# ── Validation ────────────────────────────────────────────────────────────────

def validate_urls(urls: list[str]) -> tuple[list[str], list[str]]:
    """
    Splits a list of URLs into two lists: valid and invalid.
    Returns a tuple of (valid_urls, invalid_urls).

    This lets the caller decide what to do with bad URLs —
    log them, skip them, or raise an error.

    Example:
        valid, invalid = validate_urls(["https://example.com", "bad-url"])
        # valid   → ["https://example.com"]
        # invalid → ["bad-url"]
    """
    valid = []
    invalid = []

    for url in urls:
        if is_valid_url(url):           # reusing our Day 1 helper
            valid.append(url)
        else:
            invalid.append(url)
            log.warning("Invalid URL skipped: {}", url)

    log.info("URL validation: {} valid, {} invalid", len(valid), len(invalid))
    return valid, invalid


# ── Deduplication ─────────────────────────────────────────────────────────────

def deduplicate_urls(urls: list[str]) -> list[str]:
    """
    Removes duplicate URLs while preserving the original order.

    Why preserve order? Because the caller may have intentionally ordered
    URLs by priority — reversing or scrambling that would be unexpected.

    Uses dict.fromkeys() which is faster than a loop and preserves order
    (unlike set() which randomizes order).

    Example:
        deduplicate_urls(["https://a.com", "https://b.com", "https://a.com"])
        → ["https://a.com", "https://b.com"]
    """
    original_count = len(urls)

    # dict.fromkeys() creates a dict where each URL is a key (keys are unique)
    # then we convert back to a list — duplicates are gone, order preserved
    deduped = list(dict.fromkeys(urls))

    removed = original_count - len(deduped)
    if removed > 0:
        log.info("Deduplication removed {} duplicate URLs", removed)

    return deduped


# ── Normalization ─────────────────────────────────────────────────────────────

def normalize_url(url: str) -> str:
    """
    Standardizes a URL to a consistent format so that URLs pointing to the
    same page are not treated as different due to minor formatting differences.

    What it normalizes:
    - Strips trailing slashes          example.com/page/ → example.com/page
    - Lowercases the scheme and domain HTTPS://EXAMPLE.COM → https://example.com
    - Removes default ports            example.com:80 → example.com
    - Removes fragments                example.com/page#section → example.com/page

    Why this matters: Without normalization, "https://example.com/page/" and
    "https://example.com/page" would be treated as different URLs and scraped twice.

    Example:
        normalize_url("HTTPS://Example.COM/page/#section")
        → "https://example.com/page"
    """
    parsed = urlparse(url)

    # Lowercase the scheme (https) and netloc (domain) only
    # the path is case-sensitive on some servers so we leave it alone
    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()

    # Remove default ports that are implied anyway
    # :80 is the default for http, :443 is the default for https
    netloc = netloc.replace(":80", "").replace(":443", "")

    # Strip trailing slash from the path
    path = parsed.path.rstrip("/")

    # Rebuild the URL — we drop the fragment (#section) entirely
    # fragments are browser-only, servers ignore them
    normalized = urlunparse((scheme, netloc, path, parsed.params, parsed.query, ""))

    return normalized


def normalize_urls(urls: list[str]) -> list[str]:
    """
    Applies normalize_url() to every URL in a list.
    Skips invalid URLs and logs a warning for each one.
    """
    normalized = []
    for url in urls:
        if is_valid_url(url):
            normalized.append(normalize_url(url))
        else:
            log.warning("Skipping normalization for invalid URL: {}", url)
    return normalized


# ── Chunking ──────────────────────────────────────────────────────────────────

def chunk_urls(urls: list[str], chunk_size: int) -> Generator[list[str], None, None]:
    """
    Splits a large list of URLs into smaller batches (chunks).
    Returns a generator — chunks are produced one at a time, not all at once,
    which is memory-efficient for very large URL lists.

    Used by batch_fetcher.py to process URLs in controlled batches
    instead of firing all requests simultaneously.

    Example:
        list(chunk_urls(["a","b","c","d","e"], chunk_size=2))
        → [["a","b"], ["c","d"], ["e"]]

    Args:
        urls:       list of URLs to split
        chunk_size: how many URLs per batch
    """
    if chunk_size <= 0:
        # Guard against invalid chunk sizes that would cause infinite loops
        raise ValueError(f"chunk_size must be > 0, got {chunk_size}")

    total_chunks = (len(urls) + chunk_size - 1) // chunk_size  # ceiling division
    log.debug("Chunking {} URLs into batches of {} ({} total chunks)",
              len(urls), chunk_size, total_chunks)

    # range(start, stop, step) — step through the list in chunk_size increments
    for i in range(0, len(urls), chunk_size):
        yield urls[i : i + chunk_size]   # yield one chunk at a time


# ── Domain Grouping ───────────────────────────────────────────────────────────

def group_by_domain(urls: list[str]) -> dict[str, list[str]]:
    """
    Groups URLs by their domain into a dictionary.
    Used by the rate limiter to apply per-domain request throttling.

    Example:
        group_by_domain([
            "https://amazon.com/product/1",
            "https://ebay.com/item/1",
            "https://amazon.com/product/2",
        ])
        → {
            "amazon.com": ["https://amazon.com/product/1", "https://amazon.com/product/2"],
            "ebay.com":   ["https://ebay.com/item/1"]
          }
    """
    grouped: dict[str, list[str]] = {}

    for url in urls:
        domain = get_domain(url)        # extract domain using Day 1 helper

        if domain not in grouped:
            grouped[domain] = []        # create a new list for this domain

        grouped[domain].append(url)     # add URL to its domain's list

    # Log a summary of how many URLs belong to each domain
    for domain, domain_urls in grouped.items():
        log.debug("Domain '{}': {} URLs", domain, len(domain_urls))

    return grouped


# ── Relative URL Resolution ────────────────────────────────────────────────────

def resolve_relative_urls(base_url: str, urls: list[str]) -> list[str]:
    """
    Converts relative URLs (like "/page-2.html") to absolute URLs
    by combining them with a base URL.

    When you scrape a page, links are often relative — they only make
    sense in the context of the site they came from. This function
    makes them standalone and usable by the fetcher.

    Example:
        base = "https://books.toscrape.com"
        urls = ["/catalogue/page-2.html", "https://other.com/page"]

        resolve_relative_urls(base, urls)
        → ["https://books.toscrape.com/catalogue/page-2.html",
           "https://other.com/page"]   ← absolute URLs are left unchanged
    """
    resolved = []
    for url in urls:
        # urljoin is smart — if url is already absolute it returns it unchanged
        # if url is relative it combines it with base_url correctly
        absolute = urljoin(base_url, url)
        resolved.append(absolute)

    log.debug("Resolved {} relative URLs against base: {}", len(resolved), base_url)
    return resolved


# ── URL Pagination Builder ────────────────────────────────────────────────────

def build_paginated_urls(
    base_url: str,
    total_pages: int,
    page_param: str = "page",
    start_page: int = 1,
) -> list[str]:
    """
    Generates a list of paginated URLs for a given base URL.
    Useful for scraping sites that paginate results with a ?page=N parameter.

    Example:
        build_paginated_urls("https://example.com/products", total_pages=3)
        → [
            "https://example.com/products?page=1",
            "https://example.com/products?page=2",
            "https://example.com/products?page=3",
          ]

    Args:
        base_url:    the URL without any page parameter
        total_pages: how many pages to generate
        page_param:  the query parameter name (default: "page")
        start_page:  which page number to start from (default: 1)
    """
    urls = []
    for page_num in range(start_page, start_page + total_pages):
        # urlencode converts {"page": 1} → "page=1"
        query = urlencode({page_param: page_num})
        urls.append(f"{base_url}?{query}")

    log.debug("Built {} paginated URLs from: {}", len(urls), base_url)
    return urls


# ── Master Prepare Function ───────────────────────────────────────────────────

def prepare_urls(urls: list[str]) -> list[str]:
    """
    One-stop function that runs a raw URL list through the full
    preparation pipeline before handing it to the fetcher:

        1. Normalize  → standardize format
        2. Validate   → remove invalid URLs
        3. Deduplicate → remove duplicates

    This is what the spider will call before every scrape run.

    Example:
        raw = [
            "HTTPS://Example.COM/page/",
            "https://example.com/page",   ← duplicate after normalization
            "not-a-url",                  ← invalid, will be removed
            "https://other.com/data",
        ]
        prepare_urls(raw)
        → ["https://example.com/page", "https://other.com/data"]
    """
    log.info("Preparing {} raw URLs...", len(urls))

    # Step 1 — normalize formatting
    urls = normalize_urls(urls)

    # Step 2 — validate and filter out bad URLs
    urls, invalid = validate_urls(urls)

    # Step 3 — remove duplicates (normalization may have created new ones)
    urls = deduplicate_urls(urls)

    log.info("URL preparation complete: {} clean URLs ready", len(urls))
    return urls
