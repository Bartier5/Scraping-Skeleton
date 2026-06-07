# ── fetcher/session_manager.py ────────────────────────────────────────────────
# Session manager for scraping sites that require authentication.
#
# What problem does this solve?
#   Some sites require you to be logged in to access data.
#   Without a session manager, you'd need to manually handle:
#   - Logging in (POST request with credentials)
#   - Storing the session cookies
#   - Attaching cookies to every subsequent request
#   - Detecting when the session expires
#   - Re-authenticating automatically
#
#   SessionManager handles all of this so the fetcher just works.
#
# How it works:
#   1. On first use, it logs in using provided credentials
#   2. Stores the session cookies from the login response
#   3. Injects those cookies into every subsequent request
#   4. Monitors responses for session expiry signals (401, redirect to login)
#   5. Auto re-authenticates when session expires
#
# This is built on top of HttpFetcher so it works synchronously.
# For async session management, the cookies are extracted and injected
# into AsyncFetcher headers manually.

import time
from typing import Optional, Dict, Any
import requests
from requests import Session

from fetcher.base_fetcher import BaseFetcher, FetchResult
from fetcher.http_fetcher import HttpFetcher
from config.config import Config
from utils.logger import log
from utils.helpers import get_domain


class SessionConfig:
    """
    Configuration for a site that requires authentication.
    Defines how to log in and how to detect session expiry.

    Fields:
        login_url:       URL of the login endpoint (POST request goes here)
        credentials:     dict of form fields e.g. {"username": "x", "password": "y"}
        success_check:   string that appears in the response when login succeeds
                         e.g. "Welcome" or "dashboard" — used to verify login worked
        expiry_signals:  list of signals that mean the session has expired:
                         - HTTP status codes e.g. 401
                         - URL substrings e.g. "/login" (redirected to login page)
        session_ttl:     how many seconds before we proactively re-login
                         (0 = only re-login when expiry is detected)
    """

    def __init__(
        self,
        login_url: str,
        credentials: Dict[str, str],
        success_check: str = "",
        expiry_signals: list = None,
        session_ttl: int = 3600,        # re-login every hour by default
    ):
        self.login_url = login_url
        self.credentials = credentials
        self.success_check = success_check
        self.expiry_signals = expiry_signals or [401, 403, "/login", "sign-in"]
        self.session_ttl = session_ttl


