# docker-api-notifier — Product Requirements Document

> **Status:** living document. Update alongside any change that affects
> architecture, behavior, supported notifier targets, or the contract
> with downstream consumers.

## Revision History

| Version | Date       | Changes |
|---------|------------|---------|
| 0.1     | 2026-05-10 | Initial PRD. Documents current shipped behavior at v0.2.3 and the planned v0.3.0 cleanup. |
| 0.2     | 2026-05-13 | v0.3.1 — STD reporting opt-out mode via `STD_REPORT_ALL_CONTAINERS` env var. §1.3 softened to reflect per-host opt-out scope. |
| 0.3     | 2026-05-13 | v0.3.2 — capture container network membership and port information from the Docker API and forward to STD. §3.3 base kwargs contract grows three rows (`networks`, `exposed_ports`, `published_ports`). |

---

## Table of Contents

1. [Product Overview](#1-product-overview)
2. [Scope](#2-scope)
3. [Architecture](#3-architecture)
4. [Configuration Model](#4-configuration-model)
5. [Current State (v0.3.1)](#5-current-state-v031)
6. [v0.3.0 — Cleanup Release](#6-v030--cleanup-release)
7. [v0.3.1 — STD Reporting Opt-Out Mode](#7-v031--std-reporting-opt-out-mode)
8. [v0.3.2 — Network & Port Capture](#8-v032--network--port-capture)
9. [Versioning, Branches, and Releases](#9-versioning-branches-and-releases)
10. [Cross-Repo Coordination](#10-cross-repo-coordination)
11. [Open Questions](#11-open-questions)

---

## 1. Product Overview

`docker-api-notifier` runs as a sidecar on each Docker host. Its job is to
react to container lifecycle events on that host and notify external
systems so they stay in sync with reality without a human in the loop.

### 1.1 Original problem space

- DNS records for containers drifted whenever stacks moved between hosts.
- Service dashboards became stale and required manual upkeep.

### 1.2 Solution shape

- Read Docker events from the local socket.
- Read `dockernotifier.*` labels from each container to learn what each
  container wants.
- Fan out to one or more notifier modules (DNS, dashboard, future).

The notifier deliberately holds no state. Each event is processed
independently against current container metadata.

### 1.3 Design principles

- **Opt-in per container by default.** No labels means no notification —
  run safely alongside containers that don't know or care about this
  notifier. STD reporting can be flipped to opt-out on a per-host basis
  via the `STD_REPORT_ALL_CONTAINERS` env var (see §7); other notifier
  targets remain per-container opt-in regardless, because they create
  external side effects (DNS records, etc.) that should not fire for
  containers that didn't ask.
- **Independent notifier modules.** Each downstream system is its own
  module under `notifiers/` with its own auth, retry, and payload shape.
- **No state.** No database, no cache, no queue. Everything is derived
  from the live Docker socket plus environment variables.
- **One instance per host.** Multi-host coordination is out of scope.

---

## 2. Scope

### 2.1 In scope

- Watching Docker events on a single host per running instance.
- Periodic re-scans as a self-healing measure for missed events.
- Dispatching to pluggable notifier modules under `notifiers/`.
- Reading container metadata exclusively from labels (no shared config
  file describing services).

### 2.2 Out of scope

- Multi-host orchestration. One notifier instance per host.
- Storing or rendering service state (that's STD's job).
- Acting as an authoritative source for DNS or dashboard config; both
  are derived from container labels.
- Bidirectional sync. The notifier writes outward only.

---

## 3. Architecture

```
┌────────────────────────────────┐
│   Docker host                  │
│                                │
│  ┌──────────────┐              │
│  │ Containers   │              │
│  │ with labels  │              │
│  └──────┬───────┘              │
│         │                      │
│  ┌──────▼─────────┐            │
│  │ Docker socket  │            │
│  └──────┬─────────┘            │
│         │                      │
│  ┌──────▼─────────────────┐    │
│  │ docker-api-notifier    │    │
│  │   main.py event loop   │    │
│  │   ├─ boot scan         │    │
│  │   ├─ event subscription│    │
│  │   └─ periodic re-scan  │    │
│  │                        │    │
│  │   notifiers/           │    │
│  │   ├─ technitium_dns    │    │
│  │   └─ service_tracker_  │    │
│  │      dashboard         │    │
│  └────┬───────────┬───────┘    │
└───────│───────────│────────────┘
        ▼           ▼
   Technitium     STD instance
   DNS server     /api/v1/register
```

### 3.1 Module responsibilities

- **`main.py`** — Docker client setup, event subscription, label parsing,
  per-notifier dispatch, periodic re-scan thread.
- **`notifiers/<target>.py`** — one module per downstream system. Each
  exposes a `register(...)` function and owns its own retry policy,
  authentication, and payload shape.
- **Common concerns** that should live outside individual notifier
  modules: logging configuration, retry helpers, label-to-payload
  mapping. (Today these are partially duplicated; see §5.)

### 3.2 Event flow

1. Boot pass on startup — every running container is processed with
   `action="boot"`.
2. Docker event subscription — events whose `Action` is in
   `watched_actions` are processed live.
3. Periodic loop — every `STD_REFRESH_SECONDS` (default 60s), every
   running container is reprocessed with `action="refresh"`.

The periodic loop exists for resilience: if the notifier missed an
event (network blip, container crash mid-event), the next refresh pass
catches it.

### 3.3 Notifier Module Contract

Every notifier module under `notifiers/` follows the same shape so
that adding a new downstream target is a small, mechanical change.

#### File layout

- One module per downstream system: `notifiers/<target>.py`.
- The module exposes a single public function:
  `register(**kwargs) -> None`.
- The module owns its own auth handling, payload construction,
  and wire format. It does not own logging configuration or
  retry policy — both are shared.

#### Required imports

```python
from logging_setup import get_logger
from retry import with_retry

logger = get_logger("<target>_notifier")
```

The logger name should be `<target>_notifier` so log lines remain
filterable per-target.

#### The base kwargs contract

`main.py` invokes `register(**kwargs)` with the following keyword
arguments guaranteed present:

| Key | Type | Meaning |
|-----|------|---------|
| `container_name` | str | Container name (no leading `/`) |
| `container_id` | str | Full Docker container ID |
| `docker_host` | str | The host this notifier instance runs on |
| `docker_status` | str | Container state (e.g. "running", "exited") |
| `image_name` | str | Image reference from container config |
| `stack_name` | Optional[str] | `com.docker.compose.project` label or `None` |
| `started_at` | str | ISO timestamp from container state |
| `action` | str | The action that triggered this call (e.g. "start", "boot", "refresh") |
| `networks` | list[dict] | One entry per Docker network the container is on: `{"name": str, "aliases": [str, ...]}`. Empty list if the container is on no networks. Added in v0.3.2. |
| `exposed_ports` | list[str] | Container's `ExposedPorts` config as a list of `"<port>/<proto>"` strings (e.g. `"5173/tcp"`). Empty list if none. Added in v0.3.2. |
| `published_ports` | list[dict] | One entry per `(container_port, host_port)` mapping: `{"container_port": int, "protocol": str, "host_ip": str, "host_port": int}`. Empty list if no published ports. Added in v0.3.2. |

The last three (`networks`, `exposed_ports`, `published_ports`) live
in `base_kwargs` because they are inherent container facts read off
the Docker API, not per-target extras derived from labels. STD is
the only consumer today; other notifiers receive them via
`**kwargs` and may ignore them.

Modules may additionally receive notifier-specific extras (typically
from stripped label namespaces). A module reading any extra should
use `kwargs.get(...)` with a sensible default rather than relying
on presence.

#### Required behavior

A `register()` implementation must:

1. Read its own required env vars (e.g. `<TARGET>_URL`,
   `<TARGET>_API_TOKEN`). Return early with a single info log line
   if any are missing — do not raise.
2. Translate the kwargs into the downstream system's wire format.
   The translation lives inside the module, not in `main.py`.
3. Send the request, using `@with_retry` on the network call.
4. Catch `requests.RequestException` after retries; log and return.
   Do not let transient failures kill the event loop in `main.py`.
5. Not catch broader exceptions — programming errors should propagate
   to `main.py`'s outer try/except for visibility.

#### Wiring a new notifier into dispatch

In `main.py`:

1. Add the module's name to `NOTIFIER_TRIGGERS`, declaring which
   actions the notifier responds to (drawn from
   `WATCHED_DOCKER_ACTIONS` and `SYNTHETIC_ACTIONS`).
2. Add a dispatch branch in `handle_container_event` that calls the
   module's `register(**base_kwargs, **target_specific_extras)`.

In `README.md`:

3. Document the module's required env vars.
4. Document any `dockernotifier.<target>.*` labels operators set.

A reference implementation lives at `notifiers/_template.py`.

---

## 4. Configuration Model

All configuration is via environment variables. There is no config file.

Two reasons:

1. The notifier is meant to be one-line-deployable on every host. A
   shared config file would be one more thing to template and sync.
2. Per-container behavior comes from labels on those containers, which
   is the right place for it — the people writing the compose files
   know what they want.

Environment variables are documented in the `README.md`.

---

## 5. Current State (v0.3.1)

Tags shipped on `main`: v0.1.0 → v0.3.1. v0.3.0 (2026-05-12) resolved
every issue listed in §5.2 below. v0.3.1 followed as a small additive
release introducing the `STD_REPORT_ALL_CONTAINERS` env var for
per-host opt-out reporting to STD (see §7). The next release in
flight is v0.3.2 — network & port capture (see §8).

### 5.1 What works today

- Docker event subscription with a fixed action whitelist.
- Boot-time full scan.
- Periodic re-scan thread.
- DNS notifier with no retry, requests-based, fire-and-forget.
- STD notifier with `tenacity`-backed retry, bearer-token auth.
- Label-driven notifier opt-in via `dockernotifier.notifiers`.
- Per-notifier label namespaces (`dockernotifier.dns.*`,
  `dockernotifier.std.*`).

### 5.2 Known issues at v0.2.3 (targeted for v0.3.0)

| ID  | Area                  | Issue                                                                                                  |
|-----|-----------------------|--------------------------------------------------------------------------------------------------------|
| N1  | DNS notifier          | **Resolved in v0.3.0.** No retry on transient failure. STD notifier uses `tenacity`; DNS doesn't. Asymmetric. Fixed by extracting a shared `with_retry` decorator (`retry.py`) consumed by both notifiers. DNS also now calls `raise_for_status()` so HTTP 4xx/5xx trigger retries instead of being silently logged as successes. |
| N2  | DNS notifier          | **Resolved in v0.3.0.** `trigger_reason` parameter accepted but never used. Removed from the `register()` signature; the trigger log line now reads `action` from the common kwargs contract instead, so it reports the real Docker action (`start`, `boot`, `refresh`) rather than the literal default `"event"`. |
| N3  | Logging               | **Resolved in v0.3.0.** Log handler setup duplicated across `main.py`, `notifiers/technitium_dns.py`, and `notifiers/service_tracker_dashboard.py`. |
| N4  | Event handling        | **Resolved in v0.3.0.** `"refresh"` is in `NOTIFIER_TRIGGERS["service-tracker-dashboard"]` but not in `watched_actions`, so it never fires from the event stream. The periodic loop is the only path that uses it. |
| N5  | Stack-name fallback   | **Resolved in v0.3.0.** When `com.docker.compose.project` is missing, falls back to splitting `container.name` on `_`. Fragile and wrong for any container whose name contains an underscore for unrelated reasons. Fixed by removing the fallback entirely: `stack_name` is now `None` when the label is absent, and each notifier handles that case explicitly. |
| N6  | Comments              | **Resolved in v0.3.0.** `STD_REFRESH_SECONDS` default comment in `main.py` says "60 minutes" but the value is 60 seconds.      |
| N7  | Wire contract         | **Resolved in v0.3.0.** STD notifier now translates its working kwargs dict into STD v0.5.0's canonical schema (`host`, `group_name`, `image_icon`, `internal_health_check_enabled`, `external_health_check_enabled`, `sort_priority`, ...) and posts to `/api/v1/register`. Bool and int coercion happens at the notifier boundary; unknown keys are dropped client-side so STD's strict pydantic validator does not reject the request. |

### 5.3 Minor housekeeping (not blocking v0.3.0 but worth doing)

- No CI lint job. Consider adding `ruff` to mirror downstream practices.
- `requirements.txt` is unpinned. Pinning would protect reproducibility.

---

## 6. v0.3.0 — Cleanup Release

**Required STD v0.5.0 to ship first**, because v0.3.0 emits canonical
key names against `/api/v1/register`. STD v0.5.0 introduced that
endpoint.

### 6.1 Goals

- Resolved every issue in §5.2.
- Established a small set of internal modules that future notifier targets
  can rely on (logging, retry helper).
- Switched STD notifier to canonical key names + `/api/v1/register`.

### 6.2 Behavior changes visible to operators

None for end users. Container labels and environment variables continue
to work exactly as before. The wire payload to STD changes, but STD's
v0.5.0 compat shim accepts both old and new shapes during the overlap
window.

### 6.3 Internal changes

- Single shared logging setup module; notifier modules and `main.py`
  consume it instead of re-declaring handlers.
- Shared retry helper used by both DNS and STD notifiers; symmetric
  retry policy.
- Stack-name resolution falls back to `None` rather than splitting on
  `_`. Downstream notifiers handle the missing-stack case explicitly.
- `"refresh"` removed from `NOTIFIER_TRIGGERS` (it's not an action;
  the periodic loop calls `handle_container_event(... action="refresh")`
  directly and the dispatch logic is rewritten to not consult the
  trigger map for synthetic actions).
- DNS notifier signature drops `trigger_reason`.
- Comment fix on `STD_REFRESH_SECONDS`.

### 6.4 Out of scope for v0.3.0

- New notifier targets (Slack, ntfy, etc.). The cleanup makes adding
  these easier later, but none ship in v0.3.0.
- Multi-host coordination.
- A config file. Env vars + labels remain the only inputs.
- Test suite. Worth doing eventually (see §11), not in v0.3.0.

---

## 7. v0.3.1 — STD Reporting Opt-Out Mode

A small, additive release that introduces a single env var,
`STD_REPORT_ALL_CONTAINERS`, which flips STD reporting from
per-container opt-in to per-host opt-out.

### 7.1 Goals

- Let operators who want a complete inventory of a host's running
  containers in STD avoid labelling every container individually.
- Preserve today's behavior as the default: unset env var → unchanged.

### 7.2 Scope

- **STD only.** The env var affects only the STD notifier dispatch.
  The DNS notifier (and any future notifier that creates external
  side effects) continues to require explicit per-container opt-in
  via `dockernotifier.notifiers=...`.
- **Per-host, not per-container.** The env var is read once at
  startup on each notifier instance. There is intentionally no
  per-container override label — that would defeat the purpose.
- **Running containers only.** Behavior matches existing dispatch:
  the boot pass and periodic refresh loop iterate
  `client.containers.list()`. Stopped containers are not retroactively
  reported.

### 7.3 Semantics

- `STD_REPORT_ALL_CONTAINERS` truthy values: `true`, `1`, `yes`
  (case-insensitive). Anything else (including unrecognized strings
  like `maybe`) is treated as off; unrecognized values log a single
  warning at startup.
- When on, every running container on the host is reported to STD
  on boot, on watched Docker events, and on each periodic refresh
  tick — regardless of whether the container's
  `dockernotifier.notifiers` label includes `service-tracker-dashboard`
  (or even exists at all).
- `dockernotifier.std.*` labels on individual containers are still
  honored. Containers without those labels are reported with the
  minimum information available; STD's wire contract makes most
  fields optional and applies its own defaults.
- A container with `dockernotifier.notifiers=dns` only (no STD opt-in)
  AND the env var set: STD fires (env-var path) **and** DNS fires
  (label path). The env var adds STD; it does not subtract anything.

### 7.4 Wire contract

Unchanged. STD receives identical `/api/v1/register` payloads
regardless of whether the trigger came from a label or from the env
var. STD has no way to distinguish the two paths and does not need to.

### 7.5 Design principle reconciliation

§1.3's "opt-in per container" principle is softened, not abandoned.
With the env var unset (default), per-container opt-in remains the
only path. The env var is an explicit, deliberate per-host stance
taken by the operator running the notifier instance — it does not
change what other operators experience.

### 7.6 Out of scope for v0.3.1

- Per-container opt-out (a label like `dockernotifier.std.skip=true`
  to suppress reporting even when the env var is set). Defer until
  there is a concrete request.
- Changing DNS opt-in semantics.
- Reporting non-running containers.
- Network/port capture (planned for v0.3.2).

---

## 8. v0.3.2 — Network & Port Capture

An additive release that forwards container network membership and
port information from the Docker API to STD. STD v0.6.0 consumes
these fields; STD v0.5.x will reject the payload (strict pydantic
validation), so STD v0.6.0 must be deployed first.

### 8.1 Goals

- Capture inherent container facts the notifier already has access to
  via the Docker API: which networks the container is on, what ports
  it exposes, and what ports it publishes to the host.
- Forward all three to STD as canonical fields so STD's UI can render
  badges/links without re-reading the Docker socket itself.
- Stay pure-capture. No interpretation, no derived semantics. STD
  v0.7.0 will layer interpretation on top.

### 8.2 Captured fields

Added to the base kwargs contract (see §3.3 table):

- `networks` — list of `{"name": str, "aliases": [str, ...]}`. One
  entry per Docker network the container is on. Read from
  `container.attrs["NetworkSettings"]["Networks"]`. Aliases is an
  empty list (not null) when a network has no aliases.
- `exposed_ports` — list of `"<port>/<proto>"` strings. Read from
  `container.attrs["Config"]["ExposedPorts"]`. Just the keys.
- `published_ports` — list of `{"container_port": int, "protocol":
  str, "host_ip": str, "host_port": int}`. One entry per
  `(container_port, host_port)` binding. Read from
  `container.attrs["NetworkSettings"]["Ports"]`. Entries with a null
  binding list (exposed-but-not-published) are skipped.

### 8.3 Coercion at the boundary

- `host_port` arrives from Docker as a string (`"5173"`); coerced to
  `int`.
- `container_port` is parsed from the `"<port>/<proto>"` key and
  cast to `int`.
- `protocol` is the string after the slash (typically `"tcp"` or
  `"udp"`), kept as-is.

### 8.4 Empty vs. missing

Empty values are emitted as explicit empty lists, not null. This
lets STD's UI distinguish "we know there's nothing" from "the
notifier hasn't reported yet" (where the field is absent / null).

- Container on no networks (`network_mode: none`): `networks: []`.
- Container with no exposed ports: `exposed_ports: []`.
- Container with no published ports: `published_ports: []`.

### 8.5 Wire contract

Three new fields on the canonical payload to `/api/v1/register`.
The STD notifier's `_PASSTHROUGH` set covers them; no translation
needed because they are already in canonical shape.

### 8.6 Scope of consumption

Only the STD notifier consumes these fields today. The DNS notifier
receives them through `**kwargs` and ignores them. Storing them in
`base_kwargs` rather than as STD-specific extras keeps them
available for any future notifier (e.g. a Traefik-config emitter)
without rerunning the Docker API call.

### 8.7 Out of scope for v0.3.2

- Network IPs, gateways, MAC addresses, or any per-network detail
  beyond name and aliases.
- Any interpretation of network names (e.g. "container on `proxy`
  network → mark as Traefik-exposed"). That is v0.4.0 interpreter
  work.
- Per-host configuration of which networks to report. All networks
  the container is on get reported.
- Filtering or redaction. If a future operator wants it, that's a
  separate feature.
- Sending this data to anywhere besides STD.

### 8.8 Dependencies

- Hard: STD v0.6.0 must be deployed first. v0.5.x rejects unknown
  keys.
- Soft: notifier v0.3.1 on `main` (clean version sequencing only —
  v0.3.2 does not depend on v0.3.1's behavior).

---

## 9. Versioning, Branches, and Releases

- `main` is the default branch and the source of truth for releases.
- All work happens on `dev`. PR `dev` → `main` when ready to release.
- Branch protection: require PR + green build check, block force-push,
  block deletion.
- Image tags follow `.github/workflows/docker-publish.yml`:
  - push to `dev` → `:dev` and `:sha-<short>`
  - push to `main` → `:latest` and `:sha-<short>`
  - GitHub Release published → `:latest`, `:<semver>`, `:<major>`
- Tags are cut from the GitHub Releases UI against `main`.

---

## 10. Cross-Repo Coordination

This project is paired with
[service-tracker-dashboard](https://github.com/crzykidd/service-tracker-dashboard).

### 10.1 Contract ownership

STD owns the wire contract for the register endpoint. The notifier is
a producer — it sends what STD documents. Wire-format changes start in
STD; the notifier follows.

### 10.2 Release ordering for the v0.5.0 / v0.3.0 cycle

1. STD v0.5.0 ships with `/api/v1/register` (canonical keys) and the
   compat shim on `/api/register` (legacy keys, deprecated).
2. Notifier v0.3.0 ships with canonical keys against
   `/api/v1/register`.
3. STD v0.6.0 (later) removes `/api/register` and the compat shim.

Operators must upgrade the notifier to v0.3.0+ before STD v0.6.0.

### 10.3 Release ordering for the v0.6.0 / v0.3.2 cycle

1. STD v0.6.0 ships with `networks`, `exposed_ports`, and
   `published_ports` accepted on `/api/v1/register`.
2. Notifier v0.3.2 ships emitting those three fields.

If notifier v0.3.2 is deployed against STD v0.5.x, STD's strict
pydantic validator rejects the payload (unknown keys). Operators
must upgrade STD before the notifier.

---

## 11. Open Questions

- **Test coverage.** No tests exist today. Worth investing in a small
  suite that fakes the Docker client and asserts dispatch behavior?
- **Health check of notifier itself.** Currently the only liveness
  signal is "the container is running." A `/health` endpoint or
  heartbeat to STD might be valuable.
- **Backoff state across restarts.** Retry state is in-process. If the
  notifier crashes mid-burst it loses its retry queue. Probably
  acceptable for a homelab; flag for review if scale grows.
- **New notifier targets.** Likely candidates if needed: Slack, Discord,
  ntfy, generic webhook. Each one is ~1 module under `notifiers/` plus
  env vars.
