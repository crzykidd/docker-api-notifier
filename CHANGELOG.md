# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

> Targeting v0.3.0. **Requires STD v0.5.0 or later.** This release
> emits payloads to `/api/v1/register` using STD's canonical schema;
> earlier STD versions do not expose that endpoint.

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

[Unreleased]: https://github.com/crzykidd/docker-api-notifier/compare/v0.2.3...HEAD
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
