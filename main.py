import os
import docker
from datetime import datetime
from notifiers import technitium_dns, service_tracker_dashboard
import threading
import time
from logging_setup import get_logger

logger = get_logger("main")

# === Settings ===
logger.debug("main.py is running")
STD_REFRESH_SECONDS = int(os.environ.get("STD_REFRESH_SECONDS", "60"))  # Default to 60 seconds

# Real Docker events the notifier subscribes to.
WATCHED_DOCKER_ACTIONS = frozenset({
    "start", "stop", "die", "pause", "unpause",
    "destroy", "kill", "update",
})

# Synthetic actions the notifier injects (not from Docker).
SYNTHETIC_ACTIONS = frozenset({"boot", "refresh"})

# Per-notifier action sets. Each notifier declares the actions it wants
# to be invoked for, drawn from WATCHED_DOCKER_ACTIONS and SYNTHETIC_ACTIONS.
NOTIFIER_TRIGGERS = {
    "dns": {"boot", "start"},
    "service-tracker-dashboard": WATCHED_DOCKER_ACTIONS | SYNTHETIC_ACTIONS,
}


def is_trigger_enabled(notifier, action):
    return action in NOTIFIER_TRIGGERS.get(notifier, {"start"})


def periodic_update_loop(docker_host):
    client = docker.from_env()
    while True:
        logger.debug(f"STD refresh loop — every {STD_REFRESH_SECONDS} sec")
        for container in client.containers.list():
            try:
                handle_container_event(container, docker_host, action="refresh")
            except Exception as e:
                logger.error(f"Refresh failed for {container.name}: {e}")
        time.sleep(STD_REFRESH_SECONDS)


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

    base_kwargs = {
        "container_name": container.name,
        "container_id": container.id,
        "docker_host": docker_host,
        "docker_status": container.attrs["State"]["Status"],
        "image_name": container.attrs["Config"]["Image"],
        "stack_name": labels.get("com.docker.compose.project"),
        "started_at": container.attrs["State"]["StartedAt"],
        "action": action,
    }

    logger.info(f"[MATCH] Container {action.upper()}: {container.name}")

    if action in NOTIFIER_TRIGGERS["dns"] and "dns" in notifier_list:
        container_hostname = labels.get("dockernotifier.dns.containerhostname")
        zone_label = labels.get("dockernotifier.dns.containerzone")
        docker_domain = labels.get("dockernotifier.dns.dockerdomain")
        container_fqdn = (
            f"{container_hostname}.{zone_label}"
            if container_hostname and zone_label
            else None
        )

        if container_fqdn and docker_domain and zone_label:
            logger.info(f"DNS notifier triggered for {container.name} on {action}")
            technitium_dns.register(
                **base_kwargs,
                container_fqdn=container_fqdn,
                zone=zone_label,
                value=f"{docker_host}.{docker_domain}",
            )
        else:
            logger.warning(f"Missing DNS label info for {container.name}, skipping DNS registration")

    if "service-tracker-dashboard" in notifier_list and action in NOTIFIER_TRIGGERS["service-tracker-dashboard"]:
        logger.info(f"STD notifier triggered for {container.name} on {action}")
        std_extras = {
            key.replace("dockernotifier.std.", ""): value
            for key, value in labels.items()
            if key.startswith("dockernotifier.std.")
        }
        service_tracker_dashboard.register(**base_kwargs, **std_extras)

def main():
    client = docker.from_env()
    docker_host = get_host_name()
    logger.info(f"Starting Docker API Notifier on host: {docker_host}")

    logger.info("Running boot-time scan of existing containers...")
    for container in client.containers.list():
        try:
            handle_container_event(container, docker_host, action="boot")
        except Exception as e:
            logger.error(f"Failed to process container {container.name} on boot: {e}")

    threading.Thread(target=periodic_update_loop, args=(docker_host,), daemon=True).start()

    for event in client.events(decode=True):
        if event.get("Type") != "container":
            continue
        action = event.get("Action")
        if action not in WATCHED_DOCKER_ACTIONS:
            continue
        container_id = event.get("Actor", {}).get("ID") or event.get("id")
        if not container_id:
            continue
        try:
            container = client.containers.get(container_id)
            handle_container_event(container, docker_host, action=action)
        except docker.errors.NotFound:
            pass
        except Exception as e:
            logger.error(f"Failed to handle {action} event for {container_id}: {e}")


if __name__ == "__main__":
    main()
