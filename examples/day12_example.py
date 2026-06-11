# ── examples/day12_example.py ─────────────────────────────────────────────────
# Day 12 mini example — anti-bot modules demo.
# Shows proxy rotation, header generation, and fingerprint analysis
# working together against real scraping targets.
#
# Run with: python examples/day12_example.py

import sys
import os
import asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from utils.logger import log
from utils.helpers import ensure_dir
from anti_bot.proxy_manager import ProxyManager, ProxyRecord
from anti_bot.headers_manager import HeadersManager
from anti_bot.fingerprint_manager import FingerprintAnalyzer, StealthConfig


def main():
    ensure_dir("logs")
    ensure_dir("data")

    log.info("=" * 60)
    log.info("Day 12 — Anti-Bot Modules Demo")
    log.info("=" * 60)

    # ── 1. ProxyManager ───────────────────────────────────────────────────────
    log.info("1. ProxyManager — pool management with health tracking:")

    manager = ProxyManager(
        strategy="round_robin",
        max_failures=3,
        cooldown=60,
    )

    # Load simulated proxy pool
    fake_proxies = [
        "http://user:pass@proxy1.example.com:8080",
        "http://user:pass@proxy2.example.com:8080",
        "http://user:pass@proxy3.example.com:8080",
        "http://user:pass@proxy4.example.com:8080",
        "http://user:pass@proxy5.example.com:8080",
    ]

    loaded = manager.load_from_list(fake_proxies)
    log.info("  Loaded {} proxies into pool", loaded)

    # Simulate 10 requests with rotation
    log.info("  Simulating 10 requests with round-robin rotation:")
    for i in range(1, 11):
        proxy = manager.get_proxy()
        host = proxy.split("@")[-1] if proxy else "None"
        log.debug("  Request {}: {}", i, host)

    # Simulate some failures on proxy1
    log.info("  Simulating failures on proxy1:")
    for _ in range(3):   # hit max_failures
        manager.mark_failure(fake_proxies[0], reason="connection timeout")

    stats = manager.get_stats()
    log.info("  Pool stats after failures:")
    log.info("    Total: {} | Healthy: {} | Banned: {}",
             stats["total"], stats["healthy"], stats["banned"])

    # Show proxy details
    for p in stats["proxies"]:
        log.info("    {} → {} ({})",
                 p["url"], p["status"], p["success_rate"])

    # Simulate successful requests on remaining proxies
    for proxy in fake_proxies[1:]:
        manager.mark_success(proxy)

    # Reset bans — start fresh for next job
    cleared = manager.reset_bans()
    log.info("  Reset {} bans — all proxies healthy again", cleared)
    log.info("  Healthy proxies: {}", manager.get_stats()["healthy"])

    # ── 2. ProxyManager file loading ──────────────────────────────────────────
    log.info("2. ProxyManager — loading from file:")

    import tempfile
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("# Production proxy pool\n")
        f.write("http://user:pass@res1.proxy.com:9090\n")
        f.write("http://user:pass@res2.proxy.com:9090\n")
        f.write("\n")   # empty line
        f.write("# Backup proxies\n")
        f.write("http://user:pass@dc1.proxy.com:8080\n")
        tmpfile = f.name

    file_manager = ProxyManager()
    count = file_manager.load_from_file(tmpfile)
    log.info("  Loaded {} proxies from file", count)
    os.unlink(tmpfile)

    # ── 3. HeadersManager — complete header generation ────────────────────────
    log.info("3. HeadersManager — generating browser-realistic headers:")

    # Chrome headers
    chrome_manager = HeadersManager(browser="chrome", use_fake_ua=False)
    chrome_headers = chrome_manager.get_headers(
        url="https://books.toscrape.com/catalogue/page-1.html",
        referer="https://books.toscrape.com",
    )

    log.info("  Chrome navigation headers ({} total):", len(chrome_headers))
    for key, value in chrome_headers.items():
        display_val = value[:60] + "..." if len(value) > 60 else value
        log.info("    {}: {}", key, display_val)

    # Firefox headers
    ff_manager = HeadersManager(browser="firefox", use_fake_ua=False)
    ff_headers = ff_manager.get_headers()
    log.info("  Firefox headers ({} total)", len(ff_headers))

    # AJAX headers
    ajax_headers = chrome_manager.get_ajax_headers(
        referer="https://books.toscrape.com/catalogue/page-1.html"
    )
    log.info("  AJAX headers ({} total):", len(ajax_headers))
    log.info("    Accept: {}", ajax_headers.get("Accept"))
    log.info("    X-Requested-With: {}", ajax_headers.get("X-Requested-With"))
    log.info("    Sec-Fetch-Mode: {}", ajax_headers.get("Sec-Fetch-Mode"))

    # Session consistency demo
    log.info("  Session UA consistency (rotate_per_request=False):")
    session_manager = HeadersManager(rotate_per_request=False, use_fake_ua=False)
    ua1 = session_manager.get_user_agent()
    ua2 = session_manager.get_user_agent()
    ua3 = session_manager.get_user_agent()
    log.info("  UA1 == UA2 == UA3: {}", ua1 == ua2 == ua3)
    log.info("  Session UA: {}....", ua1[:60])

    # Rotation demo
    log.info("  Rotating UAs (rotate_per_request=True):")
    rotate_manager = HeadersManager(rotate_per_request=True, use_fake_ua=False)
    uas = {rotate_manager.get_user_agent() for _ in range(5)}
    log.info("  Unique UAs across 5 calls: {}", len(uas))

    # ── 4. FingerprintAnalyzer ────────────────────────────────────────────────
    log.info("4. FingerprintAnalyzer — header risk assessment:")

    analyzer = FingerprintAnalyzer()

    # Test 1: Raw Python requests headers — high risk
    log.info("  Test A — raw Python requests headers:")
    raw_headers = {
        "User-Agent": "python-requests/2.31.0",
        "Accept-Encoding": "gzip, deflate",
        "Accept": "*/*",
        "Connection": "keep-alive",
    }
    report_a = analyzer.analyze_headers(raw_headers)

    # Test 2: Our HeadersManager output — should be low risk
    log.info("  Test B — HeadersManager output:")
    good_headers = chrome_manager.get_headers(url="https://example.com")
    report_b = analyzer.analyze_headers(good_headers)

    # Test 3: Empty headers — obvious bot
    log.info("  Test C — empty headers:")
    report_c = analyzer.analyze_headers({})

    # Summary comparison
    log.info("  Risk comparison:")
    log.info("    Raw Python requests: score={} ({})",
             report_a["risk_score"], report_a["risk_level"])
    log.info("    HeadersManager:      score={} ({})",
             report_b["risk_score"], report_b["risk_level"])
    log.info("    Empty headers:       score={} ({})",
             report_c["risk_score"], report_c["risk_level"])

    # ── 5. Stealth availability check ─────────────────────────────────────────
    log.info("5. StealthConfig — Playwright stealth availability:")
    log.info("  playwright-stealth installed: {}", StealthConfig.is_available())
    if StealthConfig.is_available():
        log.info("  → Browser fingerprint patching available")
        log.info("  → Use: await StealthConfig().apply(page) before page.goto()")
    else:
        log.info("  → Install with: pip install playwright-stealth")
        log.info("  → Required for sites that detect automation via JS")

    # ── 6. Full anti-bot stack wiring ─────────────────────────────────────────
    log.info("6. Full anti-bot stack — how everything connects:")

    log.info("  Spider flow with anti-bot:")
    log.info("    1. ProxyManager.get_proxy()     → pick a healthy proxy")
    log.info("    2. HeadersManager.get_headers() → generate realistic headers")
    log.info("    3. AsyncFetcher.async_fetch()   → send request with proxy + headers")
    log.info("    4. If 429/block → ProxyManager.mark_failure(proxy)")
    log.info("    5. If success   → ProxyManager.mark_success(proxy)")
    log.info("    6. FingerprintAnalyzer.check_headers() → audit before job")

    # Show how proxy + headers integrate
    log.info("  Example integration:")
    proxy = manager.get_proxy()
    headers = chrome_manager.get_headers(url="https://target-site.com")
    log.info("    Proxy selected: {}", proxy.split("@")[-1] if proxy else "None")
    log.info("    User-Agent: {}...", headers["User-Agent"][:50])
    log.info("    Sec-Fetch-Site: {}", headers.get("Sec-Fetch-Site"))
    log.info("    Ready to fetch with full anti-bot stack ✓")

    log.info("=" * 60)
    log.success("Day 12 complete — anti-bot modules fully working")
    log.info("=" * 60)


if __name__ == "__main__":
    main()
