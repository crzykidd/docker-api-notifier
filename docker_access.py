"""
Shared "did Docker let us look that up?" state for the optional lookups.

A Docker socket proxy (e.g. tecnativa/docker-socket-proxy) answers 403 to
API sections it does not allow. Two best-effort lookups hit that:
`networks` (per-network driver, for STD network details) and `images`
(the running image's digests, for STD `image_info`). Both used to fail
quietly, leaving the data missing with no hint why.

This module holds, per lookup kind, whether the last attempt was allowed
or denied, warns once when a kind *becomes* denied (naming the proxy
setting to change), backs off so a denied lookup is not retried on every
refresh, and logs once at INFO when it starts working again. `/healthz`
reads `statuses()`.

Only exactly 403 counts. `docker.errors.NotFound` (404) is an APIError
subclass too, but it is the normal "network/image was removed" case.

Thread safety: the refresh thread and the event loop both run lookups, so
all state is behind one lock.
"""

import threading
import time

import docker

from logging_setup import get_logger

logger = get_logger("docker_access")

BACKOFF_SECONDS = 600  # retry a denied lookup after 10 minutes

# kind -> (what the lookup is for, proxy setting, what is lost when denied)
KINDS = {
    "networks": (
        "network",
        "NETWORKS=1",
        "STD cannot recognise macvlan, ipvlan or host networks",
    ),
    "images": (
        "image",
        "IMAGES=1",
        "STD's image-digest update check gets no data",
    ),
}

_lock = threading.Lock()
_state = {}  # kind -> {"status": "ok"|"denied", "retry_at": monotonic or None}


def reset():
    """Forget all state (tests)."""
    with _lock:
        _state.clear()


def is_denied_error(exc):
    """True for a 403 from the Docker API (e.g. a socket proxy refusing)."""
    return isinstance(exc, docker.errors.APIError) and exc.status_code == 403


def should_skip(kind):
    """True while `kind` is denied and the back-off has not yet expired."""
    with _lock:
        entry = _state.get(kind)
        return bool(entry and entry["status"] == "denied"
                    and time.monotonic() < entry["retry_at"])


def record_denied(kind):
    """Note a 403. Warns only on the transition into denied. Returns True if it warned."""
    noun, setting, lost = KINDS[kind]
    with _lock:
        entry = _state.get(kind)
        transition = not (entry and entry["status"] == "denied")
        _state[kind] = {"status": "denied",
                        "retry_at": time.monotonic() + BACKOFF_SECONDS}
    if transition:
        logger.warning(
            f"Docker refused the {noun} lookup (403). If the notifier runs behind a "
            f"docker-socket-proxy, set {setting} on it (it stays read-only with "
            f"POST=0); without it {lost}. Retrying in {BACKOFF_SECONDS // 60} minutes."
        )
    return transition


def record_ok(kind):
    """Note a successful lookup. Logs once at INFO if it was denied before."""
    with _lock:
        entry = _state.get(kind)
        was_denied = bool(entry and entry["status"] == "denied")
        _state[kind] = {"status": "ok", "retry_at": None}
    if was_denied:
        logger.info(f"Docker {KINDS[kind][0]} lookups allowed again")


def status(kind):
    """`"ok"`, `"denied"`, or `"unknown"` (no lookup has run yet)."""
    with _lock:
        entry = _state.get(kind)
        return entry["status"] if entry else "unknown"


def statuses():
    return {kind: status(kind) for kind in KINDS}
