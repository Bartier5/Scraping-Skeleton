# ── tests/test_day1.py ───────────────────────────────────────────────────────
# Isolation tests for Day 1 modules: config, logger, retry, helpers.
# Run with: pytest tests/test_day1.py -v
#
# These tests verify each module works correctly on its own before
# we wire anything together in the mini example.

import pytest                           # test runner and assertion framework
import os                               # check environment variables
import time                             # measure retry timing
from unittest.mock import patch         # temporarily replace functions for testing


# ── Config Tests ──────────────────────────────────────────────────────────────

class TestConfig:
    """Tests that Config loads correctly and returns expected types."""

    def test_config_imports(self):
        # Verify Config can be imported without errors
        from config.config import Config
        assert Config is not None

    def test_timeout_is_int(self):
        # TIMEOUT must be an int — used in requests(timeout=Config.TIMEOUT)
        from config.config import Config
        assert isinstance(Config.TIMEOUT, int)

    def test_max_retries_is_int(self):
        from config.config import Config
        assert isinstance(Config.MAX_RETRIES, int)

    def test_concurrency_is_int(self):
        from config.config import Config
        assert isinstance(Config.CONCURRENCY, int)

    def test_delay_is_float(self):
        # DELAY_BETWEEN_REQUESTS must be a float — used in asyncio.sleep()
        from config.config import Config
        assert isinstance(Config.DELAY_BETWEEN_REQUESTS, float)

    def test_storage_backend_is_string(self):
        from config.config import Config
        assert isinstance(Config.STORAGE_BACKEND, str)

    def test_defaults_are_sensible(self):
        # Sanity check — defaults shouldn't be zero or negative
        from config.config import Config
        assert Config.TIMEOUT > 0
        assert Config.MAX_RETRIES > 0
        assert Config.CONCURRENCY > 0
        assert Config.DELAY_BETWEEN_REQUESTS >= 0


# ── Logger Tests ──────────────────────────────────────────────────────────────

class TestLogger:
    """Tests that the logger is set up and callable."""

    def test_logger_imports(self):
        # Verify logger module loads without errors
        from utils.logger import log
        assert log is not None

    def test_logger_has_info(self):
        # log.info must be callable — basic sanity check
        from utils.logger import log
        assert callable(log.info)

    def test_logger_has_error(self):
        from utils.logger import log
        assert callable(log.error)

    def test_logger_has_debug(self):
        from utils.logger import log
        assert callable(log.debug)

    def test_logger_does_not_raise(self):
        # Actually call the logger — should produce output without crashing
        from utils.logger import log
        try:
            log.info("Test log message from test_day1.py")
            log.debug("Debug message test")
            log.warning("Warning message test")
        except Exception as e:
            pytest.fail(f"Logger raised an exception: {e}")


# ── Retry Tests ───────────────────────────────────────────────────────────────

class TestRetry:
    """Tests that the retry decorator works correctly."""

    def test_retry_imports(self):
        from utils.retry import retry, standard_retry, aggressive_retry
        assert retry is not None
        assert standard_retry is not None
        assert aggressive_retry is not None

    def test_retry_succeeds_first_try(self):
        # A function that succeeds immediately should just return normally
        from utils.retry import retry

        call_count = {"n": 0}   # use dict to mutate inside nested function

        @retry(max_attempts=3)
        def always_succeeds():
            call_count["n"] += 1
            return "ok"

        result = always_succeeds()
        assert result == "ok"
        assert call_count["n"] == 1   # called exactly once — no retries needed

    def test_retry_retries_on_failure(self):
        # A function that fails twice then succeeds should be called 3 times total
        from utils.retry import retry

        call_count = {"n": 0}

        @retry(max_attempts=3, min_wait=0.01, max_wait=0.1)
        def fails_twice():
            call_count["n"] += 1
            if call_count["n"] < 3:
                raise ValueError("Simulated failure")
            return "recovered"

        result = fails_twice()
        assert result == "recovered"
        assert call_count["n"] == 3    # failed twice, succeeded on third attempt

    def test_retry_gives_up_after_max_attempts(self):
        # A function that always fails should raise after max_attempts
        from utils.retry import retry

        @retry(max_attempts=2, min_wait=0.01, max_wait=0.1)
        def always_fails():
            raise ConnectionError("Always fails")

        # pytest.raises verifies the exception IS raised (not swallowed)
        with pytest.raises(ConnectionError):
            always_fails()


