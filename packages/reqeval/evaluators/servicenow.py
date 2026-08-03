"""
ServiceNow/Deloitte 价值三角评估器

三角维度：成本、运营、体验（每项 1-10 分），综合平衡度为平均分。
"""
from typing import Dict, List, Any
from dataclasses import dataclass

from .base import BaseEvaluator, EvaluatorConfig
from src.packages.reqeval.data.models import (
    EvaluationReport, MetricResult, ScenarioType, EvaluationMethod
)


@dataclass
class TriangleScores:
    cost: float
    operation: float
    experience: float
    balance: float
    imbalance: float = 0.0  # 最大维度差
    guardrail_breach: bool = False


class ServiceNowEvaluator(BaseEvaluator):
    def _get_config(self) -> EvaluatorConfig:
        return EvaluatorConfig(
            method=EvaluationMethod.SERVICENOW,
            name="ServiceNow/Deloitte价值三角",
            name_en="ServiceNow Value Triangle",
            description="关注成本、运营、体验三角平衡，避免单维度优化",
            applicable_scenarios=[
                "AI客服/IT服务场景",
                "AI代码助手/工单自动化",
                "需要平衡成本、SLA与用户体验的场景"
            ],
            core_metrics=["单位成本", "处理时长/吞吐量", "用户体验/采纳率", "平衡度"],
            pre_evaluation_desc="三角破坏测试与Guardrails设定",
            post_evaluation_desc="平衡性诊断与偏态分析"
        )

    def get_required_inputs(self, scenario: ScenarioType) -> Dict[str, Any]:
        base_fields = ["service_name"]
        optional = [
            "cost_score", "operation_score", "experience_score",
            "unit_cost", "sla_hours", "throughput", "csat", "nps"
        ]
        descriptions = {
            "service_name": "服务/场景名称",
            "cost_score": "成本维度评分 1-10",
            "operation_score": "运营维度评分 1-10 (时长/吞吐/SLA)",
            "experience_score": "体验维度评分 1-10 (CSAT/NPS/采纳率)",
            "unit_cost": "单位处理成本(元)",
            "sla_hours": "平均处理时长(小时)",
            "throughput": "月度吞吐量",
            "csat": "客户满意度(0-100)",
            "nps": "NPS (-100~100)",
        }
        return {"fields": base_fields, "optional_fields": optional, "descriptions": descriptions}

    def pre_evaluation(self, inputs: Dict[str, Any]) -> EvaluationReport:
        scores = self._calculate_scores(inputs)
        metrics = self.calculate_metrics({"scores": scores, "inputs": inputs})
        summary = self._generate_summary(inputs, scores, "建设前价值三角评估")
        recommendations = self._generate_recommendations(scores)
        return self.generate_report(
            scenario=ScenarioType.PRE,
            metrics=metrics,
            summary=summary,
            recommendations=recommendations,
            user_input=inputs,
            documents=inputs.get("documents", []),
            visualizations=self._generate_visualizations(scores)
        )

    def post_evaluation(self, inputs: Dict[str, Any]) -> EvaluationReport:
        scores = self._calculate_scores(inputs)
        metrics = self.calculate_metrics({"scores": scores, "inputs": inputs})
        summary = self._generate_summary(inputs, scores, "建设后价值三角评估")
        recommendations = self._generate_recommendations(scores)
        return self.generate_report(
            scenario=ScenarioType.POST,
            metrics=metrics,
            summary=summary,
            recommendations=recommendations,
            user_input=inputs,
            documents=inputs.get("documents", []),
            visualizations=self._generate_visualizations(scores)
        )

    def calculate_metrics(self, data: Dict[str, Any]) -> List[MetricResult]:
        scores: TriangleScores = data["scores"]
        return [
            MetricResult(name="成本", value=round(scores.cost, 1), unit="分", category="成本"),
            MetricResult(name="运营", value=round(scores.operation, 1), unit="分", category="运营"),
            MetricResult(name="体验", value=round(scores.experience, 1), unit="分", category="体验"),
            MetricResult(name="平衡度", value=round(scores.balance, 1), unit="分", category="综合"),
            MetricResult(name="三角失衡度", value=round(scores.imbalance, 1), unit="分", description="三维最大差值，>2 表示偏态", category="综合"),
            MetricResult(name="Guardrail触发", value="是" if scores.guardrail_breach else "否", category="治理"),
        ]

    def _calculate_scores(self, inputs: Dict[str, Any]) -> TriangleScores:
        cost = float(inputs.get("cost_score", 6))
        operation = float(inputs.get("operation_score", 6))
        experience = float(inputs.get("experience_score", 6))
        balance = (cost + operation + experience) / 3
        imbalance = max(cost, operation, experience) - min(cost, operation, experience)
        guardrail = experience < 6 or inputs.get("csat", 80) < 60 or inputs.get("nps", 0) < 0
        return TriangleScores(cost=cost, operation=operation, experience=experience, balance=balance, imbalance=imbalance, guardrail_breach=guardrail)

    def _generate_summary(self, inputs: Dict[str, Any], scores: TriangleScores, title: str) -> str:
        return f"""
## {title}

- **场景**: {inputs.get('service_name', '未命名')}
- 平衡度: {scores.balance:.1f}/10
"""

    def _generate_recommendations(self, scores: TriangleScores) -> List[str]:
        recs = []
        dims = [("成本", scores.cost), ("运营", scores.operation), ("体验", scores.experience)]
        min_dim = min(dims, key=lambda x: x[1])
        recs.append(f"最弱维度：{min_dim[0]}，建议在不牺牲其他两项的前提下补强")
        if scores.cost < 6:
            recs.append("成本偏高：优化单位成本，审查模型/推理花费与人工对比")
        if scores.operation < 6:
            recs.append("运营效率不足：提升自动化/编排，缩短SLA并提升吞吐")
        if scores.experience < 6:
            recs.append("体验不足：关注CSAT/NPS与采纳率，优化响应质量与可用性")
        if scores.guardrail_breach:
            recs.append("触发体验/满意度 Guardrail：优先修复体验，再考虑成本和速度")
        if scores.imbalance > 2:
            recs.append("三角失衡度>2：存在偏态，需平衡成本、运营、体验")
        return recs

    def _generate_visualizations(self, scores: TriangleScores) -> Dict[str, Any]:
        return {
            "triangle_radar": {
                "type": "radar",
                "title": "价值三角",
                "categories": ["成本", "运营", "体验"],
                "values": [scores.cost, scores.operation, scores.experience],
                "max_value": 10,
            }
        }

    def get_prompt_templates(self) -> Dict[str, str]:
        return {
            "pre": (
                "你是一名价值三角评估顾问，需进行三角破坏测试并设定Guardrails。\n"
                "输入：服务场景、成本/运营/体验基线与目标。\n"
                "输出：三角平衡度、可能的负向影响预测，并设定体验底线(如NPS/CSAT下降阈值)。"
            ),
            "post": (
                "你是一名平衡性诊断顾问，需评估成本、运营、体验三角是否失衡。\n"
                "输入：成本、处理时长/吞吐、CSAT/NPS/采纳率等。\n"
                "输出：三角雷达、最弱顶点、偏态诊断和修正建议。"
            ),
        }
