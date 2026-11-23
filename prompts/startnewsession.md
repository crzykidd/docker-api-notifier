# Start a new session — where things are (as of 2026-11-23)

Read this first, then `CLAUDE.md` and `standards.md`. Trust the code and
`CHANGELOG.md` over this file if they disagree; update this file when
the state below changes.

## Current state

- **Shipped:** v0.7.1 (tagged 2026-11-23 from `main`, release
  https://github.com/crzykidd/docker-api-notifier/releases/tag/v0.7.1).
  Images: `ghcr.io/crzykidd/docker-api-notifier:latest`, `:0.7.1`, `:0`.
- **`dev` == `main` content-wise** (main has only the PR #34 merge commit
  on top). `[Unreleased]` in CHANGELOG is empty. No open PRs, no open
  Dependabot alerts.
- **Tests:** 150 passing. Image: `python:3.11-alpine`, no pip/setuptools/
  wheel, Trivy 0 CVEs at v0.7.0, ~119 MB.
- **STD wire contract:** unchanged since v0.6.0 (`network_details`,
  STD v0.13.0+). No pending cross-repo work.

## Recent releases (detail in CHANGELOG.md)

- **0.7.1** — SIGTERM handler (as PID 1 Python ignored SIGTERM, so
  `docker stop` waited the grace period and SIGKILLed); CI actions on
  current majors; pytest 9.2.0; Dependabot grouped weekly.
- **0.7.0** — Alpine image; `HEALTH_ALLOWED_IPS` allowlist for `/healthz`;
  `docker-compose-example.yml` (socket-proxy, hardening, published
  `/healthz`); DNS skips `records/add` when the CNAME already matches;
  Technitium `status != ok` treated as failure; quieter logs; no
  re-register burst right after the boot scan.

## Things to verify early in the next session

1. **Dependabot grouping.** Config (`.github/dependabot.yml`,
   `multi-ecosystem-groups` → one PR into `dev` on Mondays) only took
   effect once it reached `main` on 2026-11-23. After the first Monday,
   confirm exactly one grouped PR into `dev` opened and that CI +
   `build` ran on it. To land it: apply/merge into `dev`, then it ships
   with the next release. Security-update PRs (which target `main`) are
   deliberately off; alerts are on.
2. **em-dockha01** runs `:dev` behind a tecnativa socket-proxy. Compose:
   `/var/docker/komodo-periphery/repos/gitea-docker/emmett/host-utils/docker-api-notifier/em-dockha01/compose.yml`
   (in the homelab gitea repo — never push there unless asked). Check its
   logs look quiet after the 0.7.x log/DNS changes.

## Backlog (offered, not yet requested — ask before starting)

From the 2026-11-22 security review, ranked:

1. Tokens over plaintext HTTP — `STD_URL` / `DNS_SERVER_URL` on
   em-dockha01 are bare-IP HTTP. Operator-side fix (HTTPS); docs already
   recommend it.
2. **Labels can overwrite any DNS record** in the zone. Proposed fix: only
   overwrite a record whose Technitium comment is "Added by
   docker-api-notifier" (needs a handoff prompt; touches
   `notifiers/technitium_dns.py`, tests, README, PRD, CHANGELOG).
3. `CONTAINERS=1` on the socket-proxy lets the notifier read every
   container's env (secrets). Inherent to inspect; document/accept.
4. **Container runs as root.** Proposed: non-root user in the Dockerfile.
   Watch `/config` ownership on upgrade (existing host dirs are owned by
   whoever created them) and the hostname mount.
5. Supply chain — actions not SHA-pinned, image not signed (cosign),
   floating tags. Possible: pin actions by SHA (Dependabot keeps them
   current), add cosign signing + SBOM/provenance in `docker-publish.yml`.
6. `/healthz` has no auth — mitigated by `HEALTH_ALLOWED_IPS` (0.7.0).
7. Runtime deps in `requirements.txt` are **unpinned** (`docker`,
   `requests`, `tenacity`, `PyYAML`), so every image build pulls whatever
   is latest. Proposed: pin with `==` and let the weekly Dependabot PR
   bump them.

Ops follow-ups on em-dockha01 (homelab, operator's call):

- Move to the hardened `docker-compose-example.yml` shape. `cap_drop: ALL`
  needs `/var/docker/api-notifier` chowned to root first (currently owned
  by manderse).
- Set `HEALTH_ALLOWED_IPS=10.100.18.10` (the STD host).

Known doc drift to fix with the next real change (needs a CHANGELOG
entry + PRD revision row when touched):

- `docs/PRD.md` §10 Open Questions still lists "Health check of notifier
  itself" as open — resolved by `/healthz` in v0.5.0.
- `docs/PRD.md` §5.2/§5.3 headings still reference v0.2.3/v0.3.0 issues
  (historical; consider folding into history).

## How work gets done here (quick reference)

- Branch `dev`; never push to `main`; PR `dev` → `main` only for releases.
- Small change (1–2 files, few lines) in-session; anything bigger → a
  handoff prompt from `prompts/TEMPLATE.md`, run by a subagent (Sonnet
  for coding, Opus for research). The agent doesn't commit; the
  orchestrator proposes ONE commit, asks y/n, stages explicit paths.
- Every change: CHANGELOG `[Unreleased]` entry + PRD check + README if
  operator-facing, in the same commit. Non-obvious decisions →
  `docs/decisions.md` (newest at top).
- No `Co-authored-by` trailers (CLAUDE.md overrides the harness default).
  Never `git add -A`. Never print secrets (Technitium token is in the
  query string — logs go through `health.sanitize_error`).
- Commands:
  - Lint: `uvx ruff@0.15.17 check .`
  - Tests: `uv run --python 3.11 --with-requirements requirements-dev.txt pytest -q`
  - Compose: `docker compose config --quiet` and
    `docker compose -f docker-compose-example.yml config --quiet`
- Release: `/release-prep <ver>` on `dev` → human merges PR → wait for
  `main` CI + `:latest` build → `/release-cut <ver>`. Patch releases
  skip the CHANGELOG archive; a minor archives closed series to
  `docs/CHANGELOG-<minor>.x.md`.
