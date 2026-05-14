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
| 0.4     | 2026-05-14 | v0.4.0 — YAML interpreter mechanism, STD opt-out env var (`STD_REPORT_ALL_CONTAINERS`), network/ports capture, and design-principle softening. Originally planned as v0.3.1 / v0.3.2 / v0.4.0; consolidated into a single v0.4.0 release. §1.3 softens "no state" and "env vars only" to reflect YAML configuration. §3 architecture grows an interpreter component. §4 documents the interpreter loader paths and volume-mount convention. §11 fully documents the YAML format and wire emission. |

---

## Table of Contents

1. [Product Overview](#1-product-overview)
2. [Scope](#2-scope)
3. [Architecture](#3-architecture)
4. [Configuration Model](#4-configuration-model)
5. [Current State (v0.4.0)](#5-current-state-v040)
6. [v0.3.0 — Cleanup Release](#6-v030--cleanup-release)
7. [Delivered in v0.4.0](#7-delivered-in-v040)
8. [Versioning, Branches, and Releases](#8-versioning-branches-and-releases)
9. [Cross-Repo Coordination](#9-cross-repo-coordination)
10. [Open Questions](#10-open-questions)
11. [YAML Interpreter Format Reference](#11-yaml-interpreter-format-reference)

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

The notifier deliberately holds no per-event runtime state. Each
event is processed independently against current container metadata.
The only on-disk inputs are YAML interpreter files loaded once at
startup (see §1.3 and §11).

### 1.3 Design principles

- **Opt-in per container by default.** No labels means no notification —
  run safely alongside containers that don't know or care about this
  notifier. STD reporting can be flipped to opt-out on a per-host basis
  via the `STD_REPORT_ALL_CONTAINERS` env var (see §7.2); other notifier
  targets remain per-container opt-in regardless, because they create
  external side effects (DNS records, etc.) that should not fire for
  containers that didn't ask.
- **Independent notifier modules.** Each downstream system is its own
  module under `notifiers/` with its own auth, retry, and payload shape.
- **No runtime state.** No database, no cache, no queue. Per-event work
  is derived from the live Docker socket. As of v0.4.0 the notifier
  does load YAML interpreter files at startup (see §11) — this is
  configuration, not per-event memory, and it is read once into a
  module-level structure that does not change as events flow through.
  The "no per-event state" half of the principle still holds.
- **Configuration via env vars and labels, plus YAML for interpreters.**
  Through v0.3.x, env vars and container labels were the only inputs.
  v0.4.0 adds optional YAML interpreter files mounted into the
  container; they exist because expressing match/extract logic for
  third-party label schemes (Traefik, Dockflare, ...) as Python forks
  is heavier than necessary. See §4 for the loader layout and §11 for
  the full format.
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
│  │   interpreter_loader   │    │
│  │   ├─ builtin YAMLs     │    │
│  │   └─ user YAMLs (mount)│    │
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
- **`interpreter_loader.py`** — loads and evaluates the YAML
  interpreters introduced in v0.4.0. Runs once at startup to load
  YAMLs from `/app/interpreters/builtin/` and `/app/interpreters/user/`
  into a module-level structure; runs once per dispatch event to
  produce the list of `ExposureObservation` dicts forwarded to STD as
  `exposure_observations`. See §11 for the full design.

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
| `networks` | list[dict] | One entry per Docker network the container is on: `{"name": str, "aliases": [str, ...]}`. Empty list if the container is on no networks. Added in v0.4.0. |
| `exposed_ports` | list[str] | Container's `ExposedPorts` config as a list of `"<port>/<proto>"` strings (e.g. `"5173/tcp"`). Empty list if none. Added in v0.4.0. |
| `published_ports` | list[dict] | One entry per `(container_port, host_port)` mapping: `{"container_port": int, "protocol": str, "host_ip": str, "host_port": int}`. Empty list if no published ports. Added in v0.4.0. |

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

Most configuration is via environment variables and container labels.
Through v0.3.x there was no config file at all. As of v0.4.0 there is
one narrow exception: **YAML interpreter files** loaded from two
on-disk paths inside the container.

Two reasons env vars + labels remain the default:

1. The notifier is meant to be one-line-deployable on every host. A
   shared config file for general behavior would be one more thing to
   template and sync.
2. Per-container behavior comes from labels on those containers, which
   is the right place for it — the people writing the compose files
   know what they want.

Environment variables are documented in the `README.md`.

### 4.1 Interpreter YAML loader (v0.4.0+)

The notifier reads YAML files from two paths at startup:

- `/app/interpreters/builtin/` — baked into the container image. Ships
  `traefik.yml` and `dockflare.yml`.
- `/app/interpreters/user/` — empty by default; operators mount their
  own YAMLs here:

  ```yaml
  volumes:
    - ./my-interpreters:/app/interpreters/user:ro
  ```

A user file whose `name:` matches a builtin **overrides** the builtin
(useful for tweaking the shipped Traefik/Dockflare logic without
forking). Files that fail to parse or validate are logged at warning
level and skipped; the notifier continues with whatever loaded
successfully.

The set of loaded interpreters is read once at startup into a
module-level structure. No reload-on-change. The debug-only
`INTERPRETER_RELOAD_ON_EACH_EVENT` env var bypasses the cache and
reloads on every dispatch — useful when iterating on a YAML, not
intended for production.

See §11 for the YAML format and emission semantics.

---

## 5. Current State (v0.4.0)

Tags shipped on `main`: v0.1.0 → v0.4.0. v0.3.0 (2026-05-12) resolved
every issue listed in §5.2 below. v0.4.0 (2026-05-14) shipped the
work originally scoped across three separate releases
(v0.3.1 / v0.3.2 / v0.4.0); the consolidation is summarized in §7.

### 5.1 What works today

- Docker event subscription with a fixed action whitelist.
- Boot-time full scan.
- Periodic re-scan thread.
- DNS notifier with retry, requests-based, raises on HTTP 4xx/5xx.
- STD notifier with `tenacity`-backed retry, bearer-token auth.
- Label-driven notifier opt-in via `dockernotifier.notifiers`.
- Per-host STD opt-out via `STD_REPORT_ALL_CONTAINERS` (see §7.2).
- Network and port capture forwarded to STD on every payload (see §7.3).
- YAML-driven interpreter layer producing `exposure_observations` for
  STD (see §7.4 for the v0.4.0 summary, §11 for the format reference).
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
- Test suite. Worth doing eventually (see §10), not in v0.3.0.

---

## 7. Delivered in v0.4.0

Originally planned as three separate releases — v0.3.1
(STD opt-out env var), v0.3.2 (network & port capture), and v0.4.0
(YAML interpreter mechanism) — consolidated into a single v0.4.0
release. The full operator-facing changelog lives in `CHANGELOG.md`;
this section captures the design intent and scope decisions for each
piece so they remain part of the PRD record.

The whole bundle is **paired with STD v0.6.0**, which adds the
consumer side: it accepts `networks`, `exposed_ports`,
`published_ports`, and `exposure_observations` on `/api/v1/register`
and ships the synthesizer that turns observations into rendered
exposure rows. STD v0.5.x's strict pydantic validator rejects all
four keys, so operators must upgrade STD before the notifier.

### 7.1 Design principle reconciliation

This release deliberately softens principles previously stated in
§1.3:

- "No state." → "No runtime state." Configuration is now loaded from
  YAML at startup. Per-event state still does not exist.
- "All configuration is via environment variables." → no longer
  literally true. Env vars + labels remain the default, with a narrow
  exception for interpreter YAMLs.
- "Opt-in per container." → still the default, but STD reporting can
  be flipped to per-host opt-out via `STD_REPORT_ALL_CONTAINERS`. DNS
  and other side-effect notifiers remain per-container opt-in.

§1.3 has been updated to reflect all three softenings.

### 7.2 STD reporting opt-out mode (`STD_REPORT_ALL_CONTAINERS`)

A single env var flips STD reporting from per-container opt-in to
per-host opt-out.

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
- Truthy values: `true`, `1`, `yes` (case-insensitive). Anything
  else (including unrecognized strings like `maybe`) is treated as
  off; unrecognized values log a single warning at startup.
- When on, every running container on the host is reported to STD
  on boot, on watched Docker events, and on each periodic refresh
  tick — regardless of whether the container's
  `dockernotifier.notifiers` label includes
  `service-tracker-dashboard` (or even exists at all).
- `dockernotifier.std.*` labels on individual containers are still
  honored. Containers without those labels are reported with the
  minimum information available; STD's wire contract makes most
  fields optional and applies its own defaults.
- A container with `dockernotifier.notifiers=dns` only (no STD
  opt-in) AND the env var set: STD fires (env-var path) **and** DNS
  fires (label path). The env var adds STD; it does not subtract
  anything.
- Wire contract unchanged. STD receives identical
  `/api/v1/register` payloads regardless of whether the trigger came
  from a label or from the env var.

Out of scope: per-container opt-out (a label like
`dockernotifier.std.skip=true` to suppress reporting even when the
env var is set), changing DNS opt-in semantics, reporting
non-running containers.

### 7.3 Network & port capture

Container network membership and port information are read directly
from the Docker API and forwarded to STD as canonical fields, so
STD's UI can render badges/links without re-reading the Docker
socket itself. Pure capture — no interpretation, no derived
semantics.

Captured fields (added to the base kwargs contract; see §3.3 table):

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

Coercion at the boundary:

- `host_port` arrives from Docker as a string (`"5173"`); coerced
  to `int`.
- `container_port` is parsed from the `"<port>/<proto>"` key and
  cast to `int`.
- `protocol` is the string after the slash (typically `"tcp"` or
  `"udp"`), kept as-is.

Empty values are emitted as explicit empty lists, not null. This
lets STD's UI distinguish "we know there's nothing" from "the
notifier hasn't reported yet" (where the field is absent / null).
The STD notifier's `_PASSTHROUGH` set covers all three new fields;
no translation is needed because they are already in canonical
shape.

Only the STD notifier consumes these fields today. The DNS notifier
receives them through `**kwargs` and ignores them. Storing them in
`base_kwargs` rather than as STD-specific extras keeps them
available for any future notifier (e.g. a Traefik-config emitter)
without rerunning the Docker API call.

Out of scope: per-network detail beyond name and aliases (no IPs,
gateways, MAC addresses); per-host filtering of which networks to
report; sending the data anywhere besides STD.

### 7.4 YAML interpreter mechanism

A YAML-driven interpreter layer reads labels written by third-party
tools (Traefik, Dockflare, ...) and emits structured exposure
observations to STD as `exposure_observations`. Eliminates the need
for operators to duplicate hostnames into
`dockernotifier.std.internalurl` when the same fact is already
encoded in their Traefik/Dockflare labels.

Goals:

- Translate third-party label schemes into a uniform shape STD
  understands, without operators having to fork the notifier for
  each new tool.
- Ship sensible defaults for the two tools the maintainer actually
  runs (Traefik, Dockflare).
- Offer operators a path to add new interpreters without rebuilding
  the image: drop a YAML in a mounted directory.
- Maintain a community-reference directory in the repo for sharing
  contributed interpreters.

Loader (`interpreter_loader.py`):

- `load_interpreters()` returns a `LoadResult(interpreters, ...)`
  containing the compiled interpreters and a flag indicating whether
  any directories were even found.
- `evaluate(interpreters, labels)` runs every interpreter against a
  container's labels and returns the concatenated list of emitted
  observations.
- `/app/interpreters/builtin/` is read first. Then
  `/app/interpreters/user/` — user files with a `name:` matching a
  builtin override the builtin and the override is logged.
- Files that fail YAML parsing, validation, or regex compilation
  log a warning and are skipped. The loader does not raise; bad
  files do not block startup.
- Loaded interpreters are stored in a module-level dict keyed by
  name. Not re-read per event. The debug-only
  `INTERPRETER_RELOAD_ON_EACH_EVENT=true` env var re-reads both
  directories on every dispatch — useful when iterating on a YAML,
  not for production.

Wire emission: the STD notifier passes `exposure_observations`
through unchanged via `_PASSTHROUGH`. The value is one of:

- A **list** (possibly empty) — emitted when at least one
  interpreter is loaded. An empty list means "interpreters ran and
  nothing matched"; STD interprets this as "clear all exposure rows
  for this container."
- **`None`** — emitted when no interpreters are loaded (empty dirs
  or all failed validation). STD treats null as "no update;
  preserve existing exposure rows." This distinction matters when
  an operator disables interpreters at runtime — STD doesn't
  suddenly forget exposure data.

The STD notifier's `_to_canonical` filter drops `None` values from
outgoing payloads, so `None` becomes "field absent" on the wire.

Baked-in interpreters (`/app/interpreters/builtin/`):

- `traefik.yml` — regex-match flavor. Captures router names, reads
  the rule for `Host(...)`, reads `tls` and `entrypoints`. Emits
  one observation per router.
- `dockflare.yml` — fixed-key match (`dockflare.enable=true`).
  Reads `dockflare.hostname`, optional `dockflare.access.policy`
  and `dockflare.access.group`. Emits a single observation with
  `tls: true` (Cloudflare Tunnel implies HTTPS) and an `auth`
  string of the form `cloudflare_access:<policy>` (or `null` if no
  policy is set, thanks to the null-propagation rule).

Community-reference directory (`docs/community-interpreters/`):

- `README.md` — explains the directory, the format, and the
  explicit non-guarantee.
- `traefik.yml`, `dockflare.yml` — reference copies of the
  builtins. Operators starting a new interpreter from scratch read
  these to see the format in practice.
- `template.yml` — heavily annotated skeleton.

PRs that add new interpreters are welcome. The maintainer does not
QA every contribution — examples may or may not work for a given
operator's setup. Operators adapt and mount as needed.

The full YAML format reference (match flavors, extract semantics,
emit substitution rules, null propagation) lives in §11.

Out of scope: reloading interpreters at runtime without notifier
restart (`INTERPRETER_RELOAD_ON_EACH_EVENT` is a debugging
affordance, not a feature); per-container interpreter selection;
per-host curation of which YAMLs apply (mount different files on
different hosts is the answer); network-membership-based matching
inside the notifier (STD's synthesizer handles that on its side);
a web UI for managing interpreters; validating emit outputs against
STD's `ExposureObservation` schema beyond basic structure.

### 7.5 Dependencies

- Hard pairing: **STD v0.6.0** must be deployed before notifier
  v0.4.0 is rolled out. STD v0.5.x's strict pydantic validator
  rejects payloads carrying `networks`, `exposed_ports`,
  `published_ports`, or `exposure_observations`.

---

## 8. Versioning, Branches, and Releases

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

## 9. Cross-Repo Coordination

This project is paired with
[service-tracker-dashboard](https://github.com/crzykidd/service-tracker-dashboard).

### 9.1 Contract ownership

STD owns the wire contract for the register endpoint. The notifier is
a producer — it sends what STD documents. Wire-format changes start in
STD; the notifier follows.

### 9.2 Release ordering for the v0.5.0 / v0.3.0 cycle

1. STD v0.5.0 ships with `/api/v1/register` (canonical keys) and the
   compat shim on `/api/register` (legacy keys, deprecated).
2. Notifier v0.3.0 ships with canonical keys against
   `/api/v1/register`.
3. STD v0.6.0 (later) removes `/api/register` and the compat shim.

Operators must upgrade the notifier to v0.3.0+ before STD v0.6.0.

### 9.3 Release ordering for the v0.6.0 / v0.4.0 cycle

1. STD v0.6.0 ships with `networks`, `exposed_ports`,
   `published_ports`, and `exposure_observations` accepted on
   `/api/v1/register`, plus the synthesizer that turns observations
   into rendered exposure rows.
2. Notifier v0.4.0 ships emitting all four fields and loading the
   YAML interpreter layer that produces `exposure_observations`.

If notifier v0.4.0 is deployed against STD v0.5.x, STD's strict
pydantic validator rejects the payload (unknown keys). Operators
must upgrade STD before the notifier.

---

## 10. Open Questions

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

---

## 11. YAML Interpreter Format Reference

This is the format contract for YAML interpreter files loaded by
`interpreter_loader.py`. Community contributors and operators
writing their own interpreters should treat this section as
authoritative. See §7.4 for the surrounding release notes and
design intent.

### 11.1 File structure

One file per interpreter, one interpreter per file. Top-level keys:

```yaml
name: <identifier>          # required
description: <free text>    # optional
match:                      # required, exactly one flavor
  any_label_key_matches: '<regex with named captures>'
  # or
  label_key: '<exact key>'
  label_value_equals: '<value>'   # optional, case-insensitive
extract:                    # required (may be empty)
  <local_var>:
    from_label: '<key, may reference {captures}>'
    value_pattern: '<regex over the label value>'   # optional
    capture: '<named group from value_pattern>'      # optional
    coerce: bool | int                               # optional
    default: <value if missing or extraction fails>  # optional
emit:                       # required
  layer: <required string>
  <field>: '<literal or {local_var}>'
  details:
    <field>: '<literal or {local_var}>'
```

### 11.2 Match

- `any_label_key_matches` — regex applied to every label key on the
  container with `fullmatch`. Named captures `(?P<name>...)` become
  available in `extract` via `{name}` substitution. If multiple
  label keys match, the interpreter fires once per match — useful
  for tools that namespace per-router (Traefik).
- `label_key` + optional `label_value_equals` — fires once if the
  exact label key exists. With `label_value_equals`, the value is
  compared case-insensitively after stripping.

A single interpreter must pick exactly one flavor.

### 11.3 Extract

Each entry defines a local variable. The notifier:

1. Substitutes `{capture}` placeholders in `from_label` with values
   from the match step.
2. Looks up that label key on the container.
3. If a `value_pattern` is set, runs `re.search` over the value. If
   `capture` is set, the named group is used; otherwise the whole
   match is the result.
4. Applies `coerce` (`bool` or `int`). Boolean truthy strings are
   `true`, `1`, `yes` (case-insensitive). Failed int coercion falls
   back to `default`.
5. If anything in steps 2–4 fails (label missing, pattern doesn't
   match, capture missing), the variable takes its `default` (or
   `None` if no default was set).

### 11.4 Emit

Each key in `emit` becomes a field on the resulting observation.
String values may reference `{local_var}` placeholders from the
extract step.

Null propagation rules:

- A **bare** placeholder like `'{var}'` resolves to the variable's
  value verbatim — bools stay bools, ints stay ints, lists stay
  lists, `None` passes through as `None`.
- A **mixed** template like `'cloudflare_access:{policy}'` is built
  by string concatenation. If any referenced variable is `None`,
  the whole field resolves to `None` (rather than substituting the
  literal string `"None"`).

`emit.layer` is required and identifies the source tool on the wire.
All other emit fields are optional; STD treats missing fields as
"no information."
