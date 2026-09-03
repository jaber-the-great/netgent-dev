"""Core model invariants: JSON/YAML equivalence, graph validation, locator whitelist."""

import pytest
from pydantic import ValidationError

from netgent.core.errors import ControlSequenceError
from netgent.executor.engine import Executor
from netgent.schema.actions import DEFAULT_TIMEOUT_MS, ClickAction, GotoAction, LocatorStep, NoopAction
from netgent.schema.workflow import State, Transition, Workflow, dump_workflow, load_workflow


def make_workflow(**overrides) -> Workflow:
    data = dict(
        name="demo",
        start_state="home",
        states=[
            State(id="home", conditions=[{"type": "url_matches", "pattern": "example\\.com"}]),
            State(id="done", conditions=[{"type": "selector_visible", "selector": "#result"}]),
        ],
        transitions=[
            Transition(
                id="t1",
                source="home",
                target="done",
                action=ClickAction(locator=[LocatorStep(fn="get_by_role", args=["button"], kwargs={"name": "Go"})]),
            )
        ],
    )
    data.update(overrides)
    return Workflow(**data)


def test_version_defaults_and_round_trips(tmp_path):
    assert make_workflow().version == "1"
    wf = make_workflow(version="2")
    path = tmp_path / "wf.yaml"
    dump_workflow(wf, path)
    assert load_workflow(path).version == "2"


def test_version_must_be_a_simple_integer_string():
    with pytest.raises(ValidationError, match="version"):
        make_workflow(version="2026-08-17.1")
    with pytest.raises(ValidationError, match="version"):
        make_workflow(version="v2")
    with pytest.raises(ValidationError, match="version"):
        make_workflow(version="0")


def test_run_record_carries_workflow_version():
    import asyncio

    class FakeSession:
        async def dispatch(self, action):
            pass

        async def wait_for_state(self, state):
            return 0.0

        async def condition_report(self, state):
            return []

        class page:
            url = "https://example.com"

    record = asyncio.run(Executor(FakeSession(), make_workflow(version="7")).run())
    assert record.workflow_version == "7"


def test_json_and_yaml_load_identically(tmp_path):
    wf = make_workflow()
    json_path, yaml_path = tmp_path / "wf.json", tmp_path / "wf.yaml"
    dump_workflow(wf, json_path)
    dump_workflow(wf, yaml_path)
    assert load_workflow(json_path) == load_workflow(yaml_path) == wf


def test_unsupported_extension_rejected(tmp_path):
    path = tmp_path / "wf.toml"
    path.write_text("")
    with pytest.raises(ValueError, match="unsupported workflow format"):
        load_workflow(path)


def test_unknown_state_reference_rejected():
    with pytest.raises(ValidationError, match="unknown target state"):
        make_workflow(
            transitions=[Transition(id="t1", source="home", target="nowhere", action=NoopAction())]
        )


def test_unknown_start_state_rejected():
    with pytest.raises(ValidationError, match="start_state"):
        make_workflow(start_state="nowhere")


def test_duplicate_state_ids_rejected():
    with pytest.raises(ValidationError, match="duplicate state ids"):
        make_workflow(states=[State(id="home"), State(id="home"), State(id="done")])


def test_control_sequence_must_reference_known_transitions():
    with pytest.raises(ValidationError, match="unknown transitions"):
        make_workflow(control_sequence=["t1", "missing"])


def test_locator_fn_whitelist_enforced():
    with pytest.raises(ValidationError, match="not in the replay whitelist"):
        LocatorStep(fn="evaluate", args=["alert(1)"])


def test_action_timeout_zero_becomes_default():
    assert GotoAction(url="https://example.com", timeout_ms=0).timeout_ms == DEFAULT_TIMEOUT_MS


def test_all_action_types_round_trip():
    from typing import get_args

    from netgent.schema import Action, GoBackAction, HoverAction, Workflow

    union_members = get_args(get_args(Action)[0])
    assert GoBackAction in union_members and HoverAction in union_members
    assert len(union_members) == 11

    for action in (
        GoBackAction(),
        HoverAction(locator=[LocatorStep(fn="get_by_role", args=["link"], kwargs={"name": "Menu"})]),
    ):
        wf = make_workflow(transitions=[Transition(id="t1", source="home", target="done", action=action)])
        reloaded = Workflow.model_validate(wf.model_dump(mode="json"))
        assert type(reloaded.transitions[0].action) is type(action)


