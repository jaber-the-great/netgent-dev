"""`netgent doctor` — check installation and configuration health (read-only)."""

import json
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import typer

MIN_PYTHON = (3, 11)

# Provider prefix in NETGENT_GENERATOR_MODEL -> env vars that can satisfy it.
PROVIDER_KEYS: dict[str, tuple[str, ...]] = {
    "gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
    "openai": ("OPENAI_API_KEY",),
    "anthropic": ("ANTHROPIC_API_KEY",),
}

CHROME_CANDIDATES = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
)


@dataclass
class CheckResult:
    name: str
    status: Literal["ok", "warn", "error"]
    detail: str
    hint: str | None = None


def _load_dotenv(path: Path) -> dict[str, str]:
    """Minimal .env parser (KEY=VALUE lines); real values in os.environ take precedence."""
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip("'\"")
    return values


def _env(env_file: dict[str, str], key: str) -> str:
    return os.environ.get(key) or env_file.get(key, "")


def _check_python() -> CheckResult:
    detail = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    if sys.version_info[:2] < MIN_PYTHON:
        return CheckResult(
            "Python version", "error", detail, hint=f"netgent requires Python >= {'.'.join(map(str, MIN_PYTHON))}"
        )
    return CheckResult("Python version", "ok", detail)


def _check_env_file(env_path: Path) -> CheckResult:
    if env_path.is_file():
        return CheckResult("Config (.env)", "ok", str(env_path))
    return CheckResult(
        "Config (.env)", "warn", "no .env found in current directory", hint="cp .env.example .env and fill it in"
    )


def _check_llm_keys(env_file: dict[str, str]) -> CheckResult:
    found = sorted(
        {key for keys in PROVIDER_KEYS.values() for key in keys if _env(env_file, key)}
    )
    model = _env(env_file, "NETGENT_GENERATOR_MODEL")
    provider = model.partition("/")[0] if "/" in model else ""

    if provider and provider in PROVIDER_KEYS:
        needed = PROVIDER_KEYS[provider]
        if not any(_env(env_file, key) for key in needed):
            return CheckResult(
                "LLM API keys",
                "error",
                f"{model} needs one of: {', '.join(needed)} (found: {', '.join(found) or 'none'})",
                hint="`netgent run` works without keys; `generate`/`eval` will fail",
            )
        return CheckResult("LLM API keys", "ok", f"{model} is covered (set: {', '.join(found)})")
    if found:
        return CheckResult("LLM API keys", "ok", f"set: {', '.join(found)}")
    return CheckResult(
        "LLM API keys",
        "warn",
        "no provider keys set",
        hint="only `netgent generate`/`eval` need one; set GEMINI_API_KEY, OPENAI_API_KEY, or ANTHROPIC_API_KEY",
    )


def _check_browser(env_file: dict[str, str]) -> CheckResult:
    configured = _env(env_file, "NETGENT_BROWSER_EXECUTABLE")
    if configured:
        if Path(configured).is_file():
            return CheckResult("Browser", "ok", configured)
        return CheckResult(
            "Browser", "error", f"NETGENT_BROWSER_EXECUTABLE not found: {configured}", hint="fix the path in .env"
        )
    for candidate in CHROME_CANDIDATES:
        if Path(candidate).is_file():
            return CheckResult("Browser", "ok", f"auto-detected: {candidate}")
    for name in ("google-chrome", "chromium", "chromium-browser"):
        path = shutil.which(name)
        if path:
            return CheckResult("Browser", "ok", f"auto-detected: {path}")
    return CheckResult(
        "Browser",
        "error",
        "no Chrome/Chromium found",
        hint="install Chrome or set NETGENT_BROWSER_EXECUTABLE in .env",
    )


def _check_credentials(env_file: dict[str, str]) -> CheckResult:
    configured = _env(env_file, "NETGENT_CREDENTIALS_FILE")
    if not configured:
        return CheckResult("Credentials file", "ok", "not set (optional)")
    path = Path(configured)
    if not path.is_file():
        return CheckResult("Credentials file", "error", f"not found: {configured}", hint="fix the path in .env")
    try:
        json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        return CheckResult("Credentials file", "error", f"invalid JSON in {configured}: {exc}")
    return CheckResult("Credentials file", "ok", str(path))


_STATUS_STYLE = {"ok": ("green", "✓"), "warn": ("yellow", "!"), "error": ("red", "✗")}


def doctor() -> None:
    """Check netgent installation and configuration health."""
    env_path = Path.cwd() / ".env"
    env_file = _load_dotenv(env_path)

    results = [
        _check_python(),
        _check_env_file(env_path),
        _check_llm_keys(env_file),
        _check_browser(env_file),
        _check_credentials(env_file),
    ]

    for result in results:
        color, symbol = _STATUS_STYLE[result.status]
        typer.secho(f" {symbol} {result.name}: ", fg=color, nl=False, bold=True)
        typer.echo(result.detail)
        if result.hint:
            typer.secho(f"   hint: {result.hint}", fg="bright_black")

    errors = sum(r.status == "error" for r in results)
    warns = sum(r.status == "warn" for r in results)
    typer.echo()
    if errors:
        typer.secho(f"{errors} error(s), {warns} warning(s)", fg="red", bold=True)
        raise typer.Exit(1)
    typer.secho(f"all checks passed ({warns} warning(s))", fg="green", bold=True)
