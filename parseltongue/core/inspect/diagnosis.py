"""Backward compatibility — use evaluation.py instead."""

from .evaluation import Evaluation as Diagnosis  # noqa: F401
from .evaluation import EvaluationItem as DiagnosisItem  # noqa: F401
from .evaluation import EvaluationSearchSystem as DiagnosisSearchSystem  # noqa: F401