def test_action_union_round_trips_through_dict():
    wf = make_workflow()
    reloaded = Workflow.model_validate(wf.model_dump(mode="json"))
    action = reloaded.transitions[0].action
    assert isinstance(action, ClickAction)
    assert action.locator[0].fn == "get_by_role"


def test_executor_rejects_non_walkable_sequence():
    # t1 goes home->done; a sequence firing it twice is not walkable from `done`.
    import asyncio

    wf = make_workflow(control_sequence=["t1", "t1"])

    class FakeSession:
        async def dispatch(self, action):
            pass

        async def wait_for_state(self, state):
            return 0.0

        async def condition_report(self, state):
            return []

        class page:
            url = "https://example.com"

    executor = Executor(FakeSession(), wf)
    with pytest.raises(ControlSequenceError, match="current state is 'done'"):
        asyncio.run(executor.run())


def test_executor_walks_sequence_with_fake_session():
    import asyncio

    wf = make_workflow()

    class FakeSession:
        async def dispatch(self, action):
            pass

        async def wait_for_state(self, state):
            return 1.5

        async def condition_report(self, state):
            return []

        class page:
            url = "https://example.com/done"

    record = asyncio.run(Executor(FakeSession(), wf).run())
    assert record.success
    assert [e.outcome for e in record.edges] == ["ok"]
    assert record.edges[0].url_after == "https://example.com/done"


def test_locator_chain_is_type_checked_at_load_time():
    """R3: a schema-legal step sequence that can never resolve is rejected when the artifact
    loads, not as an AttributeError at replay (FrameLocator has no filter/fill)."""
    from netgent.schema.actions import FillAction, LocatorStep, validate_locator_chain

    frame = LocatorStep(fn="frame_locator", args=["iframe#pay"])
    css = LocatorStep(fn="locator", args=["#card"])
    # legal: frames, then the element; nth may follow a frame_locator (FrameLocator.nth exists)
    validate_locator_chain([frame, frame, css])
    validate_locator_chain([frame, LocatorStep(fn="nth", args=[1]), css])
    validate_locator_chain([css, LocatorStep(fn="filter", kwargs={"has_text": "x"}), LocatorStep(fn="nth", args=[0])])
    with pytest.raises(ValidationError, match="ends on a frame_locator"):
        FillAction(locator=[frame], text="x")
    with pytest.raises(ValidationError, match="cannot follow a 'frame' receiver"):
        ClickAction(locator=[frame, LocatorStep(fn="filter", kwargs={"has_text": "x"}), css])
    with pytest.raises(ValidationError, match="cannot follow a 'page' receiver"):
        ClickAction(locator=[LocatorStep(fn="nth", args=[0]), css])
    with pytest.raises(ValidationError, match="empty"):
        ClickAction(locator=[])


def test_actions_carry_the_closed_shadow_capability_flag():
    """R8: the flag defaults False (existing artifacts unchanged) and round-trips."""
    from netgent.schema.actions import FillAction, LocatorStep

    plain = FillAction(locator=[LocatorStep(fn="locator", args=["#a"])], text="x")
    assert plain.requires_closed_shadow is False
    flagged = FillAction(
        locator=[LocatorStep(fn="locator", args=["#ci"])], text="x", requires_closed_shadow=True
    )
    assert FillAction.model_validate(flagged.model_dump()).requires_closed_shadow is True


def test_dialog_matches_trigger_round_trips():
    from netgent.schema.triggers import DialogMatches
    from netgent.schema.workflow import State

    state = State(id="submitted", conditions=[{"type": "dialog_matches", "pattern": "alert: Form submitted"}])
    assert isinstance(state.conditions[0], DialogMatches)
    assert State.model_validate(state.model_dump()).conditions[0].pattern == "alert: Form submitted"


