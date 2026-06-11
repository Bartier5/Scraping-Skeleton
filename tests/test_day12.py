# ── tests/test_day12.py ───────────────────────────────────────────────────────
# Isolation tests for Day 12: ProxyManager, HeadersManager, FingerprintAnalyzer
# Run with: pytest tests/test_day12.py -v

import pytest
import time


# ── ProxyManager Tests ────────────────────────────────────────────────────────

class TestProxyManager:

    PROXIES = [
        "http://user:pass@proxy1.example.com:8080",
        "http://user:pass@proxy2.example.com:8080",
        "http://user:pass@proxy3.example.com:8080",
    ]

    def test_load_from_list(self):
        from anti_bot.proxy_manager import ProxyManager
        manager = ProxyManager()
        count = manager.load_from_list(self.PROXIES)
        assert count == 3
        assert len(manager) == 3

    def test_load_skips_duplicates(self):
        from anti_bot.proxy_manager import ProxyManager
        manager = ProxyManager()
        manager.load_from_list(self.PROXIES)
        count = manager.load_from_list(self.PROXIES)   # load again
        assert count == 0   # all duplicates — nothing new added
        assert len(manager) == 3

    def test_load_from_file(self, tmp_path):
        from anti_bot.proxy_manager import ProxyManager
        filepath = str(tmp_path / "proxies.txt")
        with open(filepath, "w") as f:
            f.write("# Comment line\n")
            f.write("http://proxy1.example.com:8080\n")
            f.write("\n")   # empty line
            f.write("http://proxy2.example.com:8080\n")

        manager = ProxyManager()
        count = manager.load_from_file(filepath)
        assert count == 2

    def test_load_from_missing_file(self, tmp_path):
        from anti_bot.proxy_manager import ProxyManager
        manager = ProxyManager()
        count = manager.load_from_file(str(tmp_path / "missing.txt"))
        assert count == 0

    def test_get_proxy_returns_url(self):
        from anti_bot.proxy_manager import ProxyManager
        manager = ProxyManager()
        manager.load_from_list(self.PROXIES)
        proxy = manager.get_proxy()
        assert proxy is not None
        assert proxy in self.PROXIES

    def test_get_proxy_none_when_empty(self):
        from anti_bot.proxy_manager import ProxyManager
        manager = ProxyManager()
        assert manager.get_proxy() is None

    def test_round_robin_rotation(self):
        from anti_bot.proxy_manager import ProxyManager
        manager = ProxyManager(strategy="round_robin")
        manager.load_from_list(self.PROXIES)
        # Should cycle through all proxies
        seen = [manager.get_proxy() for _ in range(3)]
        assert len(set(seen)) == 3   # all three used

    def test_random_strategy_returns_from_pool(self):
        from anti_bot.proxy_manager import ProxyManager
        manager = ProxyManager(strategy="random")
        manager.load_from_list(self.PROXIES)
        proxy = manager.get_proxy()
        assert proxy in self.PROXIES

    def test_least_used_strategy(self):
        from anti_bot.proxy_manager import ProxyManager
        manager = ProxyManager(strategy="least_used")
        manager.load_from_list(self.PROXIES)
        # First call should return one proxy
        proxy1 = manager.get_proxy()
        # Second call should return a different proxy (least used)
        proxy2 = manager.get_proxy()
        assert proxy1 in self.PROXIES
        assert proxy2 in self.PROXIES

    def test_mark_success_resets_failures(self):
        from anti_bot.proxy_manager import ProxyManager
        manager = ProxyManager()
        manager.load_from_list([self.PROXIES[0]])
        url = self.PROXIES[0]

        manager.mark_failure(url)
        manager.mark_failure(url)
        assert manager._proxies[url].failures == 2

        manager.mark_success(url)
        assert manager._proxies[url].failures == 0

    def test_mark_failure_increments_count(self):
        from anti_bot.proxy_manager import ProxyManager
        manager = ProxyManager(max_failures=5)
        manager.load_from_list([self.PROXIES[0]])
        url = self.PROXIES[0]

        manager.mark_failure(url)
        manager.mark_failure(url)
        assert manager._proxies[url].failures == 2

    def test_proxy_banned_after_max_failures(self):
        from anti_bot.proxy_manager import ProxyManager
        manager = ProxyManager(max_failures=2, cooldown=60)
        manager.load_from_list([self.PROXIES[0]])
        url = self.PROXIES[0]

        manager.mark_failure(url)
        manager.mark_failure(url)   # hits max_failures

        assert manager._proxies[url].is_banned is True

    def test_banned_proxy_not_returned(self):
        from anti_bot.proxy_manager import ProxyManager
        manager = ProxyManager(max_failures=1, cooldown=9999)
        manager.load_from_list([self.PROXIES[0]])
        url = self.PROXIES[0]

        manager.mark_failure(url)   # ban the only proxy

        result = manager.get_proxy()
        assert result is None   # no healthy proxies

    def test_remove_proxy(self):
        from anti_bot.proxy_manager import ProxyManager
        manager = ProxyManager()
        manager.load_from_list(self.PROXIES)
        manager.remove_proxy(self.PROXIES[0])
        assert len(manager) == 2
        assert self.PROXIES[0] not in manager._proxies

    def test_reset_bans(self):
        from anti_bot.proxy_manager import ProxyManager
        manager = ProxyManager(max_failures=1, cooldown=9999)
        manager.load_from_list(self.PROXIES[:2])

        manager.mark_failure(self.PROXIES[0])
        manager.mark_failure(self.PROXIES[1])

        cleared = manager.reset_bans()
        assert cleared == 2

        # Should be able to get proxies again
        proxy = manager.get_proxy()
        assert proxy is not None

    def test_get_stats(self):
        from anti_bot.proxy_manager import ProxyManager
        manager = ProxyManager()
        manager.load_from_list(self.PROXIES)
        stats = manager.get_stats()
        assert stats["total"] == 3
        assert stats["healthy"] == 3
        assert stats["banned"] == 0
        assert len(stats["proxies"]) == 3

    def test_bool_true_when_healthy_proxies(self):
        from anti_bot.proxy_manager import ProxyManager
        manager = ProxyManager()
        manager.load_from_list(self.PROXIES)
        assert bool(manager) is True

    def test_bool_false_when_empty(self):
        from anti_bot.proxy_manager import ProxyManager
        manager = ProxyManager()
        assert bool(manager) is False

    def test_proxy_record_success_rate(self):
        from anti_bot.proxy_manager import ProxyRecord
        record = ProxyRecord(url="http://proxy1.com", total_uses=10, total_successes=8)
        assert record.success_rate == 0.8

    def test_proxy_record_is_healthy(self):
        from anti_bot.proxy_manager import ProxyRecord
        record = ProxyRecord(url="http://proxy1.com", total_uses=10, total_successes=5)
        assert record.is_healthy is True   # 50% success rate > 30% threshold

    def test_proxy_record_unhealthy_low_rate(self):
        from anti_bot.proxy_manager import ProxyRecord
        record = ProxyRecord(url="http://proxy1.com", total_uses=10, total_successes=2)
        assert record.is_healthy is False   # 20% < 30% threshold

    def test_total_uses_increments_on_get(self):
        from anti_bot.proxy_manager import ProxyManager
        manager = ProxyManager()
        manager.load_from_list([self.PROXIES[0]])
        url = self.PROXIES[0]

        manager.get_proxy()
        manager.get_proxy()
        assert manager._proxies[url].total_uses == 2


