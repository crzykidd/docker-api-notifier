import os
import requests
import urllib.parse
from datetime import datetime

def register(fqdn, zone, value, container_name, docker_host, stack_name=None):
    dns_url = os.environ.get("DNS_SERVER_URL")
    token = os.environ.get("DNS_SERVER_API_TOKEN")
    if not dns_url or not token:
        print("[ERROR] Missing DNS_SERVER_URL or DNS_SERVER_API_TOKEN")
        return

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
        print(f"[INFO] DNS update response for {fqdn}: {response.text}")
    except Exception as e:
        print(f"[ERROR] DNS update failed: {e}")
