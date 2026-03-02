"""Interactive pass-by-pass pipeline runner for the CLI/TUI."""

from __future__ import annotations

import copy
import logging
import traceback
from dataclasses import dataclass, field
from threading import Event
from typing import Any

from ..core import System, load_source
from ..llm.prompts import pass1_messages, pass2_messages, pass3_messages, pass4_messages
from ..llm.provider import LLMProvider
from ..llm.resolve import ResolvedOutput, resolve_references
from ..llm.tools import ANSWER_TOOL, DERIVE_TOOL, EXTRACT_TOOL, FACTCHECK_TOOL

log = logging.getLogger("parseltongue.cli")

PASS_INFO = [
    (1, "Extract", EXTRACT_TOOL, "dsl_output"),
    (2, "Derive", DERIVE_TOOL, "dsl_output"),
    (3, "Factcheck", FACTCHECK_TOOL, "dsl_output"),
    (4, "Answer", ANSWER_TOOL, "markdown"),
]


@dataclass
class PassResult:
    """Result of a single pass."""

    pass_num: int
    source: str
    interrupted: bool = False
    error: str | None = None


@dataclass
class InteractiveResult:
    """Full pipeline result from interactive execution."""

    system: System
    pass_results: list[PassResult] = field(default_factory=list)
    pass_systems: dict[int, System] = field(default_factory=dict)
    output: ResolvedOutput | None = None

    @property
    def pass1_source(self) -> str:
        return self._get_source(1)

    @property
    def pass2_source(self) -> str:
        return self._get_source(2)

    @property
    def pass3_source(self) -> str:
        return self._get_source(3)

    @property
    def pass4_raw(self) -> str:
        return self._get_source(4)

    def _get_source(self, n: int) -> str:
        for pr in self.pass_results:
            if pr.pass_num == n:
                return pr.source
        return ""


