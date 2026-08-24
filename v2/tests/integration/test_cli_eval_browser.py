"""`netgent eval` browser-backed subcommands on LOCAL fixtures — no network, no LLM.

- `eval dataset` on evals/datasets/forms (the existing replay benchmark; behaviour kept).
- `eval som` and `eval observation` on one local fixture page (name=file:// URL).
"""

from pathlib import Path

from typer.testing import CliRunner

from netgent.cli import cli_app

runner = CliRunner()
REPO = Path(__file__).resolve().parents[2]

FIXTURE = """<!doctype html><html><head><title>Local</title></head><body>
<h1>Local fixture</h1><p>Score: <span>0</span> / 2</p>
<label>Email <input id=email type=email required></label>
<label><input type=radio name=p value=a> Alpha</label>
<select id=c><option value="">Pick</option><option value=x>X</option></select>
<button id=go>Submit</button>
<div id=box style="height:60px;overflow-y:auto"><p style="height:300px">terms</p></div>
</body></html>"""


def test_eval_dataset_replays_local_fixtures(tmp_path):
    result = runner.invoke(cli_app, ["eval", "dataset", str(REPO / "evals/datasets/forms"), "--out", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "3/3 passed" in result.output
    assert (tmp_path / "summary.json").exists()


def test_eval_som_on_local_fixture(tmp_path):
    page = tmp_path / "page.html"
    page.write_text(FIXTURE)
    out = tmp_path / "som"
    result = runner.invoke(cli_app, ["eval", "som", "--sites", f"local={page.as_uri()}", "--out", str(out)])
    assert result.exit_code == 0, result.output
    assert (out / "som_check.md").exists() and (out / "som_check.json").exists()
    assert (out / "local.png").exists()  # the annotated screenshot
    assert "| local |" in result.output
    # every in-view element is marked and lands on its element
    import json

    row = json.loads((out / "som_check.json").read_text())[0]
    assert row["unmarked_in_view"] == 0 and row["miss"] == 0 and row["marks"] >= 5


def test_eval_observation_on_local_fixture(tmp_path):
    page = tmp_path / "page.html"
    page.write_text(FIXTURE)
    out = tmp_path / "obs"
    result = runner.invoke(
        cli_app, ["eval", "observation", "--sites", f"local={page.as_uri()}", "--backends", "dom,ax", "--out", str(out)]
    )
    assert result.exit_code == 0, result.output
    assert (out / "observation_ab.md").exists() and (out / "observation_ab.json").exists()
    assert "| local | dom |" in result.output and "| local | ax |" in result.output
