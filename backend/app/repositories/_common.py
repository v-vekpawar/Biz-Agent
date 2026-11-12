"""Shared repository helpers."""

from enum import Enum
from typing import Any


def coerce_enum(value: Any, enum_cls: type[Enum], field: str) -> Enum:
    """Convert a raw string (or enum instance) into a domain enum, raising a
    descriptive ValueError for unknown values. This is the guard that keeps
    malformed statuses out of the database."""
    if isinstance(value, enum_cls):
        return value
    try:
        return enum_cls(str(value))
    except ValueError as exc:
        valid = ", ".join(m.value for m in enum_cls)
        raise ValueError(f"{field} must be one of: {valid} (got: {value!r})") from exc
