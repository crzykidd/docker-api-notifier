"""
Reference template for a new notifier module.

This file is NOT wired into `main.py`'s dispatch. It exists as a
copy-and-modify starting point for adding a new downstream target.

To add a real notifier:

1. Copy this file to `notifiers/<target>.py` (e.g. `slack.py`).
2. Replace `_TARGET` placeholders with your target name.
3. Define your wire format in `_to_payload()`.
4. Wire the module into `main.py`'s dispatch (see PRD section 3.3).
5. Document env vars and labels in `README.md`.
6. Remove this top docstring; replace with module-specific docs.

The structure below follows the notifier module contract documented
in PRD section 3.3.
"""

import os
import json
from datetime import datetime

import requests

from logging_setup import get_logger
from retry import with_retry

# Replace "_template" with your target name (e.g. "slack").
logger = get_logger("_template_notifier")


@with_retry
def _send(endpoint: str, payload: dict, headers: dict) -> requests.Response:
    """The actual network call, wrapped with shared retry policy."""
    response = requests.post(endpoint, json=payload, headers=headers)
    response.raise_for_status()
    return response


def _to_payload(kwargs: dict) -> dict:
    """
    Translate the notifier's working kwargs into the downstream
    system's wire format.

    This is where target-specific shaping lives. Examples:
      - Map field names to what the downstream API expects.
      - Coerce types (string label values -> int / bool).
      - Drop fields the target doesn't care about.
      - Add target-specific fields (e.g. a Slack channel ID).
    """
    # Example: pass through the base contract verbatim.
    # Replace with real translation for your target.
    return {
        "container": kwargs.get("container_name"),
        "host": kwargs.get("docker_host"),
        "status": kwargs.get("docker_status"),
        "action": kwargs.get("action"),
        "at": kwargs.get("timestamp", datetime.now().isoformat()),
    }


def register(**kwargs) -> None:
    """
    Entry point invoked by `main.py`.

    Receives the base kwargs contract (PRD section 3.3) plus any
    extras `main.py` passes for this specific notifier (typically
    stripped `dockernotifier.<target>.*` labels).
    """
    # 1. Read required env vars. Return early if any are missing.
    target_url = os.environ.get("_TEMPLATE_URL")
    api_token = os.environ.get("_TEMPLATE_API_TOKEN")
    if not target_url or not api_token:
        logger.info(
            "Not enabling _template integration — missing "
            "_TEMPLATE_URL or _TEMPLATE_API_TOKEN"
        )
        return

    container_name = kwargs.get("container_name", "<unknown>")
    action = kwargs.get("action", "event")
    logger.info(f'_template notifier triggered for "{container_name}" on "{action}"')

    # 2. Translate to wire format.
    payload = _to_payload(kwargs)

    # 3. Build request.
    headers = {
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json",
    }

    logger.debug("Sending payload:")
    logger.debug(json.dumps(payload, indent=2))

    # 4. Send, catching only RequestException (transient failures).
    #    Programming errors propagate to main.py's outer try/except.
    try:
        _send(target_url, payload, headers)
        logger.debug(f"Successfully sent _template event for: {container_name}")
    except requests.RequestException as e:
        logger.error(
            f"Failed to send _template event for '{container_name}' after retries: {e}"
        )
