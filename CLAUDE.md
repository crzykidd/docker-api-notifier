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

## Standards

This project adopts crzynet engineering standards from `homelab-configs`.
**Read [`standards.md`](standards.md) at session start** whenever the work
could touch anything a standard governs (branching, commits, CI, releases,
handoff prompts). It lists each adopted standard with its pinned version.

<!--
Source: standards/handoff-prompt-workflow @ v2.0.0 (crzynet/homelab-configs).
Paste the section below verbatim into the adopting project's CLAUDE.md.
The full standard (the plan→decide→execute→document principle, model selection,
TEMPLATE, adoption checklist) lives at:
https://gitea.crzynet.com/crzynet/homelab-configs/src/branch/main/standards/handoff-prompt-workflow/README.md
-->

## Handoff prompts (operational rules)

This project adopts the `handoff-prompt-workflow` standard. The full why-and-how lives at
the source above; the rules below are the per-session do/don'ts an agent must honor by
default:

- **Edit-size threshold — decide by how much you'll change:**
  - A genuinely small change — roughly **one or two files and a few lines** (a typo, one
    config value, a one-line fix) — do it **in-session**, no prompt.
  - **Anything bigger requires a handoff prompt** — more than ~2 files, a multi-step
    change, a new feature, or any edit large enough that a fresh context would run it
    more cleanly. **When in doubt, write the prompt.**
- **A handoff prompt is a file in `prompts/`** — one per task, from `prompts/TEMPLATE.md`,
  with frontmatter (`name`, `status`, `created`, `model`, `completed`, `result`). Set
  `model:` from the task type: **Opus** for research/planning, **Sonnet** for coding;
  mixed defaults to Opus.
- **Execute the prompt by spawning a subagent — don't hand the user a command.** Spawn an
  agent on the prompt's `model:`, let it run the prompt end-to-end, and **report the
  outcome back**. The agent gets a fresh context; you stay in the loop.
  - **Manual fallback only on explicit request.** If the user says e.g. "use manual
    prompts for this," give them
    `claude --model <model> "Read prompts/<file>.md and execute it as your task."`
    instead of spawning.
- **Check the working tree before editing.** Run `git status --porcelain`, cross-reference
  the files the plan touches; if any have uncommitted changes, list them and ask before
  touching. Surface unrelated dirty files once; they don't block.
- **The prompt self-updates and moves when done.** The executing agent sets its
  frontmatter (`status`/`completed`/`result`) and `git mv`s the file into `prompts/done/`
  (success) or `prompts/failed/` (failure).
- **One commit at the end; the prompt bundles in.** The prompt file is **not** committed
  up front — it lands in the single end commit alongside the work and the prompt move.
  Propose ONE commit (files list + one-line message), ask `y/n`, stage only those specific
  paths. **Never `git add -A`, never auto-commit, never push.** A spawned agent prepares
  the tree and reports the proposed commit back; the orchestrating session surfaces the
  `y/n`.
- **Record non-obvious decisions** (approach changes, rejected alternatives, workarounds)
  in `docs/decisions.md`, newest at top.

If you're unsure whether an action would violate one of the above, stop and ask before
acting.

<!--
Source: standards/code-checkin-and-pr @ v1.2.0 (crzynet/homelab-configs).
Paste the section below verbatim into the adopting project's CLAUDE.md.
The full standard (publishing matrix, retention, CI check definitions) lives at:
https://gitea.crzynet.com/crzynet/homelab-configs/src/branch/main/standards/code-checkin-and-pr/README.md
-->

## Code check-in (operational rules)

This project adopts the `code-checkin-and-pr` standard. The full why-and-how lives at
the source above; the rules below are the per-session do/don'ts a coding agent must
honor by default:

- **Never push directly to `main`.** `main` is protected. All changes land via a pull
  request from `dev` → `main`, and only when every required check is green.
