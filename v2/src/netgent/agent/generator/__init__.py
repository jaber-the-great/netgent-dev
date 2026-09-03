"""Generator — recordings in, ONE replayable workflow (NFA) out.

Three layers (docs/research/generator-agent-v2.md):

- `compiler.py` — one trajectory → NFA, pure code (the N = 1 path and the unit-test fixture).
- `merge.py` — N runs → the typed-key alignment with per-column dispositions and StepKeys (the
  cross-run EVIDENCE the agent reads) plus its own artifact (the FALLBACK). Pure code, zero LLM.
- the agent — `draft.py` (the WorkflowDraft: every leaf a pointer into the recordings),
  `evidence.py` (`gather`: the compact evidence), `materialize.py` (M1–M14 / I1–I6: resolve every
  pointer, reject what cannot be re-derived, fall back per region and wholesale below the floor),
  `models.py` (DraftOutcome, GenerateOutcome), `prompt.py`, `context.py` (GeneratorContext, passed
  as LangGraph `Runtime.context`), `agent.py` (`GeneratorAgent`, a thin façade), `graph.py`
  (gather → draft → materialize ⇄ repair, `create_generator_agent()`, the module-level
  `GENERATOR`, and `generate()` — the one run API). `generate`, `GENERATOR` and
  `create_generator_agent` import langgraph and are resolved lazily.

Zero LLM at run time is untouched: the agent runs at compile time only, and nothing it emits
reaches the artifact without materialize re-deriving it from a recording.
"""

from netgent.agent.generator.agent import GeneratorAgent
from netgent.agent.generator.compiler import compile_trajectory
from netgent.agent.generator.context import GeneratorContext
from netgent.agent.generator.draft import WorkflowDraft
from netgent.agent.generator.evidence import Evidence, gather_evidence
from netgent.agent.generator.materialize import materialize
from netgent.agent.generator.models import DraftOutcome, GenerateOutcome, acceptance_rate
from netgent.agent.generator.prompt import GENERATOR_SYSTEM, REPAIR_SYSTEM, build_generator_content

__all__ = [
    "GENERATOR",
    "GENERATOR_SYSTEM",
    "REPAIR_SYSTEM",
    "DraftOutcome",
    "Evidence",
    "GenerateOutcome",
    "GeneratorAgent",
    "GeneratorContext",
    "WorkflowDraft",
    "acceptance_rate",
    "build_generator_content",
    "compile_trajectory",
    "create_generator_agent",
    "gather_evidence",
    "generate",
    "materialize",
]

_LAZY = {"GENERATOR", "create_generator_agent", "generate"}


def __getattr__(name: str):  # PEP 562: the graph module imports langgraph
    if name in _LAZY:
        from netgent.agent.generator import graph

        return getattr(graph, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
