# docker-api-notifier — Claude Code Instructions

## Always

- After any change that affects architecture, dependencies, supported
  notifier targets, or the wire contract with downstream consumers,
  update `docs/PRD.md` and `README.md` accordingly.
- After completing a phase, update `README.md` with what has been built.
- Never leave PRD or README out of sync with the codebase.

## Commit style

- `feat:` new feature
- `chore:` config, tooling, maintenance
- `fix:` bug fix
- `docs:` documentation only changes
- `refactor:` non-behavior-changing internal cleanup

## Stack

- Python 3.11
- `docker` (Docker SDK for Python) — Docker event subscription
- `requests` — DNS notifier HTTP calls
- `tenacity` — retry-with-backoff for downstream notifier calls
- Container: single-image Docker, no compose orchestration of its own
  - `Dockerfile` — production image
  - `docker-compose.yml` — example deployment

## Configuration

- All configuration is via environment variables. There is no config file.
- Per-container behavior comes from `dockernotifier.*` labels on the
  containers being watched.
- Full ENV reference: `README.md` → Environment Variables section.

## Project Documentation

- Full PRD is at `docs/PRD.md` — read this before starting any phase.
- Project history (structural events, milestones) at `docs/HISTORY.md`.
- `README.md` at the root — keep it current with what has been built.
- Commit doc updates in the same commit as the code changes they describe.

## Build Status

Current shipped release: **v0.2.3** (latest tag on `main`)

Next release target: **v0.3.0** — cleanup release. Cannot ship until
**STD v0.5.0** is released (v0.3.0 emits canonical keys against
`/api/v1/register`, which STD v0.5.0 introduces).

- Phase 1 — Documentation baseline: IN PROGRESS
- Phase 2 — Logging consolidation: NOT STARTED
- Phase 3 — Shared retry helper: NOT STARTED
- Phase 4 — Stack-name fallback fix: NOT STARTED
- Phase 5 — `watched_actions` / `NOTIFIER_TRIGGERS` cleanup: NOT STARTED
- Phase 6 — Drop `trigger_reason` param: NOT STARTED
- Phase 7 — Switch to `/api/v1/register` + canonical keys: NOT STARTED
  *(blocked until STD v0.5.0 is released)*

## Git Workflow

- Work on `dev` branch for all changes.
- Push to `dev` freely — builds `:dev` images.
- When ready to release:
  - Create PR `dev` → `main` on GitHub.
  - Merge after CI passes.
  - Tag release from `main` via the GitHub Releases UI.
- Never push directly to `main`.
- Branch protection on `main` requires PR + green build, blocks
  force-push and deletion.
- Do NOT add `Co-authored-by` to commits.

## Release Process

- Push to `dev` — GitHub Actions builds and pushes `:dev` and
  `:sha-<short>` images to Docker Hub.
- Push to `main` (via PR from `dev`) — GitHub Actions builds and pushes
  `:latest` and `:sha-<short>` images.
- When the build is stable and ready to ship:
  1. GitHub → Releases → Draft new release.
  2. Create a new tag in `vX.Y.Z` format.
  3. Publish the release.
  4. GitHub Actions builds and pushes `:latest`, `:X.Y.Z`, and `:X` to
     Docker Hub.

## Changelog Process

- `CHANGELOG.md` lives at repo root.
- Follow Keep a Changelog format (keepachangelog.com).
- Add entries to `[Unreleased]` section as features are built.
- User-facing language only — describe what changed for the operator.
- Categories: Added, Changed, Fixed, Security, Deprecated, Removed.
- On release: move `[Unreleased]` to a new version section dated today.
- GitHub release body = that version's CHANGELOG section (single source
  of truth).

## Cross-Repo Coordination

This project is paired with
[service-tracker-dashboard](https://github.com/crzykidd/service-tracker-dashboard).
The contract is:

- **STD** owns the wire contract for the register endpoint.
- **Notifier** is a producer — it sends what STD documents.
- Wire-format changes start in STD. The notifier follows.
- For v0.3.0 specifically: STD v0.5.0 must ship first; this notifier
  release switches to canonical keys + `/api/v1/register` after.

## Notifier Module Conventions

The notifier module contract is documented in `docs/PRD.md` §3.3.
A reference template is at `notifiers/_template.py`.

In short: one module per downstream system under `notifiers/`,
exposing `register(**kwargs)`. Modules consume shared logging
(`logging_setup`) and shared retry (`retry`). They own their own
auth and wire format.

When adding a new notifier: copy `notifiers/_template.py`, replace
the placeholders, wire it into `main.py`'s `NOTIFIER_TRIGGERS` and
dispatch, document env vars and labels in `README.md`.

## Git Rules

- Do NOT add `Co-authored-by` lines to commit messages.
