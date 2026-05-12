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


def register(*, container_fqdn, zone, value, trigger_reason="event", **kwargs):
    """
    Register a CNAME with Technitium DNS.

    DNS-specific (required): container_fqdn, zone, value.

    Accepts the common notifier base kwargs contract via **kwargs;
    container_name, docker_host, and stack_name are read out for
    log lines and the record comment. Unrecognised kwargs are
    ignored, which keeps the signature forward-compatible as the
    contract grows.
    """
    dns_url = os.environ.get("DNS_SERVER_URL")
    token = os.environ.get("DNS_SERVER_API_TOKEN")
    if not dns_url or not token:
        logger.error("Missing DNS_SERVER_URL or DNS_SERVER_API_TOKEN")
        return

    container_name = kwargs.get("container_name", "<unknown>")
    docker_host = kwargs.get("docker_host", "<unknown>")
    stack_name = kwargs.get("stack_name")

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