# ── Helpers Tests ─────────────────────────────────────────────────────────────

class TestHelpers:
    """Tests for all utility functions in helpers.py."""

    def test_ensure_dir_creates_directory(self, tmp_path):
        # tmp_path is a pytest fixture — gives a fresh temp directory per test
        from utils.helpers import ensure_dir
        new_dir = str(tmp_path / "test_output")
        result = ensure_dir(new_dir)
        assert os.path.isdir(new_dir)   # directory was created
        assert result == new_dir         # returns the path

    def test_timestamp_returns_string(self):
        from utils.helpers import timestamp
        ts = timestamp()
        assert isinstance(ts, str)
        assert len(ts) > 0

    def test_timestamp_format(self):
        # Default format should be YYYYmmdd_HHMMSS — 15 chars
        from utils.helpers import timestamp
        ts = timestamp()
        assert len(ts) == 15            # "20250604_143022" = 15 characters

    def test_get_domain(self):
        from utils.helpers import get_domain
        assert get_domain("https://books.toscrape.com/catalogue/page-1.html") == "books.toscrape.com"
        assert get_domain("https://api.example.com/v1/data") == "api.example.com"

    def test_build_url_with_params(self):
        from utils.helpers import build_url
        url = build_url("https://api.example.com", "/search", {"q": "python", "page": "1"})
        assert "https://api.example.com/search" in url
        assert "q=python" in url
        assert "page=1" in url

    def test_build_url_without_params(self):
        from utils.helpers import build_url
        url = build_url("https://example.com", "/about")
        assert url == "https://example.com/about"

    def test_is_valid_url_valid(self):
        from utils.helpers import is_valid_url
        assert is_valid_url("https://example.com") is True
        assert is_valid_url("http://books.toscrape.com/page-1") is True

    def test_is_valid_url_invalid(self):
        from utils.helpers import is_valid_url
        assert is_valid_url("not-a-url") is False
        assert is_valid_url("ftp://files.example.com") is False   # not http/https
        assert is_valid_url("") is False

    def test_hash_content_returns_string(self):
        from utils.helpers import hash_content
        h = hash_content("<html>hello world</html>")
        assert isinstance(h, str)
        assert len(h) == 32   # MD5 hex digest is always 32 characters

    def test_hash_content_is_deterministic(self):
        # Same content must always produce the same hash
        from utils.helpers import hash_content
        content = "<html>test</html>"
        assert hash_content(content) == hash_content(content)

    def test_hash_content_differs_for_different_content(self):
        # Different content must produce different hashes
        from utils.helpers import hash_content
        assert hash_content("page 1 content") != hash_content("page 2 content")

    def test_clean_text_strips_whitespace(self):
        from utils.helpers import clean_text
        assert clean_text("  Hello   World  ") == "Hello World"

    def test_clean_text_collapses_newlines(self):
        from utils.helpers import clean_text
        assert clean_text("Line 1\n\nLine 2") == "Line 1 Line 2"

    def test_clean_text_empty_string(self):
        from utils.helpers import clean_text
        assert clean_text("") == ""
        assert clean_text(None) == ""   # handles None gracefully

    def test_slugify(self):
        from utils.helpers import slugify
        assert slugify("Latest Products 2025!") == "latest-products-2025"
        assert slugify("Hello   World") == "hello-world"
        assert slugify("already-slugified") == "already-slugified"

    def test_file_exists_true(self, tmp_path):
        from utils.helpers import file_exists
        f = tmp_path / "test.txt"
        f.write_text("hello")           # create the file
        assert file_exists(str(f)) is True

    def test_file_exists_false(self, tmp_path):
        from utils.helpers import file_exists
        assert file_exists(str(tmp_path / "nonexistent.txt")) is False
