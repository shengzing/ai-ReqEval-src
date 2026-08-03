from __future__ import annotations

from pathlib import Path

from .storage import JsonStore


class QASupport:
    def __init__(self, base_dir: str | Path) -> None:
        self.store = JsonStore(base_dir)

    def answer(self, project_id: str, question: str) -> str:
        lowered = question.strip().lower()
        project = self.store.read(project_id, "project_meta")
        scenario = self.store.read(project_id, "scenario_record")
        value = self.store.read(project_id, "value_record")
        result = self.store.read_or_none(project_id, "processing_result")

        if result is None:
            return (
                f"项目“{project['name']}”尚未生成处理结果。"
                "请先执行 process 命令，再进行问答。"
            )

        if "风险" in question or "risk" in lowered:
            return (
                f"项目“{project['name']}”的场景风险等级为 {scenario['risk_level']}，"
                f"HITL 等级为 {scenario['hitl_level']}，"
                f"审计要求包括：{', '.join(scenario['audit_requirements'])}。"
                " 来源：scenario_record.json。"
            )
        if "目标" in question or "sla" in lowered:
            return (
                f"目标SLA为 {result['target_sla']:.4f}，"
                f"Actual SLA为 {result['actual_sla']:.4f}，"
                f"当前建议为 {result['decision']['recommendation']}。"
                " 来源：processing_result.json。"
            )
        if "成本" in question or "价值" in question or "cost" in lowered or "value" in lowered:
            return (
                f"实施税合计为 {result['implementation_tax_total']:.2f}，"
                f"净价值为 {result['net_value']:.2f}，"
                f"业务预期收益为 {float(value['expected_benefit']):.2f}。"
                " 来源：value_record.json 与 processing_result.json。"
            )
        if "证据" in question or "报告" in question or "evidence" in lowered or "report" in lowered:
            stage_4 = self.store.read_or_none(project_id, "stage_4_result") or {}
            return (
                f"当前结论为 {stage_4.get('recommendation', result['decision']['recommendation'])}。"
                f"主要依据是 {stage_4.get('reason', result['decision']['reason'])}。"
                " 来源：stage_4_result.json 与 processing_result.json。"
            )
        if "为什么" in question or "原因" in question or "why" in lowered:
            return result["decision"]["reason"] + " 来源：processing_result.json。"

        return (
            f"项目“{project['name']}”当前建议为 {result['decision']['recommendation']}。"
            "可继续追问风险、目标SLA、Actual SLA、成本、价值或原因。"
            " 来源：项目结构化产出物。"
        )
