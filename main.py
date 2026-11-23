import os
import signal
import sys
import threading
import time

import docker

import health
import image_info
import interpreter_loader
import network_info
from logging_setup import get_logger
from notifiers import service_tracker_dashboard, technitium_dns
from notifiers.service_tracker_dashboard import parse_bool

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

# Whether the STD notifier has the env vars it needs. Checked once at
# startup so STD dispatch and the periodic refresh loop (which exists
# only to re-report containers to STD) can be skipped entirely when STD
# is not configured, instead of logging a "not enabled" line on every
# event. DNS-only deployments are the common case for this.
STD_CONFIGURED = service_tracker_dashboard.is_configured()
if not STD_CONFIGURED:
    logger.info(
        "STD_URL or STD_API_TOKEN is missing — disabling STD integration "
        "(no STD reporting, no periodic refresh loop)"
    )

# Opt-out for sending the running image's digests and OCI labels to STD
# (`image_info`). Even when on, it is only sent to an STD whose
# /api/v1/meta advertises support. Never reaches the DNS notifier.
STD_SEND_IMAGE_INFO = _parse_bool_env("STD_SEND_IMAGE_INFO", default=True)
if STD_CONFIGURED and not STD_SEND_IMAGE_INFO:
    logger.info("STD_SEND_IMAGE_INFO is off — not sending image info to STD")

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
        # Sleep first: the boot scan already reported every container.
        time.sleep(STD_REFRESH_SECONDS)
        logger.debug(f"STD refresh loop — every {STD_REFRESH_SECONDS} sec")
        for container in client.containers.list():
            try:
                handle_container_event(container, docker_host, action="refresh")
            except Exception as e:
                logger.error(f"Refresh failed for {container.name}: {e}")
        health.record_refresh()


def get_version():
    # VERSION (bare semver) sits next to main.py, both in the repo and at
    # /app/VERSION in the image. It is the release source of truth.
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "VERSION")
    try:
        with open(path) as f:
            return f.read().strip() or "unknown"
    except OSError:
        return "unknown"


def get_host_name():
    override = os.environ.get("HOST_NAME_OVERRIDE")
    if override and override.strip():
        return override.strip()
    try:
        with open("/etc/host_hostname", "r") as f:
            return f.read().strip()
    except Exception:
        return os.uname()[1]


def _extract_networks(container_attrs, client=None):
    """Networks list; pass a Docker `client` to include per-network details."""
    return network_info.collect(container_attrs, client)


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
        STD_CONFIGURED
        and (std_via_label or std_via_env)
        and action in NOTIFIER_TRIGGERS["service-tracker-dashboard"]
    )
    # `dockernotifier.std.skip=true`: never report this container to STD
    # (DNS is unaffected), even with STD_REPORT_ALL_CONTAINERS.
    if std_should_fire and _std_skip(container.name, labels):
        logger.debug(f"STD notifier skipping {container.name} (dockernotifier.std.skip)")
        std_should_fire = False
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
        # Per-network details (driver lookups) only when STD will use them.
        "networks": _extract_networks(
            container.attrs, container.client if std_should_fire else None
        ),
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
        std_extras = _std_label_extras(container.name, labels, base_kwargs)
        std_extras["exposure_observations"] = _run_interpreters(labels)
        if STD_SEND_IMAGE_INFO and service_tracker_dashboard.image_info_supported():
            info = image_info.lookup(container)
            if info:
                std_extras["image_info"] = info
        service_tracker_dashboard.register(**base_kwargs, **std_extras)


# Keys a `dockernotifier.std.<key>` label may not set, on top of the base
# kwargs: they would collide with what the notifier itself sends.
_RESERVED_STD_LABEL_KEYS = frozenset({
    "host", "image_info", "exposure_observations", "timestamp",
})
_STD_LABEL_PREFIX = "dockernotifier.std."


