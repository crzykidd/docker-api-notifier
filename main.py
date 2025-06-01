import os
import docker
from datetime import datetime
from notifiers import technitium_dns, service_tracker_dashboard
import threading
import time
import logging
from logging.handlers import RotatingFileHandler

# === Logging Setup ===
log_formatter = logging.Formatter('[%(asctime)s] [%(levelname)s] %(message)s')
log_handler = RotatingFileHandler(
    "/config/notifier.log", maxBytes=10 * 1024 * 1024, backupCount=4
)

log_handler.setFormatter(log_formatter)
log_handler.setLevel(logging.INFO)

logger = logging.getLogger()
logger.setLevel(logging.INFO)
logger.addHandler(log_handler)

# Optional: also log to console (stdout)
console_handler = logging.StreamHandler()
console_handler.setFormatter(log_formatter)
logger.addHandler(console_handler)

# === Settings ===
logger.debug("main.py is running")
STD_REFRESH_SECONDS = int(os.environ.get("STD_REFRESH_SECONDS", "60"))  # Default to 60 minutes
NOTIFIER_TRIGGERS = {
    "dns": {"boot", "start"},
    "service-tracker-dashboard": {
        "boot", "start", "stop", "die", "pause", "unpause", "destroy", "kill", "update", "refresh"
    }
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
    container_name = container.name

    # Metadata
    container_hostname = labels.get("dockernotifier.dns.containerhostname")
    zone_label = labels.get("dockernotifier.dns.containerzone")
    docker_domain = labels.get("dockernotifier.dns.dockerdomain")
    container_fqdn = f"{container_hostname}.{zone_label}" if container_hostname and zone_label else None
    stack_name = labels.get("com.docker.compose.project")
    if not stack_name and "_" in container.name:
        stack_name = container.name.split('_')[0]

    logger.info(f"[MATCH] Container {action.upper()}: {container_name}")

    if action in {"boot", "start"} and "dns" in notifier_list:
        if container_fqdn and docker_domain and zone_label:
            logger.info(f"DNS notifier triggered for {container_name} on {action}")
            technitium_dns.register(
                container_fqdn=container_fqdn,
                zone=zone_label,
                value=f"{docker_host}.{docker_domain}",
                container_name=container_name,
                docker_host=docker_host,
                stack_name=stack_name
            )
        else:
            logger.warning(f"Missing DNS label info for {container_name}, skipping DNS registration")

    if "service-tracker-dashboard" in notifier_list and action in NOTIFIER_TRIGGERS["service-tracker-dashboard"]:
        logger.info(f"STD notifier triggered for {container_name} on {action}")
        # Dynamically extract all dockernotifier.std.* labels
        std_labels = {
            key.replace("dockernotifier.std.", ""): value
            for key, value in labels.items()
            if key.startswith("dockernotifier.std.")
        }

        # Add base metadata (you can omit or include as needed)
        std_labels.update({
            "container_name": container_name,
            "docker_host": docker_host,
            "container_id": container.id,
            "docker_status": container.attrs["State"]["Status"],
            "image_name": container.attrs["Config"]["Image"],
            "stack_name": stack_name,
            "started_at": container.attrs["State"]["StartedAt"]
        })

        # Send to notifier
        service_tracker_dashboard.register(**std_labels)

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

    watched_actions = {"start", "stop", "die", "pause", "unpause", "destroy", "kill", "update"}
    for event in client.events(decode=True):
        action = event.get("Action")
        if action not in watched_actions:
            continue
        container_id = event.get("id")
        try:
            container = client.containers.get(container_id)
            handle_container_event(container, docker_host, action=action)
        except Exception as e:
            logger.error(f"Failed to handle {action} event for {container_id}: {e}")


if __name__ == "__main__":
    main()
