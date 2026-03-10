"""Main menu screen — entry point for standalone TUI mode."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.message import Message
from textual.screen import Screen
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option


class NewRunRequested(Message):
    """User wants to start a new pipeline run."""

    pass


class HistoryRequested(Message):
    """User wants to browse run history."""

    pass


class ProjectRequested(Message):
    """User wants to load a .pltg project."""

    pass


class RecentProjectsRequested(Message):
    """User wants to see recent projects."""

    pass


class ConfigureRequested(Message):
    """User wants to reconfigure settings."""

    pass


_OPTIONS = [
    Option("New run", id="new-run"),
    Option("Load project", id="load-project"),
    Option("Recent projects", id="recent-projects"),
    Option("Runs history", id="history"),
    Option("Configure", id="configure"),
    Option("Quit", id="quit"),
]


class MainMenu(Screen):
    """Landing screen with arrow-navigable option list."""

    def compose(self) -> ComposeResult:
        yield Static(
            "[bold]Parseltongue[/bold]\n[dim]A DSL for systems which refuse to speak falsehood[/dim]",
            id="menu-title",
        )
        yield OptionList(*_OPTIONS, id="menu-list")

    def on_mount(self) -> None:
        self.query_one("#menu-list", OptionList).focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        match event.option.id:
            case "new-run":
                self.post_message(NewRunRequested())
            case "load-project":
                self.post_message(ProjectRequested())
            case "recent-projects":
                self.post_message(RecentProjectsRequested())
            case "history":
                self.post_message(HistoryRequested())
            case "configure":
                self.post_message(ConfigureRequested())
            case "quit":
                self.app.exit()
