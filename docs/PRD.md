# docker-api-notifier — Product Requirements Document

> **Status:** living document. Update alongside any change that affects
> architecture, behavior, supported notifier targets, or the contract
> with downstream consumers.

## Revision History

| Version | Date       | Changes |
|---------|------------|---------|
| 0.1     | 2026-05-10 | Initial PRD. Documents current shipped behavior at v0.2.3 and the planned v0.3.0 cleanup. |

---

## Table of Contents

1. [Product Overview](#1-product-overview)
2. [Scope](#2-scope)
3. [Architecture](#3-architecture)
4. [Configuration Model](#4-configuration-model)
5. [Current State (v0.2.3)](#5-current-state-v023)
6. [v0.3.0 — Cleanup Release](#6-v030--cleanup-release)
7. [Versioning, Branches, and Releases](#7-versioning-branches-and-releases)
8. [Cross-Repo Coordination](#8-cross-repo-coordination)
9. [Open Questions](#9-open-questions)

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

- **Opt-in per container.** No labels means no notification. Run safely
  alongside containers that don't know or care about this notifier.
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

## 5. Current State (v0.2.3)

Tags shipped on `main`: v0.1.0 → v0.2.3.

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
| N2  | DNS notifier          | `trigger_reason` parameter accepted but never used.                                                    |
| N3  | Logging               | Log handler setup duplicated across `main.py`, `notifiers/technitium_dns.py`, and `notifiers/service_tracker_dashboard.py`. |
| N4  | Event handling        | `"refresh"` is in `NOTIFIER_TRIGGERS["service-tracker-dashboard"]` but not in `watched_actions`, so it never fires from the event stream. The periodic loop is the only path that uses it. |
| N5  | Stack-name fallback   | **Resolved in v0.3.0.** When `com.docker.compose.project` is missing, falls back to splitting `container.name` on `_`. Fragile and wrong for any container whose name contains an underscore for unrelated reasons. Fixed by removing the fallback entirely: `stack_name` is now `None` when the label is absent, and each notifier handles that case explicitly. |
| N6  | Comments              | `STD_REFRESH_SECONDS` default comment in `main.py` says "60 minutes" but the value is 60 seconds.      |
| N7  | Wire contract         | STD notifier currently sends a free-form kwargs dict. Needs to align with STD v0.5.0 canonical key names and target the new `/api/v1/register` endpoint. |

### 5.3 Minor housekeeping (not blocking v0.3.0 but worth doing)

- No CI lint job. Consider adding `ruff` to mirror downstream practices.
- `requirements.txt` is unpinned. Pinning would protect reproducibility.

---

## 6. v0.3.0 — Cleanup Release

**Cannot ship until STD v0.5.0 is released**, because v0.3.0 starts
emitting canonical key names against `/api/v1/register`. STD v0.5.0
introduces that endpoint.

### 6.1 Goals

- Resolve every issue in §5.2.
- Establish a small set of internal modules that future notifier targets
  can rely on (logging, retry helper).
- Switch STD notifier to canonical key names + `/api/v1/register`.

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
- Test suite. Worth doing eventually (see §9), not in v0.3.0.

---

## 7. Versioning, Branches, and Releases

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

## 8. Cross-Repo Coordination

This project is paired with
[service-tracker-dashboard](https://github.com/crzykidd/service-tracker-dashboard).

### 8.1 Contract ownership

STD owns the wire contract for the register endpoint. The notifier is
a producer — it sends what STD documents. Wire-format changes start in
STD; the notifier follows.

### 8.2 Release ordering for the v0.5.0 / v0.3.0 cycle

1. STD v0.5.0 ships with `/api/v1/register` (canonical keys) and the
   compat shim on `/api/register` (legacy keys, deprecated).
2. Notifier v0.3.0 ships with canonical keys against
   `/api/v1/register`.
3. STD v0.6.0 (later) removes `/api/register` and the compat shim.

Operators must upgrade the notifier to v0.3.0+ before STD v0.6.0.

---

## 9. Open Questions

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
