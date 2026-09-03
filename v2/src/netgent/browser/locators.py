"""Locator chains for observed elements: durable candidates, verified unique (R1), and
cross-checked against Playwright's own selector generator (R4). No LLM involved — this is
the browser layer's compile-time contract with the explorer: given a `DomElement`, the chain
a compiled workflow can replay.
"""

import re
from dataclasses import dataclass, field

from netgent.browser.dom.models import DomElement
from netgent.schema.actions import LocatorStep

# Machine-generated id signals: long digit/hex runs, framework prefixes, a colon anywhere
# (React useId `:r1:`, YouTube's per-mount `skip-button:2` — the CSS-escaped form carries a
# backslash), or a trailing counter. Such ids change per session/instance, so a compiled
# workflow could never replay them (measured: an ad-skip interrupt anchored on
# `#skip-button\:2` never fired on the next replay's ad, whose button had a fresh suffix).
_VOLATILE_ID = re.compile(r"\d{4,}|[0-9a-f]{8,}|^#(tw|ember|react)|[:\\]|[-_]?\d+$")
# Framework-generated ids that change per render (Skyvern's `_FRAGILE_ID_PATTERNS`,
# script_reviewer_v3/skills/validate.py): Ember, react-select, React's legacy data-reactid,
# DotNetNuke. Anywhere in a selector, not only as a leading #id.
_FRAGILE_ID_PATTERNS = re.compile(r"#ember-?\d+|#react-select-\d+|\[data-reactid\]|#dnn_\w+", re.IGNORECASE)


def is_volatile_selector(selector: str) -> bool:
    """True when a selector carries an id that looks machine-generated (per-session/mount/render).

    The compiler uses this to warn when an interrupt gets anchored on one: an interrupt
    exists to fire on a FUTURE instance of its overlay, which a per-mount id can never match.
    """
    if _FRAGILE_ID_PATTERNS.search(selector) is not None:
        return True
    return selector.startswith("#") and _VOLATILE_ID.search(selector) is not None


def ladder(el: DomElement) -> list[tuple[str, list[LocatorStep]]]:
    """Every durable locator chain for an element as (kind, chain), most durable first (pure).

    Each chain is frame_locator steps for the iframe path, then the element. Preference
    order: a simple #id (precise and pierces open shadow DOM) → role WITH a real accessible
    name → test-id → label → any css path → the STRUCTURAL rung (a css path anchored at the
    nearest repeated container, kind "structural": it matches every list item's counterpart,
    so it is the positional anchor — `nth(i)` picks by position — and it comes last so it
    never wins the durability ladder on its own). A role locator with no name is skipped: it
    comes from a placeholder-only field, which Playwright's role-name matching won't match.
    Ids that look machine-generated (long digit/hex runs, tw-/ember-/react- prefixes) are
    skipped: they change every session, so a compiled workflow could never replay them.
    """
    chain = [LocatorStep(fn="frame_locator", args=[sel]) for sel in el.frame_path]
    cands = el.candidates
    out: list[tuple[str, list[LocatorStep]]] = []

    def css(value: str) -> list[LocatorStep]:
        return chain + [LocatorStep(fn="locator", args=[value])]

    def add(kind: str, steps: list[LocatorStep]) -> None:
        if all(steps != c for _, c in out):
            out.append((kind, steps))

    # 1. simple, stable-looking #id — precise, and Playwright's css engine pierces open shadow roots
    for c in cands:
        if (
            c.kind == "css"
            and c.value
            and c.value.startswith("#")
            and " " not in c.value
            and not _VOLATILE_ID.search(c.value)
        ):
            add("id", css(c.value))
    # 2. role with a genuine accessible name (skip <select>: its name is an option dump)
    if el.tag != "select":
        for c in cands:
            if c.kind == "role" and c.role and c.name:
                add("role", chain + [LocatorStep(fn="get_by_role", args=[c.role], kwargs={"name": c.name})])
    # 3. test-id, 4. label
    for c in cands:
        if c.kind == "test_id" and c.value:
            add("test_id", chain + [LocatorStep(fn="get_by_test_id", args=[c.value])])
        if c.kind == "label" and c.value:
            add("label", chain + [LocatorStep(fn="get_by_label", args=[c.value])])
    # 5. any css path
    for c in cands:
        if c.kind == "css" and c.value:
            add("css", css(c.value))
    # 6. the structural (positional) rung — last, and only ever chosen with an nth
    for c in cands:
        if c.kind == "structural" and c.value:
            add("structural", css(c.value))
    if not out:
        raise ValueError(f"element {el.name!r} has no usable candidate selector")
    return out


def locator_candidates(el: DomElement) -> list[list[LocatorStep]]:
    """Every durable locator chain for an element, most durable first (pure). See `ladder`."""
    return [chain for _, chain in ladder(el)]


MATCH_INDEX_LIMIT = 50  # match_index inspects up to this many boxes — bounds the capture cost


