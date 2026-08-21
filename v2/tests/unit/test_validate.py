"""relax(): drop exactly the conditions that blocked a state, nothing else. No browser."""

from netgent.agent.validate import relax
from netgent.schema.provenance import ValidationResult
from netgent.schema.workflow import State, Transition, Workflow


def _wf():
    return Workflow(
        name="w",
        start_state="init",
        states=[
            State(id="init"),
            State(
                id="s1",
                conditions=[{"type": "url_matches", "pattern": "x"}, {"type": "text_visible", "text": "hi"}],
            ),
            State(id="s2", conditions=[{"type": "selector_visible", "selector": "video"}]),
        ],
        transitions=[
            Transition(id="t1", source="init", target="s1", action={"type": "goto", "url": "https://x.test"}),
            Transition(id="t2", source="s1", target="s2", action={"type": "noop"}),
        ],
        accept_states=["s2"],
    )


def test_relax_drops_only_the_unmet_conditions_of_the_failed_state():
    failure = ValidationResult(params={}, success=False, failed_edge="t1", failed_state="s1", unmet=["text_visible"])
    wf, dropped = relax(_wf(), failure)
    assert dropped == ["s1: text_visible"]
    assert [c.type for c in wf.state("s1").conditions] == ["url_matches"]
    assert [c.type for c in wf.state("s2").conditions] == ["selector_visible"]  # untouched


def test_relax_accept_state_failure_drops_non_url_conditions():
    failure = ValidationResult(params={}, success=False, failed_state="s2", error="accept state did not hold")
    wf, dropped = relax(_wf(), failure)
    assert dropped == ["s2: selector_visible"] and wf.state("s2").conditions == []


def test_relax_has_nothing_for_action_errors():
    failure = ValidationResult(params={}, success=False, failed_edge="t1", failed_state=None, error="locator")
    wf, dropped = relax(_wf(), failure)
    assert dropped == [] and wf is not None
