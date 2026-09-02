"""The closed loop's planner (`plan_next`): one LLM call → the next round's variations,
scoped sub-tasks and TYPED generalization hints, normalized in code (≤ N runs, canonical
names, values verbatim, hints on existing columns, one per column)."""

import asyncio

import pytest

from netgent.agent import FakeLLM
from netgent.agent.generator.hints import GeneralizationHint, HintOutcome, RepeatFold, acceptance_rate
from netgent.agent.planner import (
    NextRoundPlan,
    ScopedSubtask,
    TaskVariation,
    build_next_round_content,
    normalize_next_round_plan,
)
from netgent.agent.rounds import (
    ColumnSummary,
    GeneralizedSummary,
    ParamSummary,
    ReplaySummary,
    RoundContext,
    RoundRecord,
    RunSummary,
)
from netgent.agent.triage import Episode

pytest.importorskip("langgraph")

from netgent.agent.planner.graph import NEXT_ROUND_PLANNER, create_next_round_planner, plan_next  # noqa: E402

TASK = "search YouTube for Dream Theater and play the first video, watch 20s, fast forward 30s"


def _context() -> RoundContext:
    gen = GeneralizedSummary(
        achieved_runs=[1, 2],
        params=[ParamSummary(name="search_query", default="Dream Theater",
                             values_by_run={1: "Dream Theater", 2: "Metallica"})],
        columns=[
            ColumnSummary(index=0, disposition="aligned", action_type="goto", transition="t1"),
            ColumnSummary(index=1, disposition="param", action_type="fill", param="search_query", transition="t2"),
            ColumnSummary(index=3, disposition="target-varies", action_type="click",
                          target='role=link[name="Under a Glass Moon" i]', runs=[1, 2], support=2, transition="t4"),
            ColumnSummary(index=5, disposition="aligned", action_type="press", transition="t5"),
        ],
        warnings=["column 3: click targets differ across runs and match no planned value — kept run 1's selector"],
        hints=[HintOutcome(hint=GeneralizationHint(column=3, intent="positional"), status="rejected",
                           reason="no structural rung on run 2")],
    )
    rd = RoundRecord(
        round=1,
        variations=[TaskVariation(task_text=TASK,
                                  values={"search_query": "Dream Theater", "fast_forward_seconds": "30s"}),
                    TaskVariation(task_text=TASK.replace("Dream Theater", "Metallica"),
                                  values={"search_query": "Metallica", "fast_forward_seconds": "20s"})],
        runs=[RunSummary(run=1, round=1, task_text=TASK, values={"search_query": "Dream Theater"}, achieved=True,
                         steps=12, usage={"calls": 12, "input_tokens": 1000, "output_tokens": 100}),
              RunSummary(run=2, round=1, task_text="…", values={"search_query": "Metallica"}, achieved=True,
                         attempts=2, steps=14, unmet=["the ad-skip click did not visibly skip the ad"])],
        generalized=gen,
        replay=[ReplaySummary(values={"search_query": "Dream Theater"}, success=True, signature=["s1", "s5"]),
                ReplaySummary(values={"search_query": "Metallica"}, success=False, signature=["s1", "FAILED@t4"],
                              failed_edge="t4", outcome="action_error", unmet=["selector_visible"])],
        episodes=[Episode(kind="positional_target", source="merge", column=3, transition="t4", action_type="click",
                          runs=[1, 2], observed={1: "role=link[name=a]", 2: "role=link[name=b]"},
                          replay_values={"search_query": "Metallica"}, confirmed_by_replay=True)],
        usage={"plan": {"calls": 1, "input_tokens": 500, "output_tokens": 50},
               "run-1": {"calls": 12, "input_tokens": 1000, "output_tokens": 100}},
    )
    return RoundContext(task=TASK, url="https://www.youtube.com", runs_per_round=3, max_rounds=3,
                        canonical_names=["search_query", "fast_forward_seconds"],
                        base_values={"search_query": "Dream Theater", "fast_forward_seconds": "30s"}, rounds=[rd])


def test_next_round_planner_is_one_compiled_graph():
    mermaid = NEXT_ROUND_PLANNER.get_graph().draw_mermaid()
    assert NEXT_ROUND_PLANNER.name == "next_round_planner"
    assert "__start__ --> draft_next_round;" in mermaid and "draft_next_round --> __end__;" in mermaid
    assert create_next_round_planner().get_graph().draw_mermaid() == mermaid


def test_prompt_carries_the_round_evidence_compactly():
    [block] = build_next_round_content(_context())
    text = block["text"]
    assert f"TASK: {TASK}" in text and "N (max runs next round): 3" in text
    assert "VALUE NAMES: search_query, fast_forward_seconds" in text
    assert "=== ROUND 1 ===" in text and "run 2: achieved in 2 attempt(s), 14 steps; unmet: the ad-skip" in text
    assert "column 3: target-varies click" in text and "t4]" in text
    assert "column 0" not in text  # aligned columns are not worth the tokens
    assert "hint column 3 positional: rejected — no structural rung" in text
    assert "replay {'search_query': 'Metallica'}: FAILED at t4 (action_error; unmet ['selector_visible'])" in text
    assert "episode: positional_target column 3 at t4 [merge, replay-confirmed]" in text
    assert text.endswith("Next round:")