def _interrupt_workflow(**interrupt_overrides) -> Workflow:
    """A 2-edge word plus an ad pop-up interrupt anchored on #ad, resolved by one click."""
    interrupt = dict(
        id="ad",
        state="s_ad",
        resolve=["t_skip"],
        scope=["home"],
        max_fires=2,
    )
    interrupt.update(interrupt_overrides)
    return Workflow(
        name="demo",
        start_state="home",
        states=[
            State(id="home", conditions=[{"type": "url_matches", "pattern": "example\\.com"}]),
            State(id="done", conditions=[{"type": "selector_visible", "selector": "#result"}]),
            State(id="s_ad", conditions=[{"type": "selector_visible", "selector": "#ad"}]),
            State(id="s_ad_gone", conditions=[{"type": "selector_hidden", "selector": "#ad"}]),
        ],
        transitions=[
            Transition(
                id="t1",
                source="home",
                target="done",
                action=ClickAction(locator=[LocatorStep(fn="locator", args=["#go"])]),
            ),
            Transition(
                id="t_skip",
                source="s_ad",
                target="s_ad_gone",
                action=ClickAction(locator=[LocatorStep(fn="locator", args=["#skip"])]),
            ),
        ],
        control_sequence=["t1"],  # the word: resolution edges are NOT word members
        interrupts=[interrupt],
    )


def test_interrupt_validation():
    wf = _interrupt_workflow()
    assert wf.interrupts[0].max_fires == 2
    with pytest.raises(ValidationError, match="unknown state"):
        _interrupt_workflow(state="nope")
    with pytest.raises(ValidationError, match="unknown scope states"):
        _interrupt_workflow(scope=["nope"])
    with pytest.raises(ValidationError, match="unknown resolve transitions"):
        _interrupt_workflow(resolve=["nope"])
    with pytest.raises(ValidationError, match="resolution must chain from the interrupt state"):
        _interrupt_workflow(resolve=["t1"])  # t1 fires from home, not from s_ad
    with pytest.raises(ValidationError):
        _interrupt_workflow(max_fires=0)  # the red-line backstop is mandatory and positive
    with pytest.raises(ValidationError):
        _interrupt_workflow(scope=[])  # in-scope ε-edges, never global-by-omission


def test_executor_sweeps_interrupt_then_continues():
    import asyncio

    wf = _interrupt_workflow()
    fired: list[str] = []

    class FakeSession:
        def __init__(self):
            self.ad_showing = True

        async def dispatch(self, action):
            fired.append(getattr(action, "locator", [LocatorStep(fn="locator", args=["?"])])[0].args[0])
            if fired[-1] == "#skip":
                self.ad_showing = False

        async def wait_for_state(self, state):
            return 0.0

        async def condition_report(self, state):
            if state.id == "s_ad":
                return [("selector_visible", self.ad_showing)]
            return [(c.type, True) for c in state.conditions]

        class page:
            url = "https://example.com"

    record = asyncio.run(Executor(FakeSession(), wf).run())
    assert record.success
    # The sweep saw the ad before t1, resolved it, then the word proceeded.
    assert fired == ["#skip", "#go"]
    assert [e.transition_id for e in record.edges] == ["t_skip", "t1"]


def test_executor_interrupt_respects_max_fires():
    import asyncio

    wf = _interrupt_workflow(max_fires=1)
    dispatched: list[str] = []

    class FakeSession:  # the "ad" never goes away — the cap must stop the loop, not the page
        async def dispatch(self, action):
            dispatched.append(action.type)

        async def wait_for_state(self, state):
            return 0.0

        async def condition_report(self, state):
            if state.id == "s_ad":
                return [("selector_visible", True)]
            return [(c.type, True) for c in state.conditions]

        class page:
            url = "https://example.com"

    record = asyncio.run(Executor(FakeSession(), wf).run())
    assert record.success
    skips = [e for e in record.edges if e.transition_id == "t_skip"]
    assert len(skips) == 1  # fired once, capped, word completed


def test_executor_refires_interrupt_when_popup_chains():
    """Chained pop-ups (YouTube 'ad 1 of 2'): dismissing the first re-shows the same
    selector, so the resolve edge's selector_hidden target never settles. Resolution is
    the anchor going away (or max_fires), so the sweep re-fires instead of aborting."""
    import asyncio

    from netgent.core.errors import TriggerTimeoutError

    wf = _interrupt_workflow(max_fires=3)
    skips_dispatched: list[str] = []

    class FakeSession:
        def __init__(self):
            self.ads_remaining = 2  # a chain of two ads, same #skip selector

        async def dispatch(self, action):
            sel = getattr(action, "locator", None)
            if sel and sel[0].args[0] == "#skip":
                skips_dispatched.append("#skip")
                self.ads_remaining -= 1

        async def wait_for_state(self, state):
            if state.id == "s_ad_gone" and self.ads_remaining > 0:
                # ad 2's skip button is already visible again: selector_hidden unmet
                raise TriggerTimeoutError("s_ad_gone", ["selector_hidden"], 10000)
            return 0.0

        async def condition_report(self, state):
            if state.id == "s_ad":
                return [("selector_visible", self.ads_remaining > 0)]
            return [(c.type, True) for c in state.conditions]

        class page:
            url = "https://example.com"

    record = asyncio.run(Executor(FakeSession(), wf).run())
    assert record.success
    assert skips_dispatched == ["#skip", "#skip"]  # both ads skipped, then the word ran
    skip_edges = [e for e in record.edges if e.transition_id == "t_skip"]
    assert [e.outcome for e in skip_edges] == ["recovered", "ok"]


