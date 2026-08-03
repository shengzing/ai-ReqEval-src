"""
Supervisor agent: orchestrates method selection and execution.
当前实现：根据传入method直接路由到对应 evaluator，预留后续对话式方法推荐入口。
"""
from typing import Any, Dict, Optional

from src.packages.reqeval.agents.router import EvaluationRouter
from src.packages.reqeval.data.models import EvaluationReport, ScenarioType


class SupervisorAgent:
    """
    Minimal supervisor that can later expand to method recommendation/clarification.
    """

    def __init__(self, llm_client=None):
        self.router = EvaluationRouter(llm_client=llm_client)

    def run(self, method: str, scenario: ScenarioType, inputs: Dict[str, Any]) -> EvaluationReport:
        evaluator = self.router.route(method)
        if scenario == ScenarioType.PRE:
            return evaluator.pre_evaluation(inputs)
        return evaluator.post_evaluation(inputs)

    def recommend_method(self, user_intent: str) -> Optional[str]:
        """
        Placeholder for future method recommendation based on user intent.
        """
        return None
