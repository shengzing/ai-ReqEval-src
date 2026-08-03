"""
Orchestration state definitions for evaluation flows.
"""
from typing import Any, Dict, Optional, TypedDict

from src.packages.reqeval.data.models import EvaluationReport, ScenarioType


class EvaluationState(TypedDict, total=False):
    """
    Shared state passed between orchestration nodes.
    """

    scenario: ScenarioType
    method: str
    inputs: Dict[str, Any]
    result: Optional[EvaluationReport]
    error: Optional[str]
