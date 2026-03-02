"""Parseltongue CLI — Typer entry point."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Annotated, Optional

import typer

from .ingest import ingest_file, parse_document_arg

app = typer.Typer(
    name="parseltongue",
    help="Parseltongue: a DSL for systems which refuse to speak falsehood.",
    invoke_without_command=True,
)

log = logging.getLogger('parseltongue.cli')


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(name)s %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )


# ---------------------------------------------------------------------------
# Default callback: bare `parseltongue` launches standalone TUI
# ---------------------------------------------------------------------------


@app.callback(invoke_without_command=True)
def default_callback(ctx: typer.Context) -> None:
    """Launch the interactive TUI when no subcommand is given."""
    if ctx.invoked_subcommand is None:
        from .config import ensure_config

        config = ensure_config()
        _launch_standalone_tui(config)


# ---------------------------------------------------------------------------
# configure
# ---------------------------------------------------------------------------


@app.command()
def configure() -> None:
    """Run (or re-run) the interactive configuration wizard."""
    from .config import run_wizard

    run_wizard()


# ---------------------------------------------------------------------------
# start — explicit alias for standalone TUI
# ---------------------------------------------------------------------------


@app.command()
def start(
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Enable debug logging."),
    ] = False,
) -> None:
    """Launch the interactive TUI (file browser → query → pipeline)."""
    _setup_logging(verbose)

    from .config import ensure_config

    config = ensure_config()
    _launch_standalone_tui(config)


# ---------------------------------------------------------------------------
# run — direct pipeline execution
# ---------------------------------------------------------------------------


@app.command()
def run(
    documents: Annotated[
        list[str],
        typer.Option(
            "--document",
            "-d",
            help='Document to ingest. Format: "name:path" or just "path".',
        ),
    ],
    query: Annotated[
        str,
        typer.Option("--query", "-q", help="The question to answer."),
    ],
    model: Annotated[
        Optional[str],
        typer.Option("--model", "-m", help="LLM model (overrides config)."),
    ] = None,
    base_url: Annotated[
        Optional[str],
        typer.Option("--base-url", help="API base URL (overrides config)."),
    ] = None,
    api_key: Annotated[
        Optional[str],
        typer.Option("--api-key", help="API key (overrides config)."),
    ] = None,
    reasoning: Annotated[
        Optional[bool],
        typer.Option("--reasoning/--no-reasoning", help="Enable extended thinking."),
    ] = None,
    reasoning_tokens: Annotated[
        Optional[int],
        typer.Option("--reasoning-tokens", help="Thinking budget (token count)."),
    ] = None,
    no_tui: Annotated[
        bool,
        typer.Option("--no-tui", help="Print output to stdout instead of launching TUI."),
    ] = False,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Enable debug logging."),
    ] = False,
) -> None:
    """Run the pipeline on one or more documents."""
    _setup_logging(verbose)

    from .config import ensure_config, merge_overrides
    from .runner import RunConfig

    config = ensure_config()
    config = merge_overrides(config, base_url=base_url, api_key=api_key, model=model)

    parsed_docs = [parse_document_arg(d) for d in documents]

    # Determine reasoning config
    reason_val: bool | int | None = None
    if reasoning_tokens is not None:
        reason_val = reasoning_tokens
    elif reasoning is not None:
        reason_val = reasoning
    elif config.get("reasoning", {}).get("enabled"):
        reason_val = config["reasoning"].get("tokens") or True

    run_config = RunConfig(
        documents=parsed_docs,
        query=query,
        model=config["provider"]["model"],
        reasoning=reason_val,
        provider_config=config["provider"],
    )

    if no_tui:
        _run_plain(run_config)
    else:
        _run_tui(run_config)


# ---------------------------------------------------------------------------
# inspect — preview docling conversion
# ---------------------------------------------------------------------------


@app.command()
def inspect(
    path: Annotated[
        str,
        typer.Argument(help="Path to a document file."),
    ],
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Enable debug logging."),
    ] = False,
) -> None:
    """Preview docling conversion of a document (no pipeline run)."""
    _setup_logging(verbose)

    p = Path(path)
    if not p.exists():
        typer.echo(f"File not found: {path}", err=True)
        raise typer.Exit(1)

    from rich.console import Console
    from rich.markdown import Markdown

    console = Console()
    console.print(f"[dim]Converting: {path}[/dim]")

    try:
        text = ingest_file(str(p))
    except Exception as e:
        typer.echo(f"Conversion failed: {e}", err=True)
        raise typer.Exit(1)

    console.print()
    console.print(Markdown(text))


# ---------------------------------------------------------------------------
# history — browse / re-open past runs
# ---------------------------------------------------------------------------

history_app = typer.Typer(help="Browse and manage run history.")
app.add_typer(history_app, name="history")


@history_app.callback(invoke_without_command=True)
def history_list(ctx: typer.Context) -> None:
    """List recent pipeline runs."""
    if ctx.invoked_subcommand is not None:
        return

    from rich.console import Console
    from rich.table import Table

    from . import history

    console = Console()
    runs = history.list_runs()

    if not runs:
        console.print("[dim]No runs in history.[/dim]")
        return

    table = Table(title="Run History")
    table.add_column("ID", style="bold")
    table.add_column("Timestamp")
    table.add_column("Query")
    table.add_column("Model")
    table.add_column("Status")

    for r in runs:
        status_style = {"completed": "green", "failed": "red", "running": "yellow"}.get(r["status"], "")
        query_short = r["query"][:60] + "..." if len(r["query"]) > 60 else r["query"]
        table.add_row(
            str(r["id"]),
            r["timestamp"][:19],
            query_short,
            r["model"],
            f"[{status_style}]{r['status']}[/{status_style}]",
        )

    console.print(table)


@history_app.command("show")
def history_show(
    run_id: Annotated[int, typer.Argument(help="Run ID to re-open.")],
    no_tui: Annotated[
        bool,
        typer.Option("--no-tui", help="Dump to stdout instead of TUI."),
    ] = False,
) -> None:
    """Re-open a cached run result."""
    from rich.console import Console
    from rich.markdown import Markdown

    from . import history

    console = Console()
    data = history.get_run(run_id)

    if not data:
        typer.echo(f"Run #{run_id} not found.", err=True)
        raise typer.Exit(1)

    if data["status"] != "completed":
        typer.echo(f"Run #{run_id} status: {data['status']} (no cached result).", err=True)
        raise typer.Exit(1)

    if no_tui:
        console.print()
        console.print(Markdown(data["output_md"] or "(no output)"))
        console.print()
        if data.get("consistency"):
            console.print("[bold]Consistency Report:[/bold]")
            console.print(data["consistency"])
    else:
        _launch_history_tui(data)


@history_app.command("clear")
def history_clear() -> None:
    """Delete all run history."""
    from . import history

    count = history.clear_history()
    typer.echo(f"Deleted {count} run(s).")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_plain(config) -> None:
    """Run pipeline and dump output to stdout."""
    from rich.console import Console
    from rich.markdown import Markdown

    from .runner import run_pipeline

    console = Console()

    def on_progress(msg: str) -> None:
        console.print(f"[dim]{msg}[/dim]")

    result = run_pipeline(config, on_progress=on_progress)

    console.print()
    console.print(Markdown(str(result.output)))
    console.print()

    if result.output.references:
        console.print("[bold]References:[/bold]")
        for ref in result.output.references:
            status = "[green]OK[/green]" if ref.error is None else f"[red]{ref.error}[/red]"
            console.print(f"  [[{ref.type}:{ref.name}]] — {status}")
        console.print()

    if result.output.consistency:
        console.print("[bold]Consistency Report:[/bold]")
        console.print(result.output.consistency)


def _run_tui(config) -> None:
    """Run pipeline inside the Textual TUI."""
    try:
        from .tui.app import ParseltongueApp
    except ImportError:
        typer.echo(
            "TUI dependencies not installed. Run: pip install parseltongue-dsl[cli]\n"
            "Or use --no-tui for plain output.",
            err=True,
        )
        raise typer.Exit(1)

    tui_app = ParseltongueApp(config=config)
    tui_app.run()


def _launch_standalone_tui(config: dict) -> None:
    """Launch TUI in standalone mode with document picker."""
    try:
        from .tui.app import ParseltongueApp
    except ImportError:
        typer.echo(
            "TUI dependencies not installed. Run: pip install parseltongue-dsl[cli]\n",
            err=True,
        )
        raise typer.Exit(1)

    tui_app = ParseltongueApp.standalone(config)
    tui_app.run()


def _launch_history_tui(run_data: dict) -> None:
    """Launch TUI to view a cached historical run."""
    try:
        from .tui.app import ParseltongueApp
    except ImportError:
        typer.echo(
            "TUI dependencies not installed. Run: pip install parseltongue-dsl[cli]\n",
            err=True,
        )
        raise typer.Exit(1)

    tui_app = ParseltongueApp.from_history(run_data)
    tui_app.run()


def main() -> None:
    """Entry point for the ``parseltongue`` command."""
    app()


if __name__ == "__main__":
    main()
