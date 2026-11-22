import json
import os
import threading
import time
from datetime import datetime

import requests

import health
from logging_setup import get_logger
from retry import REQUEST_TIMEOUT_SECONDS, with_retry

logger = get_logger("std_notifier")


# Map from "what arrives in kwargs" to "what STD's canonical schema expects".
# Source keys come from a mix of the base kwargs contract and stripped
# `dockernotifier.std.*` labels.
_LEGACY_TO_CANONICAL = {
    # Base kwargs renames
    "docker_host": "host",
    # Label-derived renames
    "group": "group_name",
    "internal.health": "internal_health_check_enabled",
    "internal_health": "internal_health_check_enabled",
    "external.health": "external_health_check_enabled",
    "external_health": "external_health_check_enabled",
    "icon": "image_icon",
    "sort.priority": "sort_priority",
}

# Keys that should pass through unchanged.
_PASSTHROUGH = {
    "container_name", "container_id", "docker_status", "stack_name",
    "started_at", "image_name", "internalurl", "externalurl",
    "timestamp",
    # v0.3.2: network/port capture fields. Already in canonical shape;
    # consumed by STD v0.6.0+.
    "networks", "exposed_ports", "published_ports",
    # v0.4.0: interpreter outputs. List of ExposureObservation dicts
    # (possibly empty); consumed by STD v0.6.0+. An empty list means
    # "interpreters ran and nothing matched" (STD clears exposure
    # rows). The notifier omits the field entirely when no
    # interpreters are loaded (STD preserves existing rows).
    "exposure_observations",
    # v0.5.0: the running image's digests and OCI labels. Consumed by STD
    # v0.12.0+ only; the notifier sends it only when STD's /api/v1/meta
    # advertises the "image_info" feature (see image_info_supported()).
    "image_info",
}

# Keys in the canonical schema that need type coercion from string.
_BOOL_FIELDS = {"internal_health_check_enabled", "external_health_check_enabled"}
_INT_FIELDS = {"sort_priority"}


def _to_canonical(kwargs: dict) -> dict:
    """
    Translate the notifier's working kwargs dict into a payload
    matching STD v0.5.0's canonical schema for /api/v1/register.

    Unknown keys are dropped (with a debug log). Type coercion is
    applied for boolean and integer fields; coercion failures cause
    the field to be dropped with a warning.
    """
    out = {}
    for key, value in kwargs.items():
        if value is None:
            continue
        canonical_key = _LEGACY_TO_CANONICAL.get(key, key)
        if canonical_key not in _PASSTHROUGH \
           and canonical_key not in _LEGACY_TO_CANONICAL.values():
            logger.debug(f"Dropping unknown key '{key}' from STD payload")
            continue
        if canonical_key in _BOOL_FIELDS:
            value = str(value).strip().lower() in ("true", "1", "yes")
        elif canonical_key in _INT_FIELDS:
            try:
                value = int(value)
            except (TypeError, ValueError):
                logger.warning(
                    f"Could not coerce {canonical_key}='{value}' to int; dropping"
                )
                continue
        out[canonical_key] = value
    return out


def is_configured():
    """True when both STD env vars are set, i.e. STD dispatch can run.

    Lets `main.py` gate STD dispatch and the periodic refresh loop
    without hardcoding which env vars STD owns.
    """
    return bool(os.environ.get("STD_URL") and os.environ.get("STD_API_TOKEN"))


# --- STD capability gate (GET /api/v1/meta) -------------------------------
#
# STD's schema forbids unknown keys, so `image_info` may only be sent to an
# STD that advertises it. The answer is cached and shared between the event
# loop and the refresh-loop thread, hence the lock. It is re-checked when the
# X-STD-API-Revision header on a register response changes, or after a
# register 400 that rejects image_info.

# After a failed /meta check, try again no sooner than this (seconds) when
# nothing else (a revision header) triggers a re-check.
META_RETRY_SECONDS = 300

