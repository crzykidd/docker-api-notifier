import os
from datetime import datetime

import requests

import health
from logging_setup import get_logger
from retry import REQUEST_TIMEOUT_SECONDS, with_retry

logger = get_logger("dns_notifier")


@with_retry
def _do_dns_update(dns_url, params):
    response = requests.get(dns_url, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()
    return response


DNS_TTL = 300
_ADD_SUFFIX = "/records/add"
_warned_url = False


def _norm(name):
    return str(name or "").strip().rstrip(".").lower()


def _existing_cname_matches(dns_url, token, fqdn, zone, value, ttl):
    """Best-effort: True only when `fqdn` already has exactly this CNAME.

    Uses Technitium's `records/get`. Any problem (bad URL shape, connection
    error, non-200, `status != "ok"`, odd payload) returns False so the
    caller falls through to the add. Never logs the URL or the raw
    exception: the token rides in the query string.
    """
    global _warned_url
    if not dns_url.endswith(_ADD_SUFFIX):
        if not _warned_url:
            _warned_url = True
            logger.debug(
                f"DNS_SERVER_URL does not end in {_ADD_SUFFIX}; "
                "skipping the unchanged-record check"
            )
        return False
    get_url = dns_url[: -len(_ADD_SUFFIX)] + "/records/get"
    try:
        response = requests.get(
            get_url,
            params={"token": token, "domain": fqdn, "zone": zone},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        body = response.json()
        if body.get("status") != "ok":
            return False
        records = body["response"]["records"]
        cnames = [
            r for r in records
            if r.get("type") == "CNAME" and _norm(r.get("name")) == _norm(fqdn)
        ]
        if len(cnames) != 1:
            return False
        record = cnames[0]
        return (
            _norm(record["rData"]["cname"]) == _norm(value)
            and int(record["ttl"]) == ttl
            and not record.get("disabled", False)
        )
    except Exception as e:
        logger.debug(f"DNS record lookup for {fqdn} failed, will add: {health.sanitize_error(e)}")
        return False


def register(*, container_fqdn, zone, value, **kwargs):
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
    action = kwargs.get("action", "<unknown>")

    logger.debug(f'DNS notifier triggered for "{container_name}" due to "{action}"')

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
        "ttl": DNS_TTL,
        "overwrite": "true",
        "value": value,
        "comments": comment,
    }

    if _existing_cname_matches(dns_url, token, container_fqdn, zone, value, DNS_TTL):
        logger.debug(f"DNS record {container_fqdn} already points at {value}; unchanged")
        health.record_success("dns")
        return

    try:
        response = _do_dns_update(dns_url, params)
        logger.debug(f'DNS update response for {container_fqdn}: {response.text}')
        # Technitium reports API errors as HTTP 200 with status != "ok".
        try:
            body = response.json()
            status = body.get("status")
            error_message = body.get("errorMessage")
        except ValueError:
            status, error_message = None, None
        if status is not None and status != "ok":
            err = RuntimeError(error_message or f"status {status}")
            logger.error(
                f'DNS update failed for {container_name}: {health.sanitize_error(err)}'
            )
            health.record_error("dns", err)
            return
        logger.info(f"DNS record {container_fqdn} CNAME {value}: set")
        health.record_success("dns")
    except requests.RequestException as e:
        # requests embeds the full URL in its errors, and the token rides in
        # the query string: never log the raw exception.
        logger.error(f'DNS update failed for {container_name} after retries: {health.sanitize_error(e)}')
        health.record_error("dns", e)
