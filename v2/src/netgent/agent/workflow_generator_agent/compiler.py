"""Compile an agent trajectory into a workflow (NFA): Discovery -> artifact.

Each successful action step becomes one transition; the state after each step is
recognized by the (query-stripped) URL it landed on. Sample values the caller names
become ${name} parameters, so the compiled workflow replays for other values:

    traj = await BrowserAgent(...).run(session, task)
    wf = compile_trajectory(traj, name="twitch-live", params={"channel": "monstercat"})
    # netgent run wf.yaml --param channel=bobross
"""

import re
from urllib.parse import quote_plus

from netgent.agent.explore_agent.browser_agent import AgentTrajectory
from netgent.schema.actions import GotoAction
from netgent.schema.workflow import Param, State, Transition, Workflow

NAVIGATION_TIMEOUT_MS = 30_000  # a page load needs a navigation-scale budget, not an element-action one


def _base_url(url: str) -> str:
    """URL without query/fragment — the stable part worth recognizing a state by."""
    return url.split("#", 1)[0].split("?", 1)[0]


def compile_trajectory(
    traj: AgentTrajectory,
    name: str,
    params: dict[str, str] | None = None,
    version: str = "1",
) -> Workflow:
    """Compile the trajectory's successful action steps into a replayable Workflow.

    `params` maps a param name to the sample value used during exploration; every
    occurrence of the value (and its URL-encoded form) in the compiled workflow is
    replaced by ${name}, and the sample becomes the param's default.
    """
    steps = [s for s in traj.steps if s.action is not None and s.error is None]
    if not steps:
        raise ValueError("trajectory has no successful action steps to compile")

    states = [State(id="init")]
    transitions: list[Transition] = []
    prev_base: str | None = None
    for i, step in enumerate(steps, 1):
        base = _base_url(step.url)
        # Recognize the state by its URL only when the action moved somewhere new;
        # same-page steps (fills, same-page clicks) get an unconditioned state.
        conditions = [{"type": "url_matches", "pattern": re.escape(base)}] if base != prev_base else []
        prev_base = base
        state_id = f"s{i}"
        states.append(State(id=state_id, conditions=conditions))
        action = step.action
        if isinstance(action, GotoAction) and action.timeout_ms < NAVIGATION_TIMEOUT_MS:
            # Exploration navigated with Playwright's 30 s default; the artifact must too,
            # or a slow real site fails replay on its very first edge.
            action = action.model_copy(update={"timeout_ms": NAVIGATION_TIMEOUT_MS})
        transitions.append(Transition(id=f"t{i}", source=states[-2].id, target=state_id, action=action))

    wf = Workflow(
        name=name,
        version=version,
        description=traj.task,
        start_state="init",
        states=states,
        transitions=transitions,
        control_sequence=[t.id for t in transitions],
    )

    if params:
        data = wf.model_dump(mode="json")

        def sub(node: object) -> object:
            if isinstance(node, str):
                # longest sample values first, so overlapping values substitute correctly.
                # Case-insensitive: sites render "monstercat" as "Monstercat" in link names,
                # and Playwright's role-name matching is itself case-insensitive.
                for pname, value in sorted(params.items(), key=lambda kv: -len(kv[1])):
                    for form in (value, quote_plus(value)):  # literal + URL-encoded
                        node = re.sub(re.escape(form), "${" + pname + "}", node, flags=re.IGNORECASE)
                return node
            if isinstance(node, list):
                return [sub(x) for x in node]
            if isinstance(node, dict):
                out = {k: sub(v) for k, v in node.items()}
                # A role/label name that now carries a ${param} must not be matched exactly:
                # the replay value differs in case/wording from the accessible name the site
                # renders ("NEW Funny Cat Videos" vs query="cat videos"). Playwright's default
                # (non-exact) match is case-insensitive substring, which is what we want here.
                if out.get("exact") is True and "${" in str(out.get("name", "")):
                    out["exact"] = False
                return out
            return node

        data = sub(data)
        data["params"] = [
            Param(name=n, default=v, description=f"exploration used {v!r}").model_dump(mode="json")
            for n, v in params.items()
        ]
        wf = Workflow.model_validate(data)

    return wf
