"""`netgent eval generator` — the offline compile eval (generator-agent-v2.md §J.3) on the stored
MOP bundle with a cached draft: zero LLM, no browser, the §J.2 metrics printed per compile."""

import asyncio
import json
from pathlib import Path

from test_materialize import mop_draft

from netgent.evals.generator import load_bundle, load_draft, run_generator_eval, table

FIX = Path(__file__).parent.parent / "fixtures" / "mop"


def test_load_bundle_reads_task_names_and_runs():
    task, url, names, runs = load_bundle(FIX)
    assert task.startswith("Go to youtube.com") and url == "https://www.youtube.com"
    assert names == ["video_query", "initial_watch_time", "fast_forward_time", "second_watch_time"]
    assert [r.run for r in runs] == list(range(1, 14)) and sum(r.achieved and not r.scoped for r in runs) == 8


def test_cached_draft_compiles_with_zero_llm_and_reports_the_metrics(tmp_path):
    draft_path = tmp_path / "draft.json"
    draft_path.write_text(json.dumps({"draft": mop_draft().model_dump(mode="json")}))
    assert load_draft(draft_path).spine == 1
    summary, md = asyncio.run(run_generator_eval(FIX, tmp_path / "out", draft_path=draft_path))
    assert summary["draft_acceptance_rate"] is not None and summary["rejected"] == 0 and not summary["used_fallback"]
    assert summary["validated"] and summary["accept_states_nonempty"] and summary["interrupts"] == 2
    assert summary["derived_params"] == ["fast_forward_presses"] and summary["param_recall"] == 1.0
    assert summary["positional_clicks"] == ["t4"]
    assert "| repairs_used | 0 |" in md and "cached draft" in summary["source"]
    assert (tmp_path / "out" / "workflow.yaml").is_file() and (tmp_path / "out" / "summary.json").is_file()
    assert "positional_clicks" in table(summary)
    bare = tmp_path / "bare.json"
    bare.write_text(mop_draft().model_dump_json())
    assert load_draft(bare).kept_runs == mop_draft().kept_runs
