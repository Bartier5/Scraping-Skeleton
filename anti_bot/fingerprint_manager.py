# ── anti_bot/fingerprint_manager.py ──────────────────────────────────────────
# TLS and browser fingerprint management for advanced anti-bot evasion.
#
# What is fingerprinting and why does it matter?
#   Beyond HTTP headers, advanced anti-bot systems fingerprint:
#   - TLS handshake signature (cipher suites, extensions, curve preferences)
#   - HTTP/2 settings (SETTINGS frame values, header compression)
#   - Browser JavaScript properties (navigator.webdriver, Canvas API, WebGL)
#
#   A standard Python requests or aiohttp session has a unique TLS signature
#   that doesn't match any real browser. curl-cffi solves this by mimicking
#   Chrome's exact TLS handshake. Playwright with stealth patches solves
#   the JavaScript fingerprint problem.
#
# This module provides:
#   1. TlsFetcher — drop-in replacement for HttpFetcher using curl-cffi
#      for sites that fingerprint TLS (Cloudflare, Akamai, etc.)
#   2. StealthConfig — configuration helper for Playwright stealth mode
#   3. FingerprintAnalyzer — checks what a site can detect about you

from typing import Optional
from utils.logger import log

try:
    import curl_cffi.requests as cffi_requests
    CURL_CFFI_AVAILABLE = True
except ImportError:
    CURL_CFFI_AVAILABLE = False
    log.debug("curl-cffi not installed — TLS fingerprint spoofing unavailable")

try:
    from playwright_stealth import stealth_async
    STEALTH_AVAILABLE = True
except ImportError:
    STEALTH_AVAILABLE = False
    log.debug("playwright-stealth not installed — browser stealth unavailable")


# ── TLS Fingerprint Spoofing ──────────────────────────────────────────────────

class TlsFetcher:
    """
    HTTP fetcher using curl-cffi to spoof Chrome's TLS fingerprint.

    curl-cffi wraps libcurl with BoringSSL — the same TLS library Chrome uses.
    This makes your requests produce the same TLS handshake signature as
    a real Chrome browser, defeating JA3/JA4 fingerprinting.

    Use this for sites that block standard Python HTTP libraries based on
    their TLS signature (Cloudflare "I'm Under Attack" mode, Akamai, etc.)

    Usage:
        fetcher = TlsFetcher(browser="chrome120")
        result = fetcher.fetch("https://cloudflare-protected-site.com")
    """

    # Browser impersonation targets — each has different TLS settings
    SUPPORTED_BROWSERS = [
        "chrome99",  "chrome100", "chrome101", "chrome104",
        "chrome107", "chrome110", "chrome116", "chrome119",
        "chrome120", "firefox102", "firefox108", "safari15_3",
        "safari15_5", "safari17_0",
    ]

    def __init__(
        self,
        browser: str = "chrome120",    # which browser's TLS to impersonate
        timeout: int = 30,
    ):
        """
        Args:
            browser: browser to impersonate — must be in SUPPORTED_BROWSERS
            timeout: request timeout in seconds
        """
        if not CURL_CFFI_AVAILABLE:
            raise RuntimeError(
                "curl-cffi is required for TLS fingerprint spoofing. "
                "Install with: pip install curl-cffi"
            )

        if browser not in self.SUPPORTED_BROWSERS:
            log.warning(
                "TlsFetcher: unknown browser '{}' — defaulting to chrome120",
                browser
            )
            browser = "chrome120"

        self.browser = browser
        self.timeout = timeout

        # Create a persistent session with the chosen browser impersonation
        self._session = cffi_requests.Session(impersonate=browser)
        log.debug("TlsFetcher initialized (impersonating {})", browser)

    def fetch(self, url: str, headers: dict = None, **kwargs) -> dict:
        """
        Fetches a URL using Chrome's TLS fingerprint.

        Args:
            url:     target URL
            headers: optional additional headers
            **kwargs: passed to cffi_requests.get()

        Returns:
            dict with url, status_code, html, headers, error
        """
        try:
            log.debug("TlsFetcher fetching: {} (impersonating {})", url, self.browser)

            response = self._session.get(
                url,
                headers=headers or {},
                timeout=self.timeout,
                allow_redirects=True,
                **kwargs
            )

            log.debug("TlsFetcher OK: {} (HTTP {})", url, response.status_code)
            return {
                "url": url,
                "status_code": response.status_code,
                "html": response.text,
                "headers": dict(response.headers),
                "error": None,
            }

        except Exception as e:
            log.error("TlsFetcher failed for {}: {}", url, str(e))
            return {
                "url": url,
                "status_code": 0,
                "html": "",
                "headers": {},
                "error": str(e),
            }

    def close(self) -> None:
        """Closes the curl-cffi session."""
        if self._session:
            self._session.close()
            log.debug("TlsFetcher: session closed")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


# ── Browser Stealth Configuration ─────────────────────────────────────────────

