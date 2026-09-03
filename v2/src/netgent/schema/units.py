"""One numeric coercion for every place a param feeds a NUMBER: a Repeat count, a derived
param's source, a replay value set. Accepts what a user (or the planner's task text) writes for
a duration — '30', '30.0', '30s', '30 s', '30sec', '30 seconds', '1m', '1 min', '1h' — and returns
the number in SECONDS-or-count units (minutes/hours scaled; a bare number is taken as is).
Zero LLM, pure code. Rejects anything without a leading number."""

import re

_NUM = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([a-zA-Z]*)\s*$")
_SCALE = {
    "": 1.0, "s": 1.0, "sec": 1.0, "secs": 1.0, "second": 1.0, "seconds": 1.0,
    "m": 60.0, "min": 60.0, "mins": 60.0, "minute": 60.0, "minutes": 60.0,
    "h": 3600.0, "hr": 3600.0, "hrs": 3600.0, "hour": 3600.0, "hours": 3600.0,
    "x": 1.0, "times": 1.0, "presses": 1.0, "press": 1.0,
}

UNIT_NOTE = "accepts a number with an optional unit (15, 15s, 1m)"


def coerce_number(value: object) -> float | None:
    """The number `value` carries, with its unit scaled to seconds/count — or None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    m = _NUM.match(str(value))
    if m is None:
        return None
    scale = _SCALE.get(m.group(2).lower())
    if scale is None:
        return None
    return float(m.group(1)) * scale


def number_text(value: object) -> str | None:
    """`coerce_number` rendered as the bare number a Repeat count / dwell param carries ('30', '2.5')."""
    n = coerce_number(value)
    if n is None:
        return None
    return str(int(n)) if n == int(n) else str(n)
