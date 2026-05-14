# Community Interpreters

This directory holds **reference YAML interpreters** contributed by
operators of `docker-api-notifier`. Each file teaches the notifier how
to read labels written by a third-party tool (Traefik, Dockflare,
Caddy, Pangolin, NPM, etc.) and emit them as structured exposure
observations to STD.

## Status: examples, not products

Files here are community-contributed. They may or may not work for
your specific environment. The maintainer does not QA every
contribution — operators are expected to read the YAML, understand
what it captures, and adapt it before mounting it into a notifier
instance.

If a file here works for your setup as-is, great. If it doesn't,
edit it locally; PRs that improve an example are welcome.

## Using an interpreter

1. Copy the `.yml` file to a directory on your Docker host
   (e.g. `/etc/docker-api-notifier/interpreters/`).
2. Mount that directory into the notifier container at
   `/app/interpreters/user`:

   ```yaml
   volumes:
     - /etc/docker-api-notifier/interpreters:/app/interpreters/user:ro
   ```

3. Restart the notifier. On startup it will log which interpreters
   were loaded.

User-supplied files with the same `name:` as a builtin **override**
the builtin. That is intentional — drop in a tweaked `traefik.yml`
to customise capture without forking the notifier.

## Writing a new interpreter

See `docs/PRD.md` §12 for the full YAML format reference. The two
builtin interpreters are also mirrored here as references:

- `traefik.yml` — regex-match flavor, captures router names with a
  named group and reads multiple labels per router.
- `dockflare.yml` — fixed-key match flavor, simpler structure.

At a glance, every interpreter has three sections:

```yaml
name: <identifier>
description: <human-readable>

match:
  # Exactly one of:
  any_label_key_matches: '<regex with (?P<name>...) captures>'
  # or
  label_key: '<exact label key>'
  label_value_equals: '<expected value>'

extract:
  <local_var>:
    from_label: '<label key, may reference {captures}>'
    value_pattern: '<optional regex over the label value>'
    capture: '<named group from value_pattern>'
    coerce: bool | int
    default: <value if missing>

emit:
  layer: <required identifier>
  <field>: '<literal or {local_var}>'
  details:
    <field>: '<literal or {local_var}>'
```

**Null propagation in `emit`:** if any `{var}` referenced in a string
template resolves to `None`, the whole field becomes `None`. For a
bare placeholder (`'{var}'`), the value is passed through verbatim —
bools, ints, and lists keep their type.

## Contributing

PRs welcome. When adding a new file:

- Pick a `name:` that matches the tool being interpreted
  (e.g. `caddy`, `pangolin`, `npm`).
- Include a `description:` that names the labels read and the
  observations emitted.
- Test the YAML against a real container running the tool before
  opening the PR.
- Note any caveats in a comment near the top (e.g. "only handles
  HTTP routers, not TCP").