_state_lock = threading.Lock()
_state = {
    "std_version": None,
    "api_revision": None,
    "features": None,          # list of str once /meta answered
    "image_info_supported": False,
    "last_check": None,        # epoch seconds of the last /meta attempt
    "last_check_ok": False,
    "rejected_revision": None,  # revision at which STD 400'd image_info
}
# Log-once flags; guarded by _state_lock.
_flags = set()


def _base_url():
    return os.environ.get("STD_URL", "").rstrip("/")


def std_status():
    """Snapshot of the cached STD capability state (for /healthz and tests)."""
    with _state_lock:
        out = dict(_state)
    out["features"] = list(out["features"]) if out["features"] is not None else None
    last = out.pop("last_check")
    out["last_check"] = (
        datetime.fromtimestamp(last).isoformat() if last is not None else None
    )
    out.pop("rejected_revision", None)
    return out


def _first_time(flag):
    """True the first time `flag` is raised (until discarded), so it logs once."""
    with _state_lock:
        if flag in _flags:
            return False
        _flags.add(flag)
        return True


def refresh_meta(reason="check"):
    """Ask STD what it supports (GET /api/v1/meta, no auth) and cache it.

    Never raises. A 404 (STD older than 0.10.0), a connection error, or an
    unparseable body all mean "no image_info support".
    """
    url = f"{_base_url()}/api/v1/meta"
    version = revision = features = None
    ok = False
    try:
        response = requests.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict) or not isinstance(body.get("features"), list):
            raise ValueError("unexpected /meta response shape")
        features = [str(f) for f in body["features"]]
        version = body.get("std_version")
        revision = body.get("api_revision")
        if not isinstance(revision, int):
            revision = None
        ok = True
    except (requests.RequestException, ValueError) as e:
        logger.debug(f"STD /meta check ({reason}) failed: {e}")

    with _state_lock:
        prev_version = _state["std_version"]
        prev_revision = _state["api_revision"]
        _state["last_check"] = time.time()
        _state["last_check_ok"] = ok
        if ok:
            _state["std_version"] = version
            _state["api_revision"] = revision
            _state["features"] = features
            rejected = (
                _state["rejected_revision"] is not None
                and _state["rejected_revision"] == revision
            )
            if not rejected:
                _state["rejected_revision"] = None
            _state["image_info_supported"] = "image_info" in features and not rejected
        else:
            _state["features"] = None
            _state["image_info_supported"] = False
        supported = _state["image_info_supported"]
        cur_revision = _state["api_revision"]

    if ok:
        if (version, revision) != (prev_version, prev_revision):
            logger.info(
                f"STD at {_base_url()}: version {version}, API revision {revision}"
            )
    elif _first_time("meta_failed"):
        logger.info(
            f"Could not read STD capabilities from {url} (STD older than 0.10.0 "
            f"or unreachable); not sending image_info."
        )

    if supported:
        _flags.discard("unsupported_logged")
    elif _first_time("unsupported_logged"):
        logger.info(
            f"STD at {_base_url()} does not accept image_info (API revision "
            f"{cur_revision if cur_revision is not None else 'unknown'}); "
            f"upgrade STD to 0.12.0+ for image digest checks."
        )
    if ok:
        _flags.discard("meta_failed")
    return supported


def image_info_supported():
    """True when the STD we talk to accepts `image_info`.

    Checks /meta on first use, and again (rate-limited) while the last
    check failed.
    """
    with _state_lock:
        last = _state["last_check"]
        last_ok = _state["last_check_ok"]
        supported = _state["image_info_supported"]
    if last is None or (not last_ok and time.time() - last >= META_RETRY_SECONDS):
        return refresh_meta("first use" if last is None else "retry")
    return supported


def check_meta_at_startup():
    """Log STD's version and API revision once at startup; fill the cache."""
    return refresh_meta("startup")


