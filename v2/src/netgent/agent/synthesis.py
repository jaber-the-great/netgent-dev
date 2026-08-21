"""Synthesis: consolidate several exploration trajectories into ONE replayable workflow.

`netgent generate` runs the agent N times (fresh sessions, optionally with different
sample values for the declared params). Each run is one witness of how the task goes.
Synthesis is a pure, deterministic function over those witnesses — no LLM, no network:

1. **Abstract** every run: sample param values → ${name} in actions, URLs, evidence.
2. **Minimize** each run: drop steps no outcome depended on (a click on a field that is
   filled next; consecutive identical fills; a scroll that changed no evidence).
3. **Align** the runs' action sequences (longest common subsequence over action keys).
   Actions in every successful run form the **core path**.
4. **Optional steps** — present in only some runs (a cookie wall's "Proceed") — become a
   guarded `Branch` at the state where they occurred: an arm whose guard is the visibility
   of the step's own target (ε-transition into the interstitial state, then the resolving
   click), and an ε-arm (`noop`) for when it is absent. Nothing is speculated: only
   observed variation is recorded, and the branch is statically bounded.
5. **Conditions** for each core state come from evidence that agrees across runs: the
   (query-stripped) URL when the step navigated, `element_visible` for the next edge's
   target, `video_playing` / a `video` element on watch pages, and a text that newly
   appeared in every run. Conditions are declarative triggers — never code.

Prior art for "synthesize a reusable, guarded workflow from several agent attempts" is
ReUseIt (arXiv:2510.14308); here the result is NetGent's NFA: states carry conditions,
transitions carry exactly one atomic action from the closed set.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from urllib.parse import quote_plus

from pydantic import TypeAdapter

from netgent.agent.browser_agent import AgentTrajectory
from netgent.agent.evidence import PageEvidence, locator_of
from netgent.schema.actions import Action, NoopAction, ScrollAction
from netgent.schema.control import Branch, BranchArm, ControlNode, EdgeStep, Param
from netgent.schema.triggers import ElementVisible, SelectorVisible, TextVisible, Trigger, UrlMatches, VideoPlaying
from netgent.schema.workflow import State, Transition, Workflow

BRANCH_PROBE_MS = 3000  # how long a replay watches for an optional interstitial before taking the ε-arm
TEXT_MIN, TEXT_MAX = 3, 80
_PLACEHOLDER = re.compile(r"\$\{\w+\}")


# ── inputs ────────────────────────────────────────────────────────────────────────────


@dataclass
class Exploration:
    """One agent run plus the sample param values it explored with."""

    trajectory: AgentTrajectory
    params: dict[str, str] = field(default_factory=dict)


@dataclass
class Synthesis:
    workflow: Workflow
    notes: list[str]  # human-readable synthesis decisions (go into provenance.notes)


# ── param abstraction ─────────────────────────────────────────────────────────────────


def abstract_params(node: object, params: dict[str, str]) -> object:
    """Replace every sample value (literal and URL-encoded, case-insensitive) with ${name}
    throughout a JSON-like tree. Longest values first so overlapping samples substitute
    correctly. Case-insensitive because sites render "monstercat" as "Monstercat" in link
    names, and Playwright's role-name matching is itself case-insensitive."""
    if not params:
        return node
    if isinstance(node, str):
        for pname, value in sorted(params.items(), key=lambda kv: -len(kv[1])):
            if not value:
                continue
            for form in (value, quote_plus(value)):
                node = re.sub(re.escape(form), "${" + pname + "}", node, flags=re.IGNORECASE)
        return node
    if isinstance(node, list):
        return [abstract_params(x, params) for x in node]
    if isinstance(node, dict):
        return {k: abstract_params(v, params) for k, v in node.items()}
    return node


def _escape_keeping_params(text: str) -> str:
    """re.escape, but ${name} placeholders survive so resolve_params can fill them."""
    parts, last = [], 0
    for m in _PLACEHOLDER.finditer(text):
        parts.append(re.escape(text[last : m.start()]))
        parts.append(m.group(0))
        last = m.end()
    parts.append(re.escape(text[last:]))
    return "".join(parts)


def base_url(url: str) -> str:
    """URL without query/fragment — the stable part worth recognizing a state by."""
    return url.split("#", 1)[0].split("?", 1)[0]


# ── per-run normalization ─────────────────────────────────────────────────────────────


