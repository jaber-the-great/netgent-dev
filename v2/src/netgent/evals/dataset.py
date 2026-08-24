"""The replay benchmark (`netgent eval dataset`): run a dataset of workflow artifacts, record pass/fail.

A dataset directory holds `*.workflow.yaml` artifacts plus the static fixtures they
drive. The harness serves the directory over a local HTTP server, substitutes `{base}`
in each workflow with the server root, runs it, and marks success = the run reached its
accepting state (record.success). Raw per-task results are written under a results dir
(decision #13: committed results make claims verifiable). No LLM, no live network.

This is the deterministic-replay eval. The LLM-judged, compile-from-spec eval arrives with
the `agent/` pipeline; this harness is its runnable skeleton.
"""

import functools
import http.server
import socketserver
import threading
from datetime import datetime, timezone
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from netgent.core.logger import get_logger
from netgent.schema.records import RunRecord
from netgent.schema.workflow import Workflow

logger = get_logger(__name__)


class EvalTaskResult(BaseModel):
    task: str
    workflow_name: str
    passed: bool
    edges: int
    duration_ms: float | None = None
    error: str | None = None


class EvalSummary(BaseModel):
    dataset: str
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    total: int = 0
    passed: int = 0
    tasks: list[EvalTaskResult] = Field(default_factory=list)

    @property
    def success_rate(self) -> float:
        return self.passed / self.total if self.total else 0.0


def _substitute(node: object, base: str) -> object:
    if isinstance(node, str):
        return node.replace("{base}", base)
    if isinstance(node, list):
        return [_substitute(x, base) for x in node]
    if isinstance(node, dict):
        return {k: _substitute(v, base) for k, v in node.items()}
    return node


def _load_workflow_with_base(path: Path, base: str) -> Workflow:
    data = _substitute(yaml.safe_load(path.read_text()), base)
    return Workflow.model_validate(data)


class _StaticServer:
    """A threaded static file server rooted at a directory, on an ephemeral port."""

    def __init__(self, directory: Path):
        handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(directory))
        socketserver.ThreadingTCPServer.allow_reuse_address = True
        self._httpd = socketserver.ThreadingTCPServer(("127.0.0.1", 0), handler)
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)

    @property
    def base(self) -> str:
        host, port = self._httpd.server_address
        return f"http://{host}:{port}"

    def __enter__(self) -> "_StaticServer":
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()


async def run_dataset(dataset_dir: Path, results_dir: Path, headless: bool = True) -> EvalSummary:
    """Run every *.workflow.yaml in dataset_dir; write results + trajectories to results_dir."""
    from netgent.browser.session import BrowserSession
    from netgent.executor.engine import Executor

    dataset_dir = Path(dataset_dir)
    results_dir = Path(results_dir)
    results_dir.mkdir(parents=True, exist_ok=True)
    workflows = sorted(dataset_dir.glob("*.workflow.yaml"))
    summary = EvalSummary(dataset=dataset_dir.name, total=len(workflows))

    with _StaticServer(dataset_dir) as server:
        for wf_path in workflows:
            task = wf_path.name.removesuffix(".workflow.yaml")
            try:
                wf = _load_workflow_with_base(wf_path, server.base)
                async with BrowserSession(headless=headless, stealth=True) as session:
                    record: RunRecord = await Executor(session, wf, run_dir=results_dir / task).run()
                result = EvalTaskResult(
                    task=task,
                    workflow_name=wf.name,
                    passed=record.success,
                    edges=len(record.edges),
                    duration_ms=record.duration_ms,
                    error=next((e.error for e in record.edges if e.error), None),
                )
            except Exception as exc:  # a broken task fails that task, not the whole run
                result = EvalTaskResult(task=task, workflow_name=task, passed=False, edges=0, error=str(exc))
            summary.tasks.append(result)
            summary.passed += int(result.passed)
            logger.info("eval %s: %s", task, "PASS" if result.passed else "FAIL")

    (results_dir / "summary.json").write_text(summary.model_dump_json(indent=2) + "\n")
    return summary
