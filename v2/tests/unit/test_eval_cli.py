"""`netgent eval` sub-app wiring — help, validation, and the matrix on synthetic results (no browser/LLM)."""

import json

from typer.testing import CliRunner

from netgent.cli import cli_app

runner = CliRunner()


def test_eval_group_lists_subcommands():
    result = runner.invoke(cli_app, ["eval", "--help"])
    assert result.exit_code == 0
    for sub in ("dataset", "observation", "stress", "matrix"):
        assert sub in result.output


def test_each_subcommand_has_help():
    for sub in ("dataset", "observation", "stress", "matrix"):
        result = runner.invoke(cli_app, ["eval", sub, "--help"])
        assert result.exit_code == 0, sub
        assert "Usage" in result.output


def test_stress_validates_kind_and_backend(tmp_path):
    assert runner.invoke(cli_app, ["eval", "stress", "nope", "--out", str(tmp_path)]).exit_code == 2
    assert runner.invoke(cli_app, ["eval", "stress", "sweep", "--backend", "ax", "--out", str(tmp_path)]).exit_code == 2


def test_observation_rejects_unknown_site(tmp_path):
    result = runner.invoke(cli_app, ["eval", "observation", "--sites", "nonexistent-site", "--out", str(tmp_path)])
    assert result.exit_code == 2
    assert "unknown site" in result.output


def test_matrix_builds_table_from_synthetic_results(tmp_path):
    stress = tmp_path / "stress"
    for i, score in enumerate((13, 15)):
        d = stress / f"challenge-dom-M-r{i}"
        d.mkdir(parents=True)
        (d / "result.json").write_text(json.dumps({
            "kind": "challenge", "backend": "dom", "score": score, "wall_s": 60.0,
            "usage": {"calls": 30, "input_tokens": 100_000, "output_tokens": 3_000},
        }))
    out = tmp_path / "matrix"
    result = runner.invoke(cli_app, ["eval", "matrix", "--tags", "-M", "--results", str(stress), "--out", str(out)])
    assert result.exit_code == 0, result.output
    assert "**14.0**/15 (13, 15)" in result.output
    assert (out / "matrix.md").is_file()
