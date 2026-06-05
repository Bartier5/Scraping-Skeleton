# ── tests/test_day2.py ────────────────────────────────────────────────────────
# Isolation tests for Day 2 modules: url_utils.py and rate_limiter.py
# Run with: pytest tests/test_day2.py -v

import pytest
import asyncio
import time


# ── url_utils Tests ───────────────────────────────────────────────────────────

class TestValidateUrls:
    """Tests for validate_urls() — splits valid from invalid URLs."""

    def test_valid_urls_pass(self):
        from utils.url_utils import validate_urls
        valid, invalid = validate_urls([
            "https://example.com",
            "http://books.toscrape.com/page-1",
        ])
        assert len(valid) == 2
        assert len(invalid) == 0

    def test_invalid_urls_caught(self):
        from utils.url_utils import validate_urls
        valid, invalid = validate_urls(["not-a-url", "", "ftp://files.com"])
        assert len(valid) == 0
        assert len(invalid) == 3

    def test_mixed_list(self):
        from utils.url_utils import validate_urls
        valid, invalid = validate_urls([
            "https://good.com",
            "bad-url",
            "https://also-good.com",
            "",
        ])
        assert len(valid) == 2
        assert len(invalid) == 2


class TestDeduplicateUrls:
    """Tests for deduplicate_urls() — removes duplicates preserving order."""

    def test_removes_exact_duplicates(self):
        from utils.url_utils import deduplicate_urls
        urls = ["https://a.com", "https://b.com", "https://a.com"]
        result = deduplicate_urls(urls)
        assert result == ["https://a.com", "https://b.com"]

    def test_preserves_order(self):
        from utils.url_utils import deduplicate_urls
        urls = ["https://c.com", "https://a.com", "https://b.com"]
        result = deduplicate_urls(urls)
        # Order must be preserved exactly
        assert result == ["https://c.com", "https://a.com", "https://b.com"]

    def test_no_duplicates_unchanged(self):
        from utils.url_utils import deduplicate_urls
        urls = ["https://a.com", "https://b.com"]
        assert deduplicate_urls(urls) == urls

    def test_empty_list(self):
        from utils.url_utils import deduplicate_urls
        assert deduplicate_urls([]) == []


class TestNormalizeUrl:
    """Tests for normalize_url() — standardizes URL format."""

    def test_lowercase_scheme(self):
        from utils.url_utils import normalize_url
        assert normalize_url("HTTPS://example.com").startswith("https://")

    def test_lowercase_domain(self):
        from utils.url_utils import normalize_url
        assert "EXAMPLE" not in normalize_url("https://EXAMPLE.COM/page")

    def test_removes_trailing_slash(self):
        from utils.url_utils import normalize_url
        assert normalize_url("https://example.com/page/") == "https://example.com/page"

    def test_removes_fragment(self):
        from utils.url_utils import normalize_url
        # Fragment (#section) is browser-only, should be stripped
        result = normalize_url("https://example.com/page#section")
        assert "#section" not in result

    def test_removes_default_port_80(self):
        from utils.url_utils import normalize_url
        result = normalize_url("http://example.com:80/page")
        assert ":80" not in result

    def test_removes_default_port_443(self):
        from utils.url_utils import normalize_url
        result = normalize_url("https://example.com:443/page")
        assert ":443" not in result


