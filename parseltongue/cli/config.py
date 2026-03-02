"""Configuration management for the Parseltongue CLI."""

from __future__ import annotations

import copy
import logging
import tomllib
from pathlib import Path
from typing import Any

log = logging.getLogger('parseltongue.cli')

CONFIG_DIR = Path.home() / ".parseltongue" / "cli"
CONFIG_FILE = CONFIG_DIR / "config.toml"

DEFAULTS: dict[str, Any] = {
    "provider": {
        "base_url": "https://openrouter.ai/api/v1",
        "api_key": "",
        "model": "anthropic/claude-sonnet-4.6",
    },
    "reasoning": {
        "enabled": False,
        "tokens": None,
    },
}


def config_exists() -> bool:
    """Check whether a config file exists."""
    return CONFIG_FILE.is_file()


def load_config() -> dict[str, Any]:
    """Read and return the config dict.  Returns DEFAULTS if file missing."""
    if not config_exists():
        return copy.deepcopy(DEFAULTS)
    with open(CONFIG_FILE, "rb") as f:
        return tomllib.load(f)


def save_config(config: dict[str, Any]) -> None:
    """Write config dict to TOML file with restrictive permissions."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    content = _serialize_toml(config)
    CONFIG_FILE.write_text(content, encoding="utf-8")
    CONFIG_FILE.chmod(0o600)


def ensure_config() -> dict[str, Any]:
    """If no config exists, run interactive wizard.  Returns loaded config."""
    if config_exists():
        return load_config()
    return run_wizard()


def run_wizard() -> dict[str, Any]:
    """Interactive configuration wizard (terminal prompts, no TUI)."""
    import typer

    typer.echo("\n--- Parseltongue Configuration ---\n")

    base_url = typer.prompt(
        "API base URL (OpenAI-compatible endpoint)",
        default=DEFAULTS["provider"]["base_url"],
    )
    api_key = typer.prompt(
        "API key",
        default="",
    )
    if api_key:
        masked = api_key[:6] + "****" + api_key[-4:]
        typer.echo(f"  Key: {masked}")
    model = typer.prompt(
        "Default model",
        default=DEFAULTS["provider"]["model"],
    )
    reasoning = typer.confirm(
        "Enable extended thinking by default?",
        default=False,
    )

    reasoning_tokens: int | None = None
    if reasoning:
        raw = typer.prompt(
            "Reasoning token budget (leave empty for adaptive)",
            default="",
        )
        reasoning_tokens = int(raw) if raw.strip() else None

    config: dict[str, Any] = {
        "provider": {
            "base_url": base_url,
            "api_key": api_key,
            "model": model,
        },
        "reasoning": {
            "enabled": reasoning,
            "tokens": reasoning_tokens,
        },
    }

    save_config(config)
    typer.echo(f"\nConfig saved to {CONFIG_FILE}\n")
    return config


def merge_overrides(
    config: dict[str, Any],
    *,
    base_url: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """Return a new config dict with CLI flag overrides applied."""
    merged = copy.deepcopy(config)
    if base_url:
        merged["provider"]["base_url"] = base_url
    if api_key:
        merged["provider"]["api_key"] = api_key
    if model:
        merged["provider"]["model"] = model
    return merged


def _serialize_toml(config: dict[str, Any]) -> str:
    """Minimal TOML serializer for our two-level config schema."""
    lines: list[str] = []
    for section, values in config.items():
        lines.append(f"[{section}]")
        if isinstance(values, dict):
            for key, val in values.items():
                if val is None:
                    continue
                elif isinstance(val, bool):
                    lines.append(f"{key} = {'true' if val else 'false'}")
                elif isinstance(val, int):
                    lines.append(f"{key} = {val}")
                elif isinstance(val, str):
                    lines.append(f'{key} = "{val}"')
            lines.append("")
    return "\n".join(lines) + "\n"
