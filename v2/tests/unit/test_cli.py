"""CLI unit tests — no browser, no network, no LLM."""

from importlib import metadata

from typer.testing import CliRunner

from netgent.cli import cli_app

runner = CliRunner()


def test_help_lists_all_commands():
    result = runner.invoke(cli_app, ["--help"])
    assert result.exit_code == 0
    for command in ("run", "generate", "eval", "doctor"):
        assert command in result.output


def test_version_matches_package_metadata():
    result = runner.invoke(cli_app, ["--version"])
    assert result.exit_code == 0
    assert metadata.version("netgent") in result.output


def test_run_requires_existing_workflow_file():
    result = runner.invoke(cli_app, ["run", "does-not-exist.json"])
    assert result.exit_code == 2


def test_run_rejects_invalid_workflow_artifact(tmp_path):
    workflow = tmp_path / "workflow.json"
    workflow.write_text("{}")
    result = runner.invoke(cli_app, ["run", str(workflow)])
    assert result.exit_code == 1
    assert "invalid workflow artifact" in result.output


def test_generate_stub_exits_nonzero():
    result = runner.invoke(cli_app, ["generate", "prompts.json"])
    assert result.exit_code == 1


def test_doctor_runs_and_reports_checks(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # no .env here: doctor must still succeed with warnings
    result = runner.invoke(cli_app, ["doctor"])
    assert result.exit_code == 0
    assert "Python version" in result.output
    assert "LLM API keys" in result.output