class TestChunkUrls:
    """Tests for chunk_urls() — splits URLs into batches."""

    def test_even_split(self):
        from utils.url_utils import chunk_urls
        urls = ["a", "b", "c", "d"]
        chunks = list(chunk_urls(urls, chunk_size=2))
        assert chunks == [["a", "b"], ["c", "d"]]

    def test_uneven_split_last_chunk_smaller(self):
        from utils.url_utils import chunk_urls
        urls = ["a", "b", "c", "d", "e"]
        chunks = list(chunk_urls(urls, chunk_size=2))
        # Last chunk has only 1 item — that's correct
        assert chunks == [["a", "b"], ["c", "d"], ["e"]]

    def test_chunk_larger_than_list(self):
        from utils.url_utils import chunk_urls
        urls = ["a", "b"]
        chunks = list(chunk_urls(urls, chunk_size=10))
        # One chunk containing all URLs
        assert chunks == [["a", "b"]]

    def test_chunk_size_zero_raises(self):
        from utils.url_utils import chunk_urls
        with pytest.raises(ValueError):
            list(chunk_urls(["a", "b"], chunk_size=0))

    def test_all_urls_preserved(self):
        from utils.url_utils import chunk_urls
        urls = [f"https://example.com/page-{i}" for i in range(10)]
        chunks = list(chunk_urls(urls, chunk_size=3))
        # Flatten all chunks and verify every URL is present
        all_urls = [url for chunk in chunks for url in chunk]
        assert all_urls == urls


class TestGroupByDomain:
    """Tests for group_by_domain() — organizes URLs by domain."""

    def test_groups_correctly(self):
        from utils.url_utils import group_by_domain
        urls = [
            "https://amazon.com/product/1",
            "https://ebay.com/item/1",
            "https://amazon.com/product/2",
        ]
        grouped = group_by_domain(urls)
        assert "amazon.com" in grouped
        assert "ebay.com" in grouped
        assert len(grouped["amazon.com"]) == 2
        assert len(grouped["ebay.com"]) == 1

    def test_single_domain(self):
        from utils.url_utils import group_by_domain
        urls = ["https://example.com/1", "https://example.com/2"]
        grouped = group_by_domain(urls)
        assert len(grouped) == 1
        assert len(grouped["example.com"]) == 2


class TestResolveRelativeUrls:
    """Tests for resolve_relative_urls() — converts relative to absolute URLs."""

    def test_resolves_relative(self):
        from utils.url_utils import resolve_relative_urls
        base = "https://books.toscrape.com"
        urls = ["/catalogue/page-2.html"]
        result = resolve_relative_urls(base, urls)
        assert result[0] == "https://books.toscrape.com/catalogue/page-2.html"

    def test_leaves_absolute_unchanged(self):
        from utils.url_utils import resolve_relative_urls
        base = "https://books.toscrape.com"
        absolute = "https://other.com/page"
        result = resolve_relative_urls(base, [absolute])
        # Absolute URL should pass through unchanged
        assert result[0] == absolute


class TestBuildPaginatedUrls:
    """Tests for build_paginated_urls() — generates paginated URL lists."""

    def test_correct_count(self):
        from utils.url_utils import build_paginated_urls
        urls = build_paginated_urls("https://example.com/products", total_pages=5)
        assert len(urls) == 5

    def test_page_numbers_correct(self):
        from utils.url_utils import build_paginated_urls
        urls = build_paginated_urls("https://example.com/products", total_pages=3)
        assert "page=1" in urls[0]
        assert "page=2" in urls[1]
        assert "page=3" in urls[2]

    def test_custom_page_param(self):
        from utils.url_utils import build_paginated_urls
        urls = build_paginated_urls(
            "https://example.com/products",
            total_pages=2,
            page_param="p"
        )
        assert "p=1" in urls[0]
        assert "p=2" in urls[1]

    def test_custom_start_page(self):
        from utils.url_utils import build_paginated_urls
        urls = build_paginated_urls(
            "https://example.com/products",
            total_pages=3,
            start_page=5
        )
        assert "page=5" in urls[0]
        assert "page=7" in urls[2]


