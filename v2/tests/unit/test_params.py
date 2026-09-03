"""ParamContext: static + dynamic resolution, validate guard, action substitution."""

import asyncio

import pytest

from netgent.core.errors import ParamError
from netgent.executor.params import ParamContext
from netgent.schema.actions import FillAction, GotoAction, LocatorStep
from netgent.schema.control import Param, ParamSource


class FakeSession:
    """Returns extracted values keyed by the source's selector (or None to simulate absence)."""

    def __init__(self, values: dict[str, str | None]):
        self._values = values

    async def extract_value(self, source, timeout_ms=5000):
        return self._values.get(source.selector)


def _ctx(params, provided=None, session=None):
    return ParamContext(params, provided, session or FakeSession({}))


def test_static_provided_default_and_missing_required():
    params = [
        Param(name="user"),
        Param(name="plan", required=False, default="free"),
    ]
    ctx = _ctx(params, provided={"user": "ada"})
    assert asyncio.run(ctx.value("user")) == "ada"
    assert asyncio.run(ctx.value("plan")) == "free"

    with pytest.raises(ParamError, match="missing required param 'user'"):
        _ctx([Param(name="user")])


def test_validate_guard_rejects_bad_value():
    with pytest.raises(ParamError, match="fails guard"):
        _ctx([Param(name="year", guard=r"^\d{4}$")], provided={"year": "abc"})


def test_dynamic_extraction_and_retry():
    params = [Param(name="conf", source=ParamSource(kind="text", selector="#c"))]
    ctx = _ctx(params, session=FakeSession({"#c": "ABC123"}))
    assert asyncio.run(ctx.value("conf")) == "ABC123"

    # extraction returns None, no default, required → ParamError (the healable signal)
    ctx2 = _ctx([Param(name="conf", source=ParamSource(kind="text", selector="#c"))], session=FakeSession({"#c": None}))
    with pytest.raises(ParamError, match="could not extract dynamic param 'conf'"):
        asyncio.run(ctx2.value("conf"))


def test_dynamic_value_checked_against_guard():
    params = [Param(name="conf", source=ParamSource(kind="text", selector="#c"), guard=r"^[A-Z]{3}\d+$")]
    ctx = _ctx(params, session=FakeSession({"#c": "lowercase"}))
    with pytest.raises(ParamError, match="fails guard"):
        asyncio.run(ctx.value("conf"))


def test_resolve_action_substitutes_fields():
    params = [
        Param(name="user", default="Ada Lovelace"),
        Param(name="conf", source=ParamSource(kind="text", selector="#c")),
    ]
    ctx = _ctx(params, session=FakeSession({"#c": "XYZ9"}))
    # static substitution in a fill
    fill = asyncio.run(ctx.resolve_action(FillAction(locator=[LocatorStep(fn="locator", args=["#n"])], text="${user}")))
    assert fill.text == "Ada Lovelace"
    # dynamic substitution in a goto URL (value pulled from the page)
    goto = asyncio.run(ctx.resolve_action(GotoAction(url="https://x/confirm/${conf}")))
    assert goto.url == "https://x/confirm/XYZ9"


def test_repeat_count_resolves_from_substituted_string():
    """Repeat.count="${p}" survives resolve_params as a numeric STRING (count keeps its str
    type); the executor coerces it, and still refuses unresolved or non-numeric counts."""
    import pytest

    from netgent.core.errors import ExecutionError
    from netgent.executor.engine import Executor
    from netgent.schema.workflow import State, Workflow

    wf = Workflow(name="x", start_state="init", states=[State(id="init")], transitions=[])
    ex = Executor(session=None, workflow=wf)
    assert ex._resolve_count("10") == 10
    assert ex._resolve_count("7.0") == 7
    assert ex._resolve_count(3) == 3 and ex._resolve_count(None) is None
    with pytest.raises(ExecutionError, match="unresolved param"):
        ex._resolve_count("${watch_time}")
    with pytest.raises(ExecutionError, match="did not resolve to a number"):
        ex._resolve_count("abc")


