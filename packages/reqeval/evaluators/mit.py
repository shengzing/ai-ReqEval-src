"""
MIT AI平衡计分卡评估器

四个象限：财务、客户、流程、学习与成长
每个象限 1-10 分，综合为平均分。
"""
from typing import Dict, List, Any
from dataclasses import dataclass

from .base import BaseEvaluator, EvaluatorConfig
from src.packages.reqeval.data.models import (
    EvaluationReport, MetricResult, ScenarioType, EvaluationMethod
)


@dataclass
class MITScores:
    finance: float
    customer: float
    process: float
    learning: float
    overall: float


class MITEvaluator(BaseEvaluator):
    def _get_config(self) -> EvaluatorConfig:
        return EvaluatorConfig(
            method=EvaluationMethod.MIT,
            name="MIT AI平衡计分卡",
            name_en="MIT AI Balanced Scorecard",
            description="从财务、客户、流程、学习四象限评估AI价值，兼顾无形资产",
            applicable_scenarios=[
                "董事会/管理层汇报",
                "长期战略规划",
                "评估AI无形资产（数据/算法/人才）"
            ],
            core_metrics=["财务ROI", "客户满意度", "流程效率", "学习与成长", "综合平衡度"],
            pre_evaluation_desc="价值地图绘制（四象限映射）",
            post_evaluation_desc="无形资产盘点与平衡性评分"
        )

    def get_required_inputs(self, scenario: ScenarioType) -> Dict[str, Any]:
        fields = ["project_name"]
        optional = [
            "finance_score", "customer_score", "process_score", "learning_score",
            "data_asset_score", "talent_density_score"
        ]
        descriptions = {
            "project_name": "项目名称",
            "finance_score": "财务（ROI/成本收益）1-10",
            "customer_score": "客户/用户体验 1-10",
            "process_score": "流程效率 1-10",
            "learning_score": "学习与成长（人才/数据/算法资产）1-10",
            "data_asset_score": "数据资产评分 1-10",
            "talent_density_score": "AI人才密度 1-10",
        }
        return {"fields": fields, "optional_fields": optional, "descriptions": descriptions}

    def pre_evaluation(self, inputs: Dict[str, Any]) -> EvaluationReport:
        scores = self._calculate_scores(inputs)
        intangible_score = self._calculate_intangible_score(inputs)
        metrics = self.calculate_metrics({"scores": scores, "intangible_score": intangible_score})
        summary = self._generate_summary(inputs, scores, "建设前平衡计分卡", intangible_score)
        recommendations = self._generate_recommendations(scores, intangible_score)
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
        intangible_score = self._calculate_intangible_score(inputs)
        metrics = self.calculate_metrics({"scores": scores, "intangible_score": intangible_score})
        summary = self._generate_summary(inputs, scores, "建设后平衡计分卡", intangible_score)
        recommendations = self._generate_recommendations(scores, intangible_score)
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
        scores: MITScores = data["scores"]
        intangible = data.get("intangible_score", scores.learning)
        return [
            MetricResult(name="财务", value=round(scores.finance, 1), unit="分", category="财务"),
            MetricResult(name="客户", value=round(scores.customer, 1), unit="分", category="客户"),
            MetricResult(name="流程", value=round(scores.process, 1), unit="分", category="流程"),
            MetricResult(name="学习与成长", value=round(scores.learning, 1), unit="分", category="学习与成长"),
            MetricResult(name="综合平衡度", value=round(scores.overall, 1), unit="分", category="综合"),
            MetricResult(name="无形资产估值评分", value=round(intangible, 1), unit="分", category="学习与成长"),
        ]

    def _calculate_scores(self, inputs: Dict[str, Any]) -> MITScores:
        finance = float(inputs.get("finance_score", 6))
        customer = float(inputs.get("customer_score", 6))
        process = float(inputs.get("process_score", 6))
        learning_base = float(inputs.get("learning_score", 6))
        data_asset = float(inputs.get("data_asset_score", learning_base))
        talent = float(inputs.get("talent_density_score", learning_base))
        # 学习维度考虑数据+人才平均
        learning = (learning_base + data_asset + talent) / 3
        overall = (finance + customer + process + learning) / 4
        return MITScores(finance=finance, customer=customer, process=process, learning=learning, overall=overall)

    def _calculate_intangible_score(self, inputs: Dict[str, Any]) -> float:
        """
        简化的无形资产估值评分：数据资产与人才密度平均。
        """
        data_asset = float(inputs.get("data_asset_score", 6))
        talent = float(inputs.get("talent_density_score", 6))
        return (data_asset + talent) / 2

    def _generate_summary(self, inputs: Dict[str, Any], scores: MITScores, title: str, intangible_score: float) -> str:
        return f"""
## {title}

- **项目名称**: {inputs.get('project_name', '未命名')}
- 综合平衡度: {scores.overall:.1f}/10
- 无形资产估值评分: {intangible_score:.1f}/10

### 四象限评分
| 维度 | 得分 |
|------|------|
| 财务 | {scores.finance:.1f} |
| 客户 | {scores.customer:.1f} |
| 流程 | {scores.process:.1f} |
| 学习与成长 | {scores.learning:.1f} |
"""

    def _generate_recommendations(self, scores: MITScores, intangible_score: float) -> List[str]:
        recs = []
        min_dim = min(
            [("财务", scores.finance), ("客户", scores.customer),
             ("流程", scores.process), ("学习与成长", scores.learning)],
            key=lambda x: x[1]
        )
        recs.append(f"最弱维度：{min_dim[0]}，建议优先补强该象限")
        if scores.learning < 6:
            recs.append("学习与成长不足：提升数据资产和AI人才密度，建设知识库/特征库")
        if scores.finance < 6:
            recs.append("财务回报不足：梳理商业模式或成本节约路径，明确ROI口径")
        if intangible_score < 6:
            recs.append("无形资产得分偏低：补齐数据资产和人才密度，避免短视项目")
        if scores.learning < 6 and scores.finance > 7:
            recs.append("存在盲点：财务不错但学习与成长偏低，注意长期能力建设")
        return recs

    def _generate_visualizations(self, scores: MITScores) -> Dict[str, Any]:
        return {
            "mit_radar": {
                "type": "radar",
                "title": "MIT平衡计分卡",
                "categories": ["财务", "客户", "流程", "学习与成长"],
                "values": [scores.finance, scores.customer, scores.process, scores.learning],
                "max_value": 10,
            }
        }

    def get_prompt_templates(self) -> Dict[str, str]:
        return {
            "pre": (
                "你是一名平衡计分卡顾问，需将AI项目价值映射到财务/客户/流程/学习四象限。\n"
                "要求每个象限必须有指标，若学习与成长为空应提示盲点。\n"
                "输出四象限评分、综合平衡度及最弱象限改进建议。"
            ),
            "post": (
                "你是一名AI价值复盘顾问，需盘点无形资产并检查四象限平衡。\n"
                "输入：财务/客户/流程数据以及数据资产、算法资产、人才密度。\n"
                "输出：四象限评分、综合平衡度、弱项与改进建议。"
            ),
        }
