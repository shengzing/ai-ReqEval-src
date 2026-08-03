"""
Evaluators Module
Provides 6 AI evaluation methods implementation
"""
from .base import BaseEvaluator, EvaluatorConfig
from .yiou import YiOuEvaluator
from .mckinsey import McKinseyEvaluator
from .dx import DXEvaluator
from .bcg import BCGEvaluator
from .mit import MITEvaluator
from .servicenow import ServiceNowEvaluator

# Evaluator Registry
EVALUATORS = {
    "yiou": YiOuEvaluator,
    "mckinsey": McKinseyEvaluator,
    "dx": DXEvaluator,
    "bcg": BCGEvaluator,
    "mit": MITEvaluator,
    "servicenow": ServiceNowEvaluator,
}


def get_evaluator(method: str, llm_client=None) -> BaseEvaluator:
    """
    Get evaluator instance
    
    Args:
        method: Method name (yiou, mckinsey, dx, bcg, mit, servicenow)
        llm_client: LLM client (optional)
    
    Returns:
        Evaluator instance
    """
    evaluator_class = EVALUATORS.get(method.lower())
    if evaluator_class is None:
        available = ", ".join(EVALUATORS.keys())
        raise ValueError(f"Unknown evaluation method: {method}. Available: {available}")
    
    return evaluator_class(llm_client=llm_client)


def list_evaluators() -> list:
    """List all available evaluators"""
    return [
        {
            "method": method,
            "info": get_evaluator(method).get_info()
        }
        for method in EVALUATORS.keys()
    ]


__all__ = [
    "BaseEvaluator",
    "EvaluatorConfig", 
    "YiOuEvaluator",
    "McKinseyEvaluator",
    "DXEvaluator",
    "get_evaluator",
    "list_evaluators",
    "EVALUATORS"
]