def test_derived_param_is_computed_from_its_source_and_never_taken_from_the_caller():
    """G2 (generator-agent-v2.md §D.4): the artifact's knob stays the task's knob — fast_forward_time
    in seconds — and the press count is derived at resolve time: 35 s / 10 s per press → 4 (ceil)."""
    from netgent.schema.actions import NoopAction
    from netgent.schema.control import EdgeStep, Param, ParamDerivation, Repeat
    from netgent.schema.workflow import State, Transition, Workflow, resolve_params

    wf = Workflow(
        name="w", start_state="init", states=[State(id="init"), State(id="s1")],
        transitions=[Transition(id="t1", source="init", target="s1", action=NoopAction()),
                     Transition(id="t1_rep", source="s1", target="s1", action=NoopAction())],
        control=[EdgeStep(edge="t1"), Repeat(body=[EdgeStep(edge="t1_rep")], count="${presses}", max_iterations=12)],
        params=[Param(name="fast_forward_time", default="30s"),
                Param(name="presses", required=False,
                      derive=ParamDerivation(from_param="fast_forward_time", divide_by=10, rounding="ceil", min=1))],
    )
    assert resolve_params(wf, {}).control[1].count == "3"
    assert resolve_params(wf, {"fast_forward_time": "35"}).control[1].count == "4"
    assert resolve_params(wf, {"fast_forward_time": "45 seconds", "presses": "99"}).control[1].count == "5"
    assert resolve_params(wf, {"fast_forward_time": "3"}).control[1].count == "1"  # the floor
    floor = wf.model_copy(update={"params": [wf.params[0], wf.params[1].model_copy(
        update={"derive": ParamDerivation(from_param="fast_forward_time", divide_by=10, rounding="floor")})]})
    assert resolve_params(floor, {"fast_forward_time": "35"}).control[1].count == "3"
    import pytest

    with pytest.raises(ValueError, match="carries no number"):
        resolve_params(wf, {"fast_forward_time": "a while"})


def test_numbers_with_units_coerce_everywhere_a_param_feeds_a_number():
    """The live MOP re-run died at `repeat.count '30s'`: the planner writes durations with units, the
    dwell Repeat wanted a bare number. One coercion (schema/units.py) serves the executor's count, the
    derived param's source and the replay value sets — so `netgent run --param initial_watch_time=30s` works."""
    import pytest

    from netgent.core.errors import ExecutionError
    from netgent.executor.engine import Executor
    from netgent.schema.actions import NoopAction
    from netgent.schema.control import EdgeStep, Param, ParamDerivation, Repeat
    from netgent.schema.units import coerce_number, number_text
    from netgent.schema.workflow import State, Transition, Workflow, resolve_params

    assert [coerce_number(v) for v in ("30", "30.0", "30s", "30 s", "30sec", "30 seconds", "1m", "1 min", "1h", 7)] == [
        30.0, 30.0, 30.0, 30.0, 30.0, 30.0, 60.0, 60.0, 3600.0, 7.0]
    assert coerce_number("abc") is None and coerce_number("s30") is None and coerce_number("30 parsecs") is None
    assert number_text("30s") == "30" and number_text("2.5s") == "2.5" and number_text("x") is None
    wf = Workflow(name="x", start_state="init", states=[State(id="init")], transitions=[])
    ex = Executor(session=None, workflow=wf)
    assert ex._resolve_count("30s") == 30 and ex._resolve_count("1m") == 60 and ex._resolve_count("10") == 10
    with pytest.raises(ExecutionError, match="did not resolve to a number"):
        ex._resolve_count("abc")
    # a Repeat whose count resolves from '30s', end to end through resolve_params + the executor
    timed = Workflow(
        name="w", start_state="init", states=[State(id="init"), State(id="s1")],
        transitions=[Transition(id="t1", source="init", target="s1", action=NoopAction()),
                     Transition(id="t1_dwell", source="s1", target="s1", action=NoopAction())],
        control=[EdgeStep(edge="t1"), Repeat(body=[EdgeStep(edge="t1_dwell")], count="${watch}", max_iterations=90)],
        params=[Param(name="watch", default="15"),
                Param(name="presses", required=False, derive=ParamDerivation(from_param="watch", divide_by=10))],
    )
    resolved = resolve_params(timed, {"watch": "30s"})
    assert resolved.control[1].count == "30s" and Executor(session=None, workflow=resolved)._resolve_count("30s") == 30
    assert resolve_params(timed, {"watch": "1m"}).params  # the derived source coerces '1m' → 60 → 6 presses
    from netgent.schema.workflow import derive_value

    assert derive_value("1m", ParamDerivation(from_param="watch", divide_by=10)) == "6"
    assert derive_value("35 s", ParamDerivation(from_param="watch", divide_by=10)) == "4"
