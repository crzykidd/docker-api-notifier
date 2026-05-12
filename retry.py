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
  - Retries only on `requests.RequestException` (network errors,
    timeouts, connection errors, HTTP errors raised via
    `raise_for_status()`).
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
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

# Policy values — change here, not at call sites.
MAX_ATTEMPTS = 3
BACKOFF_MULTIPLIER = 1
BACKOFF_MIN_SECONDS = 2
BACKOFF_MAX_SECONDS = 10
RETRY_ON = (requests.RequestException,)


with_retry = retry(
    reraise=True,
    stop=stop_after_attempt(MAX_ATTEMPTS),
    wait=wait_exponential(
        multiplier=BACKOFF_MULTIPLIER,
        min=BACKOFF_MIN_SECONDS,
        max=BACKOFF_MAX_SECONDS,
    ),
    retry=retry_if_exception_type(RETRY_ON),
)
