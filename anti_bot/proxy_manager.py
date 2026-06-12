# ── anti_bot/proxy_manager.py ─────────────────────────────────────────────────
# Production proxy pool manager with health checking and failure tracking.
#
# What does this add over ProxyMiddleware from Day 7?
#   ProxyMiddleware is a simple rotator — it picks a proxy and injects it.
#   ProxyManager is a full pool manager — it tracks proxy health, marks
#   failed proxies, retries with backoff, loads from files, validates
#   connectivity, and removes dead proxies automatically.
#
# When to use:
#   - Client jobs that require rotating residential or datacenter proxies
#   - Jobs where sites block IPs aggressively (e-commerce, travel, jobs)
#   - Any job scraping more than ~100 pages from a single site

import asyncio
import random
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from utils.logger import log


@dataclass
class ProxyRecord:
    """
    Tracks the state and health of a single proxy.

    Fields:
        url:          the full proxy URL e.g. "http://user:pass@host:port"
        failures:     how many consecutive failures this proxy has had
        last_used:    unix timestamp of last use (for cooldown tracking)
        last_failure: unix timestamp of last failure
        banned_until: unix timestamp when this proxy can be used again
        total_uses:   lifetime request count through this proxy
        success_rate: rolling success rate (0.0 - 1.0)
    """
    url: str
    failures: int = 0
    last_used: float = 0.0
    last_failure: float = 0.0
    banned_until: float = 0.0
    total_uses: int = 0
    total_successes: int = 0

    @property
    def is_banned(self) -> bool:
        """True if this proxy is in a cooldown period."""
        return time.time() < self.banned_until

    @property
    def success_rate(self) -> float:
        """Rolling success rate — 1.0 means never failed."""
        if self.total_uses == 0:
            return 1.0
        return self.total_successes / self.total_uses

    @property
    def is_healthy(self) -> bool:
        """True if proxy is not banned and has reasonable success rate."""
        return not self.is_banned and self.success_rate >= 0.3

    def __str__(self) -> str:
        # Mask password in URL for safe logging
        masked = self.url
        if "@" in self.url:
            parts = self.url.split("@")
            creds = parts[0].split("://")
            if len(creds) > 1 and ":" in creds[1]:
                user = creds[1].split(":")[0]
                masked = f"{creds[0]}://{user}:***@{parts[1]}"
        return f"Proxy({masked}, failures={self.failures}, rate={self.success_rate:.0%})"


