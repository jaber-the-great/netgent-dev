"""G4 — the generator agent as one compiled graph (gather → draft → materialize ⇄ repair), driven
by a FakeLLM-scripted draft over the stored MOP bundle: no key, no browser. The repair loop is
CEGIS with the materializer as the counter-example generator; a missing draft falls back to the
merge's artifact."""

import asyncio
import json
from pathlib import Path

import pytest
from test_materialize import TASK, VIDEO_CLICK, mop_draft

from netgent.agent import FakeLLM
from netgent.agent.explorer.models import AgentTrajectory
from netgent.agent.generator import GENERATOR_SYSTEM, REPAIR_SYSTEM, GeneratorAgent, build_generator_content
from netgent.agent.generator.draft import LocatorRef
from netgent.agent.generator.evidence import gather_evidence
from netgent.agent.generator.merge import RunInput, merge_trajectories
from netgent.agent.generator.prompt import build_repair_content
from netgent.agent.rounds import RoundRecord

pytest.importorskip("langgraph")

from netgent.agent.generator.context import GeneratorContext  # noqa: E402
from netgent.agent.generator.graph import GENERATOR, create_generator_agent, generate  # noqa: E402

FIX = Path(__file__).parent.parent / "fixtures" / "mop"


def _runs() -> list[RunInput]:
    out = []
    for k in range(1, 14):
        d = FIX / f"run-{k}"
        traj = AgentTrajectory.model_validate(json.loads((d / "trajectory.json").read_text()))
        var = json.loads((d / "variation.json").read_text())
        ver = json.loads((d / "verdict.json").read_text())
        out.append(RunInput(run=k, trajectory=traj, values=var["values"], achieved=ver["achieved"],
                            scoped=var.get("scoped", False)))
    return out


@pytest.fixture(scope="module")
def merged():
    runs = _runs()
    return runs, merge_trajectories(runs, name="mop")


def test_generator_is_one_compiled_graph():
    mermaid = GENERATOR.get_graph().draw_mermaid()
    assert GENERATOR.name == "generator"
    for edge in ("__start__ --> gather;", "gather --> draft;", "draft -.-> materialize;", "materialize -.-> repair;",
                 "repair -.-> materialize;", "materialize -.-> __end__;"):
        assert edge in mermaid, mermaid
    assert create_generator_agent().get_graph().draw_mermaid() == mermaid


def test_a_scripted_draft_flows_gather_draft_materialize_to_end(merged):
    runs, m = merged
    llm = FakeLLM([], drafts=[mop_draft()])
    out = asyncio.run(generate(task=TASK, runs=runs, generalized=m.generalized, fallback=m.workflow, llm=llm,
                               url="https://www.youtube.com", name="mop"))
    assert not out.used_fallback and out.validated and out.repairs_used == 0 and out.rejections == []
    assert out.workflow.accept_states and "${fast_forward_presses}" in json.dumps(out.workflow.model_dump(mode="json"))
    # the prompt: the system rules, then the evidence with a reference on every step line
    assert len(llm.drafted) == 1
    [block] = llm.drafted[0]
    assert block["text"].startswith(f"TASK: {TASK}") and block["text"].endswith("WorkflowDraft:")
    assert "r1.s4.0" in block["text"] and "2:structural(18@0)" in block["text"]
    assert "never author content" in GENERATOR_SYSTEM and "Copy those references verbatim" in GENERATOR_SYSTEM


def test_rejections_drive_a_bounded_repair_loop(merged):
    runs, m = merged
    bad = mop_draft()
    bad.main[3].target = LocatorRef(step=VIDEO_CLICK[1], rung=7, nth=0)  # no such rung
    llm = FakeLLM([], drafts=[bad, mop_draft()])
    out = asyncio.run(generate(task=TASK, runs=runs, generalized=m.generalized, fallback=m.workflow, llm=llm))
    assert out.repairs_used == 1 and out.rejections == [] and not out.used_fallback
    assert len(llm.drafted) == 2
    repair_text = llm.drafted[1][0]["text"]
    assert "YOUR PREVIOUS DRAFT:" in repair_text and "REJECTED:" in repair_text
    assert "main[3].target (r1.s4.0): rung 7 was not recorded" in repair_text
    assert "Fix only what was rejected" in REPAIR_SYSTEM
    (click,) = [t for t in out.workflow.transitions if t.id == "t4"]
    assert click.action.locator[-1].fn == "nth"


def test_repair_budget_is_bounded_and_a_worse_repair_is_not_kept(merged):
    runs, m = merged
    bad = mop_draft()
    bad.main[3].target = LocatorRef(step=VIDEO_CLICK[1], rung=7, nth=0)
    worse = mop_draft(main=[])  # a repair that throws the main path away
    llm = FakeLLM([], drafts=[bad, worse, bad])
    out = asyncio.run(generate(task=TASK, runs=runs, generalized=m.generalized, fallback=m.workflow, llm=llm,
                               max_repairs=2))
    assert out.repairs_used == 2 and len(llm.drafted) == 3
    assert not out.used_fallback and len(out.rejections) == 1  # `bad`'s outcome, not `worse`'s fallback
    assert any("was worse" in w for w in out.warnings)


def test_no_draft_means_the_merge_artifact_verbatim(merged):
    runs, m = merged
    out = asyncio.run(generate(task=TASK, runs=runs, generalized=m.generalized, fallback=m.workflow, llm=FakeLLM([])))
    assert out.used_fallback and out.workflow == m.workflow and out.draft is None
    assert any("returned no draft" in w for w in out.warnings)
    out = asyncio.run(generate(task=TASK, runs=runs, generalized=m.generalized, fallback=m.workflow, llm=None))
    assert out.used_fallback and "no LLM" in out.warnings[0]


def test_facade_and_repair_content_are_pure(merged):
    runs, m = merged
    agent = GeneratorAgent(FakeLLM([], drafts=[mop_draft()]), max_repairs=1)
    out = asyncio.run(agent.run(TASK, runs, m.generalized, m.workflow, name="mop"))
    assert not out.used_fallback
    ctx = GeneratorContext(task=TASK, runs=tuple(runs), generalized=m.generalized, fallback=m.workflow,
                           prior=(RoundRecord(round=1, draft_outcomes=out.outcomes[:2], used_fallback=True),))
    ev = gather_evidence(ctx)
    assert "PREVIOUS ATTEMPTS" in ev.render() and "round 1: the draft was discarded" in ev.render()
    [block] = build_generator_content(ev)
    [rblock] = build_repair_content(ev, mop_draft(), ["main[0]: x"])
    assert rblock["text"].startswith(block["text"][: -len("\n\nWorkflowDraft:")])  # a stable prefix
    with pytest.raises(ValueError):
        GeneratorAgent(None, max_repairs=-1)
