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
