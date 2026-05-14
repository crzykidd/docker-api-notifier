# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.4.0] — 2026-05-14

### Added
- **YAML interpreter mechanism (v0.4.0).** The notifier now reads small
  YAML files that teach it how to interpret labels written by
  third-party tools (Traefik, Dockflare, ...) and forward them to STD
  as structured exposure observations on a new
  `exposure_observations` field. Two interpreters ship baked into the
  image (`traefik.yml`, `dockflare.yml`) and fire automatically for
  any container reported to STD — no opt-in label required. Operators
  who want to extend or override the built-ins mount a directory of
  their own YAMLs at `/app/interpreters/user/`; a user file whose
  `name:` matches a builtin overrides the builtin. Bad YAMLs log a
  warning and are skipped; the notifier continues with whatever
  loaded successfully. A new `docs/community-interpreters/` directory
  holds contributed reference YAMLs (PRs welcome — they are examples,
  not curated products). Full format reference is in `docs/PRD.md`
  §11. **Requires STD v0.6.0 or later**; earlier STD versions reject
  the unknown `exposure_observations` key.
- Debug-only env var `INTERPRETER_RELOAD_ON_EACH_EVENT`. When truthy,
  re-reads the YAML interpreter directories on every dispatch instead
  of once at startup. For iterating on a YAML; not for production
  use.
- New env var `STD_REPORT_ALL_CONTAINERS`. When set to a truthy value
  (`true`, `1`, `yes` — case-insensitive), the notifier reports every
  running container on the host to STD, regardless of whether the
  container has the `dockernotifier.notifiers=service-tracker-dashboard`
  opt-in label. Default off — existing per-container opt-in behavior
  is unchanged for operators who don't set the variable. **Only STD
  dispatch is affected**: the DNS notifier still requires explicit
  per-container opt-in via labels, because DNS records are an external
  side effect that shouldn't fire for containers that didn't ask.
  Unrecognized values (e.g. `maybe`) log a warning at startup and are
  treated as off. The wire payload to STD is identical whether the
  trigger came from a label or from this env var.
- STD payloads now include `networks`, `exposed_ports`, and
  `published_ports` read directly from the Docker API. `networks` is a
  list of `{"name", "aliases"}` objects, one per Docker network the
  container is on. `exposed_ports` is a list of `"<port>/<proto>"`
  strings from the container's `ExposedPorts` config. `published_ports`
  is a list of `{"container_port", "protocol", "host_ip", "host_port"}`
  objects, one per port binding. Empty values are emitted as explicit
  empty lists so STD can distinguish "nothing to report" from "not yet
  reported". No new env vars or labels — capture is automatic for every
  container reported to STD. **Requires STD v0.6.0 or later**; STD
  v0.5.x's strict validator will reject payloads carrying these keys.

### Changed
- **Design principles softened (v0.4.0).** Previously, PRD §1.3 stated
  "no state" and "all configuration is via environment variables.
  There is no config file." Both are now narrower. The notifier still
  holds no per-event state and still has no central config file, but
  it now loads YAML interpreter files at startup. Operators upgrading
  from v0.3.x do not need to take any action — the YAML loader works
  out of the box with the two baked-in interpreters, and the
  filesystem footprint is fully contained inside the notifier
  container.

### Fixed
- Docker event loop no longer logs `Failed to handle <action> event for
  None: Resource ID was not provided` errors. The container ID is now
  read from `event["Actor"]["ID"]` (newer Docker daemons no longer
  populate the legacy top-level `id` field), non-container events
  (network/volume/service) are filtered out before lookup, and the
  expected `NotFound` raised when querying an already-removed container
  on a `destroy` event is swallowed silently.

---

## [0.3.0] — 2026-05-12

### Added
- Shared logging setup module consumed by `main.py` and all notifier
  modules. No more duplicated handler configuration across files.
- Shared retry helper. DNS notifier now retries with backoff using the
  same policy as the STD notifier.
- Common kwargs contract: every notifier module's `register()`
  receives a documented base set of kwargs (`container_name`,
  `container_id`, `docker_host`, `docker_status`, `image_name`,
  `stack_name`, `started_at`, `action`). Notifier-specific extras
  are layered on top.
- Boolean and integer coercion for STD health-check and sort-priority
  labels at the notifier boundary. `dockernotifier.std.internal.health`
  and `dockernotifier.std.external.health` label values are converted
  from string to bool, and `dockernotifier.std.sort.priority` is
  converted from string to int, before being sent to STD.