- **Day-to-day work happens on `dev`** (or a short-lived branch off `dev`). Push to
  `dev` freely.
- **Commit message prefixes are required** — Conventional-Commits style:
  - `feat:` — new user-facing feature
  - `fix:` — bug fix
  - `chore:` — config, tooling, dependencies, maintenance
  - `docs:` — documentation-only changes
- **Do not add `Co-authored-by:` trailers** unless the user explicitly asks.
- **Doc updates ship in the same commit as the code they describe** — never as a
  follow-up commit.
- **Never bypass hooks** (no `--no-verify`, `--no-gpg-sign`, etc.) unless the user
  explicitly asks. If a hook fails, fix the underlying issue.
- **Stable releases are tagged from `main` only.** Don't tag from `dev`.

If you're unsure whether an action would violate one of the above, stop and ask before
acting.

<!--
Source: standards/release-prep-and-cut @ v1.1.0 (crzynet/homelab-configs).
Paste the section below verbatim into the adopting project's CLAUDE.md.
The full standard (two-phase prep/cut workflow, archive trigger, validation
steps, adoption checklist) lives at:
https://gitea.crzynet.com/crzynet/homelab-configs/src/branch/main/standards/release-prep-and-cut/README.md
-->

## Release process (operational rules)

This project adopts the `release-prep-and-cut` standard. The full why-and-how
lives at the source above; the rules below are the per-session do/don'ts a
coding agent must honor by default:

- **The version is stored BARE in the source-of-truth file** — no `v` prefix
  anywhere in code. The `v` prefix is added in exactly one place: the git tag
  and matching GitHub release name. Don't add it to README badges, CHANGELOG
  headers, in-code image tags, or anywhere else.
- **`CHANGELOG.md` is the single source of truth for release notes.** The PR
  description (set by `/release-prep`) and the GitHub release body (set by
  `/release-cut`) reuse the **same section verbatim**. Never author release
  notes twice.
- **One commit per release prep.** Version bump + changelog roll + every doc
  sync ship in a single `chore(release): prepare v<version>` commit. No
  `Co-authored-by:` trailers.
- **Never re-tag.** If `v<version>` already exists as a local tag, a remote
  tag, or a GitHub release, STOP. Never delete-and-recreate; never `--force`.
  Pick the next version instead.
- **`/release-cut` only after the PR has merged and CI is green.** The
  publish-to-`main` workflow must have already pushed `:latest` images to the
  registry before `/release-cut` runs. If you cannot confirm both — STOP and
  tell the user to wait.
- **The release tag is the only thing the cut command writes to `main`.** Both
  the prep commit and any follow-up docs commit land on `dev` and reach `main`
  only via PR. Never push directly to `main` as part of a release.

If you're unsure whether an action would violate one of the above, stop and
ask before acting.

## Commit style

The prefixes (`feat:`, `fix:`, `chore:`, `docs:`) and the no-`Co-authored-by`
rule come from the `code-checkin-and-pr` snippet above. Project extension:
`refactor:` for non-behavior-changing internal cleanup. A release prep uses
`chore(release): prepare v<version>`.

## Stack

- Python 3.11
- `docker` (Docker SDK for Python) — Docker event subscription
- `requests` — DNS notifier HTTP calls
- `health.py` — `/healthz` endpoint (stdlib `http.server`, no extra
  dependency) and the health state recorded by `main.py` and the notifiers
- `tenacity` — retry-with-backoff for downstream notifier calls
- `PyYAML` — interpreter YAML loading
- Container: single-image Docker on `python:3.11-alpine` (no pip in the
  final image), no compose orchestration of its own
  - `Dockerfile` — production image
  - `docker-compose.yml` — development setup (builds from source)
  - `docker-compose-example.yml` — production example (socket proxy,
    hardening, published `/healthz`); CI parses and `compose config`s it

## Configuration

