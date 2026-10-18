"""Arc-light JSON-schema validation for tool arguments (EM-404 ``em/util``).

The provider's tool surface is defined by Appendix B's schemas, and §4.4 is
explicit about what happens to every argument that goes through them:

* **types, enums: hard errors.** A wrong value cannot be guessed at, so the
  call fails with a message that names the argument, the expected shape and
  what actually arrived — the model reads it and fixes the call.
* **``maxLength`` and ``maxItems``: capping.** Over-long strings are truncated
  and trailing items dropped, each with a warning in the response (§4.4's
  "string args are length-capped"). **One deliberate exception (chunk 38):** a
  caller may name properties in ``fatal_length_keys``, for which an over-long
  value **raises** instead of clamping — the tool layer does this for a memory's
  own ``content``, because a truncated fact is silently and permanently
  indistinguishable from a complete one. The default call has an empty set, so
  nothing else changes.
* **numeric bounds: clamping.** ``limit: 99`` becomes 25 with a warning;
  ``importance: 1.4`` becomes 1.0.
* **unknown arguments: ignored, never fatal** — the projection keeps the
  schema's property set and the response carries a warning.
* ``None`` reads as "not provided" (a JSON null from the model is an absence,
  not a value), so it never fails a type check or a ``required`` list.

This is deliberately a *subset* of JSON Schema — the keywords the nine schemas
use and nothing else. It is standard library only, like the rest of ``em``, and
it knows nothing about tools, providers or the host.

Warnings are the strings the tool response carries under ``"warnings"``; the
first hard error raises :class:`ArgumentError` and validation stops there,
because fixing one argument at a time is how a model actually recovers.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

__all__ = ["ArgumentError", "validate_arguments"]


class ArgumentError(ValueError):
    """A tool call whose arguments cannot be validated into a usable shape.

    ``field`` names the offending argument (``"limit"``, ``"sources[1]"``) when
    one is to blame; it is empty for whole-payload errors.
    """

    def __init__(self, message: str, *, field: str = "") -> None:
        super().__init__(message)
        self.field = field


def _type_name(value: Any) -> str:
    """The JSON-side name of a Python value, for error messages."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, (list, tuple)):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def _is_type(value: Any, expected: str) -> bool:
    """True when ``value`` satisfies the schema type ``expected``.

    Booleans are excluded from ``integer``/``number`` on purpose: ``True`` is
    an ``int`` in Python, and a schema that says "integer" should never accept
    it (nor a float where an integer is required).
    """
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "array":
        return isinstance(value, list)
    if expected == "object":
        return isinstance(value, dict)
    return True


def _short_repr(value: Any, limit: int = 80) -> str:
    """``repr`` capped so a pathological argument cannot flood the message."""
    text = repr(value)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _enum_message(path: str, value: Any, choices: List[Any]) -> str:
    allowed = ", ".join(str(choice) for choice in choices)
    return f"`{path}` must be one of: {allowed}; got {_short_repr(value)}"


def _validate_value(
    path: str,
    value: Any,
    spec: Dict[str, Any],
    warnings: List[str],
    fatal_length_keys: Any = frozenset(),
) -> Any:
    """Validate one value against one property spec; return the cleaned value.

    Mutates ``warnings`` in place (caps and clamps are warnings, not errors).
    A key named in ``fatal_length_keys`` is the exception: over-long input
    **raises** rather than clamping, because a truncated value that is then
    persisted is silent data loss — a clipped fact reads exactly like a
    complete one, forever (chunk 38).
    """
    expected = spec.get("type")
    if expected is not None and not _is_type(value, expected):
        raise ArgumentError(
            f"`{path}` must be a {expected}, got {_type_name(value)} ({_short_repr(value)})",
            field=path,
        )

    if "enum" in spec and value not in spec["enum"]:
        raise ArgumentError(_enum_message(path, value, spec["enum"]), field=path)

    if expected == "string" and "maxLength" in spec and len(value) > spec["maxLength"]:
        limit = spec["maxLength"]
        if path in fatal_length_keys:
            raise ArgumentError(
                f"`{path}` must be at most {limit} characters, got {len(value)}",
                field=path,
            )
        warnings.append(f"`{path}` truncated to {limit} characters (maxLength {limit})")
        value = value[:limit]

    if expected == "array":
        items = spec.get("items")
        if isinstance(items, dict):
            max_items = spec.get("maxItems")
            if isinstance(max_items, int) and len(value) > max_items:
                warnings.append(f"`{path}` truncated to {max_items} items (maxItems {max_items})")
                value = value[:max_items]
            value = [
                _validate_value(
                    f"{path}[{index}]", item, items, warnings, fatal_length_keys
                )
                for index, item in enumerate(value)
            ]

    if expected in ("integer", "number"):
        minimum = spec.get("minimum")
        maximum = spec.get("maximum")
        if isinstance(minimum, (int, float)) and value < minimum:
            warnings.append(f"`{path}` clamped to {minimum} (minimum {minimum})")
            value = minimum
        if isinstance(maximum, (int, float)) and value > maximum:
            warnings.append(f"`{path}` clamped to {maximum} (maximum {maximum})")
            value = maximum

    return value


def validate_arguments(
    tool_schema: Dict[str, Any],
    arguments: Any,
    *,
    fatal_length_keys: Any = frozenset(),
) -> Tuple[Dict[str, Any], List[str]]:
    """Validate ``arguments`` against a tool schema's ``parameters``.

    Returns ``(cleaned, warnings)`` where ``cleaned`` carries only the schema's
    known properties (unknown ones are dropped with a warning, as are values
    that needed capping or clamping). Raises :class:`ArgumentError` when the
    arguments are not an object, a required property is missing, a value cannot
    be coerced (wrong type, value outside an enum, a non-array where an array
    is required), and returns the error message a model can act on.

    ``fatal_length_keys`` names properties whose ``maxLength`` is a **hard
    error** instead of a clamp (chunk 38): the default empty set keeps every
    existing caller byte-identical, so only a caller that opts in — the tool
    layer, for a memory's own ``content`` — turns an over-long value into a
    refusal rather than a silent truncation.
    """
    parameters = tool_schema.get("parameters", {}) if isinstance(tool_schema, dict) else {}
    properties: Dict[str, Any] = parameters.get("properties", {}) or {}
    required: List[str] = list(parameters.get("required", []) or [])

    if not isinstance(arguments, dict):
        raise ArgumentError(
            f"arguments must be an object, got {_type_name(arguments)} ({_short_repr(arguments)})"
        )

    provided = {key: value for key, value in arguments.items() if value is not None}
    missing = [name for name in required if name not in provided]
    if missing:
        missing_help = ", ".join(
            f"`{name}` ({properties.get(name, {}).get('type', 'value')})" for name in missing
        )
        raise ArgumentError(
            f"missing required argument{'s' if len(missing) > 1 else ''}: {missing_help}",
            field=missing[0],
        )

    cleaned: Dict[str, Any] = {}
    warnings: List[str] = []
    for key, value in provided.items():
        spec = properties.get(key)
        if spec is None:
            warnings.append(f"unrecognized argument `{key}` (ignored)")
            continue
        cleaned[key] = _validate_value(key, value, spec, warnings, fatal_length_keys)
    return cleaned, warnings
