"""Locator chains for observed elements: durable candidates, verified unique (R1), and
cross-checked against Playwright's own selector generator (R4). No LLM involved — this is
the browser layer's compile-time contract with the explorer: given a `DomElement`, the chain
a compiled workflow can replay.
"""

import re

from netgent.browser.dom.models import DomElement
from netgent.schema.actions import LocatorStep

_VOLATILE_ID = re.compile(r"\d{4,}|[0-9a-f]{8,}|^#(tw|ember|react|:)")


def locator_candidates(el: DomElement) -> list[list[LocatorStep]]:
    """Every durable locator chain for an element, most durable first (pure, no browser round trip).

    Each chain is frame_locator steps for the iframe path, then the element. Preference
    order: a simple #id (precise and pierces open shadow DOM) → role WITH a real accessible
    name → test-id → label → any css path. A role locator with no name is skipped: it comes
    from a placeholder-only field, which Playwright's role-name matching won't match. Ids
    that look machine-generated (long digit/hex runs, tw-/ember-/react- prefixes) are
    skipped: they change every session, so a compiled workflow could never replay them.
    """
    chain = [LocatorStep(fn="frame_locator", args=[sel]) for sel in el.frame_path]
    cands = el.candidates
    out: list[list[LocatorStep]] = []

    def css(value: str) -> list[LocatorStep]:
        return chain + [LocatorStep(fn="locator", args=[value])]

    # 1. simple, stable-looking #id — precise, and Playwright's css engine pierces open shadow roots
    for c in cands:
        if (
            c.kind == "css"
            and c.value
            and c.value.startswith("#")
            and " " not in c.value
            and not _VOLATILE_ID.search(c.value)
        ):
            out.append(css(c.value))
    # 2. role with a genuine accessible name (skip <select>: its name is an option dump)
    if el.tag != "select":
        for c in cands:
            if c.kind == "role" and c.role and c.name:
                out.append(chain + [LocatorStep(fn="get_by_role", args=[c.role], kwargs={"name": c.name})])
    # 3. test-id, 4. label
    for c in cands:
        if c.kind == "test_id" and c.value:
            out.append(chain + [LocatorStep(fn="get_by_test_id", args=[c.value])])
        if c.kind == "label" and c.value:
            out.append(chain + [LocatorStep(fn="get_by_label", args=[c.value])])
    # 5. any css path
    for c in cands:
        if c.kind == "css" and c.value and css(c.value) not in out:
            out.append(css(c.value))
    if not out:
        raise ValueError(f"element {el.name!r} has no usable candidate selector")
    return out


def durable_locator(el: DomElement) -> list[LocatorStep]:
    """The most durable candidate chain, unverified (pure). Prefer `unique_locator_for`."""
    return locator_candidates(el)[0]


async def unique_locator_for(session, el: DomElement) -> list[LocatorStep]:
    """The most durable candidate chain that resolves to EXACTLY one element right now.

    Playwright's css engine pierces open shadow roots, so an `#id` inside a web component
    repeats once per component instance: `#email` resolves to 2 elements and `fill` would
    fail with a strict-mode violation — at replay time, in a compiled workflow. This is
    Skyvern's `count() == 1` discipline (`skyvern/webeye/utils/dom.py`, which raises
    MultipleElementsFound rather than taking `.first`) moved to compile time: try each
    candidate in durability order and take the first unique one; if every candidate is
    ambiguous, disambiguate the most durable ambiguous one with an already-whitelisted
    `nth` step, choosing the match whose box is the observed element's. If nothing resolves
    at all (the element vanished), return the unverified chain so dispatch fails loudly.
    """
    ambiguous: list[LocatorStep] | None = None
    candidates = locator_candidates(el)
    for chain in candidates:
        try:
            n = await session.count(chain)
        except Exception:  # noqa: BLE001 — an unresolvable candidate is skipped, not fatal
            continue
        if n == 1:
            return chain
        if n > 1 and ambiguous is None:
            ambiguous = chain
    if ambiguous is None:
        return candidates[0]
    index = await session.match_index(ambiguous, el.bbox.x, el.bbox.y)
    return ambiguous + [LocatorStep(fn="nth", args=[index])]


async def capture_locator(session, el: DomElement) -> tuple[list[LocatorStep], str]:
    """The chain to store for an element, cross-checked against Playwright's generator (R4).

    1. `unique_locator_for` gives our verified-unique chain (never worse than before).
    2. `Locator.normalize()` gives Playwright's frame-aware, shadow-aware selector for the
       same element; `chain_from_normalized` maps it into our whitelist — totally, or not
       at all (an unmappable part is a recorded compile-time note, never stored raw).
    3. If both resolve to the same element: Playwright's frame steps (`iframe[name=…]`,
       `#id`) replace our nth-of-type paths unless they needed an `nth`; and if ours had to be
       disambiguated with `nth` while Playwright's is unique on its own, take Playwright's
       whole chain — a semantically keyed locator beats css+index.
    Returns (chain, note) — the note is what the trajectory records.
    """
    from netgent.browser.normalized import UnmappableSelector, chain_from_normalized, frame_steps

    ours = await unique_locator_for(session, el)
    try:
        raw = await session.normalize(ours)
    except Exception as exc:  # noqa: BLE001 — element gone / not normalizable: keep ours
        return ours, f"normalize unavailable: {str(exc).splitlines()[0]}"
    try:
        theirs = chain_from_normalized(raw)
    except UnmappableSelector as exc:
        return ours, f"normalize unmappable ({exc}); kept ours"
    if not await session.same_element(ours, theirs):
        return ours, "normalize disagreed; kept ours"
    if ours[-1].fn == "nth" and theirs[-1].fn != "nth" and await session.count(theirs) == 1:
        return theirs, "normalize agreed; took Playwright's unique chain over css+nth"
    our_frames, their_frames = frame_steps(ours), frame_steps(theirs)
    if our_frames != their_frames and not any(step.fn == "nth" for step in their_frames):
        merged = their_frames + ours[len(our_frames):]
        if await session.count(merged) == 1:
            return merged, "normalize agreed; took Playwright's frame selectors"
    return ours, "normalize agreed"
