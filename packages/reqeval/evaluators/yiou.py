"""
亿欧SCE场景评估器

SCE模型通过战略(S)-成本(C)-经济(E)三维加权打分，快速筛选高价值场景。
- S (战略价值) 权重: 30%
- C (成本价值) 权重: 30%
- E (经济价值) 权重: 40%

综合得分公式: Score = S×0.3 + C×0.3 + E×0.4
推荐阈值: >7分为优先投资场景
"""
from typing import Dict, List, Any, Optional
from dataclasses import dataclass

from .base import BaseEvaluator, EvaluatorConfig
from src.packages.reqeval.data.models import (
    EvaluationReport, MetricResult, DocumentInfo,
    ScenarioType, EvaluationMethod
)


@dataclass
class SCEScore:
    """SCE评分结果"""
    s_score: float  # 战略价值 (1-10)
    c_score: float  # 成本价值 (1-10)
    e_score: float  # 经济价值 (1-10)
    total_score: float  # 综合得分
    s_details: Dict[str, float]  # S维度详细评分
    c_details: Dict[str, float]  # C维度详细评分
    e_details: Dict[str, float]  # E维度详细评分


class YiOuEvaluator(BaseEvaluator):
    """
    亿欧SCE场景评估器

    适用场景：
    - 中国企业进行大模型选型
    - 应用场景筛选与优先级排序
    - 快速评估AI场景的商业价值
    """

    # SCE权重
    WEIGHT_S = 0.30  # 战略价值
    WEIGHT_C = 0.30  # 成本价值
    WEIGHT_E = 0.40  # 经济价值

    # 推荐阈值
    THRESHOLD_HIGH = 7.0  # 优先投资
    THRESHOLD_MEDIUM = 5.0  # 可考虑投资

    def _get_config(self) -> EvaluatorConfig:
        return EvaluatorConfig(
            method=EvaluationMethod.YIOU,
            name="亿欧SCE场景评估法",
            name_en="YiOu SCE Model",
            description="通过战略-成本-经济三维加权打分，快速筛选高价值AI应用场景",
            applicable_scenarios=[
                "中国企业进行大模型选型",
                "AI应用场景筛选",
                "项目优先级排序",
                "投资决策支持"
            ],
            core_metrics=[
                "战略价值(S)", "成本价值(C)", "经济价值(E)",
                "综合得分", "优先级排序", "兑现率"
            ],
            pre_evaluation_desc="场景打分筛选与优先级排序",
            post_evaluation_desc="价值兑现率与偏差分析"
        )

    def get_required_inputs(self, scenario: ScenarioType) -> Dict[str, Any]:
        """获取所需输入信息"""
        if scenario == ScenarioType.PRE:
            return {
                "fields": ["scenario_name", "scenario_description"],
                "optional_fields": [
                    "industry_context", "competitor_info",
                    "s_necessity", "s_security", "s_brand",
                    "c_compute_cost", "c_labor_saving", "c_marginal_cost",
                    "e_revenue", "e_willingness_to_pay", "e_ltv"
                ],
                "descriptions": {
                    "scenario_name": "场景名称",
                    "scenario_description": "场景描述",
                    "industry_context": "行业背景",
                    "competitor_info": "竞争对手动态",
                    # S维度
                    "s_necessity": "必要性：是否为行业趋势？不做是否会掉队？(1-10分)",
                    "s_security": "安全性：是否增强数据自主可控？(1-10分)",
                    "s_brand": "品牌溢价：是否提升企业科技形象？(1-10分)",
                    # C维度
                    "c_compute_cost": "算力替代：模型推理成本 vs 原有系统成本",
                    "c_labor_saving": "人力替代：FTE节省数 × 人力成本",
                    "c_marginal_cost": "边际成本：规模扩大后的成本递减效应",
                    # E维度
                    "e_revenue": "直接增收：预计带来的新订单/新客户",
                    "e_willingness_to_pay": "付费意愿：客户是否愿意为该AI功能额外付费？",
                    "e_ltv": "LTV提升：客户生命周期价值的延展"
                }
            }
        else:  # POST
            return {
                "fields": ["scenario_name", "pre_evaluation_scores"],
                "optional_fields": [
                    "actual_cost_savings", "actual_revenue",
                    "actual_fte_saved", "implementation_cost"
                ],
                "descriptions": {
                    "scenario_name": "场景名称",
                    "pre_evaluation_scores": "前期评估的SCE预测值",
                    "actual_cost_savings": "实际成本节省",
                    "actual_revenue": "实际新增收入",
                    "actual_fte_saved": "实际节省人力(FTE)",
                    "implementation_cost": "实施成本"
                }
            }

    def pre_evaluation(self, inputs: Dict[str, Any]) -> EvaluationReport:
        """
        前期评估：场景打分筛选

        输入:
            - scenario_name: 场景名称
            - scenario_description: 场景描述
            - 可选的S/C/E各维度打分（如有）

        输出:
            - SCE综合得分
            - 优先级建议
            - 风险提示
        """
        # 验证输入
        valid, errors = self.validate_inputs(inputs, ScenarioType.PRE)
        if not valid:
            # 返回错误报告
            return self.generate_report(
                scenario=ScenarioType.PRE,
                metrics=[],
                summary=f"输入验证失败: {', '.join(errors)}",
                recommendations=["请提供完整的输入信息"],
                user_input=inputs,
                documents=inputs.get("documents", [])
            )

        # 计算SCE评分
        sce_score = self._calculate_sce_score(inputs)

        # 生成指标列表
        metrics = self.calculate_metrics({"sce_score": sce_score, **inputs})

        # 生成摘要和建议
        summary = self._generate_summary(sce_score, inputs)
        recommendations = self._generate_recommendations(sce_score, inputs)

        # 生成可视化数据
        visualizations = self._generate_visualizations(sce_score)

        return self.generate_report(
            scenario=ScenarioType.PRE,
            metrics=metrics,
            summary=summary,
            recommendations=recommendations,
            user_input=inputs,
            documents=inputs.get("documents", []),
            visualizations=visualizations
        )

    def post_evaluation(self, inputs: Dict[str, Any]) -> EvaluationReport:
        """
        后期验证：价值兑现率

        输入:
            - pre_evaluation_scores: 前期评估的预测值
            - 实际运营数据

        输出:
            - 兑现率计算
            - 偏差分析
            - 改进建议
        """
        # 获取前期预测值
        pre_scores = inputs.get("pre_evaluation_scores", {})
        predicted_e = pre_scores.get("e_score", 5.0)
        predicted_c = pre_scores.get("c_score", 5.0)

        # 计算实际值
        actual_data = self._calculate_actual_values(inputs)

        # 计算兑现率
        e_realization_rate = self._calculate_realization_rate(
            predicted_e, actual_data.get("actual_e_score", 0)
        )
        c_realization_rate = self._calculate_realization_rate(
            predicted_c, actual_data.get("actual_c_score", 0)
        )

        # 生成指标
        metrics = [
            MetricResult(
                name="E值兑现率",
                value=round(e_realization_rate * 100, 1),
                unit="%",
                description="实际经济价值 / 预测经济价值",
                category="兑现率"
            ),
            MetricResult(
                name="C值兑现率",
                value=round(c_realization_rate * 100, 1),
                unit="%",
                description="实际成本价值 / 预测成本价值",
                category="兑现率"
            ),
            MetricResult(
                name="预测E值",
                value=predicted_e,
                unit="分",
                category="前期预测"
            ),
            MetricResult(
                name="实际E值",
                value=actual_data.get("actual_e_score", 0),
                unit="分",
                category="实际表现"
            )
        ]

        # 偏差分析
        deviation_analysis = self._analyze_deviation(
            pre_scores, actual_data, e_realization_rate, c_realization_rate
        )

        summary = f"""
## 价值兑现率分析

**场景**: {inputs.get('scenario_name', '未知')}

### 兑现率概览
- 经济价值(E)兑现率: {e_realization_rate*100:.1f}%
- 成本价值(C)兑现率: {c_realization_rate*100:.1f}%

### 偏差分析
{deviation_analysis}
"""

        recommendations = self._generate_post_recommendations(
            e_realization_rate, c_realization_rate, inputs
        )

        return self.generate_report(
            scenario=ScenarioType.POST,
            metrics=metrics,
            summary=summary,
            recommendations=recommendations,
            user_input=inputs,
            documents=inputs.get("documents", []),
            related_evaluation_id=inputs.get("pre_evaluation_id")
        )

    def calculate_metrics(self, data: Dict[str, Any]) -> List[MetricResult]:
        """计算评估指标"""
        sce_score: SCEScore = data.get("sce_score")
        if not sce_score:
            return []

        metrics = [
            # 综合得分
            MetricResult(
                name="SCE综合得分",
                value=round(sce_score.total_score, 2),
                unit="分",
                description=f"加权公式: S×{self.WEIGHT_S} + C×{self.WEIGHT_C} + E×{self.WEIGHT_E}",
                category="综合评估"
            ),
            # S维度
            MetricResult(
                name="战略价值(S)",
                value=round(sce_score.s_score, 2),
                unit="分",
                description="必要性、安全性、品牌溢价的综合评分",
                category="战略价值"
            ),
            # C维度
            MetricResult(
                name="成本价值(C)",
                value=round(sce_score.c_score, 2),
                unit="分",
                description="算力替代、人力替代、边际成本的综合评分",
                category="成本价值"
            ),
            # E维度
            MetricResult(
                name="经济价值(E)",
                value=round(sce_score.e_score, 2),
                unit="分",
                description="直接增收、付费意愿、LTV提升的综合评分",
                category="经济价值"
            ),
            # 优先级
            MetricResult(
                name="投资优先级",
                value=self._get_priority_level(sce_score.total_score),
                unit="",
                description=f"基于阈值判断: 高(>{self.THRESHOLD_HIGH}), 中({self.THRESHOLD_MEDIUM}-{self.THRESHOLD_HIGH}), 低(<{self.THRESHOLD_MEDIUM})",
                category="建议"
            )
        ]

        # 添加详细评分
        for key, value in sce_score.s_details.items():
            metrics.append(MetricResult(
                name=f"S-{key}",
                value=round(value, 1),
                unit="分",
                category="战略价值详情"
            ))

        for key, value in sce_score.c_details.items():
            metrics.append(MetricResult(
                name=f"C-{key}",
                value=round(value, 1),
                unit="分",
                category="成本价值详情"
            ))

        for key, value in sce_score.e_details.items():
            metrics.append(MetricResult(
                name=f"E-{key}",
                value=round(value, 1),
                unit="分",
                category="经济价值详情"
            ))

        return metrics

    def _calculate_sce_score(self, inputs: Dict[str, Any]) -> SCEScore:
        """计算SCE评分"""
        # S维度评分
        s_details = {
            "必要性": float(inputs.get("s_necessity", 5)),
            "安全性": float(inputs.get("s_security", 5)),
            "品牌溢价": float(inputs.get("s_brand", 5))
        }
        s_score = sum(s_details.values()) / len(s_details)

        # C维度评分
        c_details = {
            "算力替代": float(inputs.get("c_compute_cost", 5)),
            "人力替代": float(inputs.get("c_labor_saving", 5)),
            "边际成本": float(inputs.get("c_marginal_cost", 5))
        }
        c_score = sum(c_details.values()) / len(c_details)

        # E维度评分
        e_details = {
            "直接增收": float(inputs.get("e_revenue", 5)),
            "付费意愿": float(inputs.get("e_willingness_to_pay", 5)),
            "LTV提升": float(inputs.get("e_ltv", 5))
        }
        e_score = sum(e_details.values()) / len(e_details)

        # 综合得分
        total_score = (
            s_score * self.WEIGHT_S +
            c_score * self.WEIGHT_C +
            e_score * self.WEIGHT_E
        )

        return SCEScore(
            s_score=s_score,
            c_score=c_score,
            e_score=e_score,
            total_score=total_score,
            s_details=s_details,
            c_details=c_details,
            e_details=e_details
        )

    def _get_priority_level(self, score: float) -> str:
        """获取优先级等级"""
        if score >= self.THRESHOLD_HIGH:
            return "高优先级 - 强烈推荐投资"
        elif score >= self.THRESHOLD_MEDIUM:
            return "中优先级 - 可考虑投资"
        else:
            return "低优先级 - 建议谨慎评估"

    def _generate_summary(self, sce_score: SCEScore, inputs: Dict[str, Any]) -> str:
        """生成评估摘要"""
        scenario_name = inputs.get("scenario_name", "未命名场景")
        priority = self._get_priority_level(sce_score.total_score)

        # 找出最强和最弱维度
        dimensions = {
            "战略价值(S)": sce_score.s_score,
            "成本价值(C)": sce_score.c_score,
            "经济价值(E)": sce_score.e_score
        }
        strongest = max(dimensions, key=dimensions.get)
        weakest = min(dimensions, key=dimensions.get)

        summary = f"""
## SCE场景评估报告

### 基本信息
- **场景名称**: {scenario_name}
- **评估方法**: 亿欧SCE场景评估法

### 评分结果
| 维度 | 得分 | 权重 | 加权得分 |
|------|------|------|----------|
| 战略价值(S) | {sce_score.s_score:.1f} | {self.WEIGHT_S*100:.0f}% | {sce_score.s_score*self.WEIGHT_S:.2f} |
| 成本价值(C) | {sce_score.c_score:.1f} | {self.WEIGHT_C*100:.0f}% | {sce_score.c_score*self.WEIGHT_C:.2f} |
| 经济价值(E) | {sce_score.e_score:.1f} | {self.WEIGHT_E*100:.0f}% | {sce_score.e_score*self.WEIGHT_E:.2f} |
| **综合得分** | **{sce_score.total_score:.2f}** | - | - |

### 评估结论
- **投资建议**: {priority}
- **最强维度**: {strongest} ({dimensions[strongest]:.1f}分)
- **待提升维度**: {weakest} ({dimensions[weakest]:.1f}分)

### 评分标准
- 高优先级(>7分): 强烈推荐投资，预期回报高
- 中优先级(5-7分): 可考虑投资，需关注风险点
- 低优先级(<5分): 建议谨慎评估，可能ROI不足
"""
        return summary

    def _generate_recommendations(self, sce_score: SCEScore, inputs: Dict[str, Any]) -> List[str]:
        """生成建议"""
        recommendations = []

        # 基于综合得分
        if sce_score.total_score >= self.THRESHOLD_HIGH:
            recommendations.append("该场景综合评分较高，建议优先立项推进")
        elif sce_score.total_score >= self.THRESHOLD_MEDIUM:
            recommendations.append("该场景有一定价值，建议进行详细的可行性分析后决策")
        else:
            recommendations.append("该场景当前评分较低，建议重新审视场景定义或暂缓投入")

        # 基于各维度评分
        if sce_score.s_score < 5:
            recommendations.append("战略价值不足：建议评估该场景是否符合公司长期战略方向")

        if sce_score.c_score < 5:
            recommendations.append("成本价值不足：建议详细测算成本节省空间，可能需要优化技术方案")

        if sce_score.e_score < 5:
            recommendations.append("经济价值不足：建议验证客户付费意愿，或探索新的变现模式")

        # 基于详细评分
        if sce_score.s_details.get("必要性", 5) < 5:
            recommendations.append("必要性不高：考虑是否为跟风项目，需谨慎评估行业真实需求")

        if sce_score.c_details.get("人力替代", 5) >= 7:
            recommendations.append("人力替代价值高：建议做好变革管理，提前规划人员转型")

        if sce_score.e_details.get("付费意愿", 5) < 5:
            recommendations.append("付费意愿不足：建议进行客户调研，验证价值主张是否清晰")

        return recommendations

    def _generate_visualizations(self, sce_score: SCEScore) -> Dict[str, Any]:
        """生成可视化数据"""
        return {
            "radar_chart": {
                "type": "radar",
                "title": "SCE三维评分雷达图",
                "categories": ["战略价值(S)", "成本价值(C)", "经济价值(E)"],
                "values": [sce_score.s_score, sce_score.c_score, sce_score.e_score],
                "max_value": 10
            },
            "bar_chart": {
                "type": "bar",
                "title": "SCE详细评分",
                "data": {
                    **{f"S-{k}": v for k, v in sce_score.s_details.items()},
                    **{f"C-{k}": v for k, v in sce_score.c_details.items()},
                    **{f"E-{k}": v for k, v in sce_score.e_details.items()}
                }
            },
            "gauge_chart": {
                "type": "gauge",
                "title": "综合得分",
                "value": sce_score.total_score,
                "max_value": 10,
                "thresholds": {
                    "low": self.THRESHOLD_MEDIUM,
                    "high": self.THRESHOLD_HIGH
                }
            }
        }

    def _calculate_actual_values(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """计算实际值"""
        # 根据实际数据计算E值和C值
        actual_revenue = float(inputs.get("actual_revenue", 0))
        actual_cost_savings = float(inputs.get("actual_cost_savings", 0))
        actual_fte_saved = float(inputs.get("actual_fte_saved", 0))

        # 简化计算：将实际值映射到1-10分
        # 实际项目中需要更复杂的评分逻辑
        actual_e_score = min(10, max(1, actual_revenue / 100000))  # 假设10万为1分
        actual_c_score = min(10, max(1, (actual_cost_savings + actual_fte_saved * 50000) / 100000))

        return {
            "actual_e_score": actual_e_score,
            "actual_c_score": actual_c_score,
            "actual_revenue": actual_revenue,
            "actual_cost_savings": actual_cost_savings,
            "actual_fte_saved": actual_fte_saved
        }

    def _calculate_realization_rate(self, predicted: float, actual: float) -> float:
        """计算兑现率"""
        if predicted <= 0:
            return 0.0
        return min(2.0, actual / predicted)  # 上限200%

    def _analyze_deviation(
        self,
        pre_scores: Dict[str, Any],
        actual_data: Dict[str, Any],
        e_rate: float,
        c_rate: float
    ) -> str:
        """偏差分析"""
        analysis = []

        if e_rate < 0.5:
            analysis.append("- 经济价值严重低于预期：可能原因包括市场接受度不足、定价策略问题、推广不力")
        elif e_rate < 0.8:
            analysis.append("- 经济价值略低于预期：建议分析客户反馈，优化产品功能或营销策略")
        elif e_rate > 1.2:
            analysis.append("- 经济价值超出预期：总结成功经验，考虑扩大投入")

        if c_rate < 0.5:
            analysis.append("- 成本价值严重低于预期：可能存在技术实施问题或效率提升有限")
        elif c_rate < 0.8:
            analysis.append("- 成本价值略低于预期：建议优化流程，提升AI工具的利用率")
        elif c_rate > 1.2:
            analysis.append("- 成本价值超出预期：说明AI工具发挥了更大作用")

        if not analysis:
            analysis.append("- 整体表现符合预期，建议持续监控关键指标")

        return "\n".join(analysis)

    def _generate_post_recommendations(
        self,
        e_rate: float,
        c_rate: float,
        inputs: Dict[str, Any]
    ) -> List[str]:
        """生成后期评估建议"""
        recommendations = []

        if e_rate < 0.5 and c_rate < 0.5:
            recommendations.append("项目整体表现不佳，建议召开复盘会议，分析根本原因")
            recommendations.append("考虑是否需要调整战略方向或暂停投入")
        elif e_rate < 0.8 or c_rate < 0.8:
            recommendations.append("部分指标未达预期，建议针对性优化")
            if e_rate < c_rate:
                recommendations.append("重点关注收入端：优化产品、加强推广、调整定价")
            else:
                recommendations.append("重点关注成本端：提升效率、优化流程、加强培训")
        else:
            recommendations.append("项目表现良好，建议继续投入并考虑扩大规模")
            recommendations.append("总结最佳实践，为其他AI项目提供参考")

        return recommendations

    def evaluate_multiple_scenarios(
        self,
        scenarios: List[Dict[str, Any]]
    ) -> List[EvaluationReport]:
        """
        批量评估多个场景并排序

        Args:
            scenarios: 场景列表

        Returns:
            按优先级排序的评估报告列表
        """
        reports = []
        for scenario in scenarios:
            report = self.pre_evaluation(scenario)
            reports.append(report)

        # 按综合得分排序
        reports.sort(
            key=lambda r: next(
                (m.value for m in r.metrics if m.name == "SCE综合得分"),
                0
            ),
            reverse=True
        )

        return reports

    def get_prompt_templates(self) -> Dict[str, str]:
        return {
            "pre": (
                "你是一名业务价值评估专家，使用SCE模型对AI场景进行打分。\n"
                "输入包含场景描述及S/C/E维度的定性/定量信息。\n"
                "请输出加权得分（S 30%、C 30%、E 40%）、最弱/最强维度、投资建议和可视化要点。"
            ),
            "post": (
                "你是一名价值兑现分析师，需计算SCE前后预测与实际的兑现率。\n"
                "输入包含前期预测分与实际收益/成本数据。\n"
                "请输出E/C兑现率、偏差原因、改进建议，并标记是否继续/暂停投入。"
            ),
        }
