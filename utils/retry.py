# ── utils/retry.py ───────────────────────────────────────────────────────────
# Reusable retry decorator built on tenacity.
# Wraps any function so that if it raises an exception, it automatically
# retries with exponential backoff — waiting longer between each attempt.
#
# Usage:
#   from utils.retry import retry
#
#   @retry()                          # uses defaults from Config
#   def fetch(url): ...
#
#   @retry(max_attempts=5, min_wait=2, max_wait=30)   # custom values
#   async def async_fetch(url): ...

from tenacity import (
    retry as tenacity_retry,       # the core decorator factory
    stop_after_attempt,            # stop condition: give up after N attempts
    wait_exponential,              # wait strategy: double wait time each retry
    retry_if_exception_type,       # condition: only retry on specific exceptions
    before_sleep_log,              # hook: log a message before each sleep period
)
import logging                     # tenacity's sleep logger needs stdlib logging
from config.config import Config   # pull MAX_RETRIES from central config
from utils.logger import log       # our loguru logger for consistent output


def retry(
    max_attempts: int = Config.MAX_RETRIES,   # how many total attempts (1 original + retries)
    min_wait: float = 1.0,                    # minimum seconds to wait between retries
    max_wait: float = 60.0,                   # maximum seconds to wait (caps the backoff)
    exceptions: tuple = (Exception,),         # which exception types trigger a retry
):
    """
    Returns a tenacity retry decorator configured with exponential backoff.

    Exponential backoff means:
      Attempt 1 fails → wait 1s  → Attempt 2
      Attempt 2 fails → wait 2s  → Attempt 3
      Attempt 3 fails → wait 4s  → give up (if max_attempts=3)

    This prevents hammering a server that's struggling to respond.
    """

    return tenacity_retry(
        # Stop retrying after this many total attempts
        stop=stop_after_attempt(max_attempts),

        # Wait 2^n seconds between retries, clamped between min_wait and max_wait
        # e.g. 1s, 2s, 4s, 8s ... up to max_wait
        wait=wait_exponential(multiplier=1, min=min_wait, max=max_wait),

        # Only retry if the raised exception is one of the specified types
        # Default is (Exception,) which catches everything
        retry=retry_if_exception_type(exceptions),

        # Log a WARNING before each sleep so we can see retries happening in real time
        # uses stdlib logging internally — loguru will still capture it
        before_sleep=before_sleep_log(logging.getLogger(__name__), logging.WARNING),

        # Don't suppress the final exception — let it bubble up after all attempts fail
        # so the caller knows the operation truly failed
        reraise=True,
    )


# ── Convenience pre-built decorators ─────────────────────────────────────────
# Ready-to-use versions for common scenarios — import and apply directly

# Standard retry: uses config defaults, retries any exception
standard_retry = retry()

# Aggressive retry: more attempts, shorter waits — for fast, cheap requests
aggressive_retry = retry(max_attempts=5, min_wait=0.5, max_wait=10.0)

# Conservative retry: fewer attempts, longer waits — for rate-limited endpoints
conservative_retry = retry(max_attempts=2, min_wait=5.0, max_wait=120.0)