@dataclass
class _Step:
    action: Action  # abstracted
    key: str  # canonical identity for alignment (action minus timeouts)
    url: str  # page URL right after the action (abstracted)
    evidence: PageEvidence | None  # abstracted


def _action_key(action: Action) -> str:
    data = action.model_dump(mode="json", exclude={"timeout_ms"})
    return json.dumps(data, sort_keys=True)


def _normalize(run: Exploration) -> list[_Step]:
    steps: list[_Step] = []
    for s in run.trajectory.steps:
        if s.action is None or s.error is not None:
            continue
        action = _parse_action(abstract_params(s.action.model_dump(mode="json"), run.params))
        evidence = None
        if s.evidence is not None:
            evidence = PageEvidence.model_validate(abstract_params(s.evidence.model_dump(mode="json"), run.params))
        url = str(abstract_params(s.url, run.params))
        steps.append(_Step(action=action, key=_action_key(action), url=url, evidence=evidence))
    return steps


_ACTION = TypeAdapter(Action)


def _parse_action(data: dict) -> Action:
    return _ACTION.validate_python(data)


def _same_locator(a: Action, b: Action) -> bool:
    la, lb = locator_of(a), locator_of(b)
    return la is not None and lb is not None and [x.model_dump() for x in la] == [x.model_dump() for x in lb]


def _evidence_fingerprint(e: PageEvidence | None) -> tuple | None:
    if e is None:
        return None
    return (base_url(e.url), e.title, tuple(e.texts), e.video_present)


def minimize(steps: list[_Step], notes: list[str], label: str) -> list[_Step]:
    """Drop incidental steps — only where the outcome provably did not depend on them:

    - click(X) immediately followed by fill(X): `fill` focuses the field itself.
    - fill(X, t) immediately followed by the identical fill(X, t): a fill replaces.
    - a scroll after which the page evidence (URL, title, text sample) is unchanged:
      it revealed nothing; click/fill auto-scroll their target into view on replay.
    Steps without evidence are never judged by evidence.
    """
    changed = True
    while changed:
        changed = False
        out: list[_Step] = []
        i = 0
        while i < len(steps):
            cur = steps[i]
            nxt = steps[i + 1] if i + 1 < len(steps) else None
            if nxt is not None and cur.action.type == "click" and nxt.action.type == "fill" and _same_locator(
                cur.action, nxt.action
            ):
                notes.append(f"{label}: dropped click on a field that is filled next ({_describe(cur.action)})")
                changed = True
                i += 1
                continue
            if nxt is not None and cur.action.type == "fill" and cur.key == nxt.key:
                notes.append(f"{label}: dropped duplicate fill ({_describe(cur.action)})")
                changed = True
                i += 1
                continue
            if (
                isinstance(cur.action, ScrollAction)
                and out
                and cur.evidence is not None
                and out[-1].evidence is not None
                and _evidence_fingerprint(cur.evidence) == _evidence_fingerprint(out[-1].evidence)
            ):
                # carry the probe forward: the next target's visibility belongs to the prior state
                if cur.evidence.probes and not out[-1].evidence.probes:
                    out[-1].evidence = out[-1].evidence.model_copy(update={"probes": cur.evidence.probes})
                notes.append(f"{label}: dropped scroll that changed no page evidence")
                changed = True
                i += 1
                continue
            out.append(cur)
            i += 1
        steps = out
    return steps


def _describe(action: Action) -> str:
    chain = locator_of(action)
    if chain:
        last = chain[-1]
        target = " ".join(str(a) for a in last.args) + ("" if not last.kwargs else f" {dict(last.kwargs)}")
        return f"{action.type} {target}"
    if isinstance(action, ScrollAction):
        return f"scroll {'down' if action.down else 'up'} {action.pages:g}"
    return action.type


# ── alignment ─────────────────────────────────────────────────────────────────────────


def _lcs(a: list[str], b: list[str]) -> list[tuple[int, int]]:
    """Index pairs of one longest common subsequence of a and b (leftmost-preferring)."""
    n, m = len(a), len(b)
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        for j in range(m - 1, -1, -1):
            dp[i][j] = dp[i + 1][j + 1] + 1 if a[i] == b[j] else max(dp[i + 1][j], dp[i][j + 1])
    pairs: list[tuple[int, int]] = []
    i = j = 0
    while i < n and j < m:
        if a[i] == b[j]:
            pairs.append((i, j))
            i += 1
            j += 1
        elif dp[i + 1][j] >= dp[i][j + 1]:
            i += 1
        else:
            j += 1
    return pairs