class SessionManager(BaseFetcher):
    """
    Fetcher wrapper that maintains an authenticated session.

    Wraps HttpFetcher with automatic login, cookie management,
    and session expiry detection + re-authentication.
    """

    def __init__(
        self,
        session_config: SessionConfig,
        fetcher_config: dict = None,
    ):
        """
        Args:
            session_config: SessionConfig defining how to authenticate
            fetcher_config: optional HttpFetcher config overrides
        """
        super().__init__(fetcher_config)

        self._session_config = session_config
        self._fetcher = HttpFetcher(config=fetcher_config)

        # Session state tracking
        self._is_authenticated = False     # have we logged in yet
        self._login_time: float = 0        # when we last logged in (unix timestamp)
        self._cookies: Dict[str, str] = {} # stored session cookies

        log.debug("SessionManager initialized for: {}",
                  get_domain(session_config.login_url))

    def login(self) -> bool:
        """
        Performs the login request and stores session cookies.

        Sends a POST request to the login URL with the credentials.
        If login succeeds, extracts and stores the cookies for future requests.

        Returns:
            True if login succeeded, False if it failed
        """
        log.info("SessionManager: logging in to {}",
                 self._session_config.login_url)

        try:
            # POST the credentials to the login endpoint
            response = self._fetcher.session.post(
                self._session_config.login_url,
                data=self._session_config.credentials,  # form data
                timeout=Config.TIMEOUT,
                allow_redirects=True,   # follow the post-login redirect
            )

            # Check if login was successful
            if self._session_config.success_check:
                if self._session_config.success_check not in response.text:
                    log.error("SessionManager: login failed — success check not found")
                    return False

            # Check for obvious failure status codes
            if response.status_code >= 400:
                log.error("SessionManager: login failed — HTTP {}",
                          response.status_code)
                return False

            # Store the session cookies from the response
            # requests.Session automatically stores cookies but we also
            # keep a dict copy for inspection and injection into other fetchers
            self._cookies = dict(response.cookies)
            self._is_authenticated = True
            self._login_time = time.time()

            log.info("SessionManager: login successful — {} cookies stored",
                     len(self._cookies))
            return True

        except Exception as e:
            log.error("SessionManager: login exception — {}", str(e))
            return False

    def _is_session_expired(self, result: FetchResult) -> bool:
        """
        Checks if a fetch result indicates the session has expired.

        Looks for:
        - Status codes listed in expiry_signals (e.g. 401)
        - URL redirects listed in expiry_signals (e.g. "/login")
        - TTL expiry (session is older than session_ttl seconds)

        Args:
            result: FetchResult from a recent request

        Returns:
            True if session appears expired, False if still valid
        """
        cfg = self._session_config

        # Check TTL — proactively re-login before expiry
        if cfg.session_ttl > 0:
            age = time.time() - self._login_time
            if age > cfg.session_ttl:
                log.info("SessionManager: session TTL exceeded ({:.0f}s > {}s)",
                         age, cfg.session_ttl)
                return True

        # Check for expiry signals in the response
        for signal in cfg.expiry_signals:
            if isinstance(signal, int):
                # Numeric signal — HTTP status code
                if result.status_code == signal:
                    log.warning("SessionManager: expiry signal — HTTP {}", signal)
                    return True
            elif isinstance(signal, str):
                # String signal — check if it appears in the final URL
                if signal in result.url:
                    log.warning("SessionManager: expiry signal — URL contains '{}'",
                                signal)
                    return True

        return False

    def _ensure_authenticated(self) -> bool:
        """
        Ensures we have a valid session, logging in if necessary.
        Called before every fetch to guarantee session validity.

        Returns:
            True if authenticated, False if login failed
        """
        if not self._is_authenticated:
            return self.login()
        return True

    def fetch(self, url: str, **kwargs) -> FetchResult:
        """
        Fetch a URL with session authentication.

        Automatically handles:
        - Initial login if not yet authenticated
        - Cookie injection into the request
        - Session expiry detection
        - Re-authentication if session expired

        Args:
            url:      the URL to fetch
            **kwargs: passed through to HttpFetcher.fetch()

        Returns:
            FetchResult — same as HttpFetcher but with session cookies applied
        """
        # Ensure we're logged in before fetching
        if not self._ensure_authenticated():
            return self.make_error_result(
                url, RuntimeError("Authentication failed — cannot fetch")
            )

        # Fetch the URL — session cookies are automatically included
        # because we're using the same requests.Session that logged in
        result = self._fetcher.fetch(url, **kwargs)

        # Check if the response indicates session expiry
        if self._is_session_expired(result):
            log.info("SessionManager: session expired — re-authenticating")
            self._is_authenticated = False

            # Try to re-login
            if not self.login():
                return self.make_error_result(
                    url, RuntimeError("Re-authentication failed")
                )

            # Retry the original request with fresh session
            log.debug("SessionManager: retrying request after re-auth: {}", url)
            result = self._fetcher.fetch(url, **kwargs)

        return result

    async def async_fetch(self, url: str, **kwargs) -> FetchResult:
        """Async wrapper — runs sync fetch in thread pool."""
        import asyncio
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: self.fetch(url, **kwargs))

    async def fetch_many(self, urls: list[str], **kwargs) -> list[FetchResult]:
        """Fetch multiple URLs sequentially with session management."""
        results = []
        for url in urls:
            result = self.fetch(url, **kwargs)
            results.append(result)
        return results

    def get_cookies(self) -> Dict[str, str]:
        """
        Returns current session cookies as a plain dict.
        Useful for injecting cookies into AsyncFetcher or BrowserFetcher.

        Usage with AsyncFetcher:
            cookies = session_manager.get_cookies()
            cookie_header = "; ".join(f"{k}={v}" for k, v in cookies.items())
            result = await async_fetcher.async_fetch(url, headers={"Cookie": cookie_header})
        """
        return self._cookies.copy()

    def get_cookie_header(self) -> str:
        """
        Returns cookies formatted as a Cookie HTTP header string.

        Example output: "session_id=abc123; user_token=xyz789"
        """
        return "; ".join(f"{k}={v}" for k, v in self._cookies.items())

    def logout(self) -> None:
        """Clears session state — next request will require re-login."""
        self._is_authenticated = False
        self._cookies = {}
        self._login_time = 0
        log.debug("SessionManager: logged out")

    def close(self) -> None:
        """Closes the underlying HttpFetcher session."""
        self._fetcher.close()
        log.debug("SessionManager: closed")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False
