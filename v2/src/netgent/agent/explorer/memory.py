"""Cross-run memory for ONE explorer working several tasks (a sweep), plus the settle watcher.

A class because it owns an `asyncio.Task` with a lifecycle — the same reason langmem's
`LocalReflectionExecutor` is a class, and the same reason nothing here can move into graph
state (state is per-run) or into a checkpoint (a Task will not serialize). Swap this for a
`BaseStore`-backed implementation to run on LangGraph Platform; the four methods below are
the whole interface (docs/research/langgraph-agent-structure.md §3b, §5.2).
"""

import asyncio
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # agent.py imports this module; keep the cycle type-only until Agent is gone
    from netgent.agent.explorer.agent import StepRecord

FOLD_MIN_STEPS = 4  # note() folds the preceding task's records once it has at least this many
MAX_FOLDS = 5  # folded task summaries kept (oldest dropped)


class ExplorerMemory:
    def __init__(self) -> None:
        # Persists across explore() calls, so ONE memory can span several tasks (e.g. every
        # form in a sweep) — what worked on an earlier task informs the next.
        self.history: list["StepRecord"] = []
        # Text that appeared after an action while the model was deciding (graph._watch_texts):
        # drained into history + texts_seen at the next step, and into the trajectory at the end.
        self.noticed: list[str] = []
        self._watch: asyncio.Task | None = None

    def start_watch(self, coro) -> None:
        self.stop_watch()
        self._watch = asyncio.create_task(coro)

    def stop_watch(self) -> None:
        if self._watch is not None and not self._watch.done():
            self._watch.cancel()
        self._watch = None

    def drain_noticed(self) -> list[str]:
        out, self.noticed[:] = list(self.noticed), []
        return out

    def note(self, text: str) -> None:
        """Append a marker to the memory (e.g. 'moving on to form 3 of 21') AND fold the
        preceding task's step records into one summary line, so a sweep keeps what it
        learned two forms ago instead of losing it to the history window. Zero-LLM: the task
        boundary is known here, so no summariser is needed (memory doc §6.2d)."""
        from netgent.agent.explorer.agent import StepRecord

        acted = [r for r in self.history if r.kind not in ("note", "fold")]
        folds = [r for r in self.history if r.kind == "fold"]
        if len(acted) >= FOLD_MIN_STEPS:
            ok = sum(1 for r in acted if r.outcome in ("ok", "waited"))
            failures: list[str] = []
            for r in acted:
                if r.outcome == "failed" and r.error and r.error[:80] not in failures:
                    failures.append(r.error[:80])
            last_memory = next((r.memory for r in reversed(acted) if r.memory), "")
            summary = f"(earlier task: {len(acted)} steps, {ok} ok, {len(acted) - ok} failed"
            if failures:
                summary += "; failures: " + " | ".join(failures[:3])
            if last_memory:
                summary += f"; last memory: {last_memory}"
            summary += ")"
            self.history[:] = [*folds[-(MAX_FOLDS - 1):], StepRecord(n=0, kind="fold", note=summary)]
        elif acted:  # too few to summarise: keep them verbatim, drop the old note
            self.history[:] = [*folds[-MAX_FOLDS:], *acted]
        self.history.append(StepRecord(n=0, kind="note", note=text))
