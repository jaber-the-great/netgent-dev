"""`gather`: recordings + the merge's trail + episodes + replay + prior rounds → the compact
Evidence the generator agent reads (docs/research/generator-agent-v2.md §G.2). Pure and
deterministic, so the whole prompt is reproducible offline from a stored bundle.

What is deliberately NOT here (§G.3): screenshots, observations, `evaluation`/`memory`/`next_goal`.
The trajectories are small — MOP's eight kept runs are ~11 k tokens in this format; the
observations were the expensive part, and the generator never reads them.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from netgent.agent.explorer.models import AgentStep
from netgent.agent.generator.compiler import _base_url, _locator_selector
from netgent.agent.generator.context import GeneratorContext
from netgent.agent.generator.draft import ref_of
from netgent.agent.generator.merge import RunInput

REASONING_CHARS = 200  # the load-bearing clause is in the first sentence (§G.3)
_MEDIA_RE = re.compile(
    r"\b(video|audio)(?: \(detached\))? (PLAYING|PAUSED|ENDED) at (\d+):(\d{2})(?: / (\d+):(\d{2}))?"
)


class Evidence(BaseModel):
    """The rendered evidence, section by section (each a list of lines). `render()` joins them
    in the stable order the prompt relies on: task, values, runs, steps, alignment, episodes,
    replay, previous attempts."""

    task: str
    url: str = ""
    declared: list[str] = Field(default_factory=list)
    runs: list[str] = Field(default_factory=list)
    steps: list[str] = Field(default_factory=list)
    alignment: list[str] = Field(default_factory=list)
    episodes: list[str] = Field(default_factory=list)
    replay: list[str] = Field(default_factory=list)
    previous: list[str] = Field(default_factory=list)
    steps_shown: int = 0
    steps_total: int = 0

    def render(self) -> str:
        parts = [f"TASK: {self.task}", f"START URL: {self.url or '(none)'}",
                 f"DECLARED VALUES: {', '.join(self.declared) or '(none)'}", "", "RUNS", *self.runs, "", "STEPS",
                 *self.steps, "", "ALIGNMENT (pure code, this round)", *(self.alignment or ["  (none)"]),
                 "", "EPISODES (pure code, this round)", *(self.episodes or ["  (none)"]),
                 "", "REPLAY (zero LLM, last round)", *(self.replay or ["  (not run yet)"])]
        if self.previous:
            parts += ["", "PREVIOUS ATTEMPTS", *self.previous]
        return "\n".join(parts)


# ── step lines ───────────────────────────────────────────────────────────────


def _target_text(step: AgentStep) -> str:
    a = step.action
    locator = getattr(a, "locator", None)
    if not locator:
        return ""
    last = locator[-1]
    if last.fn == "nth" and len(locator) >= 2:
        last = locator[-2]
    if last.fn == "get_by_role" and last.args:
        name = last.kwargs.get("name")
        return f'{last.args[0]} "{str(name)[:60]}"' if name is not None else str(last.args[0])
    if last.args:
        return f"{last.fn} {str(last.args[0])[:70]!r}"
    return last.fn


def _value_text(step: AgentStep) -> str:
    d = step.action.model_dump()
    for key in ("text", "value", "url", "keys", "seconds"):
        if d.get(key) is not None:
            v = d[key]
            return f" {int(v) if key == 'seconds' and float(v) == int(v) else v!r}" if key != "seconds" else f" {v:g}s"
    return ""


def _ladder_text(step: AgentStep) -> str:
    if not step.locator_candidates:
        return ""
    used = [st.model_dump() for st in getattr(step.action, "locator", None) or []]
    rungs = []
    for i, chain in enumerate(step.locator_candidates):
        kind = step.candidate_kinds[i] if i < len(step.candidate_kinds) else "?"
        count = step.match_counts[i] if i < len(step.match_counts) else -1
        index = step.match_indices[i] if i < len(step.match_indices) else None
        star = "*" if [st.model_dump() for st in chain] == used else ""
        at = f"@{index}" if index is not None else ""
        sel = _locator_selector(chain)
        shown = f" {sel[:60]!r}" if sel is not None and kind in ("structural", "css", "id") else ""
        rungs.append(f"{i}:{kind}{star}({count}{at}){shown}")
    return " | ladder " + " ".join(rungs)


def media_reading(step: AgentStep) -> tuple[str, int, int | None] | None:
    """(state, position_s, duration_s) of the CONTENT reading on a step — the longest media
    element seen (ads and inline previews are shorter) — or None."""
    if not step.media:
        return None
    best = None
    for m in _MEDIA_RE.finditer(step.media):
        pos = int(m.group(3)) * 60 + int(m.group(4))
        dur = int(m.group(5)) * 60 + int(m.group(6)) if m.group(5) else None
        cand = (m.group(2), pos, dur)
        if best is None or (dur or 0) > (best[2] or 0):
            best = cand
    return best


def seek_between(a: AgentStep, b: AgentStep) -> float | None:
    """Position advanced from a's reading to b's, minus the wall-clock that elapsed — the seek
    a's action produced, in seconds (§D.2). None when either side lacks a playing reading or `t`."""
    ra, rb = media_reading(a), media_reading(b)
    if ra is None or rb is None or a.t is None or b.t is None:
        return None
    if ra[0] != "PLAYING" or rb[0] != "PLAYING" or (ra[2] is not None and rb[2] is not None and ra[2] != rb[2]):
        return None  # a different element is now the longest one: not the same content
    return (rb[1] - ra[1]) - (b.t - a.t)


