"""Backwards-compatibility shim — use screen.py instead."""

from .screen import ScreenSearchSystem as EvaluationSearchSystem  # noqa: F401

__all__ = ["EvaluationSearchSystem"]
