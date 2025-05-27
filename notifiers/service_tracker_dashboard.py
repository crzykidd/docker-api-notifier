import os
import requests
from datetime import datetime
import json

def register(container_name, docker_host, container_id=None, internalurl=None, externalurl=None, stack_name=None, docker_status=None, internal_health=None, external_health=None, image=None, group=None, started_at=None):
    dashboard_url = os.environ.get("SERVICE_TRACKER_URL")
    api_token = os.environ.get("SERVICE_TRACKER_API_TOKEN")

    if not dashboard_url or not api_token:
        print("[INFO] Not enabling Service Tracker Dashboard integration — missing SERVICE_TRACKER_URL or SERVICE_TRACKER_API_TOKEN")
        return

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
    if group:
        payload["started_at"] = started_at

    

    headers = {
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json"
    }

    # TEMP DEBUG LOG
    print("[DEBUG] Sending registration payload:")
    print(json.dumps(payload, indent=2))
    print(f"[DEBUG] Endpoint: {endpoint}")

    try:
        response = requests.post(endpoint, json=payload, headers=headers)
        response.raise_for_status()
        print(f"[DEBUG] Successfully registered: {container_name} on {docker_host}")
    except requests.RequestException as e:
        print(f"[ERROR] Failed to register container: {e}")
