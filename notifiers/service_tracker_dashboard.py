import os
import requests
from datetime import datetime
import json
from logging_setup import get_logger
from retry import with_retry

logger = get_logger("std_notifier")


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
    is forwarded as the JSON payload to STD's register endpoint.

    The wire format is updated to STD's canonical schema in a later
    session (SESSION 07). This session keeps the legacy wire format.
    """
    dashboard_url = os.environ.get("STD_URL")
    api_token = os.environ.get("STD_API_TOKEN")

    if not dashboard_url or not api_token:
        logger.info("Not enabling Service Tracker Dashboard integration — missing STD_URL or STD_API_TOKEN")
        return

    # Fallback timestamp if not provided
    kwargs.setdefault("timestamp", datetime.now().isoformat())

    container_name = kwargs.get("container_name")
    docker_host = kwargs.get("docker_host")

    trigger_reason = kwargs.get("docker_status") or "event"
    logger.info(f'STD notifier triggered for "{container_name}" due to "{trigger_reason}"')

    endpoint = f"{dashboard_url.rstrip('/')}/api/register"

    headers = {
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json"
    }

    logger.debug("Sending registration payload:")
    logger.debug(json.dumps(kwargs, indent=2))
    logger.debug(f"Endpoint: {endpoint}")

    try:
        post_with_retry(endpoint, kwargs, headers)
        logger.debug(f"Successfully registered: {container_name} on {docker_host}")
    except requests.RequestException as e:
        logger.error(f"Failed to register container '{container_name}' after retries: {e}")
