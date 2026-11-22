# docker-api-notifier Project History

This file documents structural events in the project's history — things
that don't fit neatly in a changelog entry but are worth knowing about.

For the feature-level changelog, see [CHANGELOG.md](../CHANGELOG.md).

---

## Documentation baseline (v0.3.0 cycle)

Through v0.2.3, the project shipped with a single `README.md` and no
PRD or HISTORY file. As part of the v0.3.0 cleanup work, this document,
[`PRD.md`](./PRD.md), and a project-level [`CLAUDE.md`](../CLAUDE.md)
were added.

### Why

The notifier was reaching the point where its rough edges (asymmetric
retry, fragile stack-name fallback, half-wired event triggers) needed
explicit listing somewhere durable. The PRD captures that list and the
intended end state. CLAUDE.md captures the workflow conventions that had
been informal up to that point.

### What changed

- `docs/PRD.md` added — current state, planned v0.3.0 changes, scope.
- `docs/HISTORY.md` (this file) added.
- `CLAUDE.md` added at repo root.
- `CHANGELOG.md` reformatted to Keep a Changelog conventions; existing
  v0.1.x and v0.2.x tags listed as stub entries (detailed notes for
  pre-v0.3.0 versions are not retained).

### Impact on existing installs

None. Documentation only.

---

## Cross-repo wire contract change (v0.3.0)

v0.3.0 is the first release of this project that emits canonical key
names to the Service Tracker Dashboard register endpoint. Prior to
v0.3.0, the STD notifier sent a free-form kwargs dict whose key names
were derived directly from `dockernotifier.std.*` label suffixes —
including legacy variants like `internal.health` (with a literal dot).

### Why

The dashboard side accumulated key-remapping logic to absorb this
variation. The remapping was undocumented and silent. v0.3.0 of the
notifier and v0.5.0 of STD together establish a canonical wire shape
documented in STD's PRD and validated by a pydantic schema.

### What changed (notifier side)

- STD notifier targets `/api/v1/register` (new in STD v0.5.0) instead
  of `/api/register`.
- Outbound payload uses canonical keys: `host`, `group`,
  `internal_health_check_enabled`, `external_health_check_enabled`,
  `internal_url`, `external_url`.

### Coordination

- STD v0.5.0 must ship before notifier v0.3.0.
- Old notifier deployments (v0.2.x) continue to work against STD v0.5.0
  via STD's compat shim until STD v0.6.0.
- Notifier v0.3.0+ deployments are required before upgrading any STD
  instance to v0.6.0.

---

## On-disk configuration introduced (v0.4.0)

Through v0.3.x, the notifier had no on-disk inputs other than the
Docker socket itself — configuration was entirely env vars and
container labels. v0.4.0 introduces the first on-disk inputs: YAML
**interpreter files** loaded at startup from
`/app/interpreters/builtin/` (baked into the image) and
`/app/interpreters/user/` (operator-mounted, optional). The image
ships two builtins (`traefik.yml`, `dockflare.yml`) that fire
automatically for any container reported to STD.

### Why

Translating third-party label schemes (Traefik routers, Dockflare
hostnames, ...) into STD's `exposure_observations` shape in hard-coded
Python would have required a notifier fork per supported tool.
Expressing the match/extract/emit logic as small YAML files keeps
operator-facing extension out of the Python codebase and lets the
community contribute interpreters without rebuilding the image.

### What changed structurally

- New module `interpreter_loader.py` with `load_interpreters()`
  (called once at startup) and `evaluate()` (called per dispatch).
- New on-disk locations: `/app/interpreters/builtin/`,
  `/app/interpreters/user/`.
- New community-reference directory `docs/community-interpreters/`
  holding example YAMLs (explicitly non-curated; PRs welcome).
- PRD §1.3 design principles softened: "no state" became "no runtime
  state" (interpreter YAML is configuration, not per-event memory);
  "all configuration via env vars" became "env vars + labels + YAML
  for interpreters."

### Coordination with STD

The interpreter mechanism emits `exposure_observations` on every
STD payload. STD's strict pydantic validator rejects unknown keys,
so **STD v0.6.0 must ship before notifier v0.4.0**. The same
ordering applies to the network/port capture fields (`networks`,
`exposed_ports`, `published_ports`) which also shipped in v0.4.0.

### Note on version numbering

The v0.4.0 release bundled work originally scoped for three separate
releases — v0.3.1 (STD opt-out env var), v0.3.2 (network/port
capture), and v0.4.0 (interpreters). v0.3.1 and v0.3.2 were never
cut as git tags; `git tag --list` jumps directly from `v0.3.0` to
`v0.4.0`. PRD revision-history rows 0.2 and 0.3 document the planning
work; row 0.4 documents the consolidation.

---

## Registry move: Docker Hub → GHCR (v0.4.2)

Through v0.4.1, images were published only to Docker Hub
(`crzykidd/docker-api-notifier`). v0.4.2 (2026-11-21) moved publishing
to GitHub Container Registry (`ghcr.io/crzykidd/docker-api-notifier`).

### Why

GHCR retention can run on the workflow's own `GITHUB_TOKEN`, which the
`code-checkin-and-pr` standard's registry-retention job needs; Docker Hub
would need a separate delete-scoped token. The paired STD project made
the same move at its v0.6.7.

### What changed

- v0.4.2 was published to **both** registries so GHCR already had an
  image for users to switch to. The Docker Hub build alone set
  `REGISTRY_NOTICE=dockerhub`, which made the notifier log a "this image
  has moved" notice at startup.
- After v0.4.2, Docker Hub publishing and the notice code were removed.
  Docker Hub is frozen at v0.4.2 (`:latest`, `:0.4.2`, `:0`).

### Impact on existing installs

Operators pulling from Docker Hub keep running v0.4.2 and see the moved
notice in their logs. Switching is a one-line compose change to
`ghcr.io/crzykidd/docker-api-notifier:<tag>`; env vars, labels, and
volumes are unchanged.
