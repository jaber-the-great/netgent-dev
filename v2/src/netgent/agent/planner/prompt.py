"""The planner's prompt: the system rules and the request rendered as message content. Pure."""

PLANNER_SYSTEM = """You plan web-automation tasks for a browser agent that acts one atomic step at a time
(goto, click, fill, press, select, scroll, upload, wait) and can only see the current page.
Given a TASK and a starting URL, decompose the task into a short ordered list of
sub-goals the agent can pursue one at a time, each with the visible page outcome that proves it
done. Keep steps at the level of user intent ("log in with the given credentials", "open the
first search result"), never individual clicks. Do not invent requirements the task does not
state; put uncertainties in `notes`."""


def build_planner_content(task: str, url: str | None = None) -> list[dict]:
    """The HumanMessage content blocks. Pure — tests pin the layout."""
    text = f"TASK: {task}\nSTART URL: {url or '(none)'}\n\nPlan:"
    return [{"type": "text", "text": text}]


VARIATIONS_SYSTEM = """You design VARIATIONS of one web-automation task, so several exploration
runs of the same task family reveal which of its concrete values are parameters.
Given a TASK, a start URL and a count N, return exactly N variations:
- Variation 1 is the TASK exactly as given; still extract its concrete values.
- Every variation stays in the SAME task family: same site, same goal shape, same steps at the
  level of user intent. Only concrete values change (a search query, a duration, a quantity, a
  choice among like items). Never add or remove requirements, and never change the website.
- `values` maps snake_case parameter names you propose (e.g. video_query, watch_time) to the
  concrete value that variation uses. Every variation carries the SAME names, and every value
  must appear VERBATIM in its variation's task_text.
- Vary at least one value between variations; keep values realistic, short, and safe.
- If the task implies a value it does not spell out (e.g. "watch a video" implies some query),
  choose a concrete value, name it, and write it into every task_text — including variation 1's
  values (variation 1's task_text still stays the original task, unchanged)."""


def build_variations_content(
    task: str, n: int, url: str | None = None, pinned: dict[str, str] | None = None
) -> list[dict]:
    """The HumanMessage content blocks for variation planning. Pure — tests pin the layout."""
    text = f"TASK: {task}\nSTART URL: {url or '(none)'}\nN: {n}"
    if pinned:
        decl = "; ".join(f"{k} = {v!r}" for k, v in sorted(pinned.items()))
        text += f"\nPINNED: one variation (not variation 1) must use exactly: {decl}"
    return [{"type": "text", "text": text + "\n\nVariations:"}]


NEXT_ROUND_SYSTEM = """You plan the NEXT ROUND of a closed-loop compile: several exploration runs of one
web-automation task family were merged (pure code) into an alignment, a generator agent drafted
ONE replayable workflow from the recordings (every choice re-derived by code, rejected choices
listed), the artifact was replayed with zero LLM for other value sets, and triaged. The replay is
the only judge of the artifact. You read the round's evidence (variations, verdicts, the merge's
column dispositions, the generator's rejected choices, replay results, typed episodes) and answer:

1. `next_variations` — full-task variations to explore next, SAME family (same site, same goal
   shape), only concrete values change, every value VERBATIM in its task_text, the same value
   names as before. Choose values that exercise the episodes: a different search so the first
   result differs; durations that are exact multiples of the site's seek step for press folds.
   Usually 1-2 variations; never more than N. Choose values whose recordings would give the
   generator the evidence it lacked (a rejected choice names it).
2. `scoped_subtasks` — optional: a short segment to explore on its own from a start URL
   ("search for X and open the first result"), when one column needs evidence.
Never write selectors, actions, regexes or artifact content. Put uncertainties in `notes`."""


def build_next_round_content(ctx) -> list[dict]:
    """The HumanMessage content blocks for next-round planning, from a RoundContext. Pure."""
    lines = [f"TASK: {ctx.task}", f"START URL: {ctx.url or '(none)'}", f"N (max runs next round): {ctx.runs_per_round}",
             f"VALUE NAMES: {', '.join(ctx.canonical_names) or '(none)'}"]
    for rd in ctx.rounds:
        lines.append(f"\n=== ROUND {rd.round} ===")
        for v in rd.variations:
            vals = ", ".join(f"{k}={val!r}" for k, val in v.values.items()) or "(no values)"
            lines.append(f"variation: {v.task_text} [{vals}]")
        for r in rd.runs:
            tail = f"; unmet: {'; '.join(u[:100] for u in r.unmet)}" if r.unmet else ""
            lines.append(f"run {r.run}{' (scoped)' if r.scoped else ''}: {'achieved' if r.achieved else 'NOT achieved'}"
                         f" in {r.attempts} attempt(s), {r.steps} steps{tail}")
        g = rd.generalized
        if g is not None:
            lines.append("merge: params " + (", ".join(
                f"{p.name}={p.default!r} ({'/'.join(str(v) for v in p.values_by_run.values())})"
                for p in g.params) or "(none)"))
            for c in g.columns:
                if c.disposition == "aligned":
                    continue
                extra = f" {c.field}={'/'.join(c.values_by_run.values())}" if c.values_by_run else ""
                lines.append(f"  column {c.index}: {c.disposition} {c.action_type}"
                             f"{' ' + (c.target or '')[:60] if c.target else ''}"
                             f"{' -> ${' + c.param + '}' if c.param else ''}{extra}"
                             f" [runs {','.join(map(str, c.runs))}{', ' + c.transition if c.transition else ''}]")
            for w in g.warnings[:8]:
                lines.append(f"  warning: {w[:160]}")
        if rd.used_fallback:
            lines.append("generator: the draft was discarded; the merge's artifact was replayed")
        for o in rd.draft_outcomes:
            if o.status == "rejected":
                lines.append(f"  draft {o.item}{f' ({o.ref})' if o.ref else ''}: rejected — {o.reason[:120]}")
        for rr in rd.replay:
            lines.append(f"replay {rr.values}: {'ok' if rr.success else 'FAILED'}"
                         + (f" at {rr.failed_edge} ({rr.outcome}; unmet {rr.unmet})" if rr.failed_edge else "")
                         + f" states {rr.signature[-3:]}")
        for e in rd.episodes:
            lines.append("episode: " + e.as_line())
    lines.append("\nNext round:")
    return [{"type": "text", "text": "\n".join(lines)}]
