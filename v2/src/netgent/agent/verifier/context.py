"""What one verification run needs. Passed as LangGraph `Runtime.context`, never checkpointed —
the same slot the explorer uses (explorer/context.py). No langchain/langgraph import."""

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from netgent.agent.verifier.models import MAX_SCREENSHOTS

if TYPE_CHECKING:
    from netgent.agent.llm import LLM


@dataclass(frozen=True, slots=True)
class VerifierContext:
    # Run dependencies.
    llm: "LLM"
    run_dir: Path | None = None  # where the explorer left its screenshots (None: judge without images)
    # Knobs.
    max_screenshots: int = MAX_SCREENSHOTS

    def __post_init__(self) -> None:
        if self.max_screenshots < 0:
            raise ValueError("max_screenshots must be >= 0")
