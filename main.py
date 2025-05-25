import os
import docker
print("[DEBUG] main.py is running")
from notifiers import technitium_dns
from datetime import datetime

def get_host_name():
    try:
        with open("/etc/host_hostname", "r") as f:
            return f.read().strip()
    except Exception:
        return os.uname()[1]

def handle_container_start(container, docker_host):
    labels = container.attrs["Config"]["Labels"]
    if labels.get("dockernotifier.enable", "false") != "true":
        return

    container_name = container.name
    container_hostname = labels.get("dockernotifier.containerhostname")
    zone_label = labels.get("dockernotifier.containerzone")
    docker_domain = labels.get("dockernotifier.dockerdomain")
    fqdn = f"{container_hostname}.{zone_label}"

    print(f"[MATCH] Container started:")
    print(f"  Container Name:      {container_name}")
    print(f"  Container Hostname:  {container_hostname}")
    print(f"  Zone Label:          {zone_label}")
    print(f"  Docker Host:         {docker_host}")
    print(f"  Docker Domain:       {docker_domain}")

    dns_type = os.environ.get("DNS_SERVER_TYPE", "").lower()
    if dns_type == "technitium":
        technitium_dns.register(
            fqdn=fqdn,
            zone=zone_label,
            value=f"{docker_host}.{docker_domain}",
            container_name=container_name,
            docker_host=docker_host
        )

def main():
    client = docker.from_env()
    docker_host = get_host_name()
    print(f"[INFO] Starting Docker API Notifier on host: {docker_host}")

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
