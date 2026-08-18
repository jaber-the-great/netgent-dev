"""On-demand JSON Schema generation from the pydantic models.

Nothing is committed to disk — the pydantic models ARE the schema. Use
`netgent schema workflow` to print one (e.g. for editor validation or an
external consumer), or --write to materialize copies somewhere yourself.
"""

import json
from pathlib import Path
from typing import Any

from netgent.schema.records import RunRecord
from netgent.schema.workflow import Workflow

SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"

SCHEMAS: dict[str, type] = {
    "workflow": Workflow,
    "run-record": RunRecord,
}


def generate(name: str) -> dict[str, Any]:
    """Generate the JSON Schema for a named artifact ('workflow' or 'run-record')."""
    schema = SCHEMAS[name].model_json_schema()
    return {"$schema": SCHEMA_DIALECT, **schema}


def render(name: str) -> str:
    return json.dumps(generate(name), indent=2) + "\n"


def write_all(directory: Path) -> list[Path]:
    """Write every schema into `directory` as <name>.schema.json; returns written paths."""
    directory.mkdir(parents=True, exist_ok=True)
    written = []
    for name in SCHEMAS:
        path = directory / f"{name}.schema.json"
        path.write_text(render(name))
        written.append(path)
    return written
