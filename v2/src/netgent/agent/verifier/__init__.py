"""Verifier — an LLM judge of task completion (compile-time only; advisory).

Judges ONE question from page evidence: does the final state of the browser show that the
user's task was accomplished? It sees the task + params, the action log (what was dispatched,
never the explorer's reasoning), the final observation, every text seen during the run,
dialogs, the final URL and the last few screenshots. Its verdict routes the pipeline (a
"not achieved" re-explores with the unmet points appended); `netgent run` replaying the artifact
with zero LLM calls is the real proof. Rationale and numbers: docs/research/agent-verification.md,
verification-papers.md (LLM judges ≤69.8% precision; all four failure modes are sycophancy
toward the agent's own narration, hence the reasoning is withheld).

Same layout as the explorer: `models.py` (Evidence, Verdict), `prompt.py` (JUDGE_SYSTEM,
build_judge_content), `context.py` (VerifierContext — the LLM and screenshot dir, passed as
LangGraph `Runtime.context`), `agent.py` (`VerifierAgent`, a thin façade), `graph.py` (gather → judge
nodes, `create_verifier_agent()`, the module-level `VERIFIER`, and `verify()` — the one run API). `verify`, `VERIFIER`,
`create_verifier_agent` and `judge_trajectory` import langgraph and are resolved lazily.
"""

from netgent.agent.verifier.agent import VerifierAgent
from netgent.agent.verifier.context import VerifierContext
from netgent.agent.verifier.models import MAX_SCREENSHOTS, Evidence, Verdict
from netgent.agent.verifier.prompt import JUDGE_SYSTEM, build_judge_content

__all__ = [
    "JUDGE_SYSTEM",
    "MAX_SCREENSHOTS",
    "VERIFIER",
    "Evidence",
    "Verdict",
    "VerifierAgent",
    "VerifierContext",
    "build_judge_content",
    "create_verifier_agent",
    "judge_trajectory",
    "verify",
]

_LAZY = {"VERIFIER", "create_verifier_agent", "judge_trajectory", "verify"}


def __getattr__(name: str):  # PEP 562: the graph module imports langgraph
    if name in _LAZY:
        from netgent.agent.verifier import graph

        return getattr(graph, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
