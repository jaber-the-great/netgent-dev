

def test_parameter_value_envelope_is_unwrapped_and_foreign_objects_rejected():
    """Measured on Claude Code 2.1.x: for a schema with a dict field the CLI returned
    {"$PARAMETER_VALUE": "<json string>"}; validating that against an all-defaults model
    silently produced an empty instance (the planner 'returned no variations')."""
    import json

    import pytest
    from langchain_core.exceptions import OutputParserException
    from langchain_core.messages import AIMessage
    from pydantic import BaseModel, Field

    from langchain_claude_code.output_parsers import parse_structured_message

    class Item(BaseModel):
        text: str
        values: dict[str, str] = Field(default_factory=dict)

    class Plan(BaseModel):
        items: list[Item] = Field(default_factory=list)
        notes: list[str] = Field(default_factory=list)

    real = {"items": [{"text": "a", "values": {"q": "x"}}], "notes": []}
    wrapped_value = {"$PARAMETER_NAME": "plan", "$PARAMETER_VALUE": json.dumps(real)}
    envelope = {"structured_output": wrapped_value}
    wrapped = AIMessage(content="", additional_kwargs=envelope)
    assert parse_structured_message(wrapped, Plan).items[0].values == {"q": "x"}

    foreign = AIMessage(content="", additional_kwargs={"structured_output": {"something_else": 1}})
    with pytest.raises(OutputParserException):
        parse_structured_message(foreign, Plan)
