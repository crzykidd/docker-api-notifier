import os
import docker
from datetime import datetime
from notifiers import technitium_dns, service_tracker_dashboard

print("[DEBUG] main.py is running")

def get_host_name():
    try:
        with open("/etc/host_hostname", "r") as f:
            return f.read().strip()
    except Exception:
        return os.uname()[1]

def handle_container_start(container, docker_host):
    labels = container.attrs["Config"]["Labels"]
    notifier_list_raw = labels.get("dockernotifier.notifiers", "").strip()
    if not notifier_list_raw:
        return
    notifier_list = [n.strip() for n in notifier_list_raw.split(",") if n.strip()]

    container_name = container.name
    container_hostname = labels.get("dockernotifier.containerhostname")
    zone_label = labels.get("dockernotifier.containerzone")
    docker_domain = labels.get("dockernotifier.dockerdomain")
    fqdn = f"{container_hostname}.{zone_label}"

    stack_name = labels.get("com.docker.compose.project")
    if not stack_name and "_" in container.name:
        stack_name = container.name.split('_')[0]

    print(f"[MATCH] Container started:")
    print(f"  Container Name:      {container_name}")
    print(f"  Container Hostname:  {container_hostname}")
    print(f"  Zone Label:          {zone_label}")
    print(f"  Docker Host:         {docker_host}")
    print(f"  Docker Domain:       {docker_domain}")
    print(f"  Stack Name:          {stack_name}")

    if "dns" in notifier_list:
        technitium_dns.register(
            fqdn=fqdn,
            zone=zone_label,
            value=f"{docker_host}.{docker_domain}",
            container_name=container_name,
            docker_host=docker_host,
            stack_name=stack_name
        )

    if "service-tracker-dashboard" in notifier_list:
        internalurl = labels.get("dockernotifier.std.internalurl")
        externalurl = labels.get("dockernotifier.std.externalurl")

        service_tracker_dashboard.register(
            container_name=container_name,
            docker_host=docker_host,
            container_id=container.id,
            internalurl=internalurl,
            externalurl=externalurl,
            stack_name=stack_name
        )

def main():
    client = docker.from_env()
    docker_host = get_host_name()
    print(f"[INFO] Starting Docker API Notifier on host: {docker_host}")

    # 🔍 Scan all running containers on startup
    for container in client.containers.list():
        try:
            handle_container_start(container, docker_host)
        except Exception as e:
            print(f"[ERROR] Failed to process running container {container.name}: {e}")

    for event in client.events(decode=True):
        if event.get("Action") != "start":
            continue
        container_id = event.get("id")
        try:
            container = client.containers.get(container_id)
            handle_container_start(container, docker_host)
        except Exception as e:
            print(f"[ERROR] Failed to handle container {container_id}: {e}")

if __name__ == "__main__":
    main()
