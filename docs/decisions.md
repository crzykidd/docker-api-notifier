# Decisions

Non-obvious decisions — approach changes, rejected alternatives,
workarounds — newest at top. One entry per decision.

---

## 2026-11-21 — Standards adoption: what was adapted, and why

Adopted `handoff-prompt-workflow` @ 2.0.0, `code-checkin-and-pr` @ 1.2.0,
and `release-prep-and-cut` @ 1.1.0, modeled on STD's adoption (2026-11-15).

- **Done in-session, not via a handoff prompt.** The adoption is what
  introduces `prompts/`; there was no queue to put it in. Work after this
  commit follows the threshold rule.
- **Root `VERSION` file** (bare semver), same as STD, not a `version.py` —
  the Dockerfile already copies the repo root to `/app`, so `main.py` reads
  `VERSION` beside itself and logs it at startup. Missing file logs
  `unknown` rather than crashing.
- **CI is push-only** (`dev`/`main`), no `pull_request` trigger, copying
  STD's fix for duplicate same-named check runs stalling required checks.
- **No migration check, no test job.** No database; no tests yet (the
  standard exempts a repo with no suite). Adding tests is still an open
  question in PRD §10.
- **Config validation also runs the real interpreter loader** over
  `interpreters/builtin/` and `docs/community-interpreters/`, not just a
  YAML parse — a structurally valid YAML can still be rejected by the
  loader and silently skipped at runtime. It sets
  `logging_setup._configured = True` before import so the loader's logger
  doesn't try to open `/config/notifier.log` on the runner. Rejected:
  adding a log-path env var just for CI.
- **Release commands adapted from the templates, not copied from STD.**
  STD's carry MCP-version, migration, badge and What's New steps that don't
  exist here. This repo's README has no badge/What's New, so Step 4 only
  touches existing version references. Added a project step: a cross-repo
  gate that stops prep if `[Unreleased]` adds an STD wire key, enforcing
  the "STD ships the schema first" rule.
- **ruff 0.15.17 with STD's rule set** (E, W, F, I, B; E501 ignored). The
  only findings were import order and two unused imports.
- **Retention copied from STD** (GHCR via `GITHUB_TOKEN`; untagged
  versions never deleted because multi-arch manifests reference them).
