"""Playwright's `Locator.normalize()` output → OUR whitelisted locator chain (R4).

`Frame.resolveSelector` (playwright-core `server/frames.ts:1312-1339`) resolves a locator to
one element, generates a selector for it (`injected/selectorGenerator.ts`, which prefers
test-id → role+name → placeholder → label → alt → text → title → css and climbs through open
shadow hosts), then walks `parentFrame()` generating one selector per <iframe> and joins them
with `>> internal:control=enter-frame >>`. The client hands the raw string back unchanged
(`client/locator.ts:274-278`). Measured shape for a shadow-DOM button in a cross-origin iframe:

    iframe[name="payframe"] >> internal:control=enter-frame >> internal:role=button[name="Deep"i]

That is exactly a NetGent chain — but in Playwright's private `internal:` engine syntax, which
must never reach an artifact. This module is the TOTAL inverse into our whitelist, mirroring the
official one (`isomorphic/locatorGenerators.ts:86-267`, `asLocator` → `get_by_role(...)`):
every part maps to a whitelisted step or the whole conversion fails with `UnmappableSelector`.
Nothing is ever stored raw.

Quoting rules (from `isomorphic/stringUtils.ts:110-124`): text-style values (`internal:text=`,
`internal:label=`, `internal:has-text=`) are a full JSON string + `i`/`s`; attribute-style
values (`[name="…"i]`) escape only `\\` and `"` and are decoded by dropping backslashes
(`selectorParser.ts:314-327`) — NOT json.loads. `s` = exact, `i` = case-insensitive substring.
"""

import json
import re

from netgent.schema.actions import LocatorStep

ENTER_FRAME = "internal:control=enter-frame"
_ENGINE_RE = re.compile(r"^([a-zA-Z_0-9\-+:*]+)=(.*)$", re.DOTALL)
# get_by_role option keys the generator can emit (locatorUtils.ts:69-89), selector → kwarg.
_ROLE_OPTIONS = {
    "name": "name",
    "description": "description",
    "checked": "checked",
    "disabled": "disabled",
    "selected": "selected",
    "expanded": "expanded",
    "pressed": "pressed",
    "level": "level",
    "include-hidden": "include_hidden",
}
_ATTR_GETTERS = {"placeholder": "get_by_placeholder", "alt": "get_by_alt_text", "title": "get_by_title"}


class UnmappableSelector(ValueError):
    """A normalized selector part has no whitelisted equivalent — a compile-time failure."""


def split_parts(selector: str) -> list[str]:
    """Split on `>>` outside quotes (selectorParser.ts:180-255 tracks ", ', ` and backslashes)."""
    parts: list[str] = []
    buf: list[str] = []
    quote: str | None = None
    i = 0
    while i < len(selector):
        ch = selector[i]
        if quote:
            buf.append(ch)
            if ch == "\\" and i + 1 < len(selector):
                buf.append(selector[i + 1])
                i += 1
            elif ch == quote:
                quote = None
        elif ch in ('"', "'", "`"):
            quote = ch
            buf.append(ch)
        elif selector.startswith(">>", i):
            parts.append("".join(buf).strip())
            buf = []
            i += 1
        else:
            buf.append(ch)
        i += 1
    parts.append("".join(buf).strip())
    return [p for p in parts if p]


def _decode_text(value: str) -> tuple[str, bool]:
    """`"foo"i` / `"foo"s` / `"foo"` (JSON string + flag) → (text, exact). Regex → unmappable."""
    if value.startswith("/"):
        raise UnmappableSelector(f"regex text selector {value!r}")
    exact = True
    if value.endswith('"s'):
        value, exact = value[:-1], True
    elif value.endswith('"i'):
        value, exact = value[:-1], False
    try:
        return json.loads(value), exact
    except json.JSONDecodeError as exc:
        raise UnmappableSelector(f"unreadable text value {value!r}") from exc


def _parse_attributes(body: str) -> tuple[str, list[tuple[str, str | int | float | bool, bool]]]:
    """`role[name="x"i][level=2][checked]` → ("role", [(key, value, exact), …])."""
    m = re.match(r"^([^\[\]]*)", body)
    head = m.group(1).strip() if m else ""
    rest = body[len(head):]
    attrs: list[tuple[str, str | int | float | bool, bool]] = []
    pos = 0
    while pos < len(rest):
        if rest[pos] != "[":
            raise UnmappableSelector(f"unexpected {rest[pos:]!r} in attribute selector")
        pos += 1
        m = re.match(r"\s*([\w\-]+)\s*", rest[pos:])
        if not m:
            raise UnmappableSelector(f"bad attribute name in {body!r}")
        key = m.group(1)
        pos += m.end()
        if rest[pos] == "]":  # truthy form `[checked]`
            attrs.append((key, True, True))
            pos += 1
            continue
        if rest[pos] != "=":
            raise UnmappableSelector(f"unsupported attribute operator in {body!r}")
        pos += 1
        if rest[pos] == '"':
            j = pos + 1
            chars: list[str] = []
            while j < len(rest) and rest[j] != '"':
                if rest[j] == "\\" and j + 1 < len(rest):
                    j += 1
                chars.append(rest[j])
                j += 1
            if j >= len(rest):
                raise UnmappableSelector(f"unterminated quoted value in {body!r}")
            j += 1  # closing quote
            exact = True
            if j < len(rest) and rest[j] in "sSiI":
                exact = rest[j] in "sS"
                j += 1
            attrs.append((key, "".join(chars), exact))
            pos = j
        elif rest[pos] == "/":
            raise UnmappableSelector(f"regex attribute value in {body!r}")
        else:
            m = re.match(r"([^\]]*)", rest[pos:])
            raw = m.group(1).strip()
            pos += m.end()
            value: str | int | float | bool
            if raw in ("true", "false"):
                value = raw == "true"
            else:
                try:
                    value = int(raw)
                except ValueError:
                    try:
                        value = float(raw)
                    except ValueError:
                        value = raw
            attrs.append((key, value, True))
        m = re.match(r"\s*\]", rest[pos:])
        if not m:
            raise UnmappableSelector(f"unterminated attribute in {body!r}")
        pos += m.end()
    return head, attrs


