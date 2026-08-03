from __future__ import annotations

from .models import ProbeRecord, ProbeSample, ProjectMeta, ScenarioRecord, ValueRecord


def build_demo_project() -> tuple[ProjectMeta, ScenarioRecord, ValueRecord, ProbeRecord]:
    meta = ProjectMeta(
        project_id="demo-loan-post-risk",
        name="贷后风险监测与预警研判",
        description="用于演示银行生成式AI前置评估MVP的示例项目",
        tags=["demo", "bank", "gai"],
    )
    scenario = ScenarioRecord(
        scenario_name="贷后风险监测与预警研判",
        scenario_type="贷后风险监测与处置",
        boundary="聚焦风险预警、等级初判与处置建议，不覆盖反欺诈等其他条线",
        sop_summary="从预警触发到人工复核再到处置建议输出的闭环流程",
        participants=["业务", "风险", "合规", "运营"],
        responsibilities=["预警识别", "风险判定", "人工复核", "审计留痕"],
        risk_level="L3",
        hitl_level="强HITL",
        audit_requirements=["全量留痕", "人工复核记录", "责任可追溯"],
    )
    value = ValueRecord(
        stakeholders=["科技", "业务", "风险", "合规", "运营"],
        implementation_tax_items=[
            {"name": "人工复核", "cost": 30000},
            {"name": "审计留痕", "cost": 8000},
            {"name": "返工处理", "cost": 5000},
        ],
        manual_baseline_cost=60000,
        ai_operating_cost=12000,
        expected_benefit=150000,
        sensitivity_notes=["高风险场景下需保持强HITL", "若人工负担升高则净价值下降"],
    )
    probe = ProbeRecord(
        atomic_tasks=["预警识别", "风险原因归纳", "等级初判", "处置建议生成"],
        rubric=["事实一致性", "关键字段完整率", "严重错误率", "人工介入比例"],
        samples=[
            ProbeSample(
                sample_id="s1",
                task_name="预警识别",
                expected="识别高风险预警",
                actual="识别高风险预警",
                score=0.96,
                severity="low",
                manual_review_minutes=8,
                passed=True,
            ),
            ProbeSample(
                sample_id="s2",
                task_name="风险原因归纳",
                expected="归纳资金回流异常",
                actual="归纳资金回流异常",
                score=0.91,
                severity="medium",
                manual_review_minutes=12,
                passed=True,
            ),
            ProbeSample(
                sample_id="s3",
                task_name="等级初判",
                expected="判定为中高风险",
                actual="判定为中风险",
                score=0.72,
                severity="critical",
                manual_review_minutes=24,
                passed=False,
            ),
            ProbeSample(
                sample_id="s4",
                task_name="处置建议生成",
                expected="建议人工复核并限额",
                actual="建议人工复核并限额",
                score=0.88,
                severity="medium",
                manual_review_minutes=15,
                passed=True,
            ),
        ],
    )
    return meta, scenario, value, probe
