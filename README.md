# 🚀 Docker API Notifier

![Docker Image](https://img.shields.io/badge/docker-ready-blue?logo=docker)
![Python](https://img.shields.io/badge/python-3.11-blue?logo=python)
![License](https://img.shields.io/badge/license-GPL--3.0-blue)

> [!IMPORTANT]
> **Images are published to GitHub Container Registry:
> `ghcr.io/crzykidd/docker-api-notifier`.** Docker Hub
> (`crzykidd/docker-api-notifier`) is no longer updated — v0.4.2 was its
> final release. If you still pull from Docker Hub, change your compose
> `image:` line to `ghcr.io/crzykidd/docker-api-notifier:latest`. Env
> vars, labels, and volumes are the same.

A lightweight, event-driven Docker monitor that listens to the Docker socket
on a host and fans out container events to multiple downstream notifiers.

It was built to solve two specific problems in a homelab:

- Keep a Technitium DNS server's records in sync with what's actually
  running on each Docker host.
- Push container metadata (URLs, health-check flags, grouping, icons) to a
  self-hosted dashboard ([Service Tracker Dashboard](https://github.com/crzykidd/service-tracker-dashboard))
  so the dashboard config is driven by `docker-compose` labels rather than
  hand-edited.

Each container opts in to notifiers via labels, so you can run this on
every Docker host without it touching things you didn't ask it to touch.

---

## Table of Contents

1. [What It Does](#what-it-does)
2. [Environment Variables](#environment-variables)
3. [Container Labels](#container-labels)
4. [Interpreters](#interpreters)
5. [Docker Compose Example](#docker-compose-example)
6. [Running behind a docker-socket-proxy](#running-behind-a-docker-socket-proxy)
7. [Health endpoint](#health-endpoint)
8. [How It Works](#how-it-works)
9. [Building Locally](#building-locally)

---

## What It Does

`docker-api-notifier` connects to the Docker socket on its host and:

1. Scans every running container at startup ("boot" pass).
2. Subscribes to the Docker event stream for ongoing changes (`start`,
   `stop`, `die`, `pause`, `unpause`, `destroy`, `kill`, `update`).
3. Re-scans every running container on a periodic interval as a
   self-healing measure (default every 60 seconds). This loop only runs
   when STD is configured — it exists to re-report containers to STD,
   and does nothing for DNS-only deployments.

For each event, it reads the container's labels and dispatches to whichever
notifiers the container has opted in to via `dockernotifier.notifiers`.

Supported notifiers today:

- **Technitium DNS** — adds/updates a CNAME record on container start.
  If the record already points at the same target with the same TTL
  (checked via `records/get`, derived from `DNS_SERVER_URL`), it is left
  alone so the zone's SOA serial doesn't bump.
- **Service Tracker Dashboard (STD)** — POSTs container metadata to
  STD's register endpoint.

The notifier is a generic event fan-out. STD is one consumer; new
notifier targets can be added without touching the core event loop.

---

## Environment Variables

### General

| Variable                  | Required | Default | Description |
|---------------------------|----------|---------|-------------|
| `TZ`                      | No       | `UTC`   | Timezone for log timestamps. |
| `STD_REFRESH_SECONDS`     | No       | `60`    | Periodic re-scan interval in **seconds**. |
| `NOTIFIER_LOG_TO_STDOUT`  | No       | `1`     | Set to `0` to silence console output. Logs still go to `/config/notifier.log`. Replaces the per-notifier `DNS_LOG_TO_STDOUT` and `STD_LOG_TO_STDOUT` vars, which are no longer recognized. |
| `HEALTH_PORT`             | No       | `8080`  | Port for the [`/healthz` health endpoint](#health-endpoint). Set to `0` to disable it (the image's `HEALTHCHECK` then always passes). A non-numeric value falls back to `8080`. |
| `HEALTH_ALLOWED_IPS`      | No       | *(unset)* | Comma- and/or whitespace-separated IPs or CIDRs (e.g. `10.100.18.10, 10.100.20.0/24, fd00::/8`) allowed to read `/healthz`; everyone else gets `403`. Unset or empty = open to any client. Loopback is always allowed. See [Health endpoint](#health-endpoint). |
| `HOST_NAME_OVERRIDE`      | No       | *host hostname* | Overrides the host name used as the DNS CNAME target (`<host>.<dockerdomain>`). If unset, the notifier reads the host's hostname from the `/etc/hostname` mount (falling back to the container's own hostname). Set this if running in WSL or other environments where the host has a different name than your DNS entries expect. |

### Technitium DNS

| Variable                | Required | Description |
|-------------------------|----------|-------------|
| `DNS_SERVER_URL`        | Yes (for DNS) | Full URL to the Technitium add-record endpoint. |
| `DNS_SERVER_API_TOKEN`  | Yes (for DNS) | API token for the DNS server. |
| `DNS_SERVER_TYPE`       | No       | Optional descriptor (informational only). |

### Service Tracker Dashboard

> **Requires STD v0.5.0 or later.** Starting in notifier v0.3.0, the
> notifier posts to STD's `/api/v1/register` endpoint using STD's
> canonical schema. Earlier STD versions do not expose that endpoint
> and will return 404.
>
> **Notifier v0.4.0 requires STD v0.6.0 or later.** Starting in v0.4.0
> the notifier emits `networks`, `exposed_ports`, `published_ports`,
> and `exposure_observations` on every STD payload. STD v0.5.x's
> strict pydantic validator rejects unknown keys and will return 400
> for these payloads — upgrade STD first.
>
> **Notifier v0.5.0 sends the running image (`image_info`) to STD
> v0.12.0 or later** for its image update check. It is sent only when
> STD's `/api/v1/meta` advertises support, so older STD versions keep
> working unchanged (the notifier logs once that image info is not
> being sent). STD should be upgraded first.
>
> **Notifier v0.6.0 sends each network's `driver`, `ip_address`,
> `ipv6_address` and `mac_address` to STD v0.13.0 or later** (for its
> macvlan/ipvlan and host-network port handling). Like `image_info` it is
> sent only when STD's `/api/v1/meta` advertises `network_details`; older
> STD gets just `name` and `aliases`, as before.

| Variable                     | Required | Default | Description |
|------------------------------|----------|---------|-------------|
| `STD_URL`                    | Yes (for STD) | —       | Base URL of the STD instance, e.g. `http://std.example.com:8815`. |
| `STD_API_TOKEN`              | Yes (for STD) | —       | Bearer token configured on the STD side. |
| `STD_REPORT_ALL_CONTAINERS`  | No       | `false` | When truthy (`true`, `1`, `yes` — case-insensitive), report **every running container on this host** to STD regardless of whether it has the `dockernotifier.notifiers=service-tracker-dashboard` opt-in label. Default off preserves per-container opt-in behavior. **Only affects STD** — the DNS notifier still requires explicit per-container opt-in via labels. Unrecognized values log a warning at startup and are treated as off. |
| `STD_SEND_IMAGE_INFO`        | No       | `true`  | When truthy, send the running image's digests (`RepoDigests`, image id), creation time, and OCI labels (`org.opencontainers.image.version` / `.revision` / `.source`) to STD, so STD 0.12.0+ can tell whether a moving tag (`latest`, `stable`) has a newer image. Only sent when STD advertises support; set `false` to never send image details. **Only affects STD.** |
| `STD_SEND_NETWORK_DETAILS`   | No       | `true`  | When truthy, send each network's driver, IPv4, IPv6 and MAC address to STD 0.13.0+. Only sent when STD advertises support; set `false` to send just network names and aliases. **Only affects STD.** |
| `INTERPRETER_RELOAD_ON_EACH_EVENT` | No       | `false` | Debug-only. When truthy, re-reads YAML interpreters from disk on every dispatch instead of once at startup. Use while iterating on a new YAML; do not leave on in production. |

If a notifier's required env vars are missing, that notifier no-ops —
the container won't fail to start. This is intentional so you can run
the same image with only DNS, only STD, or both. When STD's env vars
(`STD_URL` / `STD_API_TOKEN`) are absent the notifier logs a single
line at startup noting STD is disabled, skips the periodic refresh
loop, and does not attempt STD dispatch on any event.

---

## Container Labels

You opt a container in to notification by adding labels to it.
None of these labels are required to run the notifier itself; they're
read off the containers being watched.

### Notifier selection

| Label                       | Description |
|-----------------------------|-------------|
| `dockernotifier.notifiers`  | Comma-separated list of notifiers to run for this container. Valid values: `dns`, `service-tracker-dashboard`. |

### DNS labels

All three are required for the DNS notifier to act on a container.

| Label                                   | Description |
|-----------------------------------------|-------------|
| `dockernotifier.dns.containerhostname`  | Hostname portion of the record (e.g. `sonarr`). |
| `dockernotifier.dns.containerzone`      | Zone/domain (e.g. `home.local`). |
| `dockernotifier.dns.dockerdomain`       | Docker host domain (e.g. `docker`). The CNAME will point at `<host>.<dockerdomain>`. |

### STD labels

All STD labels are optional. Anything you set gets forwarded to STD; STD
applies its own defaults for anything you don't.

| Label                                       | Description |
|---------------------------------------------|-------------|
| `dockernotifier.std.internalurl`            | Internal service URL. |
| `dockernotifier.std.externalurl`            | Public/external URL. |
| `dockernotifier.std.internal.health`        | `true`/`false` — enable internal health check. |
| `dockernotifier.std.external.health`        | `true`/`false` — enable external health check. |
| `dockernotifier.std.group`                  | Group label for dashboard organization. |
| `dockernotifier.std.icon`                   | Icon filename (e.g. `sonarr.svg`). |
| `dockernotifier.std.sort.priority`          | Numeric sort order within a group. |
| `dockernotifier.std.skip`                   | `true` — never report this container to STD, even with `STD_REPORT_ALL_CONTAINERS` on or `service-tracker-dashboard` in `dockernotifier.notifiers`. DNS is unaffected. It only stops reporting: it does **not** remove an entry STD already has (delete it in STD). |

**Reserved keys.** A `dockernotifier.std.<key>` label whose key is something
the notifier sends itself (`container_name`, `container_id`, `docker_host`,
`docker_status`, `image_name`, `stack_name`, `started_at`, `action`,
`networks`, `exposed_ports`, `published_ports`, `host`, `image_info`,
`exposure_observations`, `timestamp`) is ignored with a warning. To set the
host name use `HOST_NAME_OVERRIDE`, not `dockernotifier.std.host`.

**Boolean labels** (`internal.health`, `external.health`, `skip`) accept
`true`/`1`/`yes`/`on` and `false`/`0`/`no`/`off`, case-insensitive. Anything
else logs a warning and the key is left out of the payload, so STD keeps
what it has (it is not sent as `false`). On a brand-new container STD
creates a missing health toggle as disabled, so a typo there still ends up
off; on an existing entry it means "no change".

> **Note on label naming.** Container label keys (the
> `dockernotifier.std.*` keys you set on watched containers) are
> unchanged. Internally, notifier v0.3.0 translates them to STD's
> canonical wire-format keys (`group_name`, `image_icon`,
> `internal_health_check_enabled`, `sort_priority`, ...) before
> posting to STD's `/api/v1/register` endpoint. Boolean and integer
> coercion happens at the same boundary, so the values STD receives
> are actual `bool`/`int` rather than strings.

> **Network and port data.** As of notifier v0.4.0, every STD payload
> also carries `networks`, `exposed_ports`, and `published_ports`
> read straight from the Docker API. No new labels or env vars are
> required to enable this — it is automatic for every container
> reported to STD. Requires STD v0.6.0+. From v0.6.0 each network entry
> also carries its driver, IPv4/IPv6 and MAC address when STD 0.13.0+
> advertises `network_details` (see `STD_SEND_NETWORK_DETAILS`).

---

## Interpreters

> **New in v0.4.0. Requires STD v0.6.0 or later.** STD v0.5.x's strict
> validator will reject payloads carrying `exposure_observations`.

Interpreters are small YAML files that teach the notifier how to read
labels written by third-party tools (Traefik, Dockflare, Caddy, ...)
and forward them to STD as structured **exposure observations**. The
goal is to stop operators from having to duplicate hostnames into
`dockernotifier.std.internalurl` when the same fact is already
encoded in their Traefik/Dockflare labels.

### What ships built in

Two interpreters live inside the container image at
`/app/interpreters/builtin/`:

- `traefik.yml` — reads `traefik.http.routers.<router>.rule`
  (hostname), `.tls`, and `.entrypoints`. Emits one observation per
  router on the container.
- `dockflare.yml` — fires when `dockflare.enable=true`; reads
  `dockflare.hostname` and optional Access policy labels. Emits a
  single observation with `tls: true` (Cloudflare Tunnel implies
  HTTPS).

Both fire automatically for any container reported to STD. There is
no opt-in label — if the labels are there, the interpreter reads
them.

### Adding your own

Mount a directory of YAML files into the container at
`/app/interpreters/user/`:

```yaml
volumes:
  - ./my-interpreters:/app/interpreters/user:ro
```

User files load alongside builtins. A user file whose `name:` matches
a builtin **overrides** the builtin — drop in a tweaked `traefik.yml`
without rebuilding the image.

### Format

Every interpreter has three sections: `match` (which containers
fire), `extract` (which labels to read), `emit` (what to send to
STD). See [`docs/PRD.md` §11](docs/PRD.md) for the full reference,
or `docs/community-interpreters/template.yml` for an annotated
skeleton.

### Community reference

`docs/community-interpreters/` collects contributed YAMLs for tools
the maintainer doesn't necessarily run. Examples there may or may
not match your environment — read before mounting. PRs welcome.

### Empty list vs. absent on the wire

The notifier sends `exposure_observations` as a list when any
interpreter is loaded, even if no interpreter matched (empty list
tells STD to clear existing exposure rows for the container). If no
interpreters are loaded at all, the field is omitted, which STD
treats as "no update" — existing exposure rows are preserved.

---

## Docker Compose Example

**For a real host, start from
[`docker-compose-example.yml`](docker-compose-example.yml).** It runs the
notifier behind a read-only
[docker-socket-proxy](#running-behind-a-docker-socket-proxy) on an internal
network, with a read-only filesystem, no Linux capabilities and
`no-new-privileges`, and publishes `/healthz` on `HEALTH_HOST_PORT`
(default `8080`) so STD can monitor it. Secrets go in a `.env` file beside
it; the file's header lists them. Because the container has no
capabilities, the `/config` directory on the host must be owned by root
(Docker creates it that way; `sudo chown root:root` an existing one).

The minimal version below mounts the Docker socket directly. It's fine for
trying the notifier out, but prefer the example file for anything that
stays running. (`docker-compose.yml` in the repo is the development setup:
it builds from source.)

```yaml
services:
  docker-api-notifier:
    image: ghcr.io/crzykidd/docker-api-notifier:latest
    container_name: docker-api-notifier
    environment:
      - DNS_SERVER_TYPE=Technitium
      - DNS_SERVER_URL=http://dns.example.com:5380/api/zones/records/add
      - DNS_SERVER_API_TOKEN=TOKENFROMDNSSERVER
      - STD_URL=http://std.example.com:8815
      - STD_API_TOKEN=TOKENFROMSTDSERVER
      - TZ=America/Los_Angeles
      - STD_REFRESH_SECONDS=60
      # Override the host name used as the DNS CNAME target (<host>.<dockerdomain>).
      # If unset, the notifier uses the host's hostname (read from the
      # /etc/hostname mount below). Set this if running in WSL or other
      # environments where the host has a different name than your DNS
      # entries expect.
#      - HOST_NAME_OVERRIDE=wsl-host 
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - /etc/hostname:/etc/host_hostname:ro
      - /var/docker/docker-api-notifier:/config
      # Optional — drop your own interpreter YAMLs in here.
      # - /etc/docker-api-notifier/interpreters:/app/interpreters/user:ro
    # Optional: reach /healthz from the host. Not published by default.
    # ports:
    #   - "8080:8080"
    restart: unless-stopped
```

Volumes:

- `/var/run/docker.sock` — required, this is how the notifier reads
  events.
- `/etc/hostname` mounted as `/etc/host_hostname` — used so the
  notifier reports the **host's** hostname, not the container's, when
  posting to downstream notifiers.
- `/config` — log file lives here (`notifier.log`, rotated at 10 MB).
- `/app/interpreters/user` — optional. Mount a directory of operator
  YAMLs here to extend or override the built-in interpreters
  (Traefik, Dockflare). See [Interpreters](#interpreters) above.

---

## Running behind a docker-socket-proxy

You can keep `/var/run/docker.sock` away from the notifier by putting a
socket proxy such as `tecnativa/docker-socket-proxy` in front of it. The
notifier only ever reads, so the proxy can stay read-only (`POST=0`).

| Proxy setting | Needed for | If it is `0` |
|---|---|---|
| `CONTAINERS=1` | Listing and inspecting containers | The notifier cannot work |
| `EVENTS=1` | The container event stream | The notifier cannot work |
| `NETWORKS=1` | Each network's driver, sent to STD 0.13.0+ as network details | The proxy answers 403; networks still reach STD (name, aliases, addresses) but without `driver`, so STD cannot recognise macvlan, ipvlan or host networks |
| `IMAGES=1` | The running image's digests, sent to STD 0.12.0+ as `image_info` | The proxy answers 403; STD's image-digest update check gets no data |
| `PING=1`, `VERSION=1`, `INFO=1` | Harmless; used by the health check | |
| `POST=0` | Keep it. The notifier never writes. | |

When the proxy refuses the network or image lookup, the notifier logs one
warning naming the setting to change, stops retrying for 10 minutes (so a
fix takes effect without a restart), and logs once at INFO when the lookup
works again. `/healthz` shows the current state under `docker_permissions`.

```yaml
services:
  docker-proxy:
    image: tecnativa/docker-socket-proxy:latest
    environment:
      - CONTAINERS=1
      - EVENTS=1
      - NETWORKS=1
      - IMAGES=1
      - PING=1
      - VERSION=1
      - INFO=1
      - POST=0
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
    restart: unless-stopped

  docker-api-notifier:
    image: ghcr.io/crzykidd/docker-api-notifier:latest
    container_name: docker-api-notifier
    depends_on:
      - docker-proxy
    environment:
      - DOCKER_HOST=tcp://docker-proxy:2375
      - STD_URL=http://std.example.com:8815
      - STD_API_TOKEN=TOKENFROMSTDSERVER
      - TZ=America/Los_Angeles
    volumes:
      # No docker.sock mount: only the proxy touches the socket.
      - /etc/hostname:/etc/host_hostname:ro
      - /var/docker/docker-api-notifier:/config
    restart: unless-stopped
```

---

## Health endpoint

The notifier serves `GET /healthz` (JSON) on `HEALTH_PORT` (default `8080`,
`0` disables it), and the image ships a Docker `HEALTHCHECK` that probes it.
The port is not published by default; add `ports: - "8080:8080"` to reach it
from the host.

`/healthz` has no login. To limit who can read it, set `HEALTH_ALLOWED_IPS`
to a list of IPs and/or CIDR networks; any other client gets
`403 {"error": "forbidden"}` (for every path). Loopback (`127.0.0.0/8`,
`::1`) is always allowed, so the image `HEALTHCHECK` keeps working. Invalid
entries are logged as warnings and skipped; if every entry is invalid the
endpoint fails closed (loopback only) and an error is logged. Denied
requests are logged at DEBUG only.

The filter checks the TCP peer address and never trusts `X-Forwarded-For`
or other headers. It sees the address Docker delivers: with normally
published ports (iptables DNAT) remote clients keep their real source IP,
but a client connecting through the host's own loopback / docker-proxy may
appear as the bridge gateway (for example `172.18.0.1`) - add that address
if you probe from the host itself.

```json
{
  "status": "ok",
  "version": "0.5.0",
  "started_at": "2026-11-21T22:00:00Z",
  "uptime_seconds": 3600,
  "host": "dockerhost1",
  "docker": {"connected": true, "server_version": "29.9.3",
             "last_event_at": "2026-11-21T22:59:10Z", "events_seen": 123},
  "refresh_loop": {"enabled": true, "interval_seconds": 60,
                   "last_run_at": "2026-11-21T22:59:30Z"},
  "docker_permissions": {"networks": "ok", "images": "ok"},
  "interpreters": ["dockflare", "traefik"],
  "notifiers": {
    "dns": {"configured": true, "last_success_at": "2026-11-21T22:10:00Z",
            "last_error_at": null, "last_error": null,
            "success_count": 10, "error_count": 0},
    "service_tracker_dashboard": {
      "configured": true, "std_version": "0.12.0", "api_revision": 5,
      "image_info_supported": true,
      "features_supported": {"image_info": true, "network_details": true},
      "last_success_at": "2026-11-21T22:59:30Z",
      "last_error_at": null, "last_error": null,
      "success_count": 40, "error_count": 0}
  }
}
```

- **200 / `"ok"`**: the Docker daemon answers (checked at most every 15 s) and
  the event loop is running.
- **503 / `"unhealthy"`**: Docker is unreachable.
- A **STD or Technitium outage does not make the notifier unhealthy**. It
  shows in that notifier's `last_error*` / `error_count` fields while the
  endpoint stays 200, so an auto-restart setup won't restart-loop over
  someone else's outage.
- `refresh_loop.last_run_at` is `null` until the first refresh pass, which
  runs `interval_seconds` after startup (the boot scan covers the start).
  It does not affect `status`.
- `configured` reflects the env vars, not whether any container opted in.
  `last_error` is a short, credential-scrubbed string. `std_version`,
  `api_revision` and `image_info_supported` are `null` until the first STD
  `/api/v1/meta` check; `features_supported` holds one boolean per gated STD
  feature (`image_info`, `network_details`), each `null` until that check.
- `docker_permissions` reports the latest outcome of the notifier's two
  optional Docker lookups, `networks` and `images`: `"ok"`, `"denied"` (Docker
  answered 403, typically a socket proxy without `NETWORKS=1` / `IMAGES=1`;
  see [Running behind a docker-socket-proxy](#running-behind-a-docker-socket-proxy))
  or `"unknown"`. A kind stays `"unknown"` until its lookup has run at least
  once, e.g. STD isn't configured, STD doesn't advertise the feature, or you
  opted out with `STD_SEND_IMAGE_INFO=false` / `STD_SEND_NETWORK_DETAILS=false`.
  A denial is informational and never makes the notifier unhealthy.
- Any other path returns 404. If the port can't be bound, the notifier logs
  an error and keeps running without the endpoint.

---

## How It Works

```
                        ┌────────────────────┐
                        │  Docker socket     │
                        │  (events stream)   │
                        └─────────┬──────────┘
                                  │
                          ┌───────▼────────┐
                          │   main.py      │  ← reads events,
                          │   event loop   │    enriches with labels,
                          └───────┬────────┘    decides who to call
                                  │
              ┌───────────────────┼────────────────────┐
              │                                        │
     ┌────────▼─────────┐                  ┌───────────▼──────────┐
     │ technitium_dns   │                  │ service_tracker_     │
     │   .register()    │                  │ dashboard.register() │
     └──────────────────┘                  └──────────────────────┘
              │                                        │
              ▼                                        ▼
        Technitium API                         STD /api/v1/register
```

- Container events arrive from the Docker socket and are filtered against
  a whitelist of actions the notifier cares about.
- Per event, container labels are read; only containers with
  `dockernotifier.notifiers` set are processed.
- Each enabled notifier is a Python module under `notifiers/` exposing a
  `register(...)` function. Adding a new notifier target is a matter of
  dropping a new module and wiring it into the dispatch in `main.py`.
- Both notifiers share a single retry-with-backoff policy
  (`tenacity`, exposed via the `with_retry` decorator in `retry.py`) for
  transient network failures: 3 attempts, exponential backoff 2s/4s/8s
  capped at 10s, retrying connection errors, timeouts, and HTTP 5xx
  responses. A 4xx response is not retried (it raises immediately). The
  DNS notifier also calls `raise_for_status()` so HTTP errors from
  Technitium are not logged as successes. Every outbound request has a
  10-second timeout, so a hung DNS server or STD cannot stall the
  notifier.

---

## Building Locally

```bash
git clone https://github.com/crzykidd/docker-api-notifier.git
cd docker-api-notifier
docker build -t docker-api-notifier:dev .
```

Run pointed at your dev Docker socket and a scratch config dir.

---

## Versioning & Releases

Images are published to `ghcr.io/crzykidd/docker-api-notifier`. Docker Hub
(`crzykidd/docker-api-notifier`) received its final release at v0.4.2.

- `:latest` follows the `main` branch — CI-verified pre-release.
- `:dev` follows the `dev` branch — work in progress.
- `:sha-<short>` is published for every push for exact pinning.
- Semver-tagged images (`:0.7.1`, `:0`) are published from GitHub Releases.

The running version is logged at startup
(`Starting Docker API Notifier version X.Y.Z on host: ...`) and lives in
the repo's `VERSION` file.

Branch protection: PRs into `main` must pass CI (lint, config and
interpreter validation, compose validation, image build, CodeQL);
force-push and branch deletion are blocked. Work happens on `dev`, opens
a PR to `main`, and merges only when CI is green. Releases are tagged
`vX.Y.Z` from `main`; release notes are the matching `CHANGELOG.md`
section. Old `:sha-*` and semver images are pruned from GHCR (newest 30
and 15 kept); `:latest`, `:dev`, and `:X` are never pruned.

---

## License

GNU General Public License v3.0 — see [LICENSE](LICENSE).
