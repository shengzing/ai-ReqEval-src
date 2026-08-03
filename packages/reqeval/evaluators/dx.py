"""
DX研发效能ROI评估器

核心逻辑：利用率-影响-成本三维矩阵评估研发AI工具效果
特别引入智能体等效工时(HEH)概念评估AI Agent的价值
"""
from typing import Dict, List, Any
from dataclasses import dataclass

from .base import BaseEvaluator, EvaluatorConfig
from src.packages.reqeval.data.models import (
    EvaluationReport, MetricResult, DocumentInfo,
    ScenarioType, EvaluationMethod
)


@dataclass
class DXMetrics:
    """DX研发效能指标"""
    # 利用率维度
    dau_rate: float  # 日活率
    wau_rate: float  # 周活率
    ai_code_ratio: float  # AI辅助代码占比

    # 影响维度
    time_saved_hours: float  # 节省时间(小时/周/人)
    cycle_time_days: float  # PR周期时间(天)
    cfr: float  # 变更失败率(%)
    heh: float  # 智能体等效工时

    # 成本维度
    net_time_gain: float  # 净时间收益
    agent_hourly_rate: float  # 智能体时薪
    license_cost: float  # License成本

    # 综合
    roi: float  # ROI


class DXEvaluator(BaseEvaluator):
    """
    DX研发效能ROI评估器

    适用场景：
    - 软件研发部门
    - CTO办公室
    - 评估Copilot或Devin类AI编程工具的效果
    """

    # 行业基准
    BENCHMARKS = {
        "dau_rate": 70,  # 日活率(%)
        "time_saved_hours": 5,  # 每周节省小时数
        "cycle_time_days": 2,  # PR周期时间(天)
        "cfr_threshold": 5,  # 变更失败率阈值(%)
    }

    def _get_config(self) -> EvaluatorConfig:
        return EvaluatorConfig(
            method=EvaluationMethod.DX,
            name="DX研发效能ROI法",
            name_en="DX Developer Experience ROI",
            description="通过利用率-影响-成本三维评估AI编程工具的真实价值",
            applicable_scenarios=[
                "AI编程助手评估（如GitHub Copilot）",
                "AI代码审查工具评估",
                "AI Agent编程工具评估（如Devin）",
                "研发效能提升项目"
            ],
            core_metrics=[
                "工具活跃度", "AI代码占比", "节省时间",
                "PR周期时间", "变更失败率", "智能体等效工时(HEH)",
                "净时间收益", "ROI"
            ],
            pre_evaluation_desc="基线与预期设定",
            post_evaluation_desc="真实ROI计算与三维诊断"
        )

    def get_required_inputs(self, scenario: ScenarioType) -> Dict[str, Any]:
        if scenario == ScenarioType.PRE:
            return {
                "fields": ["tool_name", "developer_count"],
                "optional_fields": [
                    "current_cycle_time", "current_cfr",
                    "weekly_coding_hours", "hourly_rate",
                    "expected_improvement", "license_cost_per_user"
                ],
                "descriptions": {
                    "tool_name": "AI工具名称",
                    "developer_count": "开发者人数",
                    "current_cycle_time": "当前PR周期时间(天)",
                    "current_cfr": "当前变更失败率(%)",
                    "weekly_coding_hours": "每周编码小时数",
                    "hourly_rate": "开发者时薪(元)",
                    "expected_improvement": "供应商宣称的效率提升(%)",
                    "license_cost_per_user": "每用户License成本(元/月)"
                }
            }
        else:
            return {
                "fields": ["tool_name"],
                "optional_fields": [
                    "dau", "wau", "total_developers",
                    "ai_code_lines", "total_code_lines",
                    "reported_time_saved", "actual_cycle_time",
                    "actual_cfr", "agent_tasks_completed",
                    "avg_task_hours", "prompt_engineering_hours",
                    "fix_ai_errors_hours", "license_cost", "cloud_cost"
                ],
                "descriptions": {
                    "tool_name": "AI工具名称",
                    "dau": "日活用户数",
                    "wau": "周活用户数",
                    "total_developers": "总开发者人数",
                    "ai_code_lines": "AI参与编写的代码行数",
                    "total_code_lines": "总提交代码行数",
                    "reported_time_saved": "开发者自评每周节省小时数",
                    "actual_cycle_time": "实际PR周期时间(天)",
                    "actual_cfr": "实际变更失败率(%)",
                    "agent_tasks_completed": "智能体完成的任务数",
                    "avg_task_hours": "人类完成同等任务的平均时间(小时)",
                    "prompt_engineering_hours": "提示工程花费的时间(小时)",
                    "fix_ai_errors_hours": "修复AI错误花费的时间(小时)",
                    "license_cost": "License总成本(元/月)",
                    "cloud_cost": "云资源成本(元/月)"
                }
            }

    def pre_evaluation(self, inputs: Dict[str, Any]) -> EvaluationReport:
        """前期评估：基线与预期设定"""
        developer_count = int(inputs.get("developer_count", 10))
        weekly_hours = float(inputs.get("weekly_coding_hours", 30))
        expected_improvement = float(inputs.get("expected_improvement", 30))
        hourly_rate = float(inputs.get("hourly_rate", 200))
        license_cost = float(inputs.get("license_cost_per_user", 200))

        # 计算理论节省时间（打6折消除厂商夸大）
        discount_factor = 0.6
        theoretical_time_saved = (
            developer_count * weekly_hours *
            (expected_improvement / 100) * discount_factor
        )

        # 计算理论收益
        monthly_savings = theoretical_time_saved * 4 * hourly_rate
        monthly_cost = developer_count * license_cost
        expected_roi = ((monthly_savings - monthly_cost) / monthly_cost * 100
                        if monthly_cost > 0 else 0)

        # 设定红线指标
        current_cfr = float(inputs.get("current_cfr", 3))
        cfr_redline = current_cfr + self.BENCHMARKS["cfr_threshold"]

        metrics = [
            MetricResult(
                name="理论节省时间",
                value=round(theoretical_time_saved, 1),
                unit="小时/周",
                description=f"基于{expected_improvement}%提升率，打{discount_factor}折",
                category="预期收益"
            ),
            MetricResult(
                name="预期月度收益",
                value=round(monthly_savings, 0),
                unit="元",
                category="预期收益"
            ),
            MetricResult(
                name="月度成本",
                value=round(monthly_cost, 0),
                unit="元",
                category="成本预算"
            ),
            MetricResult(
                name="预期ROI",
                value=round(expected_roi, 1),
                unit="%",
                category="投资回报"
            ),
            MetricResult(
                name="CFR红线",
                value=cfr_redline,
                unit="%",
                description="变更失败率不得超过此值，否则判定AI应用失败",
                category="质量约束"
            )
        ]

        summary = f"""
## DX研发效能基线评估报告

### 项目信息
- **AI工具**: {inputs.get('tool_name', '未知')}
- **开发者人数**: {developer_count}人
- **供应商宣称提升**: {expected_improvement}%

### 预期收益（保守估计）
| 指标 | 数值 |
|------|------|
| 理论节省时间 | {theoretical_time_saved:.1f} 小时/周 |
| 月度人力成本节省 | ¥{monthly_savings:,.0f} |
| 月度工具成本 | ¥{monthly_cost:,.0f} |
| 预期ROI | {expected_roi:.1f}% |

### 红线指标
- **变更失败率(CFR)**: 不得超过 {cfr_redline}%
- 若速度提升但CFR上升，则判定AI应用失败

### 评估说明
- 预期提升已按{discount_factor}系数打折，消除厂商夸大宣传
- 实际效果需在实施后通过遥测数据验证
"""

        recommendations = [
            f"建议先进行{min(developer_count, 10)}人的小范围试点",
            "部署前建立基线指标（PR周期、CFR、编码时长）",
            "配置遥测系统收集DAU/WAU和代码采纳率",
            "每周收集开发者自评反馈",
            f"严格监控CFR，一旦超过{cfr_redline}%立即评估"
        ]

        return self.generate_report(
            scenario=ScenarioType.PRE,
            metrics=metrics,
            summary=summary,
            recommendations=recommendations,
            user_input=inputs,
            documents=inputs.get("documents", []),
            visualizations=self._generate_pre_visualizations(inputs)
        )

    def post_evaluation(self, inputs: Dict[str, Any]) -> EvaluationReport:
        """后期验证：真实ROI计算"""
        # 计算各项指标
        dx_metrics = self._calculate_dx_metrics(inputs)

        # 三维诊断
        diagnosis = self._diagnose_three_dimensions(dx_metrics, inputs)

        # 生成指标列表
        metrics = self.calculate_metrics({"dx_metrics": dx_metrics})

        summary = self._generate_post_summary(dx_metrics, diagnosis, inputs)
        recommendations = self._generate_diagnosis_recommendations(diagnosis)

        return self.generate_report(
            scenario=ScenarioType.POST,
            metrics=metrics,
            summary=summary,
            recommendations=recommendations,
            user_input=inputs,
            documents=inputs.get("documents", []),
            visualizations=self._generate_post_visualizations(dx_metrics)
        )

    def calculate_metrics(self, data: Dict[str, Any]) -> List[MetricResult]:
        """计算评估指标"""
        dx: DXMetrics = data.get("dx_metrics")
        if not dx:
            return []

        return [
            # 利用率维度
            MetricResult(
                name="日活率(DAU)",
                value=round(dx.dau_rate, 1),
                unit="%",
                description="日活用户数 / 总开发者人数",
                category="利用率"
            ),
            MetricResult(
                name="周活率(WAU)",
                value=round(dx.wau_rate, 1),
                unit="%",
                category="利用率"
            ),
            MetricResult(
                name="AI代码占比",
                value=round(dx.ai_code_ratio, 1),
                unit="%",
                description="AI参与编写的代码行数占比",
                category="利用率"
            ),
            # 影响维度
            MetricResult(
                name="节省时间",
                value=round(dx.time_saved_hours, 1),
                unit="小时/周/人",
                description="开发者自评每周节省小时数",
                category="影响"
            ),
            MetricResult(
                name="PR周期时间",
                value=round(dx.cycle_time_days, 1),
                unit="天",
                description="PR从创建到合并的平均时长",
                category="影响"
            ),
            MetricResult(
                name="变更失败率(CFR)",
                value=round(dx.cfr, 1),
                unit="%",
                description="部署后导致回滚或Bug的比例",
                category="影响"
            ),
            MetricResult(
                name="智能体等效工时(HEH)",
                value=round(dx.heh, 1),
                unit="小时",
                description="智能体完成任务的人类等效工时",
                category="影响"
            ),
            # 成本维度
            MetricResult(
                name="净时间收益",
                value=round(dx.net_time_gain, 1),
                unit="小时/月",
                description="(节省工时+HEH) - (提示工程+修复错误时间)",
                category="成本"
            ),
            MetricResult(
                name="智能体时薪",
                value=round(dx.agent_hourly_rate, 0),
                unit="元/小时",
                description="智能体总成本 / 产出等效工时",
                category="成本"
            ),
            MetricResult(
                name="ROI",
                value=round(dx.roi, 1),
                unit="%",
                description="(收益-成本)/成本 × 100",
                category="综合"
            )
        ]

    def _calculate_dx_metrics(self, inputs: Dict[str, Any]) -> DXMetrics:
        """计算DX指标"""
        # 利用率
        dau = float(inputs.get("dau", 0))
        wau = float(inputs.get("wau", 0))
        total_devs = float(inputs.get("total_developers", 1))
        dau_rate = (dau / total_devs * 100) if total_devs > 0 else 0
        wau_rate = (wau / total_devs * 100) if total_devs > 0 else 0

        ai_code = float(inputs.get("ai_code_lines", 0))
        total_code = float(inputs.get("total_code_lines", 1))
        ai_code_ratio = (ai_code / total_code * 100) if total_code > 0 else 0

        # 影响
        time_saved = float(inputs.get("reported_time_saved", 0))
        cycle_time = float(inputs.get("actual_cycle_time", 2))
        cfr = float(inputs.get("actual_cfr", 3))

        # HEH计算
        agent_tasks = float(inputs.get("agent_tasks_completed", 0))
        avg_task_hours = float(inputs.get("avg_task_hours", 2))
        heh = agent_tasks * avg_task_hours

        # 成本
        prompt_hours = float(inputs.get("prompt_engineering_hours", 0))
        fix_hours = float(inputs.get("fix_ai_errors_hours", 0))
        license_cost = float(inputs.get("license_cost", 0))
        cloud_cost = float(inputs.get("cloud_cost", 0))
        total_cost = license_cost + cloud_cost

        # 净时间收益（月度）
        total_time_saved = time_saved * total_devs * 4  # 每周 × 人数 × 4周
        net_time_gain = total_time_saved + heh - prompt_hours - fix_hours

        # 智能体时薪
        agent_hourly_rate = (total_cost / heh) if heh > 0 else 0

        # ROI
        hourly_rate = float(inputs.get("hourly_rate", 200))
        monthly_benefit = net_time_gain * hourly_rate
        roi = ((monthly_benefit - total_cost) / total_cost * 100
               if total_cost > 0 else 0)

        return DXMetrics(
            dau_rate=dau_rate,
            wau_rate=wau_rate,
            ai_code_ratio=ai_code_ratio,
            time_saved_hours=time_saved,
            cycle_time_days=cycle_time,
            cfr=cfr,
            heh=heh,
            net_time_gain=net_time_gain,
            agent_hourly_rate=agent_hourly_rate,
            license_cost=total_cost,
            roi=roi
        )

    def _diagnose_three_dimensions(
        self,
        dx: DXMetrics,
        inputs: Dict[str, Any]
    ) -> Dict[str, Any]:
        """三维诊断"""
        diagnosis = {
            "utilization": {"status": "healthy", "issues": []},
            "impact": {"status": "healthy", "issues": []},
            "cost": {"status": "healthy", "issues": []}
        }

        # 利用率诊断
        if dx.dau_rate < self.BENCHMARKS["dau_rate"]:
            diagnosis["utilization"]["status"] = "warning"
            diagnosis["utilization"]["issues"].append(
                f"日活率({dx.dau_rate:.1f}%)低于基准({self.BENCHMARKS['dau_rate']}%)"
            )

        # 影响诊断
        if dx.time_saved_hours < self.BENCHMARKS["time_saved_hours"]:
            diagnosis["impact"]["status"] = "warning"
            diagnosis["impact"]["issues"].append(
                f"节省时间({dx.time_saved_hours:.1f}h)低于预期"
            )

        baseline_cfr = float(inputs.get("baseline_cfr", 3))
        if dx.cfr > baseline_cfr + self.BENCHMARKS["cfr_threshold"]:
            diagnosis["impact"]["status"] = "critical"
            diagnosis["impact"]["issues"].append(
                f"CFR({dx.cfr:.1f}%)超过红线，AI应用判定失败"
            )

        # 成本诊断
        if dx.roi < 0:
            diagnosis["cost"]["status"] = "critical"
            diagnosis["cost"]["issues"].append("ROI为负，成本大于收益")
        elif dx.roi < 50:
            diagnosis["cost"]["status"] = "warning"
            diagnosis["cost"]["issues"].append("ROI较低，需优化使用效率")

        return diagnosis

    def _generate_diagnosis_recommendations(
        self,
        diagnosis: Dict[str, Any]
    ) -> List[str]:
        """生成诊断建议"""
        recommendations = []

        # 利用率问题
        if diagnosis["utilization"]["status"] != "healthy":
            recommendations.extend([
                "利用率不足：检查是否存在采纳障碍",
                "建议开展培训，分享最佳实践",
                "收集不使用工具的原因反馈"
            ])

        # 影响问题
        if diagnosis["impact"]["status"] == "critical":
            recommendations.extend([
                "紧急：CFR超标，建议暂停AI工具使用",
                "分析AI生成代码的质量问题",
                "加强代码审查流程"
            ])
        elif diagnosis["impact"]["status"] == "warning":
            recommendations.extend([
                "效果不及预期：分析使用场景是否合适",
                "优化提示词工程，提升生成质量"
            ])

        # 成本问题
        if diagnosis["cost"]["status"] == "critical":
            recommendations.extend([
                "成本过高：评估是否继续使用",
                "考虑降低License数量或选择更经济的方案"
            ])
        elif diagnosis["cost"]["status"] == "warning":
            recommendations.append("提升使用效率以改善ROI")

        if not recommendations:
            recommendations.append("整体表现良好，建议扩大使用范围")

        return recommendations

    def _generate_post_summary(
        self,
        dx: DXMetrics,
        diagnosis: Dict[str, Any],
        inputs: Dict[str, Any]
    ) -> str:
        """生成后期评估摘要"""
        # 获取状态图标
        def status_icon(status):
            return {"healthy": "✅", "warning": "⚠️", "critical": "❌"}.get(status, "")

        return f"""
## DX研发效能ROI评估报告

### 工具信息
- **AI工具**: {inputs.get('tool_name', '未知')}
- **开发者人数**: {inputs.get('total_developers', '-')}人
- **评估周期**: 月度

### 三维评估结果

#### 利用率维度 {status_icon(diagnosis['utilization']['status'])}
| 指标 | 数值 | 基准 |
|------|------|------|
| 日活率(DAU) | {dx.dau_rate:.1f}% | {self.BENCHMARKS['dau_rate']}% |
| 周活率(WAU) | {dx.wau_rate:.1f}% | - |
| AI代码占比 | {dx.ai_code_ratio:.1f}% | - |

#### 影响维度 {status_icon(diagnosis['impact']['status'])}
| 指标 | 数值 | 说明 |
|------|------|------|
| 节省时间 | {dx.time_saved_hours:.1f}h/周/人 | 开发者自评 |
| PR周期时间 | {dx.cycle_time_days:.1f}天 | - |
| 变更失败率 | {dx.cfr:.1f}% | 关键约束指标 |
| 智能体等效工时 | {dx.heh:.1f}h | HEH |

#### 成本维度 {status_icon(diagnosis['cost']['status'])}
| 指标 | 数值 |
|------|------|
| 净时间收益 | {dx.net_time_gain:.1f}h/月 |
| 智能体时薪 | ¥{dx.agent_hourly_rate:.0f}/小时 |
| 月度成本 | ¥{dx.license_cost:,.0f} |
| **ROI** | **{dx.roi:.1f}%** |

### 诊断结论
- 利用率: {diagnosis['utilization']['status'].upper()}
- 影响: {diagnosis['impact']['status'].upper()}
- 成本: {diagnosis['cost']['status'].upper()}
"""

    def _generate_pre_visualizations(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "expected_roi": {
                "type": "gauge",
                "title": "预期ROI",
                "value": float(inputs.get("expected_improvement", 30)) * 0.6,
                "max_value": 100
            }
        }

    def _generate_post_visualizations(self, dx: DXMetrics) -> Dict[str, Any]:
        return {
            "three_dimensions": {
                "type": "radar",
                "title": "三维评估雷达图",
                "categories": ["利用率", "影响", "成本效益"],
                "values": [
                    min(100, dx.dau_rate),
                    min(100, dx.time_saved_hours * 10),
                    min(100, max(0, dx.roi))
                ],
                "max_value": 100
            },
            "metrics_bar": {
                "type": "bar",
                "title": "关键指标",
                "data": {
                    "DAU率": dx.dau_rate,
                    "AI代码占比": dx.ai_code_ratio,
                    "CFR": dx.cfr,
                    "ROI": max(0, dx.roi)
                }
            }
        }

    def get_prompt_templates(self) -> Dict[str, str]:
        return {
            "pre": (
                "你是一名研发效能分析师，基于DX利用率-影响-成本框架。\n"
                "输入：开发者人数、周编码时长、预期提升率、基线CFR等。\n"
                "请计算理论节省时间、预期ROI，设定CFR红线，输出摘要和建议。"
            ),
            "post": (
                "你是一名研发效能复盘分析师，需计算真实ROI与三维诊断。\n"
                "输入：DAU/WAU、AI代码占比、节省时间、实际CFR、智能体任务数、成本。\n"
                "请计算净时间收益、智能体时薪、ROI，并给出利用率/影响/成本三个维度诊断与建议。"
            ),
        }
