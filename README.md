# 🚀 Docker API Notifier

![Docker Image](https://img.shields.io/badge/docker-ready-blue?logo=docker)
![Python](https://img.shields.io/badge/python-3.11-blue?logo=python)
![License](https://img.shields.io/badge/license-MIT-green)

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
6. [How It Works](#how-it-works)
7. [Building Locally](#building-locally)

---

## What It Does

`docker-api-notifier` connects to the Docker socket on its host and:

1. Scans every running container at startup ("boot" pass).
2. Subscribes to the Docker event stream for ongoing changes (`start`,
   `stop`, `die`, `pause`, `unpause`, `destroy`, `kill`, `update`).
3. Re-scans every running container on a periodic interval as a
   self-healing measure (default every 60 seconds).

For each event, it reads the container's labels and dispatches to whichever
notifiers the container has opted in to via `dockernotifier.notifiers`.

Supported notifiers today:

- **Technitium DNS** — adds/updates a CNAME record on container start.
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
> strict pydantic validator rejects unknown keys and will return 422
> for these payloads — upgrade STD first.

| Variable                     | Required | Default | Description |
|------------------------------|----------|---------|-------------|
| `STD_URL`                    | Yes (for STD) | —       | Base URL of the STD instance, e.g. `http://std.example.com:8815`. |
| `STD_API_TOKEN`              | Yes (for STD) | —       | Bearer token configured on the STD side. |
| `STD_REPORT_ALL_CONTAINERS`  | No       | `false` | When truthy (`true`, `1`, `yes` — case-insensitive), report **every running container on this host** to STD regardless of whether it has the `dockernotifier.notifiers=service-tracker-dashboard` opt-in label. Default off preserves per-container opt-in behavior. **Only affects STD** — the DNS notifier still requires explicit per-container opt-in via labels. Unrecognized values log a warning at startup and are treated as off. |
| `INTERPRETER_RELOAD_ON_EACH_EVENT` | No       | `false` | Debug-only. When truthy, re-reads YAML interpreters from disk on every dispatch instead of once at startup. Use while iterating on a new YAML; do not leave on in production. |

If a notifier's required env vars are missing, that notifier silently
no-ops — the container won't fail to start. This is intentional so you
can run the same image with only DNS, only STD, or both.

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
> reported to STD. Requires STD v0.6.0+.

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

```yaml
services:
  docker-api-notifier:
    image: crzykidd/docker-api-notifier:latest
    container_name: docker-api-notifier
    environment:
      - DNS_SERVER_TYPE=Technitium
      - DNS_SERVER_URL=http://dns.example.com:5380/api/zones/records/add
      - DNS_SERVER_API_TOKEN=TOKENFROMDNSSERVER
      - STD_URL=http://std.example.com:8815
      - STD_API_TOKEN=TOKENFROMSTDSERVER
      - TZ=America/Los_Angeles
      - STD_REFRESH_SECONDS=60
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - /etc/hostname:/etc/host_hostname:ro
      - /var/docker/docker-api-notifier:/config
      # Optional — drop your own interpreter YAMLs in here.
      # - /etc/docker-api-notifier/interpreters:/app/interpreters/user:ro
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
  capped at 10s, retries on `requests.RequestException`. The DNS
  notifier also calls `raise_for_status()` so HTTP 4xx/5xx responses
  from Technitium trigger retries instead of being logged as
  successes.

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

- `:latest` follows the `main` branch — CI-verified pre-release.
- `:dev` follows the `dev` branch — work in progress.
- `:sha-<short>` is published for every push for exact pinning.
- Semver-tagged images (`:0.3.0`, `:0`) are published from GitHub Releases.

Branch protection: PRs into `main` must pass the build check; force-push
and branch deletion are blocked. Work happens on `dev`, opens a PR to
`main`, and merges only when CI is green. Release tags are cut from the
GitHub Releases UI on `main`.

---

## License

MIT — see [LICENSE](LICENSE).