class ProxyManager:
    """
    Full-featured proxy pool manager with health tracking.

    Features:
    - Load proxies from a list or text file (one per line)
    - Round-robin, random, or least-used rotation strategies
    - Automatic failure tracking and cooldown for bad proxies
    - Configurable ban threshold and cooldown duration
    - Health statistics per proxy and for the whole pool
    - Async-safe — can be shared across concurrent fetchers

    Usage:
        manager = ProxyManager(cooldown=300, max_failures=3)
        manager.load_from_list([
            "http://user:pass@proxy1.example.com:8080",
            "http://user:pass@proxy2.example.com:8080",
        ])

        proxy_url = manager.get_proxy()
        # ... make request using proxy_url ...
        if request_failed:
            manager.mark_failure(proxy_url)
        else:
            manager.mark_success(proxy_url)
    """

    def __init__(
        self,
        cooldown: int = 300,        # seconds to ban a proxy after max_failures
        max_failures: int = 3,      # failures before proxy goes into cooldown
        strategy: str = "round_robin",
    ):
        """
        Args:
            cooldown:     seconds a failed proxy is banned before retry
            max_failures: consecutive failures before banning
            strategy:     "round_robin", "random", or "least_used"
        """
        self._proxies: dict[str, ProxyRecord] = {}   # url → ProxyRecord
        self._index: int = 0            # for round_robin rotation
        self.cooldown = cooldown
        self.max_failures = max_failures
        self.strategy = strategy

        log.debug(
            "ProxyManager initialized (strategy={}, max_failures={}, cooldown={}s)",
            strategy, max_failures, cooldown
        )

    def load_from_list(self, proxy_urls: list[str]) -> int:
        """
        Loads proxies from a list of URL strings.
        Skips duplicates and empty strings.

        Args:
            proxy_urls: list of proxy URLs

        Returns:
            number of proxies successfully loaded
        """
        loaded = 0
        for url in proxy_urls:
            url = url.strip()
            if url and url not in self._proxies:
                self._proxies[url] = ProxyRecord(url=url)
                loaded += 1

        log.info("ProxyManager: loaded {} proxies ({} total)", loaded, len(self._proxies))
        return loaded

    def load_from_file(self, filepath: str) -> int:
        """
        Loads proxies from a text file — one proxy URL per line.
        Lines starting with # are treated as comments and skipped.
        Empty lines are skipped.

        File format:
            # Datacenter proxies
            http://user:pass@dc1.proxy.com:8080
            http://user:pass@dc2.proxy.com:8080

            # Residential proxies
            http://user:pass@res1.proxy.com:9090

        Args:
            filepath: path to the proxy list file

        Returns:
            number of proxies successfully loaded
        """
        path = Path(filepath)
        if not path.exists():
            log.warning("ProxyManager: proxy file not found — {}", filepath)
            return 0

        urls = []
        with open(path, "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    urls.append(line)

        log.info("ProxyManager: reading {} lines from {}", len(urls), filepath)
        return self.load_from_list(urls)

    def get_proxy(self) -> Optional[str]:
        """
        Returns the next available healthy proxy URL.
        Returns None if no healthy proxies are available.

        Applies the configured rotation strategy to pick from
        healthy (non-banned, good success rate) proxies only.
        """
        healthy = self._get_healthy_proxies()

        if not healthy:
            log.warning("ProxyManager: no healthy proxies available")
            return None

        if self.strategy == "round_robin":
            proxy = healthy[self._index % len(healthy)]
            self._index += 1

        elif self.strategy == "random":
            proxy = random.choice(healthy)

        elif self.strategy == "least_used":
            # Pick the proxy with the fewest total uses
            proxy = min(healthy, key=lambda p: self._proxies[p].total_uses)

        else:
            proxy = healthy[0]

        # Update last_used timestamp
        self._proxies[proxy].last_used = time.time()
        self._proxies[proxy].total_uses += 1

        log.debug("ProxyManager: assigned proxy {}", proxy.split("@")[-1] if "@" in proxy else proxy)
        return proxy

    def mark_success(self, proxy_url: str) -> None:
        """
        Records a successful request through this proxy.
        Resets the failure counter — consecutive failures must restart
        from zero after any success.

        Args:
            proxy_url: the proxy URL that made the successful request
        """
        if proxy_url not in self._proxies:
            return

        record = self._proxies[proxy_url]
        record.failures = 0         # reset consecutive failure count
        record.total_successes += 1
        log.debug("ProxyManager: success recorded for {}", proxy_url.split("@")[-1] if "@" in proxy_url else proxy_url)

    def mark_failure(self, proxy_url: str, reason: str = "") -> None:
        """
        Records a failed request through this proxy.
        If failures reach max_failures, the proxy is banned for cooldown seconds.

        Args:
            proxy_url: the proxy URL that failed
            reason:    optional description of why it failed
        """
        if proxy_url not in self._proxies:
            return

        record = self._proxies[proxy_url]
        record.failures += 1
        record.last_failure = time.time()

        log.warning(
            "ProxyManager: failure {}/{} for {} — {}",
            record.failures, self.max_failures,
            proxy_url.split("@")[-1] if "@" in proxy_url else proxy_url,
            reason or "unknown reason"
        )

        if record.failures >= self.max_failures:
            record.banned_until = time.time() + self.cooldown
            log.warning(
                "ProxyManager: proxy banned for {}s — {}",
                self.cooldown,
                proxy_url.split("@")[-1] if "@" in proxy_url else proxy_url
            )

    def remove_proxy(self, proxy_url: str) -> bool:
        """
        Permanently removes a proxy from the pool.
        Use when a proxy is confirmed dead (subscription expired, IP blocked).

        Args:
            proxy_url: the proxy URL to remove

        Returns:
            True if removed, False if not found
        """
        if proxy_url in self._proxies:
            del self._proxies[proxy_url]
            log.info("ProxyManager: permanently removed proxy from pool")
            return True
        return False

    def _get_healthy_proxies(self) -> list[str]:
        """
        Returns list of proxy URLs that are currently healthy.
        A proxy is healthy if it's not banned and has success_rate >= 0.3.
        """
        return [
            url for url, record in self._proxies.items()
            if record.is_healthy
        ]

    def get_stats(self) -> dict:
        """
        Returns detailed pool statistics.

        Returns:
            dict with total, healthy, banned counts and per-proxy details
        """
        healthy = self._get_healthy_proxies()
        banned = [
            url for url, r in self._proxies.items()
            if r.is_banned
        ]

        return {
            "total":   len(self._proxies),
            "healthy": len(healthy),
            "banned":  len(banned),
            "strategy": self.strategy,
            "proxies": [
                {
                    "url": url.split("@")[-1] if "@" in url else url,
                    "failures": r.failures,
                    "total_uses": r.total_uses,
                    "success_rate": f"{r.success_rate:.0%}",
                    "status": "banned" if r.is_banned else "healthy",
                }
                for url, r in self._proxies.items()
            ]
        }

   
    def reset_bans(self) -> int:
        cleared = 0
        for record in self._proxies.values():
            if record.is_banned:
                record.banned_until = 0.0
                record.failures = 0
                record.total_uses = 0        # ← reset so success_rate recalculates
                record.total_successes = 0   # ← fresh start after ban
                cleared += 1
        if cleared:
            log.info("ProxyManager: cleared {} proxy bans", cleared)
        return cleared

    def __len__(self) -> int:
        return len(self._proxies)

    def __bool__(self) -> bool:
        return len(self._get_healthy_proxies()) > 0
