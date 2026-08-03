"""
Evaluation method router.
"""
from src.packages.reqeval.evaluators import get_evaluator, EVALUATORS


class EvaluationRouter:
    """
    Simple router mapping method key to evaluator instance.
    """

    def __init__(self, llm_client=None):
        self.llm_client = llm_client

    def route(self, method: str):
        """
        Return evaluator instance for given method.
        """
        if method not in EVALUATORS:
            available = ", ".join(EVALUATORS.keys())
            raise ValueError(f"Unknown method: {method}. Available: {available}")
        return get_evaluator(method, llm_client=self.llm_client)
