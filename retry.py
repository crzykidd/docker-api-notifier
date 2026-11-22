"""
Shared retry policy for notifier modules.

Wraps `tenacity` with the project-wide retry policy. Use as a
decorator on functions that make outbound HTTP calls:

    from retry import with_retry

    @with_retry
    def my_outbound_call(...):
        ...

The retry policy:
  - 3 attempts total
  - Exponential backoff: 2s, 4s, 8s (capped at 10s)
  - Retries connection errors, timeouts, and HTTP 5xx errors raised via
    `raise_for_status()`. A 4xx response is a definitive answer (bad
    request, bad token, not found), so it raises immediately instead
    of burning the backoff window.
  - Re-raises the last exception if all attempts fail.

These values are deliberately module-level constants so a future
parameterized version (e.g. per-notifier policy presets) is a small
refactor rather than a redesign.

Idempotency: `with_retry` assumes the wrapped operation is idempotent.
If a request succeeds on the server but the response is lost in
transit, retrying will re-issue the same request. Both current
consumers (STD `/api/register` upsert, Technitium DNS with
`overwrite=true`) are idempotent. A future notifier wrapping a
non-idempotent operation must NOT use `with_retry` and should
implement explicit single-attempt error handling instead.
"""

import requests
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

# Policy values — change here, not at call sites.
MAX_ATTEMPTS = 3
BACKOFF_MULTIPLIER = 1
BACKOFF_MIN_SECONDS = 2
BACKOFF_MAX_SECONDS = 10
# Per-request timeout (seconds) for every outbound `requests` call. Use
# this at each call site so a hung downstream cannot block the event loop.
REQUEST_TIMEOUT_SECONDS = 10


def is_retryable(exc):
    """True for connection errors, timeouts and 5xx; False for 4xx."""
    if isinstance(exc, requests.HTTPError):
        response = exc.response
        status = getattr(response, "status_code", None)
        return status is None or status >= 500
    return isinstance(exc, requests.RequestException)


with_retry = retry(
    reraise=True,
    stop=stop_after_attempt(MAX_ATTEMPTS),
    wait=wait_exponential(
        multiplier=BACKOFF_MULTIPLIER,
        min=BACKOFF_MIN_SECONDS,
        max=BACKOFF_MAX_SECONDS,
    ),
    retry=retry_if_exception(is_retryable),
)