- PRD §3.3 documents the notifier module contract.
- `notifiers/_template.py` reference implementation for adding new
  notifier targets.

### Changed
- STD notifier emits canonical key names (`host`, `group_name`,
  `internal_health_check_enabled`, `image_icon`, `sort_priority`, ...)
  and posts to `/api/v1/register` instead of `/api/register`. The
  notifier translates legacy label-derived keys to canonical names
  client-side; unknown keys are dropped before sending so STD's
  strict pydantic validator does not reject the request.
- Stack-name resolution: when `com.docker.compose.project` is missing,
  the notifier passes `stack_name=None` rather than splitting the
  container name on `_`.
- Replaced per-notifier `DNS_LOG_TO_STDOUT` and `STD_LOG_TO_STDOUT`
  env vars with a single `NOTIFIER_LOG_TO_STDOUT`. Default unchanged
  (console on). Operators who previously set `DNS_LOG_TO_STDOUT=0` or
  `STD_LOG_TO_STDOUT=0` should switch to `NOTIFIER_LOG_TO_STDOUT=0`.
- DNS notifier now raises on HTTP 4xx/5xx responses from Technitium
  and retries transient failures. Previously HTTP errors were silently
  logged as successes.
- DNS notifier's "triggered for" log line now reports the actual Docker
  action (e.g. `start`, `boot`, `refresh`) instead of the literal string
  `"event"`. Operators with log filters or alerts that grep specifically
  for `due to "event"` will need to update them.

### Removed
- Unused `trigger_reason` parameter from the DNS notifier's `register()`
  signature.
- Inline `watched_actions` literal in `main()`; the Docker event loop
  now reads from the module-level `WATCHED_DOCKER_ACTIONS` constant.

### Fixed
- Real Docker actions and synthetic actions (`boot`, `refresh`) are now
  declared as separate constants in `main.py` (`WATCHED_DOCKER_ACTIONS`
  and `SYNTHETIC_ACTIONS`) and composed into `NOTIFIER_TRIGGERS`. No
  behavior change — clarifies what the notifier subscribes to from
  Docker vs. what it injects internally.
- Misleading comment on `STD_REFRESH_SECONDS` ("60 minutes" → "60
  seconds").

---

## [0.2.3] — 2026-XX-XX

Released. Detailed notes not retained.

## [0.2.2] — 2026-XX-XX
Released.

## [0.2.1] — 2026-XX-XX
Released.

## [0.2.0] — 2026-XX-XX
Released.

## [0.1.5] — 2026-XX-XX
Released.

## [0.1.4] — 2026-XX-XX
Released.

## [0.1.3] — 2026-XX-XX
Released.

## [0.1.2] — 2026-XX-XX
Released.

## [0.1.1] — 2026-XX-XX
Released.

## [0.1.0] — 2026-XX-XX

Initial public release.

[Unreleased]: https://github.com/crzykidd/docker-api-notifier/compare/v0.4.0...HEAD
[0.4.0]: https://github.com/crzykidd/docker-api-notifier/releases/tag/v0.4.0
[0.3.0]: https://github.com/crzykidd/docker-api-notifier/releases/tag/v0.3.0
[0.2.3]: https://github.com/crzykidd/docker-api-notifier/releases/tag/v0.2.3
[0.2.2]: https://github.com/crzykidd/docker-api-notifier/releases/tag/v0.2.2
[0.2.1]: https://github.com/crzykidd/docker-api-notifier/releases/tag/v0.2.1
[0.2.0]: https://github.com/crzykidd/docker-api-notifier/releases/tag/v0.2.0
[0.1.5]: https://github.com/crzykidd/docker-api-notifier/releases/tag/v0.1.5
[0.1.4]: https://github.com/crzykidd/docker-api-notifier/releases/tag/v0.1.4
[0.1.3]: https://github.com/crzykidd/docker-api-notifier/releases/tag/v0.1.3
[0.1.2]: https://github.com/crzykidd/docker-api-notifier/releases/tag/v0.1.2
[0.1.1]: https://github.com/crzykidd/docker-api-notifier/releases/tag/v0.1.1
[0.1.0]: https://github.com/crzykidd/docker-api-notifier/releases/tag/v0.1.0
