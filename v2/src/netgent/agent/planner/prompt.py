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