class TestPrepareUrls:
    """Tests for prepare_urls() — full pipeline: normalize + validate + dedup."""

    def test_removes_invalid(self):
        from utils.url_utils import prepare_urls
        urls = ["https://example.com", "not-a-url"]
        result = prepare_urls(urls)
        assert len(result) == 1
        assert result[0] == "https://example.com"

    def test_deduplicates_after_normalization(self):
        from utils.url_utils import prepare_urls
        # These are the same URL — one has trailing slash, one uppercase
        urls = [
            "https://example.com/page/",
            "HTTPS://example.com/page",
        ]
        result = prepare_urls(urls)
        # After normalization both become "https://example.com/page"
        # After dedup only one remains
        assert len(result) == 1

    def test_empty_list(self):
        from utils.url_utils import prepare_urls
        assert prepare_urls([]) == []


# ── rate_limiter Tests ────────────────────────────────────────────────────────

class TestRateLimiter:
    """Tests for RateLimiter — per-domain async rate limiting."""

    def test_initializes_correctly(self):
        from utils.rate_limiter import RateLimiter
        limiter = RateLimiter(rate=2.0, burst=1)
        assert limiter.rate == 2.0
        assert limiter.burst == 1

    def test_defaults_from_config(self):
        from utils.rate_limiter import RateLimiter
        from config.config import Config
        limiter = RateLimiter()
        # Rate should be derived from config delay
        expected_rate = 1.0 / Config.DELAY_BETWEEN_REQUESTS
        assert abs(limiter.rate - expected_rate) < 0.01   # floating point tolerance

    def test_creates_limiter_per_domain(self):
        from utils.rate_limiter import RateLimiter
        limiter = RateLimiter(rate=10.0)

        async def run():
            await limiter.wait("amazon.com")
            await limiter.wait("ebay.com")
            stats = limiter.get_stats()
            assert stats["tracked_domains"] == 2
            assert "amazon.com" in stats["domains"]
            assert "ebay.com" in stats["domains"]

        asyncio.run(run())

    def test_acquire_does_not_block_at_high_rate(self):
        # At a very high rate limit, acquire() should return almost instantly
        from utils.rate_limiter import RateLimiter
        limiter = RateLimiter(rate=1000.0)   # 1000 req/s — effectively no limit

        async def run():
            start = time.time()
            await limiter.wait("example.com")
            elapsed = time.time() - start
            # Should complete in well under 1 second
            assert elapsed < 0.5

        asyncio.run(run())

    def test_reset_single_domain(self):
        from utils.rate_limiter import RateLimiter
        limiter = RateLimiter(rate=10.0)

        async def run():
            await limiter.wait("amazon.com")
            await limiter.wait("ebay.com")
            limiter.reset("amazon.com")
            stats = limiter.get_stats()
            # amazon.com removed, ebay.com remains
            assert "amazon.com" not in stats["domains"]
            assert "ebay.com" in stats["domains"]

        asyncio.run(run())

    def test_reset_all(self):
        from utils.rate_limiter import RateLimiter
        limiter = RateLimiter(rate=10.0)

        async def run():
            await limiter.wait("amazon.com")
            await limiter.wait("ebay.com")
            limiter.reset()
            stats = limiter.get_stats()
            assert stats["tracked_domains"] == 0

        asyncio.run(run())

    def test_get_stats_structure(self):
        from utils.rate_limiter import RateLimiter
        limiter = RateLimiter(rate=5.0, burst=2)
        stats = limiter.get_stats()
        # Verify all expected keys are present
        assert "tracked_domains" in stats
        assert "rate_per_second" in stats
        assert "burst_size" in stats
        assert "domains" in stats


class TestPolitDelay:
    """Tests for polite_delay() — simple async sleep helper."""

    def test_polite_delay_completes(self):
        from utils.rate_limiter import polite_delay

        async def run():
            # Should complete without error
            await polite_delay(0.05)   # 50ms — fast enough for tests

        asyncio.run(run())

    def test_polite_delay_custom_seconds(self):
        from utils.rate_limiter import polite_delay

        async def run():
            start = time.time()
            await polite_delay(0.1)   # 100ms
            elapsed = time.time() - start
            # Should have waited at least 100ms
            assert elapsed >= 0.09    # small tolerance for timing variance

        asyncio.run(run())