def test_normalize_bounds_runs_fills_names_and_forces_values_verbatim():
    draft = NextRoundPlan(
        next_variations=[
            TaskVariation(task_text="search YouTube for Rush and play the first video",
                          values={"search_query": "Rush"}),
            TaskVariation(task_text="search YouTube for Tool and play the first video",
                          values={"search_query": "Tool", "speed": "2"}),  # not canonical: dropped
            TaskVariation(task_text="search YouTube for Yes", values={"search_query": "Opeth"}),  # not verbatim
            TaskVariation(task_text="   ", values={"search_query": "Kansas"}),  # empty: dropped
        ],
        scoped_subtasks=[ScopedSubtask(task_text="search for Rush and open the first result",
                                       start_url="https://www.youtube.com", values={"search_query": "Rush", "x": "1"})],
    )
    plan = normalize_next_round_plan(draft, n=3, canonical_names=["search_query", "fast_forward_seconds"],
                                     base_values={"search_query": "Dream Theater", "fast_forward_seconds": "30s"},
                                     columns=[0, 1, 3])
    assert [v.values for v in plan.next_variations] == [
        {"search_query": "Rush", "fast_forward_seconds": "30s"},
        {"search_query": "Tool", "fast_forward_seconds": "30s"},
        {"search_query": "Opeth", "fast_forward_seconds": "30s"},
    ]
    # the gap-filled base value and the non-verbatim value are written into the text
    assert plan.next_variations[0].task_text.endswith("Use fast_forward_seconds = '30s'.")
    assert "Use search_query = 'Opeth'." in plan.next_variations[2].task_text
    assert any("dropped value name(s) ['speed']" in n for n in plan.notes)
    assert any("empty task_text" in n for n in plan.notes)
    assert plan.scoped_subtasks == []  # three variations already spend N=3
    assert any("run budget is spent" in n for n in plan.notes)


def test_normalize_keeps_scoped_subtasks_within_the_budget_and_strips_unknown_values():
    draft = NextRoundPlan(
        next_variations=[TaskVariation(task_text="search YouTube for Rush", values={"search_query": "Rush"})],
        scoped_subtasks=[ScopedSubtask(task_text="search for Rush and open the first result",
                                       start_url="https://www.youtube.com", values={"search_query": "Rush", "x": "1"}),
                         ScopedSubtask(task_text="", start_url="https://www.youtube.com")],
    )
    plan = normalize_next_round_plan(draft, n=2, canonical_names=["search_query"], base_values={}, columns=[])
    (st,) = plan.scoped_subtasks
    assert st.values == {"search_query": "Rush"} and any("no task_text" in n for n in plan.notes)


def test_normalize_hints_need_an_existing_column_one_per_column_and_canonical_names():
    draft = NextRoundPlan(generalization_hints=[
        GeneralizationHint(column=3, intent="positional", why="the task says 'the first video'"),
        GeneralizationHint(column=3, intent="instance"),  # second hint for the column: dropped
        GeneralizationHint(column=9, intent="positional"),  # unknown column: dropped
        GeneralizationHint(column=5, intent="instance", param_name="not-a-name",
                           repeat_fold=RepeatFold(kind="press", count_param="Fast Forward")),
        GeneralizationHint(column=1, intent="text_contains_param", param_name="search_query"),
    ])
    plan = normalize_next_round_plan(draft, n=3, canonical_names=["search_query", "fast_forward_seconds"],
                                     base_values={}, columns=[0, 1, 3, 5])
    assert [(h.column, h.intent) for h in plan.generalization_hints] == [
        (3, "positional"), (5, "instance"), (1, "text_contains_param")]
    fold = plan.generalization_hints[1]
    assert fold.param_name is None and fold.repeat_fold is not None and fold.repeat_fold.count_param is None
    assert plan.generalization_hints[2].param_name == "search_query"
    assert sum("dropped a second hint" in n for n in plan.notes) == 1
    assert sum("unknown column 9" in n for n in plan.notes) == 1
    assert sum("is not canonical; cleared" in n for n in plan.notes) == 1
    assert sum("is not a canonical name; cleared" in n for n in plan.notes) == 1


def test_plan_next_runs_through_the_llm_seam_and_normalizes():
    draft = NextRoundPlan(
        next_variations=[TaskVariation(task_text="search YouTube for Rush and play the first video, watch 20s, "
                                                 "fast forward 30s", values={"search_query": "Rush"})],
        generalization_hints=[GeneralizationHint(column=3, intent="positional", why="'the first video'"),
                              GeneralizationHint(column=42, intent="positional")],
        notes=["Metallica replay failed at the title-keyed click"],
    )
    llm = FakeLLM([], verdicts=[draft])
    plan = asyncio.run(plan_next(_context(), llm=llm))
    assert [v.values for v in plan.next_variations] == [{"search_query": "Rush", "fast_forward_seconds": "30s"}]
    assert [h.column for h in plan.generalization_hints] == [3]
    assert "Metallica replay failed at the title-keyed click" in plan.notes and any("42" in n for n in plan.notes)
    text = llm.judged[0][0]["text"]
    assert "episode: positional_target column 3" in text  # the planner saw the evidence
    assert "Next round:" in text and "role=link[name=a]" in text


def test_round_context_helpers():
    ctx = _context()
    assert [c.index for c in ctx.latest_columns()] == [0, 1, 3, 5]
    assert ctx.all_values_seen() == [{"search_query": "Dream Theater"}, {"search_query": "Metallica"}]
    assert ctx.total_usage() == {"calls": 13, "input_tokens": 1500, "output_tokens": 150}
    assert ctx.current.hint_acceptance_rate() is None  # this round consumed no hints
    outcomes = [HintOutcome(hint=GeneralizationHint(column=3), status="applied"),
                HintOutcome(hint=GeneralizationHint(column=5), status="rejected", reason="x")]
    assert acceptance_rate(outcomes) == 0.5 and acceptance_rate([]) is None
    assert RoundContext.model_validate_json(ctx.model_dump_json()) == ctx  # persists as context.json
