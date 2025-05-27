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

def handle_container_event(container, docker_host, action):
    labels = container.attrs["Config"]["Labels"]
    notifier_list_raw = labels.get("dockernotifier.notifiers", "").strip()
    if not notifier_list_raw:
        return
    notifier_list = [n.strip() for n in notifier_list_raw.split(",") if n.strip()]

    container_name = container.name
    container_hostname = labels.get("dockernotifier.containerhostname")
    zone_label = labels.get("dockernotifier.containerzone")
    docker_domain = labels.get("dockernotifier.dockerdomain")
    fqdn = f"{container_hostname}.{zone_label}" if container_hostname and zone_label else None

    stack_name = labels.get("com.docker.compose.project")
    if not stack_name and "_" in container.name:
        stack_name = container.name.split('_')[0]

    print(f"[MATCH] Container {action.upper()}: {container_name}")

    if "dns" in notifier_list and action == "start":
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
        internal_health = labels.get("dockernotifier.std.internal.health")
        external_health = labels.get("dockernotifier.std.external.health")
        group = labels.get("dockernotifier.std.group")
        image = container.image.tags[0] if container.image.tags else container.image.short_id
        started_at = container.attrs["State"]["StartedAt"]
        service_tracker_dashboard.register(
            container_name=container_name,
            docker_host=docker_host,
            container_id=container.id,
            internalurl=internalurl,
            externalurl=externalurl,
            stack_name=stack_name,
            docker_status=action,
            internal_health=internal_health,
            external_health=external_health,
            image=image,
            group=group,
            started_at=started_at
        )




def main():
    client = docker.from_env()
    docker_host = get_host_name()
    print(f"[INFO] Starting Docker API Notifier on host: {docker_host}")

    # Process running containers at startup
    for container in client.containers.list():
        try:
            handle_container_event(container, docker_host, action="start")
        except Exception as e:
            print(f"[ERROR] Failed to process running container {container.name}: {e}")

    # Monitor live events
    watched_actions = {
        "start", "stop", "die", "pause", "unpause", "destroy", "kill", "update"
    }

    for event in client.events(decode=True):
        action = event.get("Action")
        if action not in watched_actions:
            continue
        container_id = event.get("id")
        try:
            container = client.containers.get(container_id)
            handle_container_event(container, docker_host, action)
        except Exception as e:
            print(f"[ERROR] Failed to handle {action} event for {container_id}: {e}")

if __name__ == "__main__":
    main()