def test_element_triggers_take_exactly_one_of_selector_or_locator():
    """An anchor names its element by a locator chain (the compiler's form — the very chain
    the guarded edge dispatches) OR by a selector string in a frame path; never both, never
    neither, and a chain carries its own frame steps."""
    from netgent.schema.actions import LocatorStep
    from netgent.schema.triggers import SelectorHidden, SelectorVisible

    chain = [LocatorStep(fn="frame_locator", args=["iframe"]),
             LocatorStep(fn="get_by_role", args=["link"], kwargs={"name": "Web icon An illustration of a"})]
    assert SelectorVisible(locator=chain).locator == chain
    assert SelectorHidden(selector="#x", frame_path=["iframe"]).frame_path == ["iframe"]
    with pytest.raises(ValueError, match="exactly one"):
        SelectorVisible()
    with pytest.raises(ValueError, match="exactly one"):
        SelectorVisible(selector="#x", locator=chain)
    with pytest.raises(ValueError, match="frame_path"):
        SelectorVisible(locator=chain, frame_path=["iframe"])
    with pytest.raises(ValueError):  # the chain is type-checked like an action's
        SelectorVisible(locator=[LocatorStep(fn="frame_locator", args=["iframe"])])
    # round-trips through the artifact form
    dumped = SelectorVisible(locator=chain).model_dump(mode="json")
    assert SelectorVisible.model_validate(dumped).locator == chain


def test_media_playing_min_position_is_a_number_or_one_param_reference():
    """The goal gate stays code-free: a number (with the unit coercion a Repeat count gets) or ONE
    ${param}; an expression is refused at the schema — a sum is a derived param."""
    from netgent.schema.triggers import MediaPlaying

    assert MediaPlaying(min_position_s=60).min_position_s == 60
    assert MediaPlaying(min_position_s="60s").min_position_s == "60s"
    assert MediaPlaying(min_position_s="${fast_forward_time}").min_position_s == "${fast_forward_time}"
    for bad in ("${a}+${b}", "${a} ${b}", "sixty", "${a}s"):
        with pytest.raises(ValidationError, match="single"):
            MediaPlaying(min_position_s=bad)


def test_a_goal_gate_must_be_recognized_within_the_settle_budget():
    """State recognition polls up to timeout_ms, and 1× playback satisfies any position floor given
    time (measured: a one-press replay of a 60 s seek passed after 56 s of polling). A state carrying
    media_playing.min_position_s therefore needs timeout_ms <= GOAL_GATE_MAX_TIMEOUT_MS at the schema."""
    from netgent.schema.triggers import GOAL_GATE_MAX_TIMEOUT_MS

    gate = {"type": "media_playing", "min_position_s": "${fast_forward_time}"}
    ok = make_workflow(states=[
        State(id="home", conditions=[{"type": "url_matches", "pattern": "example\\.com"}]),
        State(id="done", conditions=[gate], timeout_ms=GOAL_GATE_MAX_TIMEOUT_MS),
    ])
    assert ok.state("done").conditions[0].min_position_s == "${fast_forward_time}"
    with pytest.raises(ValidationError, match="pollable goal gate is vacuous"):
        make_workflow(states=[
            State(id="home", conditions=[{"type": "url_matches", "pattern": "example\\.com"}]),
            State(id="done", conditions=[gate]),  # the 10 s default
        ])
    # the same state without the floor may poll as long as it likes
    make_workflow(states=[
        State(id="home", conditions=[{"type": "url_matches", "pattern": "example\\.com"}]),
        State(id="done", conditions=[{"type": "media_playing", "min_duration_s": 120}], timeout_ms=130_000),
    ])
