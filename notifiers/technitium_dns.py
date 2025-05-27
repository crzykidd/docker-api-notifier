import os
import requests
import urllib.parse
from datetime import datetime
import logging
from logging.handlers import RotatingFileHandler

NOTIFIER_LOG_FILE = "/config/notifier.log"

# === Logging Setup ===
logger = logging.getLogger("dns_notifier")
if not logger.handlers:
    log_formatter = logging.Formatter('[%(asctime)s] [%(levelname)s] %(message)s')
    log_handler = RotatingFileHandler(
        NOTIFIER_LOG_FILE, maxBytes=10 * 1024 * 1024, backupCount=1
    )
    log_handler.setFormatter(log_formatter)
    logger.setLevel(logging.INFO)
    logger.addHandler(log_handler)

    # Optional: also log to console if running standalone
    if os.environ.get("DNS_LOG_TO_STDOUT", "1") == "1":
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(log_formatter)
        logger.addHandler(console_handler)


def register(fqdn, zone, value, container_name, docker_host, stack_name=None, trigger_reason="event"):
    dns_url = os.environ.get("DNS_SERVER_URL")
    token = os.environ.get("DNS_SERVER_API_TOKEN")
    if not dns_url or not token:
        logger.error("Missing DNS_SERVER_URL or DNS_SERVER_API_TOKEN")
        return

    logger.info(f'DNS notifier triggered for "{container_name}" due to "{trigger_reason}"')

    timestamp = datetime.now().strftime("%Y-%m-%dT%H:%M:%S%z")
    if stack_name:
        comment = f"Added by docker-api-notifier for {container_name} (stack: {stack_name}) at {timestamp} for {docker_host}"
    else:
        comment = f"Added by docker-api-notifier for {container_name} at {timestamp} for {docker_host}"

    params = {
        "token": token,
        "domain": fqdn,
        "zone": zone,
        "type": "CNAME",
        "ttl": 300,
        "overwrite": "true",
        "value": value,
        "comments": comment,
    }

    try:
        response = requests.get(dns_url, params=params)
        logger.info(f'DNS update response for {fqdn}: {response.text}')
    except Exception as e:
        logger.error(f'DNS update failed for {container_name}: {e}')
