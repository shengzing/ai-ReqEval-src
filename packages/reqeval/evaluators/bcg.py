"""
BCG变革配比评估器 (10-20-70)

核心逻辑：
- 技术投入占比（10%）
- IT/数据基础设施投入占比（20%）
- 业务变革投入占比（70%）
目标是避免技术中心化，确保业务变革占比足够。
"""
from typing import Dict, List, Any
from dataclasses import dataclass

from .base import BaseEvaluator, EvaluatorConfig
from src.packages.reqeval.data.models import (
    EvaluationReport, MetricResult, ScenarioType, EvaluationMethod
)


@dataclass
class BCGAllocation:
    tech_pct: float
    it_pct: float
    business_pct: float
    imbalance_score: float  # 0-10，越低表示偏差越大
    allocation_gap: Dict[str, float]  # 相对目标配比的偏差（百分点）
    risk_flags: List[str] = None


class BCGEvaluator(BaseEvaluator):
    """
    BCG变革配比评估器
    """

    TARGETS = {"tech": 10, "it": 20, "business": 70}  # 目标配比(%)

    def _get_config(self) -> EvaluatorConfig:
        return EvaluatorConfig(
            method=EvaluationMethod.BCG,
            name="BCG变革配比法(10-20-70)",
            name_en="BCG Transformation Allocation",
            description="强调AI项目中的业务变革投入（70%）优先，防止技术中心化",
            applicable_scenarios=[
                "数字化/智能化转型立项",
                "AI项目预算与资源审计",
                "评估业务变革深度"
            ],
            core_metrics=[
                "技术投入占比", "IT/数据基建占比", "业务变革占比",
                "配比偏差", "变革深度评分"
            ],
            pre_evaluation_desc="预算与资源审计（10-20-70配比）",
            post_evaluation_desc="变革深度与价值归因"
        )

    def get_required_inputs(self, scenario: ScenarioType) -> Dict[str, Any]:
        if scenario == ScenarioType.PRE:
            return {
                "fields": ["project_name", "budget_total"],
                "optional_fields": ["budget_tech", "budget_it", "budget_business", "has_change_champions"],
                "descriptions": {
                    "project_name": "项目名称",
                    "budget_total": "总预算(万元)",
                    "budget_tech": "模型/算法投入(万元)",
                    "budget_it": "IT和数据基建投入(万元)",
                    "budget_business": "业务变革投入(万元)",
                    "has_change_champions": "是否有业务变革owner/冠军团队"
                }
            }
        else:
            return {
                "fields": ["project_name"],
                "optional_fields": [
                    "actual_budget_tech", "actual_budget_it", "actual_budget_business",
                    "process_reengineering_score", "adoption_rate", "value_attribution_clarity"
                ],
                "descriptions": {
                    "project_name": "项目名称",
                    "actual_budget_tech": "实际模型/算法投入(万元)",
                    "actual_budget_it": "实际IT/数据基建投入(万元)",
                    "actual_budget_business": "实际业务变革投入(万元)",
                    "process_reengineering_score": "流程重塑深度(1-10)",
                    "adoption_rate": "一线团队采纳率(%)",
                    "value_attribution_clarity": "价值归因清晰度(1-10)"
                }
            }

    def pre_evaluation(self, inputs: Dict[str, Any]) -> EvaluationReport:
        allocation = self._calculate_allocation(
            tech=inputs.get("budget_tech"),
            it=inputs.get("budget_it"),
            business=inputs.get("budget_business"),
        )

        metrics = self.calculate_metrics({"allocation": allocation, "scenario": "pre"})
        summary = self._generate_pre_summary(inputs, allocation)
        recommendations = self._generate_pre_recommendations(allocation, inputs)

        return self.generate_report(
            scenario=ScenarioType.PRE,
            metrics=metrics,
            summary=summary,
            recommendations=recommendations,
            user_input=inputs,
            documents=inputs.get("documents", []),
            visualizations=self._generate_pre_visualizations(allocation)
        )

    def post_evaluation(self, inputs: Dict[str, Any]) -> EvaluationReport:
        allocation = self._calculate_allocation(
            tech=inputs.get("actual_budget_tech"),
            it=inputs.get("actual_budget_it"),
            business=inputs.get("actual_budget_business"),
        )

        process_score = float(inputs.get("process_reengineering_score", 5))
        adoption_rate = float(inputs.get("adoption_rate", 50))
        value_attr = float(inputs.get("value_attribution_clarity", 5))

        metrics = self.calculate_metrics({
            "allocation": allocation,
            "scenario": "post",
            "process_score": process_score,
            "adoption_rate": adoption_rate,
            "value_attr": value_attr,
            "flow_reengineering_rate": min(100.0, process_score * 10),
        })

        summary = self._generate_post_summary(inputs, allocation, process_score, adoption_rate, value_attr)
        recommendations = self._generate_post_recommendations(allocation, process_score, adoption_rate, value_attr)

        return self.generate_report(
            scenario=ScenarioType.POST,
            metrics=metrics,
            summary=summary,
            recommendations=recommendations,
            user_input=inputs,
            documents=inputs.get("documents", []),
            visualizations=self._generate_post_visualizations(allocation, process_score, adoption_rate, value_attr)
        )

    def calculate_metrics(self, data: Dict[str, Any]) -> List[MetricResult]:
        allocation: BCGAllocation = data["allocation"]
        scenario = data.get("scenario", "pre")
        metrics = [
            MetricResult(
                name="技术投入占比",
                value=round(allocation.tech_pct, 1),
                unit="%",
                category="配比"
            ),
            MetricResult(
                name="IT/数据基建占比",
                value=round(allocation.it_pct, 1),
                unit="%",
                category="配比"
            ),
            MetricResult(
                name="业务变革占比",
                value=round(allocation.business_pct, 1),
                unit="%",
                category="配比"
            ),
            MetricResult(
                name="配比平衡度",
                value=round(allocation.imbalance_score, 1),
                unit="分",
                description="10=完全符合10/20/70，低于6需调整",
                category="配比"
            ),
        ]

        # 偏差指标
        for k, gap in allocation.allocation_gap.items():
            metrics.append(MetricResult(
                name=f"偏差-{k}",
                value=round(gap, 1),
                unit="百分点",
                category="配比偏差"
            ))

        if scenario == "post":
            metrics.extend([
                MetricResult(
                    name="流程重塑深度",
                    value=round(data.get("process_score", 0), 1),
                    unit="分",
                    category="变革深度"
                ),
                MetricResult(
                    name="采纳率",
                    value=round(data.get("adoption_rate", 0), 1),
                    unit="%",
                    category="变革落地"
                ),
                MetricResult(
                    name="流程重塑率",
                    value=round(data.get("flow_reengineering_rate", 0), 1),
                    unit="%",
                    description="估算：流程重塑深度×10%",
                    category="变革落地"
                ),
                MetricResult(
                    name="价值归因清晰度",
                    value=round(data.get("value_attr", 0), 1),
                    unit="分",
                    category="治理"
                ),
            ])

        return metrics

    def _calculate_allocation(self, tech: Any, it: Any, business: Any) -> BCGAllocation:
        tech = float(tech or 0)
        it = float(it or 0)
        business = float(business or 0)
        total = tech + it + business
        if total <= 0:
            return BCGAllocation(0, 0, 0, imbalance_score=0, allocation_gap={}, risk_flags=["未提供预算"])

        tech_pct = tech / total * 100
        it_pct = it / total * 100
        business_pct = business / total * 100

        gaps = {
            "技术": tech_pct - self.TARGETS["tech"],
            "IT/数据": it_pct - self.TARGETS["it"],
            "业务变革": business_pct - self.TARGETS["business"],
        }

        # 用偏差绝对值的平均映射到 0-10 分
        avg_abs_gap = (abs(gaps["技术"]) + abs(gaps["IT/数据"]) + abs(gaps["业务变革"])) / 3
        imbalance_score = max(0, 10 - avg_abs_gap * 0.2)  # 10分代表完美配比，偏差每5个百分点扣1分

        risk_flags: List[str] = []
        if business_pct < 50:
            risk_flags.append("业务变革投入<50%，高风险（技术中心化）")
        if imbalance_score < 6:
            risk_flags.append("配比严重失衡")
        if tech_pct > self.TARGETS["tech"] + 20:
            risk_flags.append("技术投入占比过高，易陷入试点炼狱")

        return BCGAllocation(
            tech_pct=tech_pct,
            it_pct=it_pct,
            business_pct=business_pct,
            imbalance_score=imbalance_score,
            allocation_gap=gaps,
            risk_flags=risk_flags
        )

    def _generate_pre_summary(self, inputs: Dict[str, Any], allocation: BCGAllocation) -> str:
        return f"""
## BCG变革配比（立项前）报告

### 项目信息
- **项目名称**: {inputs.get('project_name', '未命名')}
- **总预算**: {inputs.get('budget_total', '-') } 万元

### 预算配比
| 维度 | 当前占比 | 目标占比 |
|------|----------|----------|
| 技术(模型/算法) | {allocation.tech_pct:.1f}% | {self.TARGETS['tech']}% |
| IT/数据基建 | {allocation.it_pct:.1f}% | {self.TARGETS['it']}% |
| 业务变革 | {allocation.business_pct:.1f}% | {self.TARGETS['business']}% |

### 结论
- 配比平衡度: {allocation.imbalance_score:.1f}/10
- 业务变革投入偏差: {allocation.allocation_gap.get('业务变革', 0):.1f} 个百分点
"""

    def _generate_post_summary(
        self,
        inputs: Dict[str, Any],
        allocation: BCGAllocation,
        process_score: float,
        adoption_rate: float,
        value_attr: float
    ) -> str:
        return f"""
## BCG变革配比（实施后）报告

### 项目信息
- **项目名称**: {inputs.get('project_name', '未命名')}

### 实际投入配比
| 维度 | 实际占比 | 目标占比 |
|------|----------|----------|
| 技术(模型/算法) | {allocation.tech_pct:.1f}% | {self.TARGETS['tech']}% |
| IT/数据基建 | {allocation.it_pct:.1f}% | {self.TARGETS['it']}% |
| 业务变革 | {allocation.business_pct:.1f}% | {self.TARGETS['business']}% |

### 变革落地
- 流程重塑深度: {process_score:.1f}/10
- 一线采纳率: {adoption_rate:.1f}%
- 价值归因清晰度: {value_attr:.1f}/10
"""

    def _generate_pre_recommendations(self, allocation: BCGAllocation, inputs: Dict[str, Any]) -> List[str]:
        recs = []
        if allocation.business_pct < self.TARGETS["business"]:
            recs.append("业务变革投入不足：增加流程重塑、培训、变革管理预算，确保70%投入")
        if allocation.tech_pct > self.TARGETS["tech"] + 10:
            recs.append("技术投入过高：避免技术中心化，适当将预算转向变革和基建")
        if allocation.it_pct < self.TARGETS["it"] - 10:
            recs.append("IT/数据投入不足：补齐数据治理、管线、监控等基建")
        if inputs.get("has_change_champions") is not True:
            recs.append("建议指定业务变革Champion，负责推进采纳和流程重塑")
        if allocation.risk_flags:
            recs.extend(allocation.risk_flags)
        if not recs:
            recs.append("配比合理，建议保持10/20/70原则并持续跟踪执行")
        return recs

    def _generate_post_recommendations(
        self,
        allocation: BCGAllocation,
        process_score: float,
        adoption_rate: float,
        value_attr: float
    ) -> List[str]:
        recs = []
        if allocation.business_pct < self.TARGETS["business"]:
            recs.append("实际业务变革投入不足：补足培训/流程重塑资源，提升一线采纳率")
        if process_score < 6:
            recs.append("流程重塑深度不足：识别高价值流程，优先改造核心旅程")
        if adoption_rate < 60:
            recs.append("采纳率偏低：加强变革沟通与激励机制，收集一线阻力点")
        if value_attr < 6:
            recs.append("价值归因不清：建立收益归因框架，明确KPI到收益的映射")
        if allocation.risk_flags:
            recs.extend(allocation.risk_flags)
        if not recs:
            recs.append("变革执行良好，保持10/20/70配比并持续监测采纳率和价值归因")
        return recs

    def _generate_pre_visualizations(self, allocation: BCGAllocation) -> Dict[str, Any]:
        return {
            "allocation_bar": {
                "type": "bar",
                "title": "预算配比 vs 目标",
                "data": {
                    "技术": allocation.tech_pct - self.TARGETS["tech"],
                    "IT/数据": allocation.it_pct - self.TARGETS["it"],
                    "业务变革": allocation.business_pct - self.TARGETS["business"],
                }
            }
        }

    def _generate_post_visualizations(
        self,
        allocation: BCGAllocation,
        process_score: float,
        adoption_rate: float,
        value_attr: float
    ) -> Dict[str, Any]:
        return {
            "allocation_bar": {
                "type": "bar",
                "title": "实际配比偏差",
                "data": {
                    "技术": allocation.tech_pct - self.TARGETS["tech"],
                    "IT/数据": allocation.it_pct - self.TARGETS["it"],
                    "业务变革": allocation.business_pct - self.TARGETS["business"],
                }
            },
            "change_radar": {
                "type": "radar",
                "title": "变革落地",
                "categories": ["流程重塑深度", "采纳率(归一到10)", "价值归因清晰度"],
                "values": [process_score, min(10, adoption_rate / 10), value_attr],
                "max_value": 10
            }
        }

    def get_prompt_templates(self) -> Dict[str, str]:
        return {
            "pre": (
                "你是一名BCG变革配比评估顾问，需审计10/20/70资源分配。\n"
                "输入：预算/时间在模型、IT/数据、业务变革的占比。\n"
                "输出：配比偏差、平衡度评分、高风险预警（若业务变革<50%需警告）。"
            ),
            "post": (
                "你是一名流程变革复盘分析师，需评估实际投入配比与变革落地。\n"
                "输入：实际技术/IT/业务投入，流程重塑深度、采纳率、价值归因清晰度。\n"
                "输出：配比偏差、变革落地雷达、是否进入试点炼狱的诊断建议。"
            ),
        }
