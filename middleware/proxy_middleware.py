# ── middleware/proxy_middleware.py ────────────────────────────────────────────
# Proxy middleware — injects a proxy into every outgoing request.
#
# Why use a proxy?
#   Sites detect scraping by seeing too many requests from the same IP.
#   A proxy routes your request through a different IP address so the
#   site sees traffic from many different locations, not one source.
#
# How it works:
#   On every process_request() call, it picks a proxy from the pool
#   (rotating through them) and injects it into the RequestContext.
#   The fetcher then uses that proxy for the actual HTTP call.

import random
from typing import Optional

from middleware.base_middleware import BaseMiddleware, RequestContext, ResponseContext
from utils.logger import log


class ProxyMiddleware(BaseMiddleware):
    """
    Rotates through a pool of proxies, injecting one into each request.

    Proxy format: "http://user:pass@host:port" or "http://host:port"

    Supports three rotation strategies:
    - "round_robin": cycle through proxies in order
    - "random":      pick a random proxy each time
    - "sticky":      use the same proxy per domain (avoids session issues)
    """

    def __init__(
        self,
        config: dict = None,
        proxies: list[str] = None,
        strategy: str = "round_robin",  # "round_robin", "random", "sticky"
    ):
        """
        Args:
            proxies:  list of proxy URLs
                      e.g. ["http://user:pass@proxy1:8080", "http://proxy2:8080"]
            strategy: rotation strategy
        """
        super().__init__(config)
        self._proxies = proxies or []
        self._strategy = strategy
        self._index = 0                         # current position for round_robin
        self._domain_map: dict[str, str] = {}   # domain → proxy for sticky strategy

        if not self._proxies:
            log.warning("ProxyMiddleware initialized with empty proxy list")
        else:
            log.debug(
                "ProxyMiddleware initialized ({} proxies, strategy={})",
                len(self._proxies), strategy
            )

    def _get_proxy(self, domain: str = "") -> Optional[str]:
        """
        Returns the next proxy based on the rotation strategy.

        Args:
            domain: used for sticky strategy to assign consistent proxy per domain

        Returns:
            proxy URL string or None if pool is empty
        """
        if not self._proxies:
            return None

        if self._strategy == "round_robin":
            # Cycle through proxies in order — index wraps around
            proxy = self._proxies[self._index % len(self._proxies)]
            self._index += 1
            return proxy

        elif self._strategy == "random":
            # Pick a random proxy each time
            return random.choice(self._proxies)

        elif self._strategy == "sticky":
            # Same proxy for the same domain — preserves sessions
            if domain and domain not in self._domain_map:
                # First time seeing this domain — assign a proxy
                self._domain_map[domain] = random.choice(self._proxies)
            return self._domain_map.get(domain, self._proxies[0])

        return self._proxies[0]

    async def process_request(self, context: RequestContext) -> RequestContext:
        """
        Injects a proxy into the request context before the request is sent.
        If no proxies configured or middleware disabled, passes through unchanged.
        """
        if not self.enabled or not self._proxies:
            return context

        from utils.helpers import get_domain
        domain = get_domain(context.url)
        proxy = self._get_proxy(domain)

        if proxy:
            context.proxy = proxy
            log.debug("ProxyMiddleware: injected proxy for {}", domain)

        return context

    async def process_response(self, context: ResponseContext) -> ResponseContext:
        """
        Checks if the response indicates the proxy was blocked (407, 403).
        Marks the proxy as failed in metadata for monitoring.
        """
        if not self.enabled:
            return context

        # 407 = Proxy Authentication Required — proxy creds wrong
        # Some sites return 403 when they detect/block a proxy
        if context.result.status_code in (407, 403):
            log.warning(
                "ProxyMiddleware: possible proxy block — HTTP {} for {}",
                context.result.status_code, context.result.url
            )
            context.metadata["proxy_blocked"] = True

        return context

    def add_proxy(self, proxy: str) -> None:
        """Adds a proxy to the pool at runtime."""
        self._proxies.append(proxy)
        log.debug("ProxyMiddleware: added proxy — pool size now {}", len(self._proxies))

    def remove_proxy(self, proxy: str) -> None:
        """Removes a proxy from the pool — called when a proxy is confirmed dead."""
        if proxy in self._proxies:
            self._proxies.remove(proxy)
            log.debug("ProxyMiddleware: removed proxy — pool size now {}", len(self._proxies))

    def get_stats(self) -> dict:
        """Returns current proxy pool stats."""
        return {
            "pool_size": len(self._proxies),
            "strategy": self._strategy,
            "sticky_assignments": len(self._domain_map),
        }