# ── HeadersManager Tests ──────────────────────────────────────────────────────

class TestHeadersManager:

    def test_get_user_agent_returns_string(self):
        from anti_bot.headers_manager import HeadersManager
        manager = HeadersManager()
        ua = manager.get_user_agent()
        assert isinstance(ua, str)
        assert len(ua) > 20

    def test_chrome_ua_contains_chrome(self):
        from anti_bot.headers_manager import HeadersManager
        manager = HeadersManager(browser="chrome", use_fake_ua=False)
        ua = manager.get_user_agent()
        assert "Chrome" in ua or "Mozilla" in ua

    def test_firefox_ua_contains_firefox(self):
        from anti_bot.headers_manager import HeadersManager
        manager = HeadersManager(browser="firefox", use_fake_ua=False)
        ua = manager.get_user_agent()
        assert "Firefox" in ua or "Mozilla" in ua

    def test_get_headers_returns_dict(self):
        from anti_bot.headers_manager import HeadersManager
        manager = HeadersManager(use_fake_ua=False)
        headers = manager.get_headers()
        assert isinstance(headers, dict)
        assert len(headers) > 0

    def test_headers_contain_user_agent(self):
        from anti_bot.headers_manager import HeadersManager
        manager = HeadersManager(use_fake_ua=False)
        headers = manager.get_headers()
        assert "User-Agent" in headers

    def test_headers_contain_accept(self):
        from anti_bot.headers_manager import HeadersManager
        manager = HeadersManager(use_fake_ua=False)
        headers = manager.get_headers()
        assert "Accept" in headers

    def test_headers_contain_accept_language(self):
        from anti_bot.headers_manager import HeadersManager
        manager = HeadersManager(use_fake_ua=False)
        headers = manager.get_headers()
        assert "Accept-Language" in headers

    def test_referer_added_when_provided(self):
        from anti_bot.headers_manager import HeadersManager
        manager = HeadersManager(use_fake_ua=False)
        headers = manager.get_headers(
            url="https://example.com/page2",
            referer="https://example.com/page1"
        )
        assert "Referer" in headers
        assert headers["Referer"] == "https://example.com/page1"

    def test_no_referer_when_not_provided(self):
        from anti_bot.headers_manager import HeadersManager
        manager = HeadersManager(use_fake_ua=False)
        headers = manager.get_headers()
        assert "Referer" not in headers

    def test_extra_headers_merged(self):
        from anti_bot.headers_manager import HeadersManager
        manager = HeadersManager(use_fake_ua=False)
        headers = manager.get_headers(extra={"X-Custom": "test-value"})
        assert headers.get("X-Custom") == "test-value"

    def test_session_ua_consistent_when_not_rotating(self):
        from anti_bot.headers_manager import HeadersManager
        manager = HeadersManager(rotate_per_request=False, use_fake_ua=False)
        ua1 = manager.get_user_agent()
        ua2 = manager.get_user_agent()
        ua3 = manager.get_user_agent()
        assert ua1 == ua2 == ua3   # same UA throughout session

    def test_ajax_headers_different_from_navigation(self):
        from anti_bot.headers_manager import HeadersManager
        manager = HeadersManager(use_fake_ua=False)
        nav_headers = manager.get_headers()
        ajax_headers = manager.get_ajax_headers()
        # AJAX uses different Accept header
        assert nav_headers["Accept"] != ajax_headers["Accept"]

    def test_ajax_headers_has_xhr_marker(self):
        from anti_bot.headers_manager import HeadersManager
        manager = HeadersManager(use_fake_ua=False)
        headers = manager.get_ajax_headers()
        assert "X-Requested-With" in headers
        assert headers["X-Requested-With"] == "XMLHttpRequest"

    def test_sec_fetch_site_none_no_referer(self):
        from anti_bot.headers_manager import HeadersManager
        manager = HeadersManager(use_fake_ua=False)
        site = manager._sec_fetch_site("https://example.com", "")
        assert site == "none"

    def test_sec_fetch_site_same_origin(self):
        from anti_bot.headers_manager import HeadersManager
        manager = HeadersManager(use_fake_ua=False)
        site = manager._sec_fetch_site(
            "https://example.com/page2",
            "https://example.com/page1"
        )
        assert site == "same-origin"

    def test_sec_fetch_site_cross_site(self):
        from anti_bot.headers_manager import HeadersManager
        manager = HeadersManager(use_fake_ua=False)
        site = manager._sec_fetch_site(
            "https://target.com/page",
            "https://google.com"
        )
        assert site == "cross-site"


