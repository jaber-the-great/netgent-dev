"""The structured-output parser undoes the CLI's envelopes before validating."""

import json

import pytest
from langchain_core.exceptions import OutputParserException
from langchain_core.messages import AIMessage
from pydantic import BaseModel

from langchain_claude_code.output_parsers import parse_structured_message, unwrap_envelope


class Variation(BaseModel):
    task_text: str
    values: dict[str, str] = {}


class Plan(BaseModel):
    variations: list[Variation] = []
    notes: list[str] = []


class Answer(BaseModel):
    answer: str


PLAN = {
    "variations": [{"task_text": "watch a cat video", "values": {"query": "cat"}}],
    "notes": ["n"],
}


def _msg(data):
    return AIMessage(content="", additional_kwargs={"structured_output": data})


def test_plain_object_is_validated_as_is():
    assert parse_structured_message(_msg(PLAN), Plan) == Plan.model_validate(PLAN)


def test_dict_valued_field_name_envelope_is_unwrapped():
    """Measured (Claude Code 2.1.257): a schema with a dict-valued field came back as
    {"<field>": "<the whole answer as a JSON string>"} — a plan with no variations after
    validation, which cost a whole round of identical exploration runs."""
    wrapped = {"values": json.dumps(PLAN)}
    assert unwrap_envelope(wrapped, Plan) == PLAN
    assert parse_structured_message(_msg(wrapped), Plan).variations[0].values == {"query": "cat"}


def test_parameter_value_envelope_and_nesting_are_unwrapped():
    nested = {"$PARAMETER_VALUE": json.dumps({"result": json.dumps(PLAN)})}
    assert unwrap_envelope(nested, Plan) == PLAN


def test_parameter_name_value_pair_is_unwrapped():
    """Measured (Claude Code 2.1.257): the tool-parameter wrapper with BOTH keys — it read as an
    empty plan and ended a closed-loop compile at round 1 ("the planner proposed no runs")."""
    pair = {"$PARAMETER_NAME": "response", "$PARAMETER_VALUE": json.dumps(PLAN)}
    assert unwrap_envelope(pair, Plan) == PLAN
    assert parse_structured_message(_msg(pair), Plan).variations[0].task_text == "watch a cat video"
    # a two-key dict that is NOT the wrapper stays as it is
    other = {"$PARAMETER_VALUE": json.dumps(PLAN), "extra": 1}
    assert unwrap_envelope(other, Plan) == other


def test_a_genuine_single_string_field_is_left_alone():
    """{"answer": "{...}"} where `answer` IS the schema's string field and the inner object
    carries none of the schema's properties: not an envelope."""
    data = {"answer": json.dumps({"foo": 1})}
    assert unwrap_envelope(data, Answer) == data
    assert parse_structured_message(_msg(data), Answer).answer == json.dumps({"foo": 1})
    plain = {"answer": "four"}
    assert unwrap_envelope(plain, Answer) == plain


def test_text_fallback_is_unwrapped_too():
    msg = AIMessage(content=json.dumps({"values": json.dumps(PLAN)}))
    assert parse_structured_message(msg, Plan).notes == ["n"]
    with pytest.raises(OutputParserException):
        parse_structured_message(AIMessage(content="not json"), Plan)


def test_an_object_sharing_no_field_with_the_schema_is_rejected():
    """A model whose fields all have defaults would otherwise validate a foreign object into
    an empty instance — silently (how 'planner returned no variations' first showed up)."""
    foreign = AIMessage(content="", additional_kwargs={"structured_output": {"something_else": 1}})
    with pytest.raises(OutputParserException):
        parse_structured_message(foreign, Plan)
