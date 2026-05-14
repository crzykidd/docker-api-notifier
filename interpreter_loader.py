"""
YAML interpreter loader and evaluator for docker-api-notifier.

Interpreters read labels written by third-party tools (Traefik,
Dockflare, etc.) and emit structured exposure observations that the
notifier forwards to STD. See PRD §12 for the full design and YAML
format reference.

Public surface:
    load_interpreters() -> LoadResult
    evaluate(interpreters, labels) -> list[dict]

The module is named `interpreter_loader` (not `interpreters`) to
avoid a name collision with the on-disk `interpreters/builtin/` and
`interpreters/user/` directories used as the YAML search roots:
Python's namespace-package mechanism would otherwise shadow the
module file with the directory.

`load_interpreters()` is called once at notifier startup. The returned
LoadResult carries the list of compiled interpreters plus a flag
indicating whether any directory was even searched / loaded — this
distinguishes "interpreters ran and nothing matched" (empty list on
the wire) from "interpreters disabled" (null on the wire).

`evaluate()` is called per container event with the container's
labels dict. It runs every loaded interpreter against the labels and
returns the union of their emitted observations.
"""

import os
import re
from dataclasses import dataclass, field
from typing import Any, Optional

import yaml

from logging_setup import get_logger

logger = get_logger("interpreters")

BUILTIN_DIR = "/app/interpreters/builtin"
USER_DIR = "/app/interpreters/user"

_TRUTHY = {"true", "1", "yes"}


@dataclass
class ExtractSpec:
    """One entry in the `extract:` section."""
    name: str
    from_label_template: str
    value_pattern: Optional[re.Pattern] = None
    value_capture: Optional[str] = None
    coerce: Optional[str] = None  # "bool" or "int"
    default: Any = None


@dataclass
class Interpreter:
    name: str
    description: str
    # Match — exactly one flavor is populated.
    match_any_label_key: Optional[re.Pattern] = None
    match_label_key: Optional[str] = None
    match_label_value_equals: Optional[str] = None
    extract: list = field(default_factory=list)  # list[ExtractSpec]
    emit: dict = field(default_factory=dict)
    source_path: str = ""


@dataclass
class LoadResult:
    interpreters: list  # list[Interpreter]
    directories_searched: bool  # True if either builtin/user dir was found

    @property
    def any_loaded(self) -> bool:
        return bool(self.interpreters)


# ---------------------------------------------------------------------------
# Loading & validation
# ---------------------------------------------------------------------------

def load_interpreters(
    builtin_dir: str = BUILTIN_DIR,
    user_dir: str = USER_DIR,
) -> LoadResult:
    """
    Load YAML interpreters from builtin and user directories.

    User-supplied interpreters with the same `name` as a builtin
    override the builtin. Invalid files log a warning and are
    skipped; the loader continues with the rest.
    """
    by_name: dict = {}
    directories_searched = False

    if os.path.isdir(builtin_dir):
        directories_searched = True
        for interp in _load_dir(builtin_dir, "builtin"):
            by_name[interp.name] = interp

    if os.path.isdir(user_dir):
        directories_searched = True
        for interp in _load_dir(user_dir, "user"):
            if interp.name in by_name:
                logger.info(
                    f"[interpreter:{interp.name}] user file {interp.source_path} "
                    f"overrides builtin"
                )
            by_name[interp.name] = interp

    interpreters = sorted(by_name.values(), key=lambda i: i.name)
    if interpreters:
        names = ", ".join(i.name for i in interpreters)
        logger.info(f"Loaded {len(interpreters)} interpreter(s): {names}")
    elif directories_searched:
        logger.info("No interpreters loaded (directories present but empty or all invalid)")
    else:
        logger.info("No interpreters loaded (no interpreter directories present)")

    return LoadResult(
        interpreters=interpreters,
        directories_searched=directories_searched,
    )