def _std_skip(container_name, labels):
    """True when `dockernotifier.std.skip` is set to a true value."""
    raw = labels.get(_STD_LABEL_PREFIX + "skip")
    if raw is None:
        return False
    parsed = parse_bool(raw)
    if parsed is None:
        logger.warning(
            f"Container '{container_name}': label '{_STD_LABEL_PREFIX}skip'='{raw}' "
            f"is not a boolean (use true/false); not skipping"
        )
        return False
    return parsed


def _std_label_extras(container_name, labels, base_kwargs):
    """The `dockernotifier.std.*` labels as kwargs for the STD notifier.

    Labels whose key collides with a base kwarg or another reserved key are
    dropped with a warning (a collision would raise TypeError in
    `register(**base_kwargs, **extras)` and the container would never
    register). `skip` is consumed by `_std_skip` and never forwarded.
    """
    reserved = set(base_kwargs) | _RESERVED_STD_LABEL_KEYS
    extras = {}
    for label, value in labels.items():
        if not label.startswith(_STD_LABEL_PREFIX):
            continue
        key = label[len(_STD_LABEL_PREFIX):]
        if key == "skip":
            continue
        if key in reserved:
            hint = " (set the host name with HOST_NAME_OVERRIDE)" if key == "host" else ""
            logger.warning(
                f"Container '{container_name}': ignoring label '{label}' — "
                f"'{key}' is set by the notifier{hint}"
            )
            continue
        extras[key] = value
    return extras


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

def _handle_sigterm(signum, frame):
    # As PID 1 in a container, Python gets no default SIGTERM action, so
    # `docker stop` would wait out the grace period and SIGKILL us.
    logger.info("SIGTERM received; shutting down")
    sys.exit(0)


def main():
    signal.signal(signal.SIGTERM, _handle_sigterm)
    client = docker.from_env()
    docker_host = get_host_name()
    version = get_version()
    logger.info(f"Starting Docker API Notifier version {version} on host: {docker_host}")

    # Start the /healthz endpoint first so it answers during a slow boot
    # scan. A separate Docker client keeps health pings off the event
    # stream's connection. Failure to start it never stops notifying.
    health.configure(
        version=version,
        host=docker_host,
        refresh_enabled=STD_CONFIGURED,
        refresh_interval=STD_REFRESH_SECONDS if STD_CONFIGURED else None,
        interpreters=[i.name for i in INTERPRETER_LOAD_RESULT.interpreters],
    )
    try:
        health.configure(docker_client=docker.from_env())
        health.start_from_env()
    except Exception as e:
        logger.error(f"Health endpoint setup failed: {e}; continuing without it")

    if STD_CONFIGURED:
        # Logs STD's version and API revision and caches what it supports.
        service_tracker_dashboard.check_meta_at_startup()

    logger.info("Running boot-time scan of existing containers...")
    for container in client.containers.list():
        try:
            handle_container_event(container, docker_host, action="boot")
        except Exception as e:
            logger.error(f"Failed to process container {container.name} on boot: {e}")

    # The periodic loop re-reports containers to STD; it does nothing for
    # DNS (which only triggers on boot/start). Skip it entirely when STD
    # is not configured.
    if STD_CONFIGURED:
        threading.Thread(target=periodic_update_loop, args=(docker_host,), daemon=True).start()
    else:
        logger.info("Periodic refresh loop not started — STD integration disabled")

    health.set_event_loop(True)
    try:
        for event in client.events(decode=True):
            if event.get("Type") != "container":
                continue
            action = event.get("Action")
            if action not in WATCHED_DOCKER_ACTIONS:
                continue
            container_id = event.get("Actor", {}).get("ID") or event.get("id")
            if not container_id:
                continue
            health.record_event()
            try:
                container = client.containers.get(container_id)
                handle_container_event(container, docker_host, action=action)
            except docker.errors.NotFound:
                pass
            except Exception as e:
                logger.error(f"Failed to handle {action} event for {container_id}: {e}")

    finally:
        health.set_event_loop(False)

if __name__ == "__main__":
    main()
