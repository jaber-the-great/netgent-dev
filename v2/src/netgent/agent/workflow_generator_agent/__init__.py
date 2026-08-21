"""Workflow generator agent — trajectories in, a workflow (NFA) out.

Pure, deterministic code with no LLM and no browser: actions become transitions, observed
URLs become state conditions, and caller-named sample values become ${name} parameters.
(The explore→synthesize consolidation of MULTIPLE runs lives on the discovery branch and
joins this package when merged.)
"""

from netgent.agent.workflow_generator_agent.compiler import compile_trajectory

__all__ = ["compile_trajectory"]
