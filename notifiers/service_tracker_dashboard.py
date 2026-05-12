import os
import requests
from datetime import datetime
import json
from logging_setup import get_logger
from retry import with_retry

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


@with_retry
def post_with_retry(endpoint, payload, headers):
    response = requests.post(endpoint, json=payload, headers=headers)
    response.raise_for_status()
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
        logger.info("Not enabling Service Tracker Dashboard integration — missing STD_URL or STD_API_TOKEN")
        return

    kwargs.setdefault("timestamp", datetime.now().isoformat())

    container_name = kwargs.get("container_name")
    action = kwargs.get("action", "event")
    logger.info(f'STD notifier triggered for "{container_name}" on "{action}"')

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
        post_with_retry(endpoint, payload, headers)
        logger.debug(f"Successfully registered: {container_name} on {payload.get('host')}")
    except requests.RequestException as e:
        logger.error(f"Failed to register container '{container_name}' after retries: {e}")
