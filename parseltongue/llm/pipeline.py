"""
Three-pass grounded inference pipeline.

Usage::

    from core import System
    from parseltongue.llm import Pipeline
    from parseltongue.llm.openrouter import OpenRouterProvider

    system = System(overridable=True)
    provider = OpenRouterProvider()

    pipeline = Pipeline(system, provider)
    pipeline.add_document("Q3 Report", path="resources/q3_report.txt")

    result = pipeline.run("Did we beat our growth target?")
    print(result.output)
"""

from __future__ import annotations

import logging

from ..core import System, load_source
from .prompts import pass1_messages, pass2_messages, pass3_messages, pass4_messages
from .provider import LLMProvider
from .resolve import ResolvedOutput, resolve_references
from .tools import ANSWER_TOOL, DERIVE_TOOL, EXTRACT_TOOL, FACTCHECK_TOOL

log = logging.getLogger('parseltongue.llm')


class PipelineResult:
    """Container for the full pipeline result."""

    def __init__(
        self,
        output: ResolvedOutput,
        system: System,
        pass1_source: str,
        pass2_source: str,
        pass3_source: str,
        pass4_raw: str,
    ):
        self.output = output
        self.system = system
        self.pass1_source = pass1_source
        self.pass2_source = pass2_source
        self.pass3_source = pass3_source
        self.pass4_raw = pass4_raw

    def __str__(self):
        return str(self.output)


class Pipeline:
    """Four-pass grounded inference pipeline.

    Args:
        system: a parseltongue System instance (will be mutated)
        provider: an LLMProvider instance for tool-calling completion
    """

    def __init__(self, system: System, provider: LLMProvider):
        self._system = system
        self._provider = provider
        self._documents: dict[str, str] = {}

    def add_document(self, name: str, path: str | None = None, text: str | None = None):
        """Register a source document.

        Args:
            name: document name (referenced in :evidence blocks)
            path: file path to load from
            text: inline text (alternative to path)
        """
        if path is not None:
            self._system.load_document(name, path)
            with open(path) as f:
                self._documents[name] = f.read()
        elif text is not None:
            self._system.register_document(name, text)
            self._documents[name] = text
        else:
            raise ValueError("Provide either path or text")

    def run(self, query: str, **kwargs) -> PipelineResult:
        """Execute the three-pass pipeline.

        Args:
            query: natural language question
            **kwargs: passed to LLM provider (temperature, max_tokens, etc.)

        Returns:
            PipelineResult with resolved output and intermediate state.
        """
        if not self._documents:
            raise ValueError("No documents registered. Call add_document() first.")

        doc = self._system.doc()

        # Pass 1: Extraction
        log.info("Pass 1: Extraction")
        messages = pass1_messages(doc, self._documents, query)
        result = self._provider.complete(messages, [EXTRACT_TOOL], **kwargs)
        pass1_source = result['dsl_output']
        log.info("Pass 1 output:\n%s", pass1_source)

        load_source(self._system, pass1_source)

        # Pass 2: Derivation (blinded)
        log.info("Pass 2: Derivation (blinded)")
        messages = pass2_messages(doc, self._system, query)
        result = self._provider.complete(messages, [DERIVE_TOOL], **kwargs)
        pass2_source = result['dsl_output']
        log.info("Pass 2 output:\n%s", pass2_source)

        load_source(self._system, pass2_source)

        # Pass 3: Fact Check (full state visible)
        log.info("Pass 3: Fact Check")
        messages = pass3_messages(doc, self._system, query)
        result = self._provider.complete(messages, [FACTCHECK_TOOL], **kwargs)
        pass3_source = result['dsl_output']
        log.info("Pass 3 output:\n%s", pass3_source)

        load_source(self._system, pass3_source)

        # Pass 4: Inference
        log.info("Pass 4: Inference")
        messages = pass4_messages(self._system, query)
        result = self._provider.complete(messages, [ANSWER_TOOL], **kwargs)
        pass4_raw = result['markdown']
        log.info("Pass 4 raw:\n%s", pass4_raw)

        output = resolve_references(pass4_raw, self._system)

        return PipelineResult(
            output=output,
            system=self._system,
            pass1_source=pass1_source,
            pass2_source=pass2_source,
            pass3_source=pass3_source,
            pass4_raw=pass4_raw,
        )
