# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

> Targeting v0.3.0. **Must ship after STD v0.5.0** — this release starts
> emitting canonical keys against `/api/v1/register`, which STD v0.5.0
> introduces.

### Added
- Shared logging setup module consumed by `main.py` and all notifier
  modules. No more duplicated handler configuration across files.
- Shared retry helper. DNS notifier now retries with backoff using the
  same policy as the STD notifier.

### Changed
- STD notifier emits canonical key names (`host`, `group`,
  `internal_health_check_enabled`, ...) and posts to
  `/api/v1/register` instead of `/api/register`. Old STD instances
  continue to work via STD's compat shim until STD v0.6.0.
- Stack-name resolution: when `com.docker.compose.project` is missing,
  the notifier passes `stack_name=None` rather than splitting the
  container name on `_`.

### Removed
- Unused `trigger_reason` parameter from the DNS notifier's `register()`
  signature.
- Stale `"refresh"` entry in `NOTIFIER_TRIGGERS`. The periodic re-scan
  path no longer consults the trigger map.

### Fixed
- `watched_actions` now includes everything `NOTIFIER_TRIGGERS`
  references, so events the notifier claims to support actually fire.
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