def _load_dir(path: str, source_label: str):
    """Yield validated Interpreter objects from every *.yml file in path."""
    try:
        entries = sorted(os.listdir(path))
    except OSError as e:
        logger.warning(f"Could not list interpreter dir {path}: {e}")
        return
    for entry in entries:
        if not (entry.endswith(".yml") or entry.endswith(".yaml")):
            continue
        full = os.path.join(path, entry)
        try:
            with open(full, "r", encoding="utf-8") as f:
                doc = yaml.safe_load(f)
        except (OSError, yaml.YAMLError) as e:
            logger.warning(f"Failed to read {source_label} interpreter {full}: {e}")
            continue
        interp = _validate_and_compile(doc, full)
        if interp is not None:
            yield interp


def _validate_and_compile(doc: Any, source_path: str) -> Optional[Interpreter]:
    """Return a compiled Interpreter, or None if the document is invalid."""
    prefix = f"[interpreter @ {source_path}]"
    if not isinstance(doc, dict):
        logger.warning(f"{prefix} top-level YAML must be a mapping; skipping")
        return None

    name = doc.get("name")
    if not isinstance(name, str) or not name.strip():
        logger.warning(f"{prefix} missing or invalid `name`; skipping")
        return None
    name = name.strip()

    description = doc.get("description") or ""
    if not isinstance(description, str):
        description = str(description)

    match = doc.get("match")
    if not isinstance(match, dict):
        logger.warning(f"[interpreter:{name}] missing or invalid `match` section; skipping")
        return None

    interp = Interpreter(
        name=name,
        description=description.strip(),
        source_path=source_path,
    )

    has_regex = "any_label_key_matches" in match
    has_fixed = "label_key" in match
    if has_regex and has_fixed:
        logger.warning(
            f"[interpreter:{name}] match section has both regex and fixed-key flavors; "
            f"only one is allowed. Skipping."
        )
        return None
    if not has_regex and not has_fixed:
        logger.warning(
            f"[interpreter:{name}] match section must define either "
            f"`any_label_key_matches` or `label_key`. Skipping."
        )
        return None

    if has_regex:
        pattern_str = match["any_label_key_matches"]
        if not isinstance(pattern_str, str):
            logger.warning(f"[interpreter:{name}] `any_label_key_matches` must be a string; skipping")
            return None
        try:
            interp.match_any_label_key = re.compile(pattern_str)
        except re.error as e:
            logger.warning(
                f"[interpreter:{name}] could not compile `any_label_key_matches` "
                f"regex {pattern_str!r}: {e}. Skipping."
            )
            return None
    else:
        key = match["label_key"]
        if not isinstance(key, str) or not key.strip():
            logger.warning(f"[interpreter:{name}] `label_key` must be a non-empty string; skipping")
            return None
        interp.match_label_key = key
        value_equals = match.get("label_value_equals")
        if value_equals is not None and not isinstance(value_equals, str):
            value_equals = str(value_equals)
        interp.match_label_value_equals = value_equals

    extract_section = doc.get("extract") or {}
    if not isinstance(extract_section, dict):
        logger.warning(f"[interpreter:{name}] `extract` must be a mapping; skipping")
        return None
    for var_name, spec in extract_section.items():
        compiled = _compile_extract(name, var_name, spec)
        if compiled is None:
            return None
        interp.extract.append(compiled)

    emit_section = doc.get("emit")
    if not isinstance(emit_section, dict):
        logger.warning(f"[interpreter:{name}] missing or invalid `emit` section; skipping")
        return None
    if "layer" not in emit_section:
        logger.warning(f"[interpreter:{name}] `emit` must include a `layer` field; skipping")
        return None
    interp.emit = emit_section

    logger.debug(f"[interpreter:{name}] loaded from {source_path}")
    return interp


