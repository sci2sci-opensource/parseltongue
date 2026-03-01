"""
Parseltongue LLM — four-pass grounded inference pipeline.

    from parseltongue.llm import Pipeline, LLMProvider
    from parseltongue.llm.openrouter import OpenRouterProvider
    from parseltongue import System

    system = System(overridable=True)
    provider = OpenRouterProvider()
    pipeline = Pipeline(system, provider)
    pipeline.add_document("Report", path="report.txt")
    result = pipeline.run("What was Q3 revenue?")
"""

from .pipeline import Pipeline, PipelineResult  # noqa: F401
from .provider import LLMProvider  # noqa: F401
from .resolve import Reference, ResolvedOutput  # noqa: F401

# Concrete providers — import explicitly to avoid pulling in their deps:
#   from parseltongue.llm.openrouter import OpenRouterProvider
