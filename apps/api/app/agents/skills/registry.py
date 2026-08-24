"""Fixed skill registry for the MVP."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SkillDefinition:
    name: str
    stage_suffix: str
    description: str
    input_schema: dict[str, str] = field(default_factory=dict)
    output_schema: dict[str, str] = field(default_factory=dict)
    allowed_tools: list[str] = field(default_factory=list)
    allowed_subagents: list[str] = field(default_factory=list)
    auto_run_condition: str = "manual"  # 已固化为 manual：执行仅人工触发；AutoResearch 走独立 API
    visibility: str = "visible"
    # HCR-P0-04: explicit per-Skill HITL checkpoint policy. "never" takes no
    # durable checkpoint (stage-2/3/4 keep their existing non-paused flow);
    # "risk_gated" takes a checkpoint before the decision node so the
    # contract's L3/boundary gate can decide pause-vs-discard. This field
    # controls checkpoint-taking *only* — the L3-mandatory human-review rule
    # lives in ``stage1_contract.stage1_requires_human_review`` and fires
    # regardless of this value.
    hitl_policy: str = "never"


SKILL_DEFINITIONS = [
    SkillDefinition(
        name="scenario_risk_skill",
        stage_suffix="stage-1",
        description="识别场景边界、风险等级和 HITL 约束。",
        input_schema={"goal": "string", "stage_id": "string", "project_id": "string", "file_ids": "list[string]", "evidence_ids": "list[string]"},
        output_schema={"summary": "string", "stage_result_patch": "object", "stage1_validation": "object", "input_binding": "object"},
        allowed_tools=["document_parse", "vision_parse", "risk_identify"],
        allowed_subagents=["risk_review_subagent"],
        hitl_policy="risk_gated",
    ),
    SkillDefinition(
        name="value_modeling_skill",
        stage_suffix="stage-2",
        description="计算目标 SLA、价值和实施税。",
        input_schema={"goal": "string", "stage_id": "string", "project_id": "string"},
        output_schema={"summary": "string", "stage_result_patch": "object"},
        allowed_tools=["value_model", "sla_target"],
        allowed_subagents=["value_review_subagent"],
    ),
    SkillDefinition(
        name="probe_validation_skill",
        stage_suffix="stage-3",
        description="设计探针、样本台账和 Actual SLA 汇总。",
        input_schema={"goal": "string", "stage_id": "string", "project_id": "string"},
        output_schema={"summary": "string", "stage_result_patch": "object"},
        allowed_tools=["sample_score", "actual_sla_summary"],
        allowed_subagents=["probe_review_subagent"],
    ),
    SkillDefinition(
        name="evidence_decision_skill",
        stage_suffix="stage-4",
        description="整合证据并输出决策建议。",
        input_schema={"goal": "string", "stage_id": "string", "project_id": "string"},
        output_schema={"summary": "string", "stage_result_patch": "object"},
        allowed_tools=["evidence_bundle", "report_generate"],
        allowed_subagents=["evidence_review_subagent"],
    ),
    SkillDefinition(
        name="report_generation_skill",
        stage_suffix="stage-4",
        description="生成阶段报告草稿、决策卡和导出包。",
        input_schema={"goal": "string", "stage_id": "string", "project_id": "string"},
        output_schema={"summary": "string", "report_stub": "object"},
        allowed_tools=["report_generate", "export_bundle"],
        allowed_subagents=["report_review_subagent"],
    ),
]


def list_skills(stage_id: Optional[str] = None) -> list[SkillDefinition]:
    if stage_id is None:
        return list(SKILL_DEFINITIONS)
    return [item for item in SKILL_DEFINITIONS if stage_id.endswith(item.stage_suffix)]


def get_skill_by_name(skill_name: str) -> SkillDefinition:
    for item in SKILL_DEFINITIONS:
        if item.name == skill_name:
            return item
    raise KeyError(skill_name)


def get_skill_for_stage(stage_id: str) -> SkillDefinition:
    for item in SKILL_DEFINITIONS:
        if stage_id.endswith(item.stage_suffix):
            return item
    return SkillDefinition(
        name="generic_stage_skill",
        stage_suffix="unknown",
        description="通用阶段处理入口。",
        allowed_tools=["document_parse"],
        allowed_subagents=[],
    )
