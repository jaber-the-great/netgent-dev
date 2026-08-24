"""`netgent eval` sub-app wiring: --help for every subcommand, matrix on synthetic results (no
browser); the browser-backed subcommands are covered in tests/integration/test_cli_eval_browser.py."""

import json

from typer.testing import CliRunner

from netgent.cli import cli_app

runner = CliRunner()


def test_eval_help_lists_subcommands():
    result = runner.invoke(cli_app, ["eval", "--help"])
    assert result.exit_code == 0
    for sub in ("dataset", "observation", "som", "stress", "matrix"):
        assert sub in result.output


def test_each_eval_subcommand_documents_what_it_measures():
    expectations = {
        "dataset": "Replay benchmark",
        "observation": "DOM walk vs accessibility tree",
        "som": "Set-of-Marks geometry",
        "stress": "sweep",
        "matrix": "comparison table",
    }
    for sub, phrase in expectations.items():
        result = runner.invoke(cli_app, ["eval", sub, "--help"])
        assert result.exit_code == 0, result.output
        assert phrase in result.output, f"{sub} --help should say what it measures"


def test_eval_with_no_subcommand_shows_help():
    result = runner.invoke(cli_app, ["eval"])
    assert "observation" in result.output


def test_stress_rejects_unknown_kind_and_backend():
    assert runner.invoke(cli_app, ["eval", "stress", "nope", "--backend", "ax"]).exit_code == 2
    assert runner.invoke(cli_app, ["eval", "stress", "sweep", "--backend", "nope"]).exit_code == 2


def test_observation_rejects_unknown_site():
    result = runner.invoke(cli_app, ["eval", "observation", "--sites", "not-a-site"])
    assert result.exit_code == 2 and "unknown site" in result.output


def test_matrix_assembles_from_result_json(tmp_path):
    stress = tmp_path / "stress"
    for i, score in enumerate((13, 15)):
        d = stress / f"challenge-hybrid-T-r{i}"
        d.mkdir(parents=True)
        (d / "result.json").write_text(json.dumps({
            "kind": "challenge", "score": score, "wall_s": 80.0,
            "usage": {"calls": 30, "input_tokens": 150_000, "output_tokens": 3000, "images": 30},
        }))
    out = tmp_path / "matrix"
    result = runner.invoke(cli_app, ["eval", "matrix", "--tags", "-T", "--results", str(stress), "--out", str(out)])
    assert result.exit_code == 0, result.output
    assert "**14.0**/15 (13, 15)" in result.output
    assert "40,950 (30 imgs)" in result.output  # 30 images × 1365 tokens, reported separately
    assert (out / "matrix.md").exists()


def test_matrix_with_no_results_still_succeeds(tmp_path):
    result = runner.invoke(cli_app, ["eval", "matrix", "--results", str(tmp_path), "--out", str(tmp_path / "m")])
    assert result.exit_code == 0 and "no results" in result.output
