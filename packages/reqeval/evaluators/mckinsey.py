"""
麦肯锡高效能基准评估器

核心逻辑：通过对标行业"AI高效能者（AI High Performers）"进行评估
- 部署原型选择：Taker/Shaper/Maker
- 五大评估维度：部署原型、战略、运营模式、技术与数据、风险管理
"""
from typing import Dict, List, Any
from dataclasses import dataclass
from enum import Enum

from .base import BaseEvaluator, EvaluatorConfig
from src.packages.reqeval.data.models import (
    EvaluationReport, MetricResult, DocumentInfo,
    ScenarioType, EvaluationMethod
)


class DeploymentArchetype(str, Enum):
    """部署原型"""
    TAKER = "taker"  # 直接使用
    SHAPER = "shaper"  # 微调/集成
    MAKER = "maker"  # 自研模型


@dataclass
class MaturityScore:
    """成熟度评分"""
    deployment: float  # 部署原型得分
    strategy: float  # 战略得分
    operating_model: float  # 运营模式得分
    tech_data: float  # 技术与数据得分
    risk: float  # 风险管理得分
    overall: float  # 综合得分
    archetype: DeploymentArchetype  # 建议的部署原型
    details: Dict[str, Any]  # 详细评分


class McKinseyEvaluator(BaseEvaluator):
    """
    麦肯锡高效能基准评估器

    适用场景：
    - 企业级AI成熟度评估
    - 寻找与行业领跑者的差距
    - AI战略规划
    """

    # 高效能者基准（基于麦肯锡报告）
    HIGH_PERFORMER_BENCHMARKS = {
        "project_cycle": 4,  # 项目上线周期（月）
        "component_reuse_rate": 60,  # 组件复用率(%)
        "monitoring_coverage": 80,  # 监控覆盖率(%)
        "ebit_contribution": 10,  # EBIT贡献(%)
    }

    def _get_config(self) -> EvaluatorConfig:
        return EvaluatorConfig(
            method=EvaluationMethod.MCKINSEY,
            name="麦肯锡高效能基准法",
            name_en="McKinsey High Performer Benchmarking",
            description="通过对标行业高效能者的实践，评估AI部署路径和成熟度",
            applicable_scenarios=[
                "企业级AI成熟度评估",
                "寻找与行业领跑者的差距",
                "AI战略规划",
                "数字化转型评估"
            ],
            core_metrics=[
                "部署原型", "战略清晰度", "运营敏捷度",
                "技术工程化水平", "风险管理成熟度", "综合成熟度"
            ],
            pre_evaluation_desc="部署路径决策（Taker/Shaper/Maker）",
            post_evaluation_desc="成熟度对标与差距分析"
        )

    def get_required_inputs(self, scenario: ScenarioType) -> Dict[str, Any]:
        if scenario == ScenarioType.PRE:
            return {
                "fields": ["project_name", "business_requirement"],
                "optional_fields": [
                    "data_assets", "team_capability", "budget",
                    "timeline_requirement", "data_sensitivity"
                ],
                "descriptions": {
                    "project_name": "项目名称",
                    "business_requirement": "业务需求描述",
                    "data_assets": "数据资产情况（是否有独特私有数据）",
                    "team_capability": "AI工程团队能力（人数、技能栈）",
                    "budget": "项目预算",
                    "timeline_requirement": "时间要求",
                    "data_sensitivity": "数据敏感度级别"
                }
            }
        else:
            return {
                "fields": ["project_name"],
                "optional_fields": [
                    "project_duration", "ebit_contribution",
                    "has_roadmap", "has_coe", "has_agile_budget",
                    "component_reuse_rate", "monitoring_coverage",
                    "has_early_compliance", "has_hallucination_mitigation"
                ],
                "descriptions": {
                    "project_name": "项目名称",
                    "project_duration": "项目上线周期(月)",
                    "ebit_contribution": "EBIT贡献估算(%)",
                    "has_roadmap": "是否有全企业AI路线图",
                    "has_coe": "是否有中心化团队(COE)",
                    "has_agile_budget": "预算流程是否支持敏捷迭代",
                    "component_reuse_rate": "组件复用率(%)",
                    "monitoring_coverage": "模型监控覆盖率(%)",
                    "has_early_compliance": "法律/合规是否在开发初期介入",
                    "has_hallucination_mitigation": "是否有幻觉缓解措施"
                }
            }

    def pre_evaluation(self, inputs: Dict[str, Any]) -> EvaluationReport:
        """前期评估：部署路径决策"""
        # 判定部署原型
        archetype = self._determine_archetype(inputs)

        # 预测项目周期
        predicted_cycle = self._predict_project_cycle(archetype)

        # 生成建议
        recommendations = self._generate_archetype_recommendations(archetype, inputs)

        metrics = [
            MetricResult(
                name="建议部署原型",
                value=self._get_archetype_name(archetype),
                description=self._get_archetype_description(archetype),
                category="部署决策"
            ),
            MetricResult(
                name="预计上线周期",
                value=predicted_cycle,
                unit="个月",
                description="基于部署原型的典型周期",
                category="项目规划"
            ),
            MetricResult(
                name="定制化程度",
                value=self._get_customization_level(archetype),
                unit="",
                category="技术选型"
            )
        ]

        summary = self._generate_pre_summary(archetype, predicted_cycle, inputs)

        return self.generate_report(
            scenario=ScenarioType.PRE,
            metrics=metrics,
            summary=summary,
            recommendations=recommendations,
            user_input=inputs,
            documents=inputs.get("documents", []),
            visualizations=self._generate_pre_visualizations(archetype)
        )

    def post_evaluation(self, inputs: Dict[str, Any]) -> EvaluationReport:
        """后期验证：成熟度对标"""
        # 计算成熟度评分
        maturity = self._calculate_maturity_score(inputs)

        # 与高效能者基准比对
        gaps = self._analyze_gaps(inputs, maturity)

        metrics = self.calculate_metrics({"maturity": maturity, "gaps": gaps})

        summary = self._generate_post_summary(maturity, gaps, inputs)
        recommendations = self._generate_gap_recommendations(gaps)

        return self.generate_report(
            scenario=ScenarioType.POST,
            metrics=metrics,
            summary=summary,
            recommendations=recommendations,
            user_input=inputs,
            documents=inputs.get("documents", []),
            visualizations=self._generate_post_visualizations(maturity, gaps)
        )

    def calculate_metrics(self, data: Dict[str, Any]) -> List[MetricResult]:
        """计算评估指标"""
        maturity: MaturityScore = data.get("maturity")
        gaps: Dict = data.get("gaps", {})

        if not maturity:
            return []

        metrics = [
            MetricResult(
                name="综合成熟度",
                value=round(maturity.overall, 1),
                unit="分",
                description="五维度加权平均(满分10分)",
                category="综合评估"
            ),
            MetricResult(
                name="部署原型成熟度",
                value=round(maturity.deployment, 1),
                unit="分",
                category="维度评分"
            ),
            MetricResult(
                name="战略成熟度",
                value=round(maturity.strategy, 1),
                unit="分",
                category="维度评分"
            ),
            MetricResult(
                name="运营模式成熟度",
                value=round(maturity.operating_model, 1),
                unit="分",
                category="维度评分"
            ),
            MetricResult(
                name="技术与数据成熟度",
                value=round(maturity.tech_data, 1),
                unit="分",
                category="维度评分"
            ),
            MetricResult(
                name="风险管理成熟度",
                value=round(maturity.risk, 1),
                unit="分",
                category="维度评分"
            )
        ]

        # 添加差距指标
        for gap_name, gap_value in gaps.items():
            metrics.append(MetricResult(
                name=f"差距-{gap_name}",
                value=gap_value.get("gap", 0),
                unit=gap_value.get("unit", ""),
                description=f"当前: {gap_value.get('current')}, 基准: {gap_value.get('benchmark')}",
                category="差距分析"
            ))

        return metrics

    def _determine_archetype(self, inputs: Dict[str, Any]) -> DeploymentArchetype:
        """判定部署原型"""
        business_req = inputs.get("business_requirement", "").lower()
        data_assets = inputs.get("data_assets", "")
        team_capability = inputs.get("team_capability", "")
        data_sensitivity = inputs.get("data_sensitivity", "")

        # 简单规则判断
        score = 0

        # 数据依赖度
        if "独特" in data_assets or "私有" in data_assets or "专有" in data_assets:
            score += 2
        if "敏感" in data_sensitivity or "高" in data_sensitivity:
            score += 1

        # 团队能力
        if "资深" in team_capability or "强" in team_capability:
            score += 2

        # 业务需求复杂度
        complex_keywords = ["自研", "颠覆", "创新", "核心竞争力", "差异化"]
        if any(kw in business_req for kw in complex_keywords):
            score += 2

        simple_keywords = ["通用", "邮件", "助手", "简单", "快速"]
        if any(kw in business_req for kw in simple_keywords):
            score -= 2

        if score >= 4:
            return DeploymentArchetype.MAKER
        elif score >= 1:
            return DeploymentArchetype.SHAPER
        else:
            return DeploymentArchetype.TAKER

    def _predict_project_cycle(self, archetype: DeploymentArchetype) -> int:
        """预测项目周期"""
        cycles = {
            DeploymentArchetype.TAKER: 2,
            DeploymentArchetype.SHAPER: 4,
            DeploymentArchetype.MAKER: 8
        }
        return cycles.get(archetype, 4)

    def _get_archetype_name(self, archetype: DeploymentArchetype) -> str:
        names = {
            DeploymentArchetype.TAKER: "Taker (直接使用)",
            DeploymentArchetype.SHAPER: "Shaper (微调/集成)",
            DeploymentArchetype.MAKER: "Maker (自研模型)"
        }
        return names.get(archetype, "Unknown")

    def _get_archetype_description(self, archetype: DeploymentArchetype) -> str:
        descriptions = {
            DeploymentArchetype.TAKER: "直接使用现成的AI产品或API，快速上线，成本低",
            DeploymentArchetype.SHAPER: "基于开源或商业模型进行微调，平衡定制化和成本",
            DeploymentArchetype.MAKER: "自研模型，高度定制，适合核心竞争力场景"
        }
        return descriptions.get(archetype, "")

    def _get_customization_level(self, archetype: DeploymentArchetype) -> str:
        levels = {
            DeploymentArchetype.TAKER: "低 - 开箱即用",
            DeploymentArchetype.SHAPER: "中 - 适度定制",
            DeploymentArchetype.MAKER: "高 - 深度定制"
        }
        return levels.get(archetype, "")

    def _calculate_maturity_score(self, inputs: Dict[str, Any]) -> MaturityScore:
        """计算成熟度评分"""
        # 部署原型评分
        deployment_score = 5.0  # 基础分

        # 战略评分
        strategy_score = 5.0
        if inputs.get("has_roadmap"):
            strategy_score += 2.5
        if inputs.get("business_value_clear"):
            strategy_score += 2.5

        # 运营模式评分
        operating_score = 5.0
        project_duration = float(inputs.get("project_duration", 6))
        if project_duration <= self.HIGH_PERFORMER_BENCHMARKS["project_cycle"]:
            operating_score += 2.0
        if inputs.get("has_coe"):
            operating_score += 1.5
        if inputs.get("has_agile_budget"):
            operating_score += 1.5

        # 技术与数据评分
        tech_score = 5.0
        reuse_rate = float(inputs.get("component_reuse_rate", 0))
        monitoring = float(inputs.get("monitoring_coverage", 0))
        if reuse_rate >= self.HIGH_PERFORMER_BENCHMARKS["component_reuse_rate"]:
            tech_score += 2.5
        if monitoring >= self.HIGH_PERFORMER_BENCHMARKS["monitoring_coverage"]:
            tech_score += 2.5

        # 风险管理评分
        risk_score = 5.0
        if inputs.get("has_early_compliance"):
            risk_score += 2.5
        if inputs.get("has_hallucination_mitigation"):
            risk_score += 2.5

        # 综合评分
        overall = (deployment_score + strategy_score + operating_score +
                   tech_score + risk_score) / 5

        return MaturityScore(
            deployment=min(10, deployment_score),
            strategy=min(10, strategy_score),
            operating_model=min(10, operating_score),
            tech_data=min(10, tech_score),
            risk=min(10, risk_score),
            overall=min(10, overall),
            archetype=DeploymentArchetype.SHAPER,
            details=inputs
        )

    def _analyze_gaps(self, inputs: Dict[str, Any], maturity: MaturityScore) -> Dict[str, Any]:
        """分析与高效能者的差距"""
        gaps = {}

        # 项目周期差距
        current_cycle = float(inputs.get("project_duration", 6))
        benchmark_cycle = self.HIGH_PERFORMER_BENCHMARKS["project_cycle"]
        gaps["项目周期"] = {
            "current": current_cycle,
            "benchmark": benchmark_cycle,
            "gap": current_cycle - benchmark_cycle,
            "unit": "月"
        }

        # 组件复用率差距
        current_reuse = float(inputs.get("component_reuse_rate", 0))
        benchmark_reuse = self.HIGH_PERFORMER_BENCHMARKS["component_reuse_rate"]
        gaps["组件复用率"] = {
            "current": current_reuse,
            "benchmark": benchmark_reuse,
            "gap": benchmark_reuse - current_reuse,
            "unit": "%"
        }

        # 监控覆盖率差距
        current_monitoring = float(inputs.get("monitoring_coverage", 0))
        benchmark_monitoring = self.HIGH_PERFORMER_BENCHMARKS["monitoring_coverage"]
        gaps["监控覆盖率"] = {
            "current": current_monitoring,
            "benchmark": benchmark_monitoring,
            "gap": benchmark_monitoring - current_monitoring,
            "unit": "%"
        }

        return gaps

    def _generate_archetype_recommendations(
        self,
        archetype: DeploymentArchetype,
        inputs: Dict[str, Any]
    ) -> List[str]:
        """生成部署原型建议"""
        recommendations = []

        if archetype == DeploymentArchetype.TAKER:
            recommendations.extend([
                "建议直接采用成熟的AI产品或API服务",
                "优先选择主流云服务商的AI服务（如Azure OpenAI、AWS Bedrock等）",
                "关注数据安全和隐私合规，确保数据不外泄",
                "建立使用规范和最佳实践，快速推广"
            ])
        elif archetype == DeploymentArchetype.SHAPER:
            recommendations.extend([
                "建议基于开源模型进行微调，或使用企业级API进行定制",
                "投入资源构建高质量的训练数据集",
                "建立MLOps能力，支持模型的持续迭代",
                "评估私有化部署需求，平衡成本和数据安全"
            ])
        else:  # MAKER
            recommendations.extend([
                "建议组建专业的AI研发团队",
                "投入足够的计算资源和数据资源",
                "建立完整的模型研发流程和评估体系",
                "考虑与学术机构或研究院所合作",
                "注意：自研周期长、投入大，需确保战略必要性"
            ])

        return recommendations

    def _generate_gap_recommendations(self, gaps: Dict[str, Any]) -> List[str]:
        """生成差距改进建议"""
        recommendations = []

        if gaps.get("项目周期", {}).get("gap", 0) > 2:
            recommendations.append("项目周期过长：建议采用敏捷方法，缩短迭代周期，快速验证价值")

        if gaps.get("组件复用率", {}).get("gap", 0) > 20:
            recommendations.append("组件复用率不足：建议建立AI组件库和最佳实践，提升复用率")

        if gaps.get("监控覆盖率", {}).get("gap", 0) > 20:
            recommendations.append("监控覆盖不足：建议部署MLOps平台，实现模型输出的实时监控")

        if not recommendations:
            recommendations.append("当前表现接近高效能者水平，建议持续保持并向更高标准迈进")

        return recommendations

    def _generate_pre_summary(
        self,
        archetype: DeploymentArchetype,
        cycle: int,
        inputs: Dict[str, Any]
    ) -> str:
        return f"""
## 麦肯锡部署路径评估报告

### 项目信息
- **项目名称**: {inputs.get('project_name', '未命名')}
- **业务需求**: {inputs.get('business_requirement', '未提供')[:100]}...

### 部署路径建议
| 项目 | 建议 |
|------|------|
| 部署原型 | {self._get_archetype_name(archetype)} |
| 定制化程度 | {self._get_customization_level(archetype)} |
| 预计周期 | {cycle}个月 |

### 原型说明
{self._get_archetype_description(archetype)}

### 决策依据
基于以下因素综合判断：
- 数据资产情况
- 团队技术能力
- 业务需求复杂度
- 数据敏感度要求
"""

    def _generate_post_summary(
        self,
        maturity: MaturityScore,
        gaps: Dict[str, Any],
        inputs: Dict[str, Any]
    ) -> str:
        return f"""
## 麦肯锡成熟度对标报告

### 项目信息
- **项目名称**: {inputs.get('project_name', '未命名')}

### 成熟度评分（满分10分）
| 维度 | 得分 | 说明 |
|------|------|------|
| 部署原型 | {maturity.deployment:.1f} | 定制化程度与价值匹配度 |
| 战略 | {maturity.strategy:.1f} | 路线图清晰度与价值阐述 |
| 运营模式 | {maturity.operating_model:.1f} | 敏捷交付能力 |
| 技术与数据 | {maturity.tech_data:.1f} | 工程化水平 |
| 风险管理 | {maturity.risk:.1f} | 左移程度与缓解措施 |
| **综合成熟度** | **{maturity.overall:.1f}** | 五维度加权平均 |

### 与高效能者差距
| 指标 | 当前值 | 基准值 | 差距 |
|------|--------|--------|------|
| 项目周期 | {gaps.get('项目周期', {}).get('current', '-')}月 | {gaps.get('项目周期', {}).get('benchmark', '-')}月 | {gaps.get('项目周期', {}).get('gap', '-')}月 |
| 组件复用率 | {gaps.get('组件复用率', {}).get('current', '-')}% | {gaps.get('组件复用率', {}).get('benchmark', '-')}% | {gaps.get('组件复用率', {}).get('gap', '-')}% |
| 监控覆盖率 | {gaps.get('监控覆盖率', {}).get('current', '-')}% | {gaps.get('监控覆盖率', {}).get('benchmark', '-')}% | {gaps.get('监控覆盖率', {}).get('gap', '-')}% |
"""

    def _generate_pre_visualizations(self, archetype: DeploymentArchetype) -> Dict[str, Any]:
        return {
            "archetype_comparison": {
                "type": "comparison",
                "title": "部署原型对比",
                "data": {
                    "Taker": {"周期": 2, "成本": "低", "定制化": "低"},
                    "Shaper": {"周期": 4, "成本": "中", "定制化": "中"},
                    "Maker": {"周期": 8, "成本": "高", "定制化": "高"}
                },
                "selected": archetype.value
            }
        }

    def _generate_post_visualizations(
        self,
        maturity: MaturityScore,
        gaps: Dict[str, Any]
    ) -> Dict[str, Any]:
        return {
            "maturity_radar": {
                "type": "radar",
                "title": "成熟度雷达图",
                "categories": ["部署原型", "战略", "运营模式", "技术与数据", "风险管理"],
                "values": [
                    maturity.deployment, maturity.strategy,
                    maturity.operating_model, maturity.tech_data, maturity.risk
                ],
                "max_value": 10
            },
            "gap_bar": {
                "type": "bar",
                "title": "与高效能者差距",
                "data": {k: v.get("gap", 0) for k, v in gaps.items()}
            }
        }

    def get_prompt_templates(self) -> Dict[str, str]:
        return {
            "pre": (
                "你是一名麦肯锡风格的AI项目评估顾问。\n"
                "根据业务需求、数据资产、团队能力，判定部署原型(Taker/Shaper/Maker)，"
                "并预测上线周期，给出部署建议与风险提示。"
            ),
            "post": (
                "你是一名成熟度对标分析师，需对比高效能者基准。\n"
                "输入：项目周期、COE/路线图/监控/合规等实践，计算成熟度评分并给出差距与改进建议。"
            ),
        }
