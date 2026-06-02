# docker-api-notifier — Claude Code Instructions

## Always — Definition of Done

No change is complete until its documentation is updated **in the same
commit as the code**. This is not optional and not deferrable:

1. **CHANGELOG.md — every change, no exceptions.** Add an entry under
   `[Unreleased]` describing what changed for the operator. A code
   change with no CHANGELOG entry is an incomplete change.
2. **PRD (`docs/PRD.md`) — confirm on every change.** Before
   finishing, explicitly check whether the change touches anything the
   PRD documents (architecture, the wire contract with STD, supported
   notifier targets, env vars, labels, the interpreter YAML format).
   If yes, update the PRD and bump its revision-history table. If no,
   confirm that in your summary ("PRD reviewed, no change needed")
   rather than silently skipping it.
3. **README.md — when operator-facing behavior changes.** Env vars,
   labels, deployment, interpreters: keep the README tables current.
4. Never leave CHANGELOG, PRD, or README out of sync with the code.

> **Known debt:** the PRDs and CLAUDE.md files in both this repo and
> STD have drifted from shipped reality before. A full audit of both
> repos' `docs/` against actual shipped state is a pending task (see
> the matching note in STD's `CLAUDE.md`). Until that audit happens,
> trust the code and CHANGELOG over the PRD where they disagree, and
> flag any contradiction you notice rather than propagating it.

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

Current shipped release: **v0.4.1** (latest tag on `main`).

Nothing currently in flight (`[Unreleased]` in `CHANGELOG.md` is
empty). v0.4.1 is a DNS/logging fix release (DNS host-name override,
STD-unconfigured log-flood fix) and does not change the STD wire
contract — the paired STD release for the capture/interpreter features
remains STD v0.6.0+.

> Do not maintain a per-phase checklist here — it rots (this section
> was stale by two minor releases before this note was added). The
> CHANGELOG `[Unreleased]` section is the live record of work in
> flight; git tags are the record of what shipped. On release, update
> only the "Current shipped release" line above.

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
[service-tracker-dashboard](https://github.com/crzykidd/service-tracker-dashboard)
(STD). They are **two independent apps** — separate version lines,
separate Docker images, separate release cadences. The notifier is not
an STD component: it also drives Technitium DNS and can run with DNS
only, STD only, or both.

The two are coupled at exactly one seam: STD's `/api/v1/register` wire
contract.

- **STD owns the contract.** Its pydantic schemas define a valid
  payload and use `extra="forbid"` — unknown keys get rejected with
  HTTP 422, not ignored.
- **This notifier is the producer.** It sends what STD documents. The
  wire format lives in `notifiers/service_tracker_dashboard.py`
  (`_to_canonical`).

### The ordering rule

Because STD's validator rejects unknown keys, **the schema-accepting
side (STD) must ship before the schema-sending side (this notifier).**

- Adding a field this notifier will send → STD must accept it first.
  Ship STD's schema change, *then* ship the notifier that emits the
  field. Shipping the notifier first means STD 422s every payload from
  upgraded hosts.
- A field STD wants to consume → STD can add the column/UI, but it
  stays empty until a notifier version populates it. Feature isn't live
  until both ship, notifier last.

**Consumer leads, producer follows. STD may lead; this notifier may
lag; this notifier must not lead the schema.**

### Safe-degradation guarantee (don't break it)

The notifier must keep older STD versions working:

- Capture fields (`networks` / `exposed_ports` / `published_ports`)
  and `exposure_observations` require STD v0.6.0+. They are documented
  as such in the README.
- `exposure_observations` semantics STD relies on: omit the field
  entirely when no interpreters are loaded (STD reads absence as "no
  update, preserve existing exposure rows"); send `[]` when
  interpreters ran but nothing matched (STD reads that as "clear the
  rows"). Do not collapse these two cases — `interpreter_loader`
  returning `None` vs. `[]` is the distinction, and
  `_run_interpreters` in `main.py` preserves it.

### Version pairing history (informational, not the rule)

- Notifier v0.3.0 switched to canonical keys + `/api/v1/register`;
  requires STD v0.5.0+.
- Notifier v0.4.0 added capture fields + the interpreter mechanism
  (`exposure_observations`); requires STD v0.6.0+.

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
