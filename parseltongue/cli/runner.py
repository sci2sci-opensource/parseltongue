"""Pipeline runner — wraps the LLM pipeline with progress callbacks."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from ..core import System
from ..llm import Pipeline, PipelineResult
from .ingest import ingest_file

log = logging.getLogger("parseltongue.cli")


@dataclass
class RunConfig:
    """Configuration for a CLI pipeline run."""

    documents: list[tuple[str, str]]  # (name, path)
    query: str
    model: str = "anthropic/claude-sonnet-4.6"
    reasoning: bool | int | None = None
    provider_config: dict[str, Any] = field(default_factory=dict)
    ingest_errors: dict[str, str] = field(default_factory=dict)  # name -> error message


def _create_provider(config: RunConfig):
    """Create an LLM provider from RunConfig."""
    from ..llm.openrouter import OpenRouterProvider

    prov = config.provider_config
    return OpenRouterProvider(
        model=config.model,
        api_key=prov.get("api_key") or None,
        base_url=prov.get("base_url", "https://openrouter.ai/api/v1"),
        reasoning=config.reasoning,
    )


def run_pipeline(
    config: RunConfig,
    on_progress: Callable[[str], None] | None = None,
) -> PipelineResult:
    """Run the full pipeline with progress reporting.

    Args:
        config: Run configuration.
        on_progress: Callback (message).

    Returns:
        PipelineResult with output, system, and intermediate DSL.
    """
    from . import history

    def progress(msg: str):
        if on_progress:
            on_progress(msg)
        log.info(msg)

    prov = config.provider_config
    run_id = history.save_run(
        query=config.query,
        model=config.model,
        base_url=prov.get("base_url", ""),
        documents=[{"name": n, "path": p} for n, p in config.documents],
    )

    try:
        system = System(overridable=True)
        provider = _create_provider(config)
        pipeline = Pipeline(system, provider)

        for name, path in config.documents:
            progress(f"Ingesting: {name}")
            try:
                text = ingest_file(path)
                pipeline.add_document(name, text=text)
            except Exception as exc:
                config.ingest_errors[name] = str(exc)
                progress(f"Skipping {name}: {exc}")

        progress("Running pipeline (4 passes: extract → derive → factcheck → answer)...")
        result = pipeline.run(config.query)
        progress("Done.")

        history.complete_run(run_id, result)
        return result
    except Exception as exc:
        history.fail_run(run_id, str(exc))
        raise


def create_interactive_pipeline(
    config: RunConfig,
    on_progress: Callable[[str], None] | None = None,
    pre_ingested: dict[str, str] | None = None,
):
    """Set up an InteractivePipeline from RunConfig.

    Args:
        config: Run configuration.
        on_progress: Callback (message).
        pre_ingested: Already-ingested documents {name: text}. Skips ingestion.

    Returns (InteractivePipeline, history_run_id) — caller drives the passes.
    """
    from . import history
    from .interactive import InteractivePipeline

    def progress(msg: str):
        if on_progress:
            on_progress(msg)
        log.info(msg)

    system = System(overridable=True)
    provider = _create_provider(config)

    if pre_ingested:
        documents = dict(pre_ingested)
        for name, text in documents.items():
            system.register_document(name, text)
    else:
        documents = {}
        for name, path in config.documents:
            progress(f"Ingesting: {name}")
            try:
                text = ingest_file(path)
                system.register_document(name, text)
                documents[name] = text
            except Exception as exc:
                config.ingest_errors[name] = str(exc)
                progress(f"Skipping {name}: {exc}")

    prov = config.provider_config
    run_id = history.save_run(
        query=config.query,
        model=config.model,
        base_url=prov.get("base_url", ""),
        documents=[{"name": n, "path": p} for n, p in config.documents],
    )

    pipeline = InteractivePipeline(system, provider, documents, config.query)
    return pipeline, run_id
