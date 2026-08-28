"""Verifier — an LLM judge of task completion (compile-time only; advisory).

Judges ONE question from page evidence: does the final state of the browser show that the
user's task was accomplished? It sees the task + params, the action log (what was dispatched,
never the explorer's reasoning), the final observation, every text seen during the run,
dialogs, the final URL and the last few screenshots. Its verdict routes the pipeline (a
"not achieved" re-explores with the unmet points appended) but never certifies the artifact —
the zero-LLM replay still gates. Rationale and numbers: docs/research/agent-verification.md,
verification-papers.md (LLM judges ≤69.8% precision; all four failure modes are sycophancy
toward the agent's own narration, hence the reasoning is withheld).
"""

from netgent.agent.verifier.judge import JUDGE_SYSTEM, Evidence, Verdict, build_judge_content, judge_trajectory

__all__ = ["JUDGE_SYSTEM", "Evidence", "Verdict", "build_judge_content", "judge_trajectory"]