def _core_keys(runs: list[list[_Step]]) -> list[str]:
    core = [s.key for s in runs[0]]
    for run in runs[1:]:
        pairs = _lcs(core, [s.key for s in run])
        core = [core[i] for i, _ in pairs]
    return core


# ── condition derivation ──────────────────────────────────────────────────────────────


def _all(values: list[bool | None]) -> bool:
    return bool(values) and all(v is True for v in values)


def _url_condition(step_urls: list[str], prev_url: str | None) -> tuple[list[Trigger], str | None]:
    urls = {base_url(u) for u in step_urls}
    if len(urls) != 1:  # runs landed on different pages: no URL is safe to assert
        return [], None
    (url,) = urls
    if url == prev_url:
        return [], url
    return [UrlMatches(pattern=_escape_keeping_params(url))], url


def _evidence_conditions(
    evidences: list[PageEvidence | None],
    prev_evidences: list[PageEvidence | None],
    next_action: Action | None,
    min_runs_for_text: int = 2,
) -> list[Trigger]:
    """Conditions every run's evidence supports at this state (beyond the URL)."""
    conds: list[Trigger] = []
    if any(e is None for e in evidences) or not evidences:
        return conds
    target = locator_of(next_action) if next_action is not None else None
    if target is not None:
        want = [x.model_dump() for x in target]
        seen = [
            next((p.visible for p in e.probes if [x.model_dump() for x in p.locator] == want), None)
            for e in evidences
        ]
        if _all(seen):
            conds.append(ElementVisible(locator=target))
    if all(e.video_playing for e in evidences):
        conds.append(VideoPlaying())
    elif all(e.video_present for e in evidences):
        conds.append(SelectorVisible(selector="video"))
    if len(evidences) >= min_runs_for_text:
        common = set(evidences[0].texts)
        for e in evidences[1:]:
            common &= set(e.texts)
        before = set().union(*(set(p.texts) for p in prev_evidences if p is not None))
        for text in evidences[0].texts:  # run-0 document order: headings come first
            if (
                text in common
                and text not in before
                and TEXT_MIN <= len(text) <= TEXT_MAX
                and "${" not in text
                and not text.isdigit()
            ):
                conds.append(TextVisible(text=text))
                break
    return conds


# ── the synthesizer ───────────────────────────────────────────────────────────────────