def _observe_headers(response):
    """Re-check /meta when X-STD-API-Revision changes; log X-STD-Version changes."""
    if response is None:
        return
    rev_header = response.headers.get("X-STD-API-Revision")
    ver_header = response.headers.get("X-STD-Version")
    revision_changed = False
    version_changed = False
    with _state_lock:
        if rev_header is not None:
            try:
                revision_changed = int(rev_header) != _state["api_revision"]
            except ValueError:
                pass
        if ver_header and ver_header != _state["std_version"]:
            version_changed = _state["std_version"] is not None
            if not revision_changed:
                _state["std_version"] = ver_header
    if revision_changed:
        refresh_meta("API revision header changed")
    elif version_changed:
        logger.info(f"STD at {_base_url()} version is now {ver_header}")


def _is_image_info_rejection(response):
    """True when a 400 register response blames the image_info field."""
    try:
        body = response.json()
    except ValueError:
        return False
    if not isinstance(body, dict):
        return False
    if "image_info" in (body.get("unknown_keys") or []):
        return True
    for detail in body.get("details") or []:
        loc = detail.get("loc") if isinstance(detail, dict) else None
        if isinstance(loc, (list, tuple)) and loc and loc[0] == "image_info":
            return True
    return False


@with_retry
def post_with_retry(endpoint, payload, headers):
    response = requests.post(
        endpoint, json=payload, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS
    )
    response.raise_for_status()
    return response


def _post_register(endpoint, payload, headers, container_name):
    """POST a register; on a 400 that rejects image_info, retry once without it."""
    try:
        response = post_with_retry(endpoint, payload, headers)
    except requests.HTTPError as e:
        response = e.response
        _observe_headers(response)
        if (
            "image_info" in payload
            and response is not None
            and response.status_code == 400
            and _is_image_info_rejection(response)
        ):
            logger.warning(
                f"STD rejected image_info for '{container_name}'; "
                f"retrying once without it"
            )
            with _state_lock:
                _state["rejected_revision"] = _state["api_revision"]
                _state["image_info_supported"] = False
            refresh_meta("register 400 on image_info")
            stripped = {k: v for k, v in payload.items() if k != "image_info"}
            return post_with_retry(endpoint, stripped, headers)
        raise
    _observe_headers(response)
    return response


def register(**kwargs):
    """
    Register a container with the Service Tracker Dashboard.

    Receives the common notifier base kwargs contract (see PRD §3.3)
    plus all stripped `dockernotifier.std.*` labels. The merged dict
    is translated into STD v0.5.0's canonical schema via
    `_to_canonical()` before being posted to `/api/v1/register`.
    """
    dashboard_url = os.environ.get("STD_URL")
    api_token = os.environ.get("STD_API_TOKEN")

    if not dashboard_url or not api_token:
        # Normally unreachable: main.py gates STD dispatch on
        # is_configured() and logs the disabled state once at startup.
        # Kept as a defensive guard; debug level avoids per-event spam.
        logger.debug("STD register() called without STD_URL/STD_API_TOKEN — skipping")
        return

    kwargs.setdefault("timestamp", datetime.now().isoformat())

    container_name = kwargs.get("container_name")
    action = kwargs.get("action", "event")
    logger.info(f'STD notifier triggered for "{container_name}" on "{action}"')

    # Defensive: never send image_info to an STD that has not advertised it.
    if kwargs.get("image_info") is not None and not image_info_supported():
        kwargs.pop("image_info")

    payload = _to_canonical(kwargs)

    if "host" not in payload or "container_name" not in payload:
        logger.error(
            f"STD payload missing required fields after canonical translation; "
            f"skipping. Payload keys: {sorted(payload.keys())}"
        )
        return

    endpoint = f"{dashboard_url.rstrip('/')}/api/v1/register"
    headers = {
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json",
    }

    logger.debug("Sending registration payload:")
    logger.debug(json.dumps(payload, indent=2))
    logger.debug(f"Endpoint: {endpoint}")

    try:
        _post_register(endpoint, payload, headers, container_name)
        logger.debug(f"Successfully registered: {container_name} on {payload.get('host')}")
        health.record_success("service_tracker_dashboard")
    except requests.RequestException as e:
        logger.error(f"Failed to register container '{container_name}' after retries: {e}")
        health.record_error("service_tracker_dashboard", e)