def _fmt_pos(seconds: int) -> str:
    return f"{seconds // 60}:{seconds % 60:02d}"


def step_line(run: int, step: AgentStep, prev: AgentStep | None, nxt: AgentStep | None) -> str:
    """One recorded step as the agent reads it: its reference, action, value, target, ladder;
    then url change, media reading (+ the seek the step produced), and one clause of reasoning."""
    ref = ref_of(run, step)
    head = f"{ref:<10} {step.action.type}{_value_text(step)}"
    target = _target_text(step)
    if target:
        head += f" -> {target}"
    head += _ladder_text(step)
    tail = []
    base, prev_base = _base_url(step.url), _base_url(prev.url) if prev is not None else None
    if prev_base is not None and base != prev_base:
        tail.append(f"url {_path(prev_base)} -> {_path(base)}")
    reading = media_reading(step)
    if reading is not None:
        state, pos, dur = reading
        media = f"media {state} {_fmt_pos(pos)}" + (f"/{_fmt_pos(dur)}" if dur is not None else "")
        if nxt is not None and (seek := seek_between(step, nxt)) is not None:
            media += f" seek{seek:+.0f}s"
        tail.append(media)
    why = (step.reasoning or "").strip().replace("\n", " ")[:REASONING_CHARS]
    if why:
        tail.append(f"why: {why}")
    return head + ("\n" + " " * 11 + "  ".join(tail) if tail else "")


def _path(base: str) -> str:
    m = re.match(r"^[a-z]+://[^/]+(/.*)?$", base)
    return (m.group(1) or "/") if m else base


def run_steps(run: RunInput) -> list[AgentStep]:
    """The recorded steps materialize and the prompt agree on: successful action steps only."""
    return [s for s in run.trajectory.steps if s.action is not None and s.error is None]


# ── the gather ───────────────────────────────────────────────────────────────


def gather_evidence(ctx: GeneratorContext) -> Evidence:
    achieved = ctx.achieved()
    runs_lines = []
    for r in ctx.runs:
        vals = " ".join(f"{k}={v!r}" for k, v in r.values.items())
        n = len(run_steps(r))
        status = "achieved" if r.achieved and not r.scoped else ("scoped" if r.scoped else "NOT achieved")
        line = f"  run {r.run:<3} {status:<13} {n:>2} steps  {vals}"
        if not r.achieved and r.trajectory.stopped_reason:
            line += f"  stopped: {r.trajectory.stopped_reason[:80]}"
        runs_lines.append(line)

    steps_lines: list[str] = []
    total = sum(len(run_steps(r)) for r in achieved)
    shown = 0
    for r in achieved:
        steps = run_steps(r)
        steps_lines.append(f"=== run {r.run} ===")
        if shown + len(steps) > ctx.max_steps_shown and shown > 0:
            steps_lines.append(f"  ({len(steps)} steps not shown — budget; refer to the alignment)")
            continue
        for i, s in enumerate(steps):
            prev, nxt = (steps[i - 1] if i else None), (steps[i + 1] if i + 1 < len(steps) else None)
            steps_lines.append(step_line(r.run, s, prev, nxt))
        shown += len(steps)

    align = []
    for c in ctx.generalized.columns:
        head = f"  key {c.key:<34} {c.disposition:<14} support {c.support}/{len(achieved)}"
        if c.param:
            head += f" param {c.param}"
        if c.transition:
            head += f" -> {c.transition}"
        align.append(head)
        if c.disposition in ("target-varies", "param-target", "positional", "interrupt", "dropped", "branch"):
            for rid, t in list(c.targets_by_run.items())[:8]:
                align.append(f"       run {rid}: {t[:90]}")
        if c.values_by_run:
            align.append("       " + c.field + " " + "/".join(c.values_by_run.values()))
    for w in ctx.generalized.warnings[:12]:
        align.append(f"  warning: {w[:180]}")
    episodes = [f"  {e.as_line()[:300]}" for e in ctx.episodes]
    replay = []
    if ctx.replay is not None:
        for rr in ctx.replay.runs:
            status = "ok" if rr.success else f"FAILED at {rr.failed_edge} ({rr.outcome}; unmet {rr.unmet})"
            replay.append(f"  {rr.values}: {status} states {rr.signature[-4:]}")
    previous = []
    for rd in ctx.prior:
        outcomes = [o for o in getattr(rd, "draft_outcomes", []) if o.status != "applied"]
        for o in outcomes[:20]:
            where = f" ({o.ref})" if o.ref else ""
            previous.append(f"  round {rd.round} draft {o.item}{where} — {o.status.upper()}: {o.reason[:160]}")
        if getattr(rd, "used_fallback", False):
            previous.append(f"  round {rd.round}: " + (
                "the draft was discarded (fewer than half its steps materialized); the merge's artifact was replayed"
                if getattr(rd, "draft_outcomes", []) else "no draft arrived; the merge's artifact was replayed"))
    return Evidence(task=ctx.task, url=ctx.url or "", declared=list(next(iter(ctx.values_by_run.values()), {})),
                    runs=runs_lines, steps=steps_lines, alignment=align, episodes=episodes, replay=replay,
                    previous=previous, steps_shown=shown, steps_total=total)
