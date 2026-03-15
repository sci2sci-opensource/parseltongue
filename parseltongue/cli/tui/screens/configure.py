"""Configuration screen — edit provider settings within the TUI."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Checkbox, Input, Label

from ..widgets.hints_bar import HintsBar


class ConfigureScreen(Screen):
    """In-app settings editor for provider configuration."""

    BINDINGS = [
        ("escape", "dismiss", "Back"),
        ("ctrl+s", "save", "Save"),
    ]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._config: dict = {}

    def compose(self) -> ComposeResult:
        from ...config import DEFAULTS, load_config

        self._config = load_config()
        provider = self._config.get("provider", DEFAULTS["provider"])
        reasoning = self._config.get("reasoning", DEFAULTS["reasoning"])

        with Container(id="config-container"):
            yield Label("Configuration", id="config-title")

            with VerticalScroll(id="config-fields"):
                yield Label("API base URL")
                yield Input(
                    value=provider.get("base_url", ""),
                    placeholder="https://openrouter.ai/api/v1",
                    id="cfg-base-url",
                )

                yield Label("API key")
                yield Input(
                    value=provider.get("api_key", ""),
                    placeholder="sk-...",
                    password=True,
                    id="cfg-api-key",
                )

                yield Label("Model")
                yield Input(
                    value=provider.get("model", ""),
                    placeholder="anthropic/claude-sonnet-4.6",
                    id="cfg-model",
                )

                yield Checkbox(
                    "Enable extended thinking",
                    value=bool(reasoning.get("enabled", False)),
                    id="cfg-reasoning",
                )

                yield Label("Reasoning token budget (empty = adaptive)", id="cfg-tokens-label")
                yield Input(
                    value=str(reasoning["tokens"]) if reasoning.get("tokens") else "",
                    placeholder="adaptive",
                    id="cfg-tokens",
                )

            with Horizontal(id="config-buttons"):
                yield Button("Save", id="cfg-save", variant="primary")
                yield Button("Cancel", id="cfg-cancel")

        yield HintsBar(
            [
                ("Ctrl+S", "Save", "screen.save"),
                ("Esc", "Back", "screen.dismiss"),
            ]
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button.id == "cfg-save":
            self.action_save()
        elif event.button.id == "cfg-cancel":
            self.dismiss()

    def action_save(self) -> None:
        from ...config import save_config

        base_url = self.query_one("#cfg-base-url", Input).value.strip()
        api_key = self.query_one("#cfg-api-key", Input).value.strip()
        model = self.query_one("#cfg-model", Input).value.strip()
        reasoning_enabled = self.query_one("#cfg-reasoning", Checkbox).value
        tokens_raw = self.query_one("#cfg-tokens", Input).value.strip()
        reasoning_tokens = int(tokens_raw) if tokens_raw.isdigit() else None

        config = {
            "provider": {
                "base_url": base_url,
                "api_key": api_key,
                "model": model,
            },
            "reasoning": {
                "enabled": reasoning_enabled,
                "tokens": reasoning_tokens,
            },
        }

        save_config(config)
        self.notify("Config saved")
        self.dismiss()