class StealthConfig:
    """
    Configuration and application of Playwright stealth patches.

    playwright-stealth patches the browser's JavaScript environment to
    hide automation artifacts that sites use to detect Playwright:

    Patches applied:
    - navigator.webdriver → removes the automation flag
    - navigator.plugins → populates with realistic plugin list
    - navigator.languages → sets realistic language preferences
    - Chrome runtime → adds Chrome-specific properties Firefox lacks
    - Permissions API → makes permission queries return realistic values
    - WebGL vendor/renderer → spoofs GPU information
    - Canvas fingerprint → adds subtle noise to canvas output

    Usage:
        config = StealthConfig()
        async with async_playwright() as pw:
            browser = await pw.chromium.launch()
            page = await browser.new_page()
            await config.apply(page)    # apply stealth patches
            await page.goto(url)
    """

    def __init__(
        self,
        webgl_vendor: str = "Intel Inc.",
        webgl_renderer: str = "Intel Iris OpenGL Engine",
        languages: list = None,
    ):
        """
        Args:
            webgl_vendor:   GPU vendor string — should match common hardware
            webgl_renderer: GPU renderer string
            languages:      browser language preferences
        """
        self.webgl_vendor = webgl_vendor
        self.webgl_renderer = webgl_renderer
        self.languages = languages or ["en-US", "en"]
        log.debug("StealthConfig initialized")

    async def apply(self, page) -> bool:
        """
        Applies stealth patches to a Playwright page.

        Must be called BEFORE page.goto() — patches need to be in place
        before any JavaScript executes on the page.

        Args:
            page: Playwright Page object

        Returns:
            True if stealth was applied, False if playwright-stealth not installed
        """
        if not STEALTH_AVAILABLE:
            log.warning(
                "playwright-stealth not installed — "
                "browser fingerprint not patched. "
                "Install with: pip install playwright-stealth"
            )
            return False

        try:
            await stealth_async(page)
            log.debug("StealthConfig: stealth patches applied")
            return True
        except Exception as e:
            log.error("StealthConfig.apply failed: {}", str(e))
            return False

    @staticmethod
    def is_available() -> bool:
        """Returns True if playwright-stealth is installed."""
        return STEALTH_AVAILABLE


# ── Fingerprint Analyzer ──────────────────────────────────────────────────────

class FingerprintAnalyzer:
    """
    Analyzes what fingerprint information a target site can collect.
    Use this to understand what your scraper is revealing before
    running a large job against a protected site.

    Checks:
    - TLS fingerprint (JA3 hash)
    - HTTP/2 fingerprint
    - Header signature (which headers are present and in what order)
    - IP reputation (known datacenter vs residential)

    Usage:
        analyzer = FingerprintAnalyzer()
        report = await analyzer.analyze("https://target-site.com")
        print(report)
    """

    # Public fingerprint checking services
    TLS_CHECK_URL = "https://tls.peet.ws/api/all"
    HEADER_CHECK_URL = "https://httpbin.org/headers"
    IP_CHECK_URL = "https://httpbin.org/ip"

    def __init__(self):
        log.debug("FingerprintAnalyzer initialized")

    def check_headers(self, headers: dict) -> dict:
        """
        Analyzes a header set for common bot detection signals.

        Checks:
        - Missing headers that real browsers always send
        - Headers that are bot-specific
        - Suspicious User-Agent patterns

        Args:
            headers: the headers dict your fetcher is sending

        Returns:
            dict with issues list and risk_score (0=safe, 10=obvious bot)
        """
        issues = []
        risk_score = 0

        # Check for missing critical headers
        critical_headers = ["User-Agent", "Accept", "Accept-Language", "Accept-Encoding"]
        for h in critical_headers:
            if h not in headers:
                issues.append(f"Missing critical header: {h}")
                risk_score += 2

        # Check for bot-like User-Agent
        ua = headers.get("User-Agent", "")
        bot_signals = ["python", "requests", "aiohttp", "scrapy", "bot", "crawler", "spider"]
        for signal in bot_signals:
            if signal.lower() in ua.lower():
                issues.append(f"Bot-like User-Agent contains '{signal}'")
                risk_score += 3

        # Check for missing Sec-Fetch headers (Chrome always sends these)
        if "Chrome" in ua:
            sec_headers = ["Sec-Fetch-Dest", "Sec-Fetch-Mode", "Sec-Fetch-Site"]
            for h in sec_headers:
                if h not in headers:
                    issues.append(f"Missing Chrome security header: {h}")
                    risk_score += 1

        # Check for suspicious header combinations
        if "X-Forwarded-For" in headers:
            issues.append("X-Forwarded-For present — may reveal proxy usage")
            risk_score += 1

        return {
            "risk_score": min(risk_score, 10),
            "risk_level": "LOW" if risk_score <= 2 else "MEDIUM" if risk_score <= 5 else "HIGH",
            "issues": issues,
            "recommendation": self._get_recommendation(risk_score),
        }

    def _get_recommendation(self, risk_score: int) -> str:
        """Returns a human-readable recommendation based on risk score."""
        if risk_score == 0:
            return "Headers look clean — no obvious bot signals detected"
        elif risk_score <= 2:
            return "Minor issues — should work on most sites"
        elif risk_score <= 5:
            return "Medium risk — use HeadersManager to improve headers"
        else:
            return "High risk — use TlsFetcher + HeadersManager for this site"

    def analyze_headers(self, headers: dict) -> None:
        """
        Analyzes and logs a header fingerprint report.
        Convenience method that runs check_headers() and logs results.
        """
        report = self.check_headers(headers)
        log.info(
            "FingerprintAnalyzer: risk={} ({})",
            report["risk_score"], report["risk_level"]
        )
        for issue in report["issues"]:
            log.warning("  ⚠ {}", issue)
        log.info("  → {}", report["recommendation"])
        return report
