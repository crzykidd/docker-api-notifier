import os
import requests
import urllib.parse
from datetime import datetime
from logging_setup import get_logger
from retry import with_retry

logger = get_logger("dns_notifier")


@with_retry
def _do_dns_update(dns_url, params):
    response = requests.get(dns_url, params=params)
    response.raise_for_status()
    return response


def register(container_fqdn, zone, value, container_name, docker_host, stack_name=None, trigger_reason="event"):
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
        "domain": container_fqdn,
        "zone": zone,
        "type": "CNAME",
        "ttl": 300,
        "overwrite": "true",
        "value": value,
        "comments": comment,
    }

    try:
        response = _do_dns_update(dns_url, params)
        logger.info(f'DNS update response for {container_fqdn}: {response.text}')
    except requests.RequestException as e:
        logger.error(f'DNS update failed for {container_name} after retries: {e}')