class InteractivePipeline:
    """Pass-by-pass pipeline with review, retry, and interrupt.

    Usage::

        ip = InteractivePipeline(system, provider, documents, query)

        # Run passes one at a time
        for pass_num in range(1, 5):
            result = ip.run_pass(pass_num)
            # User reviews system state...
            # To retry: ip.retry_pass(pass_num, feedback="fix X")
            # To skip:  ip.skip_pass(pass_num)
    """

    def __init__(
        self,
        system: System,
        provider: LLMProvider,
        documents: dict[str, str],
        query: str,
    ):
        self.system = system
        self.provider = provider
        self.documents = documents
        self.query = query
        self.interrupt = Event()

        self._pass_results: list[PassResult] = []
        self._snapshots: dict[int, Any] = {}  # pass_num -> system deepcopy (before pass)
        self._post_snapshots: dict[int, Any] = {}  # pass_num -> system deepcopy (after pass)
        self._extra_messages: dict[int, list[dict]] = {}  # pass_num -> user feedback messages

    def run_pass(self, pass_num: int, **kwargs) -> PassResult:
        """Run a single pass.  Snapshots system state before execution."""
        self.interrupt.clear()
        self._last_source = ""
        self._snapshots[pass_num] = copy.deepcopy(self.system)

        try:
            source = self._execute_pass(pass_num, **kwargs)
            result = PassResult(pass_num=pass_num, source=source)
        except _Interrupted:
            result = PassResult(pass_num=pass_num, source=self._last_source, interrupted=True)
        except Exception as exc:
            tb = traceback.format_exc()
            result = PassResult(pass_num=pass_num, source=self._last_source, error=f"{exc}\n{tb}")

        self._set_result(pass_num, result)
        return result

    def retry_pass(self, pass_num: int, feedback: str, **kwargs) -> PassResult:
        """Rollback system to pre-pass state, append previous result + feedback, re-run."""
        # Capture previous output before rollback
        prev = self._get_result(pass_num)
        prev_source = prev.source if prev else ""

        snapshot = self._snapshots.get(pass_num)
        if snapshot is not None:
            self._restore_system(snapshot)
            self._snapshots[pass_num] = copy.deepcopy(self.system)

        # Build conversation: assistant's previous output + user feedback
        if pass_num not in self._extra_messages:
            self._extra_messages[pass_num] = []
        if prev_source:
            self._extra_messages[pass_num].append({"role": "assistant", "content": prev_source})
        self._extra_messages[pass_num].append({"role": "user", "content": feedback})

        self.interrupt.clear()
        self._last_source = ""
        try:
            source = self._execute_pass(pass_num, **kwargs)
            result = PassResult(pass_num=pass_num, source=source)
        except _Interrupted:
            result = PassResult(pass_num=pass_num, source=self._last_source, interrupted=True)
        except Exception as exc:
            tb = traceback.format_exc()
            result = PassResult(pass_num=pass_num, source=self._last_source, error=f"{exc}\n{tb}")

        self._set_result(pass_num, result)
        return result

    def skip_pass(self, pass_num: int) -> PassResult:
        """Skip a pass — rollback to snapshot, record empty result."""
        snapshot = self._snapshots.get(pass_num)
        if snapshot is not None:
            self._restore_system(snapshot)

        result = PassResult(pass_num=pass_num, source="")
        self._set_result(pass_num, result)
        return result

    def finalize(self) -> InteractiveResult:
        """Build the final result after all passes."""
        ir = InteractiveResult(
            system=self.system,
            pass_results=list(self._pass_results),
            pass_systems=dict(self._post_snapshots),
        )
        pass4 = self._get_result(4)
        if pass4 and pass4.source:
            ir.output = resolve_references(pass4.source, self.system)
        return ir

    def request_interrupt(self) -> None:
        """Cancel the in-flight LLM request and signal the pipeline to stop."""
        self.interrupt.set()
        self.provider.cancel()

    # ------------------------------------------------------------------

    def _execute_pass(self, pass_num: int, **kwargs) -> str:
        """Build messages, call provider, load DSL into system."""
        if self.interrupt.is_set():
            raise _Interrupted

        messages = self._build_messages(pass_num)
        extras = self._extra_messages.get(pass_num, [])
        messages.extend(extras)

        _, _, tool, result_key = PASS_INFO[pass_num - 1]

        log.info("Pass %d: calling provider", pass_num)
        try:
            result = self.provider.complete(messages, [tool], **kwargs)
        except Exception:
            if self.interrupt.is_set():
                raise _Interrupted
            raise
        source = result[result_key]
        self._last_source = source

        if self.interrupt.is_set():
            raise _Interrupted

        if pass_num <= 3:
            load_source(self.system, source)
        # Pass 4 is markdown, no DSL to load

        return source

    def _build_messages(self, pass_num: int) -> list[dict]:
        doc = self.system.doc()
        if pass_num == 1:
            return pass1_messages(doc, self.documents, self.query)
        elif pass_num == 2:
            return pass2_messages(doc, self.system, self.query)
        elif pass_num == 3:
            return pass3_messages(doc, self.system, self.query)
        else:
            return pass4_messages(self.system, self.query)

    def _restore_system(self, snapshot) -> None:
        """Replace current system's mutable state from a snapshot."""
        self.system.axioms = snapshot.axioms
        self.system.theorems = snapshot.theorems
        self.system.terms = snapshot.terms
        self.system.facts = snapshot.facts
        self.system.env = snapshot.env
        self.system.diffs = snapshot.diffs

    def _set_result(self, pass_num: int, result: PassResult) -> None:
        self._pass_results = [pr for pr in self._pass_results if pr.pass_num != pass_num]
        self._pass_results.append(result)
        self._post_snapshots[pass_num] = copy.deepcopy(self.system)

    def _get_result(self, pass_num: int) -> PassResult | None:
        for pr in self._pass_results:
            if pr.pass_num == pass_num:
                return pr
        return None


class _Interrupted(Exception):
    pass
