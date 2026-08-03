"""
LangGraph-based orchestration for evaluation flows.
"""
from typing import Any, Dict

from langgraph.graph import END, StateGraph

from src.packages.reqeval.agents.state import EvaluationState
from src.packages.reqeval.data.models import EvaluationReport, ScenarioType
from src.packages.reqeval.evaluators import get_evaluator
from src.packages.reqeval.data.document_processor import DocumentProcessor


def _parse_documents(state: EvaluationState) -> EvaluationState:
    """
    Parse raw document objects (if any) into text content.
    """
    inputs = dict(state.get("inputs", {}))
    docs = inputs.get("documents") or []
    parsed_docs = []
    for doc in docs:
        # 支持 DocumentInfo 或原始文件对象/路径
        if hasattr(doc, "content") and getattr(doc, "content"):
            parsed_docs.append(doc)
        else:
            try:
                content = DocumentProcessor.process_file(doc)
            except Exception as exc:  # pragma: no cover - best-effort
                return {**state, "error": f"文档解析失败: {exc}"}
            parsed_docs.append({"filename": getattr(doc, "name", str(doc)), "content": content})
    inputs["documents"] = parsed_docs
    return {**state, "inputs": inputs, "error": None}


def _evaluate(state: EvaluationState) -> EvaluationState:
    """
    Run the selected evaluator and attach the result to state.
    """
    try:
        evaluator = get_evaluator(state["method"])
        if state["scenario"] == ScenarioType.PRE:
            result = evaluator.pre_evaluation(state["inputs"])
        else:
            result = evaluator.post_evaluation(state["inputs"])

        # 记录编排引擎来源，便于对比
        result.metadata["engine"] = "langgraph"
        return {**state, "result": result, "error": None}
    except Exception as exc:  # pragma: no cover - pass-through error
        return {**state, "result": None, "error": str(exc)}


class LangGraphOrchestrator:
    """
    Minimal LangGraph runner with a two-step pipeline:
    1) parse_documents: 解析上传文档
    2) evaluate: 调用具体评估器
    可以在此基础上继续扩展多节点/多step的状态机。
    """

    def __init__(self):
        graph = StateGraph(EvaluationState)
        graph.add_node("parse_documents", _parse_documents)
        graph.add_node("evaluate", _evaluate)
        graph.set_entry_point("parse_documents")
        graph.add_edge("parse_documents", "evaluate")
        graph.add_edge("evaluate", END)
        self.app = graph.compile()

    def run(self, method: str, scenario: ScenarioType, inputs: Dict[str, Any]) -> EvaluationReport:
        """
        Execute the graph and return the evaluation report.
        """
        initial_state: EvaluationState = {
            "scenario": scenario,
            "method": method,
            "inputs": inputs,
            "result": None,
            "error": None,
        }
        final_state = self.app.invoke(initial_state)
        if final_state.get("error"):
            raise RuntimeError(f"LangGraph orchestration failed: {final_state['error']}")
        return final_state["result"]