@dataclass
class LadderProbe:
    """The candidate ladder as the live page resolved it at capture time — compile-time
    provenance recorded on the AgentStep, so a later compile can pick a DIFFERENT rung
    (the positional one) and check it offline, without re-exploring.

    `counts[k]` is how many elements rung k resolved to (-1: could not be resolved);
    `indices[k]` is the acted element's position among those matches, computed only where
    it is cheap and useful: the first ambiguous rung (what `unique_locator_for` needs for
    its `nth`) and the structural rung (what a positional generalization needs).
    """

    chains: list[list[LocatorStep]] = field(default_factory=list)
    kinds: list[str] = field(default_factory=list)
    counts: list[int] = field(default_factory=list)
    indices: list[int | None] = field(default_factory=list)

    def rung(self, kind: str) -> int | None:
        return next((k for k, kd in enumerate(self.kinds) if kd == kind), None)


async def probe_ladder(session, el: DomElement) -> LadderProbe:
    """Count every rung of `ladder(el)` against the live page, and locate the acted element
    among the matches of the first ambiguous rung and of the structural rung."""
    rungs = ladder(el)
    probe = LadderProbe(chains=[c for _, c in rungs], kinds=[k for k, _ in rungs])
    for chain in probe.chains:
        try:
            probe.counts.append(await session.count(chain))
        except Exception:  # noqa: BLE001 — an unresolvable candidate is skipped, not fatal
            probe.counts.append(-1)
    probe.indices = [None] * len(probe.chains)
    first_ambiguous = next((k for k, n in enumerate(probe.counts) if n > 1), None)
    structural = probe.rung("structural")
    for k in {first_ambiguous, structural} - {None}:
        if 1 < probe.counts[k] <= MATCH_INDEX_LIMIT or (k == first_ambiguous and probe.counts[k] > 1):
            try:
                probe.indices[k] = await session.match_index(probe.chains[k], el.bbox.x, el.bbox.y)
            except Exception:  # noqa: BLE001 — leave the index unknown
                probe.indices[k] = None
    return probe


def durable_locator(el: DomElement) -> list[LocatorStep]:
    """The most durable candidate chain, unverified (pure). Prefer `unique_locator_for`."""
    return locator_candidates(el)[0]


async def unique_locator_for(session, el: DomElement, probe: LadderProbe | None = None) -> list[LocatorStep]:
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
    `probe` (from `probe_ladder`) supplies the counts when the caller already has them.
    """
    probe = probe if probe is not None else await probe_ladder(session, el)
    for chain, n in zip(probe.chains, probe.counts, strict=True):
        if n == 1:
            return chain
    ambiguous = next((k for k, n in enumerate(probe.counts) if n > 1), None)
    if ambiguous is None:
        return probe.chains[0]
    index = probe.indices[ambiguous]
    if index is None:
        index = await session.match_index(probe.chains[ambiguous], el.bbox.x, el.bbox.y)
    return probe.chains[ambiguous] + [LocatorStep(fn="nth", args=[index])]


async def capture_locator(session, el: DomElement) -> tuple[list[LocatorStep], str]:
    """The chain to store for an element, cross-checked against Playwright's generator (R4).
    See `capture_ladder`, which also returns the probed ladder the explorer records."""
    chain, note, _probe = await capture_ladder(session, el)
    return chain, note


async def capture_ladder(session, el: DomElement) -> tuple[list[LocatorStep], str, LadderProbe]:
    """The chain to store for an element, cross-checked against Playwright's generator (R4),
    plus the probed candidate ladder (M0: the record keeps every rung, not just the winner).

    1. `unique_locator_for` gives our verified-unique chain (never worse than before).
    2. `Locator.normalize()` gives Playwright's frame-aware, shadow-aware selector for the
       same element; `chain_from_normalized` maps it into our whitelist — totally, or not
       at all (an unmappable part is a recorded compile-time note, never stored raw).
    3. If both resolve to the same element: Playwright's frame steps (`iframe[name=…]`,
       `#id`) replace our nth-of-type paths unless they needed an `nth`; and if ours had to be
       disambiguated with `nth` while Playwright's is unique on its own, take Playwright's
       whole chain — a semantically keyed locator beats css+index.
    Returns (chain, note, probe) — the note is what the trajectory records.
    """
    from netgent.browser.normalized import UnmappableSelector, chain_from_normalized, frame_steps

    probe = await probe_ladder(session, el)
    ours = await unique_locator_for(session, el, probe)
    try:
        raw = await session.normalize(ours)
    except Exception as exc:  # noqa: BLE001 — element gone / not normalizable: keep ours
        return ours, f"normalize unavailable: {str(exc).splitlines()[0]}", probe
    try:
        theirs = chain_from_normalized(raw)
    except UnmappableSelector as exc:
        return ours, f"normalize unmappable ({exc}); kept ours", probe
    if not await session.same_element(ours, theirs):
        return ours, "normalize disagreed; kept ours", probe
    if ours[-1].fn == "nth" and theirs[-1].fn != "nth" and await session.count(theirs) == 1:
        return theirs, "normalize agreed; took Playwright's unique chain over css+nth", probe
    our_frames, their_frames = frame_steps(ours), frame_steps(theirs)
    if our_frames != their_frames and not any(step.fn == "nth" for step in their_frames):
        merged = their_frames + ours[len(our_frames):]
        if await session.count(merged) == 1:
            return merged, "normalize agreed; took Playwright's frame selectors", probe
    return ours, "normalize agreed", probe
