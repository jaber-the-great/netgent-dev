"""What one exploration run needs. Passed as LangGraph `Runtime.context`, never checkpointed
(measured: context is not written to the checkpoint — docs/research/langgraph-agent-structure.md
§3a). No langchain/langgraph import: this module is safe for `netgent.agent` to import eagerly."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from netgent.agent.explorer.decision import ALL_KINDS, DEFAULT_KINDS, MAX_BATCH
from netgent.agent.explorer.memory import ExplorerMemory
from netgent.browser.session import BrowserSession


@dataclass(frozen=True, slots=True)
class ExplorerContext:
    # Run dependencies — LangGraph's own words for this slot (langgraph/runtime.py:199-201).
    session: BrowserSession
    llm: Any  # an `LLM` (the seam); Any so pydantic can build tool schemas
    memory: ExplorerMemory
    task: str
    # Knobs.
    max_steps: int = 25
    frame_filter: list[str] | None = None  # focus on one form (iframe) for a sweep
    # The action kinds the explorer may emit. hover/press/goto are opt-in (decision.py
    # DEFAULT_KINDS); the prompt and the structured-output schema both reflect the set.
    allowed_kinds: frozenset[str] = DEFAULT_KINDS
    # How many atomic actions one decision may carry (1 = single-action semantics; up to
    # MAX_BATCH). Each executed item is still one AgentStep → one transition.
    max_actions_per_step: int = 1
    run_dir: Path | None = None  # screenshots + trajectory.json land here (None: keep nothing)
    # File offered to any file input via kind="upload". A default sample is created on demand
    # (graph.upload_path) so uploads work autonomously without the caller supplying one.
    upload_file: Path | None = None

    def __post_init__(self) -> None:
        if not 1 <= self.max_actions_per_step <= MAX_BATCH:
            raise ValueError(f"max_actions_per_step must be 1..{MAX_BATCH}")
        kinds = frozenset(self.allowed_kinds)
        unknown = kinds - ALL_KINDS
        if unknown:
            raise ValueError(f"unknown action kinds {sorted(unknown)}; choose from {sorted(ALL_KINDS)}")
        object.__setattr__(self, "allowed_kinds", kinds)  # frozen: normalise a set to a frozenset
