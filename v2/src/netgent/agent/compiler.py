"""Compile an agent trajectory into a workflow (NFA): Discovery -> artifact.

The one-run convenience over `netgent.agent.synthesis.synthesize`: each successful action
step becomes one transition; states are recognized by the (query-stripped) URL they landed
on plus whatever page evidence the step recorded; sample values the caller names become
${name} parameters, so the compiled workflow replays for other values:

    traj = await BrowserAgent(...).run(session, task)
    wf = compile_trajectory(traj, name="twitch-live", params={"channel": "monstercat"})
    # netgent run wf.yaml --param channel=bobross
"""

from netgent.agent.browser_agent import AgentTrajectory
from netgent.agent.synthesis import Exploration, synthesize
from netgent.schema.workflow import Workflow


def compile_trajectory(
    traj: AgentTrajectory,
    name: str,
    params: dict[str, str] | None = None,
    version: str = "1",
) -> Workflow:
    """Compile one trajectory's successful action steps into a replayable Workflow."""
    if not any(s.action is not None and s.error is None for s in traj.steps):
        raise ValueError("trajectory has no successful action steps to compile")
    run = Exploration(traj.model_copy(update={"success": True}), dict(params or {}))
    return synthesize([run], name=name, version=version).workflow