def _compile_extract(interp_name: str, var_name: str, spec: Any) -> Optional[ExtractSpec]:
    if not isinstance(spec, dict):
        logger.warning(
            f"[interpreter:{interp_name}] extract.{var_name} must be a mapping; skipping interpreter"
        )
        return None
    from_label = spec.get("from_label")
    if not isinstance(from_label, str) or not from_label.strip():
        logger.warning(
            f"[interpreter:{interp_name}] extract.{var_name}.from_label must be a non-empty string; "
            f"skipping interpreter"
        )
        return None
    coerce = spec.get("coerce")
    if coerce is not None and coerce not in ("bool", "int"):
        logger.warning(
            f"[interpreter:{interp_name}] extract.{var_name}.coerce={coerce!r} must be 'bool' or 'int'; "
            f"skipping interpreter"
        )
        return None
    value_pattern_str = spec.get("value_pattern")
    value_pattern = None
    value_capture = spec.get("capture")
    if value_pattern_str is not None:
        if not isinstance(value_pattern_str, str):
            logger.warning(
                f"[interpreter:{interp_name}] extract.{var_name}.value_pattern must be a string; "
                f"skipping interpreter"
            )
            return None
        try:
            value_pattern = re.compile(value_pattern_str)
        except re.error as e:
            logger.warning(
                f"[interpreter:{interp_name}] extract.{var_name}.value_pattern {value_pattern_str!r} "
                f"could not compile: {e}. Skipping interpreter."
            )
            return None
    return ExtractSpec(
        name=var_name,
        from_label_template=from_label,
        value_pattern=value_pattern,
        value_capture=value_capture,
        coerce=coerce,
        default=spec.get("default"),
    )


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

def evaluate(interpreters, labels: dict) -> list:
    """
    Run every interpreter against the container's labels.

    Returns the concatenated list of observations. An interpreter
    can produce zero or more observations: a regex-match flavor can
    fire multiple times (e.g. multiple Traefik routers on one
    container) and emits one observation per match; a fixed-key
    flavor emits at most one observation.
    """
    results = []
    for interp in interpreters:
        try:
            results.extend(_evaluate_one(interp, labels))
        except Exception as e:  # defensive — bad regex at runtime, etc.
            logger.warning(
                f"[interpreter:{interp.name}] unexpected error during evaluation: {e}; skipping"
            )
    return results


def _evaluate_one(interp: Interpreter, labels: dict) -> list:
    """Evaluate a single interpreter against labels; return list of observations."""
    if interp.match_any_label_key is not None:
        captures_list = []
        for key in labels:
            m = interp.match_any_label_key.fullmatch(key)
            if m is None:
                continue
            captures_list.append(dict(m.groupdict()))
        if not captures_list:
            return []
        out = []
        for captures in captures_list:
            obs = _run_extract_and_emit(interp, labels, captures)
            if obs is not None:
                out.append(obs)
        return out

    # Fixed-key match flavor.
    value = labels.get(interp.match_label_key)
    if value is None:
        return []
    if interp.match_label_value_equals is not None:
        if str(value).strip().lower() != interp.match_label_value_equals.strip().lower():
            return []
    obs = _run_extract_and_emit(interp, labels, {})
    return [obs] if obs is not None else []


def _run_extract_and_emit(interp: Interpreter, labels: dict, captures: dict) -> Optional[dict]:
    """Run the extract step (using captures) and then the emit step."""
    local_vars: dict = {}
    for spec in interp.extract:
        try:
            label_key = _substitute(spec.from_label_template, captures)
        except KeyError as e:
            logger.debug(
                f"[interpreter:{interp.name}] extract.{spec.name}: capture {e} not available; "
                f"using default"
            )
            local_vars[spec.name] = spec.default
            continue
        raw_value = labels.get(label_key)
        local_vars[spec.name] = _resolve_extract_value(interp.name, spec, raw_value)
    return _build_emit(interp, local_vars)