- Configuration is via environment variables; there is no central config
  file. The one on-disk input is interpreter YAML (`interpreters/builtin/`
  baked in, `/app/interpreters/user/` operator-mounted) — see PRD §11.
- Per-container behavior comes from `dockernotifier.*` labels on the
  containers being watched.
- Full ENV reference: `README.md` → Environment Variables section.

## Project Documentation

- Full PRD is at `docs/PRD.md` — read this before starting any phase.
- Project history (structural events, milestones) at `docs/HISTORY.md`.
- `README.md` at the root — keep it current with what has been built.
- Commit doc updates in the same commit as the code changes they describe.
- Adopted engineering standards and their pinned versions at `standards.md`.
- Handoff prompts (live queue + `done/`/`failed/` archive) in `prompts/`.
- Non-obvious decisions (newest at top) at `docs/decisions.md`.

## Build Status

Current shipped release: **v0.7.0** (latest tag on `main`).

Work in flight is under `[Unreleased]` in `CHANGELOG.md`. v0.7.0 does not
change the STD wire contract. It adds an optional `/healthz` client-IP
allowlist (`HEALTH_ALLOWED_IPS`) and `docker-compose-example.yml` (socket
proxy, hardening, published `/healthz`), moves the image to
`python:3.11-alpine` without pip/setuptools/wheel, skips DNS `records/add`
when the CNAME already matches, treats a Technitium `status != ok` reply as
a failure, logs each dispatch once, and no longer re-registers everything
right after the boot scan. v0.6.0 extends
the wire contract: each `networks[]` item can carry `driver`,
`ip_address`, `ipv6_address` and `mac_address`, sent only to STD v0.13.0+
that advertises `network_details` via `/api/v1/meta` (older STD gets just
name/aliases). It also adds `dockernotifier.std.skip`, hardens the
`dockernotifier.std.*` labels (reserved keys, `host`, bool typos), and
reports a docker-socket-proxy 403 once with the setting to change. v0.5.1
was a docs-only patch. v0.5.0 added the
`image_info` wire key (running image digests and OCI labels), sent only to
STD v0.12.0+ that advertises it via `/api/v1/meta` — older STD keeps
working without it. It also added the `/healthz` endpoint and image
`HEALTHCHECK`, stops retrying 4xx, puts a 10 s timeout on every request,
adds the `pytest` suite, and stops the DNS token being logged on failure.

> Do not maintain a per-phase checklist here — it rots (this section
> was stale by two minor releases before this note was added). The
> CHANGELOG `[Unreleased]` section is the live record of work in
> flight; git tags are the record of what shipped. `/release-prep`
> updates this block on release.

## CI, Registry, and Releases

Branching, PR flow, and the release rules are in the snippets above; the
project-specific facts are:

- **CI** (`.github/workflows/ci.yml`, push to `dev`/`main` only): `Lint`
  (ruff 0.15.17, rules in `ruff.toml`), `Config validation` (every YAML/JSON
  parses, and every interpreter YAML passes `interpreter_loader`),
  `Compose validation`, and `Test` (`pytest -q` over `tests/`, which fake
  the Docker client and HTTP; deps in `requirements-dev.txt`). No migration
  check (no database). CodeQL runs as GitHub's default code-scanning setup.
- **Required checks on `main`** (ruleset "Require PR for Main"): `build`
  (image build, `docker-publish.yml`), `Lint`, `Config validation`,
  `Compose validation`, `Test`, plus a CodeQL `code_scanning` rule. CodeQL must
  complete, but its findings don't block merge (thresholds `none`) —
  triage them in the repo's Security → Code scanning view.
- **GHCR is the only registry** (`ghcr.io/crzykidd/docker-api-notifier`,
  via `.github/workflows/docker-publish.yml`). Docker Hub is frozen at
  v0.4.2. Push to `dev` builds `:dev` and `:sha-<short>`; push to `main`
  builds `:latest` and `:sha-<short>`; a published release builds `:latest`,
  `:X.Y.Z`, and `:X`. `retention.yml` prunes old GHCR versions (30 `sha-*`,
  15 semver; `:latest`/`:dev`/`:X` never).
