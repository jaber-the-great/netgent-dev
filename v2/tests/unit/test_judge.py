"""The verifier's evidence and prompt layout — pure, no browser, no model."""

from pathlib import Path

from netgent.agent.explorer.agent import AgentStep, AgentTrajectory
from netgent.agent.verifier import Evidence, Verdict, build_judge_content
from netgent.schema.actions import ClickAction, FillAction, LocatorStep


def _traj(tmp_path: Path, n_shots: int = 5) -> AgentTrajectory:
    steps = []
    for i in range(n_shots):
        rel = f"screenshots/step-{i:02d}.png"
        (tmp_path / "screenshots").mkdir(exist_ok=True)
        (tmp_path / rel).write_bytes(b"\x89PNG" + bytes([i]))
        steps.append(AgentStep(n=i, kind="click", reasoning="SECRET REASONING", url="http://x", screenshot=rel))
    steps[0].action = FillAction(locator=[LocatorStep(fn="locator", args=["#email"])], text="a@b.c")
    steps[1].action = ClickAction(locator=[LocatorStep(fn="get_by_role", args=["button"], kwargs={"name": "Submit"})])
    steps[1].dialogs = ["alert: Form submitted successfully!"]
    steps[2].error = "click failed: timeout"
    return AgentTrajectory(
        task="submit the form", steps=steps, success=True, texts_seen=["Success!"],
        final_observation='[0] button "Submit"', final_url="http://x/done",
        dialogs=["alert: Form submitted successfully!"],
    )


def test_evidence_carries_actions_effects_and_last_three_screenshots_but_no_reasoning(tmp_path):
    ev = Evidence.from_trajectory("submit the form", _traj(tmp_path), params={"who": "Ada"}, run_dir=tmp_path)
    assert ev.action_log[0] == "0. fill '#email' = 'a@b.c'"
    assert ev.action_log[1].startswith("1. click 'Submit'") and "dialog: alert: Form submitted" in ev.action_log[1]
    assert "FAILED: click failed" in ev.action_log[2]
    assert len(ev.screenshots) == 3 and ev.screenshots[-1].endswith(bytes([4]))  # the final state is last
    content = build_judge_content(ev)
    text = content[0]["text"]
    assert "SECRET REASONING" not in text  # the judge never sees the agent's narration
    assert "${who} = 'Ada'" in text and "FINAL URL: http://x/done" in text and "- Success!" in text
    assert [c["type"] for c in content] == ["text", "image_url", "image_url", "image_url"]
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_verdict_schema_defaults():
    v = Verdict(achieved=False, unmet=["no confirmation shown"])
    assert v.confidence == "medium" and v.evidence == []
