"""`ExplorerAgent` for the create_agent arm — v1's façade with the same constructor and `run()`,
so the sweep and the stress eval can switch arms. `llm` is a chat model or its `provider:model`
string; `usage` mirrors LangChainLLM.usage from LangChain's usage callback."""

from pathlib import Path
from typing import TYPE_CHECKING, Any

from netgent.agent.explorer.context import ExplorerContext
from netgent.agent.explorer.decision import DEFAULT_KINDS
from netgent.agent.explorer.memory import ExplorerMemory
from netgent.agent.explorer.models import AgentTrajectory, StepRecord
from netgent.browser.session import BrowserSession

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel


class ExplorerAgent:
    def __init__(
        self,
        llm: "str | BaseChatModel",
        *,
        max_steps: int = 25,
        run_dir: Path | None = None,
        allowed_kinds: frozenset[str] | set[str] = DEFAULT_KINDS,
        max_actions_per_step: int = 1,
        upload_file: Path | None = None,
        memory: ExplorerMemory | None = None,
    ):
        self.llm = llm
        self.max_steps = max_steps
        self.run_dir = run_dir
        self.allowed_kinds = frozenset(allowed_kinds)
        self.max_actions_per_step = max_actions_per_step
        self.upload_file = upload_file
        self.memory = memory if memory is not None else ExplorerMemory()
        self._usage: Any = None
        ExplorerContext(  # validate the knobs now (the session is only known at run time)
            session=None, llm=llm, memory=self.memory, task="", max_steps=max_steps,  # type: ignore[arg-type]
            allowed_kinds=self.allowed_kinds, max_actions_per_step=max_actions_per_step, run_dir=run_dir,
            upload_file=upload_file,
        )

    @property
    def history(self) -> list[StepRecord]:
        return self.memory.history

    def note(self, text: str) -> None:
        self.memory.note(text)

    @property
    def usage(self) -> dict[str, int]:
        """Totals across run() calls, in LangChainLLM.usage's keys (calls unavailable: 0)."""
        meta = {}
        if self._usage is not None:
            for m in self._usage.usage_metadata.values():
                for k, v in m.items():
                    if isinstance(v, int):
                        meta[k] = meta.get(k, 0) + v
                details = m.get("input_token_details") or {}
                meta["cache_read"] = meta.get("cache_read", 0) + int(details.get("cache_read", 0) or 0)
        return {
            "calls": 0, "input_tokens": meta.get("input_tokens", 0), "output_tokens": meta.get("output_tokens", 0),
            "cache_read_tokens": meta.get("cache_read", 0), "cache_creation_tokens": 0,
        }

    async def run(
        self,
        session: BrowserSession,
        task: str,
        url: str | None = None,
        frame_filter: list[str] | None = None,
        max_steps: int | None = None,
    ) -> AgentTrajectory:
        from langchain_core.callbacks import UsageMetadataCallbackHandler

        from netgent.agent.explorer_v2.graph import explore

        if self._usage is None:
            self._usage = UsageMetadataCallbackHandler()
        return await explore(
            session, task, model=self.llm, memory=self.memory, url=url, frame_filter=frame_filter,
            max_steps=max_steps or self.max_steps, run_dir=self.run_dir, allowed_kinds=self.allowed_kinds,
            max_actions_per_step=self.max_actions_per_step, upload_file=self.upload_file, usage=self._usage,
        )