def _resolve_extract_value(interp_name: str, spec: ExtractSpec, raw_value: Any) -> Any:
    """Apply value_pattern, coerce, and default for a single extract spec."""
    if raw_value is None:
        return spec.default
    value: Any = raw_value
    if spec.value_pattern is not None:
        m = spec.value_pattern.search(str(raw_value))
        if m is None:
            logger.debug(
                f"[interpreter:{interp_name}] extract.{spec.name}: value_pattern did not match "
                f"label value {raw_value!r}; using default"
            )
            return spec.default
        if spec.value_capture is not None:
            try:
                value = m.group(spec.value_capture)
            except IndexError as e:
                logger.warning(
                    f"[interpreter:{interp_name}] extract.{spec.name}: capture group "
                    f"{spec.value_capture!r} missing in match: {e}"
                )
                return spec.default
        else:
            value = m.group(0)
    if spec.coerce == "bool":
        value = str(value).strip().lower() in _TRUTHY
    elif spec.coerce == "int":
        try:
            value = int(value)
        except (TypeError, ValueError):
            logger.debug(
                f"[interpreter:{interp_name}] extract.{spec.name}: could not coerce "
                f"{value!r} to int; using default"
            )
            return spec.default
    return value


def _build_emit(interp: Interpreter, local_vars: dict) -> Optional[dict]:
    """Walk the emit dict recursively, substituting {name} from local_vars."""
    result = _substitute_value(interp.emit, local_vars, interp.name)
    if not isinstance(result, dict):
        logger.warning(
            f"[interpreter:{interp.name}] emit did not resolve to a mapping; skipping"
        )
        return None
    return result


def _substitute_value(value: Any, local_vars: dict, interp_name: str) -> Any:
    """
    Recursively walk a value from the emit section, substituting any
    `{var}` placeholders in string leaves against local_vars.

    Null propagation: if a string template contains a `{var}` whose
    value is None, the whole string field resolves to None.
    """
    if isinstance(value, dict):
        return {k: _substitute_value(v, local_vars, interp_name) for k, v in value.items()}
    if isinstance(value, list):
        return [_substitute_value(v, local_vars, interp_name) for v in value]
    if isinstance(value, str):
        return _substitute_string_leaf(value, local_vars, interp_name)
    return value


def _substitute_string_leaf(template: str, local_vars: dict, interp_name: str) -> Any:
    """
    Substitute {name} placeholders in a string.

    Special cases:
      - If the template is exactly `{name}` and `local_vars[name]` is
        not a string, return that value verbatim (preserves bools,
        ints, lists).
      - If any referenced var is None, the whole resolved value is None.
      - If a referenced var is missing from local_vars, log a debug
        message and treat as None (null propagation).
    """
    refs = list(_FIELD_NAME_RE.finditer(template))
    if not refs:
        return template

    # Bare-placeholder shortcut: '{x}' returns x verbatim (preserves type / null).
    if len(refs) == 1 and refs[0].group(0) == template:
        name = refs[0].group(1)
        if name not in local_vars:
            logger.debug(
                f"[interpreter:{interp_name}] emit template references unknown var {{{name}}}"
            )
            return None
        return local_vars[name]

    # Multi-placeholder / partial string. Substitute textually.
    # If any referenced var is None, the whole field becomes None.
    out_parts = []
    last = 0
    for m in refs:
        out_parts.append(template[last:m.start()])
        name = m.group(1)
        val = local_vars.get(name)
        if val is None:
            return None
        out_parts.append(str(val))
        last = m.end()
    out_parts.append(template[last:])
    return "".join(out_parts)


_FIELD_NAME_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _substitute(template: str, mapping: dict) -> str:
    """
    Substitute {name} placeholders in a label-key template (extract.from_label).

    Raises KeyError if a referenced name is missing — the caller falls
    back to the extract spec's default.
    """
    def repl(m):
        name = m.group(1)
        if name not in mapping:
            raise KeyError(name)
        val = mapping[name]
        if val is None:
            raise KeyError(name)
        return str(val)
    return _FIELD_NAME_RE.sub(repl, template)
