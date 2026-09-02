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
