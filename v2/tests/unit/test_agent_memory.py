"""The agent's typed memory: StepRecord rendering, the history window, fold-at-note
compaction, and the working-memory fields on the decision
(docs/research/browser-agent-memory.md §6)."""

from netgent.agent.explorer.browser_agent import FOLD_MIN_STEPS, MAX_FOLDS, BrowserAgent, StepRecord
from netgent.agent.explorer.decision import AgentDecision
from netgent.agent.llm import FULL_BLOCKS, HISTORY_WINDOW, decision_schema, render_history


def _rec(n, **kw):
    kw.setdefault("kind", "click")
    kw.setdefault("target", f"el{n}")
    kw.setdefault("reasoning", f"r{n}")
    return StepRecord(n=n, **kw)


def test_record_lines_carry_outcome_and_target_not_only_index():
    assert _rec(3, index=7).to_line() == "3. click(el3) r3"
    assert _rec(4, target="", index=7).to_line() == "4. click(7) r4"
    assert _rec(5, outcome="failed", error="boom").to_line().endswith("-> FAILED: boom")
    assert "DONE WAITING" in _rec(7, kind="wait", outcome="waited", error="waited 10s").to_line()
    assert StepRecord(n=0, kind="note", note="--- form 2 ---").to_line() == "--- form 2 ---"


def test_block_adds_the_models_own_fields_only_when_present():
    bare = _rec(1)
    assert bare.to_block() == bare.to_line()
    full = _rec(2, evaluation="Verdict: Success", memory="3 of 5 fields done", next_goal="submit")
    block = full.to_block()
    assert block.splitlines()[0] == full.to_line()
    assert "eval: Verdict: Success" in block and "memory: 3 of 5" in block and "goal: submit" in block


def test_history_window_keeps_folds_and_notes_beyond_the_acted_window():
    """The old history[-10:] erased a sweep's cross-form memory; folds/notes are always shown."""
    history = [StepRecord(n=0, kind="fold", note="(earlier task: 9 steps, 8 ok, 1 failed)"),
               StepRecord(n=0, kind="note", note="--- now working form 3 ---")]
    history += [_rec(i, memory=f"m{i}") for i in range(1, 25)]
    text = render_history(history)
    lines = text.splitlines()
    assert lines[0].startswith("(earlier task") and lines[1].startswith("--- now working")
    acted = [ln for ln in lines if ln[0].isdigit()]
    assert len(acted) == HISTORY_WINDOW and acted[0].startswith(f"{25 - HISTORY_WINDOW}.")
    assert sum("memory:" in ln for ln in lines) == FULL_BLOCKS  # only the last 3 get blocks
    assert render_history([]) == "(none yet)"


def test_note_folds_the_previous_task_into_one_line_and_keeps_failures_and_memory():
    class NoLLM:
        async def decide(self, *a, **k):
            raise AssertionError

    agent = BrowserAgent(NoLLM())
    agent.note("--- form 1 ---")
    agent.history += [_rec(1, memory="date wants YYYY-MM-DD"), _rec(2, outcome="failed", error="not an option"),
                      _rec(3), _rec(4, memory="submitted form 1")]
    agent.note("--- form 2 ---")
    kinds = [r.kind for r in agent.history]
    assert kinds == ["fold", "note"]
    fold = agent.history[0].note
    assert "4 steps, 3 ok, 1 failed" in fold and "not an option" in fold and "submitted form 1" in fold
    assert agent.history[1].note == "--- form 2 ---"
    # short tasks are kept verbatim rather than summarised; folds are bounded
    agent.history += [_rec(5)]
    agent.note("--- form 3 ---")
    assert [r.kind for r in agent.history] == ["fold", "click", "note"]
    for i in range(MAX_FOLDS + 3):
        agent.history += [_rec(j) for j in range(FOLD_MIN_STEPS)]
        agent.note(f"--- form {i + 4} ---")
    assert sum(r.kind == "fold" for r in agent.history) == MAX_FOLDS


def test_decision_memory_fields_default_empty_and_keep_reasoning_first():
    d = AgentDecision(reasoning="r", kind="click", index=1)
    assert (d.evaluation, d.memory, d.next_goal) == ("", "", "")
    names = list(AgentDecision.model_fields)
    assert names.index("reasoning") < names.index("kind")
    assert names.index("evaluation") < names.index("kind")


def test_memory_less_schema_variant_drops_exactly_the_three_fields():
    core = decision_schema(memory_fields=False)
    assert set(AgentDecision.model_fields) - set(core.model_fields) == {"evaluation", "memory", "next_goal"}
    assert decision_schema(True) is AgentDecision
    lite = core(reasoning="r", kind="fill", index=2, text="x")
    assert AgentDecision.model_validate(lite.model_dump()).text == "x"