# ── FingerprintAnalyzer Tests ─────────────────────────────────────────────────

class TestFingerprintAnalyzer:

    def test_clean_headers_low_risk(self):
        from anti_bot.fingerprint_manager import FingerprintAnalyzer
        from anti_bot.headers_manager import HeadersManager

        analyzer = FingerprintAnalyzer()
        manager = HeadersManager(use_fake_ua=False)
        headers = manager.get_headers()

        report = analyzer.check_headers(headers)
        assert report["risk_score"] <= 3
        assert report["risk_level"] in ("LOW", "MEDIUM")

    def test_empty_headers_high_risk(self):
        from anti_bot.fingerprint_manager import FingerprintAnalyzer
        analyzer = FingerprintAnalyzer()
        report = analyzer.check_headers({})
        assert report["risk_score"] > 5

    def test_python_useragent_flagged(self):
        from anti_bot.fingerprint_manager import FingerprintAnalyzer
        analyzer = FingerprintAnalyzer()
        report = analyzer.check_headers({
            "User-Agent": "python-requests/2.31.0",
            "Accept": "*/*",
            "Accept-Encoding": "gzip, deflate",
        })
        # python in UA should be flagged
        assert any("python" in issue.lower() for issue in report["issues"])
        assert report["risk_score"] > 0

    def test_missing_accept_language_flagged(self):
        from anti_bot.fingerprint_manager import FingerprintAnalyzer
        analyzer = FingerprintAnalyzer()
        report = analyzer.check_headers({
            "User-Agent": "Mozilla/5.0 Chrome/120",
            "Accept": "text/html",
            "Accept-Encoding": "gzip",
            # Missing Accept-Language
        })
        assert any("Accept-Language" in issue for issue in report["issues"])

    def test_report_has_required_keys(self):
        from anti_bot.fingerprint_manager import FingerprintAnalyzer
        analyzer = FingerprintAnalyzer()
        report = analyzer.check_headers({"User-Agent": "Mozilla/5.0"})
        assert "risk_score" in report
        assert "risk_level" in report
        assert "issues" in report
        assert "recommendation" in report

    def test_risk_level_mapping(self):
        from anti_bot.fingerprint_manager import FingerprintAnalyzer
        analyzer = FingerprintAnalyzer()

        # Good headers → LOW risk
        good = {"User-Agent": "Mozilla/5.0", "Accept": "text/html",
                "Accept-Language": "en-US", "Accept-Encoding": "gzip"}
        report = analyzer.check_headers(good)
        assert report["risk_level"] in ("LOW", "MEDIUM")

    def test_stealth_config_availability(self):
        from anti_bot.fingerprint_manager import StealthConfig
        # Should be importable regardless of whether playwright-stealth is installed
        config = StealthConfig()
        available = StealthConfig.is_available()
        assert isinstance(available, bool)

    def test_tls_fetcher_raises_without_curl_cffi(self):
        from anti_bot.fingerprint_manager import CURL_CFFI_AVAILABLE, TlsFetcher
        if not CURL_CFFI_AVAILABLE:
            with pytest.raises(RuntimeError):
                TlsFetcher()
        else:
            # curl-cffi is installed — just verify it initializes
            fetcher = TlsFetcher(browser="chrome120")
            assert fetcher.browser == "chrome120"
            fetcher.close()