- **The version lives in the bare-semver `VERSION` file** at the repo root.
  `main.py` logs it at startup; `docker-publish.yml` fails a release whose
  tag (minus `v`) != `VERSION`.
- **To ship:** `/release-prep <version>` on `dev` (bumps `VERSION`, rolls
  CHANGELOG, syncs docs, opens the PR) → human merges the PR and waits for
  CI and the `:latest` build → `/release-cut <version>` (tags `v<version>`,
  publishes the release). Commands live in `.claude/commands/`.

## Changelog Process

- `CHANGELOG.md` lives at repo root.
- Follow Keep a Changelog format (keepachangelog.com).
- Add entries to `[Unreleased]` section as features are built.
- User-facing language only — describe what changed for the operator.
- Categories: Added, Changed, Fixed, Security, Deprecated, Removed.
- On release, `/release-prep` moves `[Unreleased]` to a new version
  section dated today and, on a new minor/major, archives closed minor
  series to `docs/CHANGELOG-<minor>.x.md` (summarize-on-archive).
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
  HTTP 400 (`unknown_keys` in the body), not ignored.
- **This notifier is the producer.** It sends what STD documents. The
  wire format lives in `notifiers/service_tracker_dashboard.py`
  (`_to_canonical`).

### The ordering rule

Because STD's validator rejects unknown keys, **the schema-accepting
side (STD) must ship before the schema-sending side (this notifier).**

- Adding a field this notifier will send → STD must accept it first.
  Ship STD's schema change, *then* ship the notifier that emits the
  field. Shipping the notifier first means STD 400s every payload from
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

- `image_info` (the running image's digests and OCI labels) requires
  STD v0.12.0+ (API revision 5). It is sent **only** when STD's
  unauthenticated `GET /api/v1/meta` lists `"image_info"` in `features`;
  the answer is cached and re-checked when the `X-STD-API-Revision`
  response header changes or STD 400s the field. Opt out with
  `STD_SEND_IMAGE_INFO=false`. The DNS notifier never receives it.

- `networks[].driver` / `ip_address` / `ipv6_address` / `mac_address`
  require STD v0.13.0+ (feature `network_details`). Same mechanism as
  `image_info`; opt out with `STD_SEND_NETWORK_DETAILS=false`. The gate
  and the 400-retry live in the STD notifier. A 400 is attributed from
  `details[].loc` only, never from `"networks"` in `unknown_keys`.

### Version pairing history (informational, not the rule)

- Notifier v0.3.0 switched to canonical keys + `/api/v1/register`;
  requires STD v0.5.0+.
- Notifier v0.4.0 added capture fields + the interpreter mechanism
  (`exposure_observations`); requires STD v0.6.0+.
- Notifier v0.5.0 added `image_info`, gated on STD's `/api/v1/meta`;
  pairs with STD v0.12.0+ (older STD keeps working, it just never gets
  the field).
- Notifier v0.6.0 added `networks[]` details, gated on `network_details`;
  pairs with STD v0.13.0+ (older STD gets name/aliases only).

## Notifier Module Conventions

The notifier module contract is documented in `docs/PRD.md` §3.3.
A reference template is at `notifiers/_template.py`.

In short: one module per downstream system under `notifiers/`,
exposing `register(**kwargs)`. Modules consume shared logging
(`logging_setup`) and shared retry (`retry`). They own their own
auth and wire format, and record their final outcome with
`health.record_success()` / `health.record_error()` (surfaced by
`/healthz`).

When adding a new notifier: copy `notifiers/_template.py`, replace
the placeholders, wire it into `main.py`'s `NOTIFIER_TRIGGERS` and
dispatch, document env vars and labels in `README.md`.
