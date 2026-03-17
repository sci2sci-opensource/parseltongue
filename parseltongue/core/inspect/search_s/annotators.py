"""Annotation strategies — post-index metadata enrichment.

An AnnotationStrategy takes a SearchDocument and adds metadata marks.
Strategies are pluggable: pass them to DocumentSearchIndex, they run
on every document after indexing.

Built-in strategies:
    exception_handling  — marks try/except/raise/Error lines
    imports             — marks import lines
    definitions         — marks def/class lines
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from .document import SearchDocument


class AnnotationStrategy(Protocol):
    """Protocol for document annotation strategies."""

    name: str

    def annotate(self, sdoc: "SearchDocument") -> None:
        """Add metadata marks to a SearchDocument. Mutates in place."""
        ...


class ExceptionHandlingAnnotator:
    """Marks exception handling patterns: try, except, raise, Error, Exception."""

    name = "exception_handling"

    _PATTERNS = [
        (re.compile(r"^\s*try\s*:"), "try", 1.5),
        (re.compile(r"^\s*except\b"), "except", 1.5),
        (re.compile(r"^\s*finally\s*:"), "finally", 1.2),
        (re.compile(r"\braise\b"), "raise", 2.0),
        (re.compile(r"\bException\b"), "exception_class", 1.8),
        (re.compile(r"\bError\b"), "error_class", 1.8),
        (re.compile(r"\bWarning\b"), "warning_class", 1.3),
    ]

    def annotate(self, sdoc: "SearchDocument") -> None:
        for line_num, line_text in enumerate(sdoc.lines, 1):
            for rx, tag, weight in self._PATTERNS:
                if rx.search(line_text):
                    sdoc.meta.add_line(line_num, f"exception:{tag}", line_text.strip(), weight)


class ImportAnnotator:
    """Marks import lines."""

    name = "imports"

    _RX = re.compile(r"^\s*(from\s+\S+\s+)?import\s+")

    def annotate(self, sdoc: "SearchDocument") -> None:
        for line_num, line_text in enumerate(sdoc.lines, 1):
            if self._RX.match(line_text):
                sdoc.meta.add_line(line_num, "structure:import", line_text.strip(), 1.2)


class DefinitionAnnotator:
    """Marks def/class definition lines."""

    name = "definitions"

    _DEF_RX = re.compile(r"^\s*def\s+(\w+)")
    _CLASS_RX = re.compile(r"^\s*class\s+(\w+)")

    def annotate(self, sdoc: "SearchDocument") -> None:
        for line_num, line_text in enumerate(sdoc.lines, 1):
            m = self._DEF_RX.match(line_text)
            if m:
                name = m.group(1)
                sdoc.meta.add_line(line_num, "structure:def", name, 1.5)
                sdoc.meta.add_word(name, "definition", name, 1.8)
                continue
            m = self._CLASS_RX.match(line_text)
            if m:
                name = m.group(1)
                sdoc.meta.add_line(line_num, "structure:class", name, 1.5)
                sdoc.meta.add_word(name, "definition", name, 1.8)


# Default set of annotators
DEFAULT_ANNOTATORS: list[AnnotationStrategy] = [
    ExceptionHandlingAnnotator(),
    ImportAnnotator(),
    DefinitionAnnotator(),
]
