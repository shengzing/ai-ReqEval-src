"""
DeepAgent-style orchestration for evaluation flows.

说明：
- 如果环境已安装 deepagent，可在此文件内接入真实的 Agent/Tool 定义。
- 若未安装，则回退为直接调用 evaluator，并在元数据中标注 engine=fallback-deepagent。
"""
from typing import Any, Callable, Dict, Optional

from src.packages.reqeval.data.models import EvaluationReport, ScenarioType
from src.packages.reqeval.evaluators import get_evaluator


class DeepAgentOrchestrator:
    """
    Lightweight wrapper to align with DeepAgent 接口习惯。
    - 可注入自定义 agent_runner(method, scenario, inputs) 以调用实际 DeepAgent 实例。
    - 若本地已安装 deepagent，可在 __init__ 时构建默认 runner；否则回退到直接调用 evaluator。
    """

    def __init__(self, agent_runner: Optional[Callable[[str, ScenarioType, Dict[str, Any]], EvaluationReport]] = None):
        self.agent_runner = agent_runner
        try:
            import deepagent  # noqa: F401

            self.has_lib = True
        except ImportError:
            # 未安装依赖时回退到直接调用，方便本地演示与对比
            self.has_lib = False

    def run(self, method: str, scenario: ScenarioType, inputs: Dict[str, Any]) -> EvaluationReport:
        """
        Execute evaluation through DeepAgent or fallback.
        """
        # 如果传入了自定义 DeepAgent runner，优先使用
        if self.agent_runner is not None:
            result = self.agent_runner(method, scenario, inputs)
            result.metadata["engine"] = "deepagent-custom"
            return result

        # 默认分支：检测 deepagent 是否可用
        if self.has_lib:
            # 这里保留扩展点：项目需要时可在此处实例化真实的 deepagent 代理
            # 目前先回退到直接调用，并在 metadata 标注
            pass

        evaluator = get_evaluator(method)
        if scenario == ScenarioType.PRE:
            result = evaluator.pre_evaluation(inputs)
        else:
            result = evaluator.post_evaluation(inputs)

        # 标注执行引擎，便于后续对比
        result.metadata["engine"] = "deepagent" if self.has_lib else "deepagent-fallback"
        if not self.has_lib:
            result.metadata["note"] = "deepagent package not installed; used direct evaluator call"
        else:
            result.metadata["note"] = "deepagent available; using evaluator fallback until custom agent_runner is provided"
        return result
