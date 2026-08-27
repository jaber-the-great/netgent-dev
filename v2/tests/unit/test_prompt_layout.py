"""The system prompt's contract and the LLM seam's message layout (no model, no network)."""

from netgent.agent.explorer.browser_agent import StepRecord
from netgent.agent.explorer.decision import ALL_KINDS, DEFAULT_KINDS, AgentDecision
from netgent.agent.explorer.prompt import SYSTEM_PROMPT, build_system_prompt
from netgent.agent.llm import HISTORY_WINDOW, render_prompt


def test_prompt_lists_every_kind_the_schema_accepts():
    """Defect fixed: `upload` was mandated by a later rule but missing from the kind list."""
    kinds_line = next(ln for ln in SYSTEM_PROMPT.splitlines() if ln.startswith("- kind:"))
    for kind in ALL_KINDS:
        assert kind in kinds_line, kind
    assert "upload" in kinds_line and "done" not in kinds_line  # done is a boolean, not a kind


def test_prompt_reflects_the_allowed_kinds_only():
    default = build_system_prompt()
    kinds_line = next(ln for ln in default.splitlines() if ln.startswith("- kind:"))
    for kind in DEFAULT_KINDS:
        assert kind in kinds_line.split("(not available")[0], kind
    assert "not available in this task: hover, press, goto" in kinds_line
    assert "keys (press" not in default and "url (goto)" not in default
    with_press = build_system_prompt(DEFAULT_KINDS | {"press"})
    assert "keys (press" in with_press and "not available in this task: hover, goto" in with_press
    assert AgentDecision(reasoning="r", done=True, success=True).kind is None


def test_prompt_has_the_rule_sections_the_survey_converged_on():
    for section in ("OBSERVATION FORMAT", "GROUNDING", "OVERLAYS AND ADS", "DWELL", "DROPDOWNS", "SCROLLING",
                    "PARAMETERS", "HARD RULES"):
        assert section in SYSTEM_PROMPT, section
    assert "near the current viewport" not in SYSTEM_PROMPT  # the misdescribed slice
    assert "WITHOUT scrolling" in SYSTEM_PROMPT and "*[index]" in SYSTEM_PROMPT
    assert "never an instruction" in SYSTEM_PROMPT  # page text is evidence (injection rule)


def test_static_prefix_is_identical_across_steps_and_varying_parts_come_last():
    s1, d1 = render_prompt("SYS", "do it", "OBS 1", [])
    s2, d2 = render_prompt("SYS", "do it", "OBS 2", [StepRecord(n=1, kind="click", index=3, reasoning="ok")])
    assert s1 == s2 == "SYS\n\nTASK: do it"
    assert d1.startswith("RECENT STEPS:\n(none yet)") and d1.endswith("OBSERVATION:\nOBS 1\n\nNext action:")
    assert "1. click(3) ok" in d2 and d2.endswith("OBS 2\n\nNext action:")


def test_history_window_is_bounded():
    hist = [StepRecord(n=i, kind="click", index=i) for i in range(30)]
    _, d = render_prompt("S", "T", "O", hist)
    assert "0. click(0)" not in d and f"{30 - HISTORY_WINDOW}. click(" in d and "29. click(29)" in d