def _element_step(part: str) -> LocatorStep:
    """One non-frame part → one whitelisted step, or UnmappableSelector."""
    m = _ENGINE_RE.match(part)
    if not m:  # unprefixed = css (joinTokens emits css without an engine prefix)
        return LocatorStep(fn="locator", args=[part])
    engine, body = m.group(1), m.group(2)
    if engine == "nth":
        return LocatorStep(fn="nth", args=[int(body)])
    if engine == "internal:role":
        role, attrs = _parse_attributes(body)
        kwargs: dict[str, str | int | float | bool] = {}
        for key, value, exact in attrs:
            kwarg = _ROLE_OPTIONS.get(key)
            if kwarg is None:
                raise UnmappableSelector(f"unknown role option {key!r} in {part!r}")
            if key in ("name", "description"):
                if exact:
                    kwargs["exact"] = True
            elif key == "level":
                value = int(value)
            kwargs[kwarg] = value
        return LocatorStep(fn="get_by_role", args=[role], kwargs=kwargs)
    if engine == "internal:testid":
        _, attrs = _parse_attributes(body)
        if len(attrs) != 1:
            raise UnmappableSelector(f"bad test-id selector {part!r}")
        key, value, _ = attrs[0]
        if key == "data-testid":
            return LocatorStep(fn="get_by_test_id", args=[str(value)])
        return LocatorStep(fn="locator", args=[f'[{key}="{value}"]'])  # non-default test-id attribute
    if engine in ("internal:text", "internal:label"):
        text, exact = _decode_text(body)
        fn = "get_by_text" if engine == "internal:text" else "get_by_label"
        return LocatorStep(fn=fn, args=[text], kwargs={"exact": True} if exact else {})
    if engine == "internal:attr":
        _, attrs = _parse_attributes(body)
        if len(attrs) != 1:
            raise UnmappableSelector(f"bad attribute selector {part!r}")
        key, value, exact = attrs[0]
        getter = _ATTR_GETTERS.get(key)
        if getter is None:
            raise UnmappableSelector(f"attribute {key!r} has no get_by_* equivalent ({part!r})")
        return LocatorStep(fn=getter, args=[str(value)], kwargs={"exact": True} if exact else {})
    if engine in ("internal:has-text", "internal:has-not-text"):
        text, exact = _decode_text(body)
        if exact:
            raise UnmappableSelector(f"exact has-text has no filter() equivalent ({part!r})")
        key = "has_text" if engine == "internal:has-text" else "has_not_text"
        return LocatorStep(fn="filter", kwargs={key: text})
    if engine == "visible":
        return LocatorStep(fn="filter", kwargs={"visible": body == "true"})
    raise UnmappableSelector(f"selector engine {engine!r} is not in the replay whitelist ({part!r})")


def chain_from_normalized(selector: str) -> list[LocatorStep]:
    """Playwright's normalized selector → our chain: frame_locator steps (with nth where the
    generator disambiguated an <iframe>), then the element steps. Total: raises
    UnmappableSelector for anything without a whitelisted equivalent."""
    parts = split_parts(selector)
    if not parts:
        raise UnmappableSelector("empty selector")
    chain: list[LocatorStep] = []
    group: list[str] = []
    for part in parts:
        if part == ENTER_FRAME:
            if not group:
                raise UnmappableSelector("enter-frame with no frame selector")
            head, *tail = group
            if _ENGINE_RE.match(head) and not head.startswith("css="):
                raise UnmappableSelector(f"frame selector {head!r} is not css")
            chain.append(LocatorStep(fn="frame_locator", args=[head.removeprefix("css=")]))
            for extra in tail:
                step = _element_step(extra)
                if step.fn != "nth":
                    raise UnmappableSelector(f"unexpected {extra!r} in a frame selector")
                chain.append(step)
            group = []
        else:
            group.append(part)
    if not group:
        raise UnmappableSelector("selector ends inside a frame (no element part)")
    chain.extend(_element_step(p) for p in group)
    return chain


def frame_steps(chain: list[LocatorStep]) -> list[LocatorStep]:
    """The leading frame_locator (+ nth) prefix of a chain."""
    out: list[LocatorStep] = []
    for step in chain:
        if step.fn == "frame_locator" or (step.fn == "nth" and out and out[-1].fn == "frame_locator"):
            out.append(step)
        else:
            break
    return out
