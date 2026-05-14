import os
import docker
from datetime import datetime
from notifiers import technitium_dns, service_tracker_dashboard
import threading
import time
from logging_setup import get_logger
import interpreter_loader

logger = get_logger("main")

# === Settings ===
logger.debug("main.py is running")
STD_REFRESH_SECONDS = int(os.environ.get("STD_REFRESH_SECONDS", "60"))  # Default to 60 seconds


def _parse_bool_env(name, default=False):
    raw = os.environ.get(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in ("true", "1", "yes"):
        return True
    if normalized in ("false", "0", "no", ""):
        return False
    logger.warning(
        f"Unrecognized boolean value for {name}={raw!r}; treating as off"
    )
    return False


# When True, the STD notifier fires for every running container on this
# host regardless of whether the container has the
# `dockernotifier.notifiers=service-tracker-dashboard` opt-in label.
# Scope is intentionally limited to STD — other notifiers (DNS) still
# require explicit per-container opt-in.
STD_REPORT_ALL_CONTAINERS = _parse_bool_env("STD_REPORT_ALL_CONTAINERS")
if STD_REPORT_ALL_CONTAINERS:
    logger.info(
        "STD_REPORT_ALL_CONTAINERS is on — every running container on this host "
        "will be reported to STD regardless of opt-in label"
    )

# Debug-only: re-load interpreters on every event instead of once at
# startup. Not for production use; intended for iterating on YAML
# files without bouncing the notifier.
INTERPRETER_RELOAD_ON_EACH_EVENT = _parse_bool_env("INTERPRETER_RELOAD_ON_EACH_EVENT")

# Loaded once at startup. See `interpreter_loader.py`.
INTERPRETER_LOAD_RESULT = interpreter_loader.load_interpreters()

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


def _extract_networks(container_attrs):
    network_settings = container_attrs.get("NetworkSettings") or {}
    networks_raw = network_settings.get("Networks") or {}
    return [
        {"name": name, "aliases": (data.get("Aliases") or []) if isinstance(data, dict) else []}
        for name, data in networks_raw.items()
    ]


def _extract_exposed_ports(container_attrs):
    config = container_attrs.get("Config") or {}
    exposed = config.get("ExposedPorts") or {}
    return list(exposed.keys())


def _extract_published_ports(container_attrs):
    network_settings = container_attrs.get("NetworkSettings") or {}
    ports_raw = network_settings.get("Ports") or {}
    out = []
    for port_key, bindings in ports_raw.items():
        if not bindings:
            continue
        try:
            container_port_str, protocol = port_key.split("/", 1)
            container_port = int(container_port_str)
        except (ValueError, AttributeError):
            logger.debug(f"Skipping malformed port key {port_key!r}")
            continue
        for binding in bindings:
            if not isinstance(binding, dict):
                continue
            host_port_raw = binding.get("HostPort")
            try:
                host_port = int(host_port_raw)
            except (TypeError, ValueError):
                logger.debug(
                    f"Skipping binding with non-integer HostPort={host_port_raw!r} for {port_key}"
                )
                continue
            out.append({
                "container_port": container_port,
                "protocol": protocol,
                "host_ip": binding.get("HostIp", "") or "",
                "host_port": host_port,
            })
    return out


def handle_container_event(container, docker_host, action):
    labels = container.attrs["Config"]["Labels"] or {}
    notifier_list_raw = labels.get("dockernotifier.notifiers", "").strip()
    notifier_list = [n.strip() for n in notifier_list_raw.split(",") if n.strip()]

    std_via_label = "service-tracker-dashboard" in notifier_list
    std_via_env = STD_REPORT_ALL_CONTAINERS
    std_should_fire = (
        (std_via_label or std_via_env)
        and action in NOTIFIER_TRIGGERS["service-tracker-dashboard"]
    )
    dns_should_fire = (
        "dns" in notifier_list and action in NOTIFIER_TRIGGERS["dns"]
    )

    if not std_should_fire and not dns_should_fire:
        return

    base_kwargs = {
        "container_name": container.name,
        "container_id": container.id,
        "docker_host": docker_host,
        "docker_status": container.attrs["State"]["Status"],
        "image_name": container.attrs["Config"]["Image"],
        "stack_name": labels.get("com.docker.compose.project"),
        "started_at": container.attrs["State"]["StartedAt"],
        "action": action,
        "networks": _extract_networks(container.attrs),
        "exposed_ports": _extract_exposed_ports(container.attrs),
        "published_ports": _extract_published_ports(container.attrs),
    }

    logger.info(f"[MATCH] Container {action.upper()}: {container.name}")

    if dns_should_fire:
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

    if std_should_fire:
        if std_via_env and not std_via_label:
            logger.debug(
                f"STD notifier firing for {container.name} via "
                f"STD_REPORT_ALL_CONTAINERS (no opt-in label)"
            )
        logger.info(f"STD notifier triggered for {container.name} on {action}")
        std_extras = {
            key.replace("dockernotifier.std.", ""): value
            for key, value in labels.items()
            if key.startswith("dockernotifier.std.")
        }
        std_extras["exposure_observations"] = _run_interpreters(labels)
        service_tracker_dashboard.register(**base_kwargs, **std_extras)


def _run_interpreters(labels):
    """
    Run all loaded interpreters against a container's labels.

    Returns:
      - a list of ExposureObservation dicts (possibly empty) if any
        interpreters were loaded successfully;
      - None if no interpreters are loaded — STD treats null as
        "no update; preserve existing exposure rows."
    """
    global INTERPRETER_LOAD_RESULT
    if INTERPRETER_RELOAD_ON_EACH_EVENT:
        INTERPRETER_LOAD_RESULT = interpreter_loader.load_interpreters()
    if not INTERPRETER_LOAD_RESULT.any_loaded:
        return None
    return interpreter_loader.evaluate(INTERPRETER_LOAD_RESULT.interpreters, labels)

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
