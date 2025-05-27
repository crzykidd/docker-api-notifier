import os
import requests
from datetime import datetime
import json
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import logging
from logging.handlers import RotatingFileHandler

NOTIFIER_LOG_FILE = "/config/notifier.log"

# === Logging Setup ===
logger = logging.getLogger("std_notifier")
if not logger.handlers:
    log_formatter = logging.Formatter('[%(asctime)s] [%(levelname)s] %(message)s')
    log_handler = RotatingFileHandler(
        NOTIFIER_LOG_FILE, maxBytes=10 * 1024 * 1024, backupCount=1
    )
    log_handler.setFormatter(log_formatter)
    logger.setLevel(logging.INFO)
    logger.addHandler(log_handler)

    # Optional console logging
    if os.environ.get("STD_LOG_TO_STDOUT", "1") == "1":
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(log_formatter)
        logger.addHandler(console_handler)


@retry(
    reraise=True,
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type(requests.RequestException)
)
def post_with_retry(endpoint, payload, headers):
    response = requests.post(endpoint, json=payload, headers=headers)
    response.raise_for_status()
    return response


def register(container_name, docker_host, container_id=None, internalurl=None, externalurl=None, stack_name=None,
             docker_status=None, internal_health=None, external_health=None, image=None, group=None, started_at=None):

    dashboard_url = os.environ.get("SERVICE_TRACKER_URL")
    api_token = os.environ.get("SERVICE_TRACKER_API_TOKEN")

    if not dashboard_url or not api_token:
        logger.info("Not enabling Service Tracker Dashboard integration — missing SERVICE_TRACKER_URL or SERVICE_TRACKER_API_TOKEN")
        return

    # 🔔 Log notifier trigger with reason
    trigger_reason = docker_status if docker_status in {"boot", "refresh"} else "event"
    logger.info(f'STD notifier triggered for "{container_name}" due to "{trigger_reason}"')

    endpoint = f"{dashboard_url.rstrip('/')}/api/register"

    payload = {
        "host": docker_host,
        "container_name": container_name,
        "timestamp": datetime.now().isoformat(),
        "image": image
    }

    if container_id:
        payload["container_id"] = container_id
    if internalurl:
        payload["internalurl"] = internalurl
    if externalurl:
        payload["externalurl"] = externalurl
    if stack_name:
        payload["stack_name"] = stack_name
    if docker_status:
        payload["docker_status"] = docker_status
    if internal_health is not None:
        payload["internal_health_check_enabled"] = internal_health
    if external_health is not None:
        payload["external_health_check_enabled"] = external_health
    if group:
        payload["group"] = group
    if started_at:
        payload["started_at"] = started_at

    headers = {
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json"
    }

    logger.debug("Sending registration payload:")
    logger.debug(json.dumps(payload, indent=2))
    logger.debug(f"Endpoint: {endpoint}")

    try:
        post_with_retry(endpoint, payload, headers)
        logger.debug(f"Successfully registered: {container_name} on {docker_host}")
    except requests.RequestException as e:
        logger.error(f"Failed to register container '{container_name}' after retries: {e}")
