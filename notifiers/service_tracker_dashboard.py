import os
import requests
from datetime import datetime

def register(container_name, docker_host, container_id=None, internalurl=None, externalurl=None, stack_name=None, docker_status=None):
    dashboard_url = os.environ.get("SERVICE_TRACKER_URL")
    api_token = os.environ.get("SERVICE_TRACKER_API_TOKEN")

    if not dashboard_url or not api_token:
        print("[INFO] Not enabling Service Tracker Dashboard integration — missing SERVICE_TRACKER_URL or SERVICE_TRACKER_API_TOKEN")
        return

    endpoint = f"{dashboard_url.rstrip('/')}/api/register"

    payload = {
        "host": docker_host,
        "container_name": container_name,
        "timestamp": datetime.now().isoformat()
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

    headers = {
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json"
    }

    try:
        response = requests.post(endpoint, json=payload, headers=headers)
        print(f"[INFO] service-tracker-dashboard response: {response.status_code} {response.text}")
    except Exception as e:
        print(f"[ERROR] Failed to notify service-tracker-dashboard: {e}")