def synthesize(
    explorations: list[Exploration],
    name: str,
    version: str = "1",
    declared_params: dict[str, str] | None = None,
) -> Synthesis:
    """Consolidate explorations into a Workflow. `declared_params` maps each param name to
    its default (the primary exploration's sample); defaults to the first run's params."""
    notes: list[str] = []
    successful = [x for x in explorations if x.trajectory.success]
    failed = len(explorations) - len(successful)
    if failed:
        notes.append(f"{failed} of {len(explorations)} exploration(s) did not reach done; used the rest")
    if not successful:
        raise ValueError("no successful exploration to synthesize from")

    runs: list[list[_Step]] = []
    for k, x in enumerate(successful, 1):
        steps = minimize(_normalize(x), notes, label=f"run {k}")
        if not steps:
            raise ValueError(f"exploration {k} has no successful action steps")
        runs.append(steps)

    core_keys = _core_keys(runs)
    if not core_keys:
        raise ValueError("explorations share no common action — nothing to synthesize")
    # Embed the core in each run → per-run gaps (the optional steps between core actions).
    embeds: list[list[int]] = []
    for run in runs:
        pairs = _lcs(core_keys, [s.key for s in run])
        assert len(pairs) == len(core_keys), "core must embed in every run"
        embeds.append([j for _, j in pairs])
    gaps: list[list[list[_Step]]] = []  # gaps[i][run] = steps after core i, before core i+1
    for i in range(len(core_keys)):
        per_run = []
        for run, pos in zip(runs, embeds, strict=True):
            end = pos[i + 1] if i + 1 < len(pos) else len(run)
            per_run.append(run[pos[i] + 1 : end])
        gaps.append(per_run)
    if len(runs) > 1:
        notes.append(f"core path: {len(core_keys)} action(s) common to all {len(runs)} successful run(s)")

    states: list[State] = [State(id="init")]
    transitions: list[Transition] = []
    control: list[ControlNode] = []
    has_branch = False
    prev_url: str | None = None
    prev_evidence: list[PageEvidence | None] = [None] * len(runs)
    current = "init"

    for i in range(1, len(core_keys) + 1):
        core_steps = [run[pos[i - 1]] for run, pos in zip(runs, embeds, strict=True)]
        action = core_steps[0].action
        next_action = (
            runs[0][embeds[0][i]].action if i < len(core_keys) else None
        )
        # the "settled" evidence just before the next core action (after any optional steps)
        settled = [
            (gap[-1].evidence if gap else s.evidence) for gap, s in zip(gaps[i - 1], core_steps, strict=True)
        ]
        url_conds, prev_url = _url_condition([s.url for s in core_steps], prev_url)
        sid = f"s{i}"
        states.append(State(id=sid, description=f"after {_describe(action)}", conditions=url_conds))
        transitions.append(Transition(id=f"t{i}", source=current, target=sid, action=action))
        control.append(EdgeStep(edge=f"t{i}"))
        current = sid

        variants, dropped = _variants(gaps[i - 1])
        if dropped:
            notes.append(f"state {sid}: dropped {dropped} incidental step(s) seen in some runs (not guardable)")
        if variants:
            has_branch = True
            join = f"{sid}j"
            arms: list[BranchArm] = []
            for v, steps in enumerate(variants, 1):
                first = steps[0]
                guard_state = f"{sid}b{v}"
                states.append(
                    State(
                        id=guard_state,
                        description=f"interstitial present: {_describe(first.action)}",
                        conditions=[ElementVisible(locator=locator_of(first.action))],
                    )
                )
                eps = f"t{i}b{v}_eps"
                transitions.append(Transition(id=eps, source=sid, target=guard_state, action=NoopAction()))
                arm_nodes: list[ControlNode] = [EdgeStep(edge=eps)]
                src = guard_state
                for k, step in enumerate(steps, 1):
                    last = k == len(steps)
                    tgt = join if last else f"{sid}b{v}_{k}"
                    if not last:
                        states.append(State(id=tgt, description=f"after {_describe(step.action)}"))
                    tid = f"t{i}b{v}_{k}"
                    transitions.append(Transition(id=tid, source=src, target=tgt, action=step.action))
                    arm_nodes.append(EdgeStep(edge=tid))
                    src = tgt
                arms.append(BranchArm(when=guard_state, then=arm_nodes))
                notes.append(
                    f"state {sid}: optional step(s) seen in some runs → guarded branch: "
                    + ", ".join(_describe(s.action) for s in steps)
                )
            else_nodes = None
            if any(not gap for gap in gaps[i - 1]):
                eps_id = f"t{i}_eps"
                transitions.append(Transition(id=eps_id, source=sid, target=join, action=NoopAction()))
                else_nodes = [EdgeStep(edge=eps_id)]
            control.append(Branch(arms=arms, else_=else_nodes, probe_ms=BRANCH_PROBE_MS))
            states.append(
                State(
                    id=join,
                    description=f"{sid}, interstitial resolved",
                    conditions=_evidence_conditions(settled, prev_evidence, next_action),
                )
            )
            current = join
        else:
            states[-1].conditions.extend(_evidence_conditions(settled, prev_evidence, next_action))
        prev_evidence = settled

    params = declared_params if declared_params is not None else dict(successful[0].params)
    wf = Workflow(
        name=name,
        version=version,
        description=successful[0].trajectory.task,
        start_state="init",
        states=states,
        transitions=transitions,
        params=[Param(name=n, default=v, description=f"exploration used {v!r}") for n, v in params.items()],
        control=control if has_branch else None,
        control_sequence=None if has_branch else [t.id for t in transitions],
        accept_states=[current],
    )
    return Synthesis(workflow=wf, notes=notes)


def _variants(per_run: list[list[_Step]]) -> tuple[list[list[_Step]], int]:
    """Distinct, guardable optional sequences in a gap, plus how many steps were dropped.
    Leading steps without a locator (scroll/wait/press) cannot be guarded and are trimmed;
    a variant with nothing guardable left is incidental and dropped entirely."""
    seen: dict[str, list[_Step]] = {}
    dropped = 0
    for gap in per_run:
        trimmed = list(gap)
        while trimmed and locator_of(trimmed[0].action) is None:
            trimmed.pop(0)
            dropped += 1
        if not trimmed:
            continue
        seen.setdefault("|".join(s.key for s in trimmed), trimmed)
    return list(seen.values()), dropped
