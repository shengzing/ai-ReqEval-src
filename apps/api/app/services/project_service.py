"""Project and stage services."""

from __future__ import annotations

import logging
import base64
import hashlib
import mimetypes
import re
from pathlib import Path
from uuid import uuid4
from typing import Any, Optional

from fastapi import HTTPException, status
from pymongo.errors import PyMongoError

from src.apps.api.app.domain.models import Conversation, ConversationMessage, EvidenceItem, FileArtifact, Project, ReportArtifact, Stage, StageResult, utcnow
from src.apps.api.app.integrations.file_storage import LocalFileStorage
from src.packages.reqeval.data.document_processor import DocumentProcessor, generate_document_summary
from src.apps.api.app.repositories.store import (
    add_conversation_message,
    count_file_artifacts_for_projects,
    delete_conversation_messages_by_run,
    delete_evidence_items_by_file,
    get_file_artifact,
    get_conversation as repo_get_conversation,
    get_project as repo_get_project,
    get_report as repo_get_report,
    get_stage as repo_get_stage,
    get_latest_stage_result,
    get_latest_valid_stage_result,
    get_run as repo_get_run,
    list_file_artifacts,
    list_autoresearch_records as repo_list_autoresearch_records,
    list_autoresearch_records_for_stages,
    list_conversations as repo_list_conversations,
    list_conversations_for_stages,
    list_conversation_action_proposals,
    list_evidence_items,
    list_projects as repo_list_projects,
    list_run_events_by_conversation,
    list_run_events_for_conversations,
    list_stage_results as repo_list_stage_results,
    list_stages as repo_list_stages,
    list_stages_for_projects,
    save_conversation,
    save_evidence_item,
    save_file_artifact,
    save_project,
    save_report,
    save_stage_result,
    save_stage,
    update_conversation_status,
    upsert_conversation_message_by_run,
)
from src.apps.api.app.services.log_service import create_execution_log, create_version_log, list_execution_logs, list_version_logs
from src.apps.api.app.services.settings_service import ensure_default_settings
from src.apps.api.app.services.stage_result_service import build_stage_result_diff
from src.apps.api.app.security.sanitization import redact_document_for_analysis

# Marker prefix for the initial message of a button-triggered stage Run. The
# frontend sends a hidden marker so the conversation is created without a
# user-visible "goal" bubble; the goal is surfaced by the execution timeline
# and the terminal assistant message instead.
RUN_TRIGGER_MESSAGE_PREFIX = "[RUN] "

DEFAULT_STAGES: tuple[tuple[str, str, str], ...] = (
    ("stage-1", "阶段一：场景解构与风险定级", "识别场景边界、流程节点、风险等级和 HITL。"),    ("stage-2", "阶段二：价值建模与目标 SLA", "把风险结论转成价值、成本和目标 SLA。"),
    ("stage-3", "阶段三：任务拆解与微型探针", "设计原子任务、样本台账和 Actual SLA。"),
    ("stage-4", "阶段四：三维对齐与报告", "汇总证据、生成建议和报告。"),
)
logger = logging.getLogger(__name__)


AUTO_PARSE_SUFFIXES = {
    ".txt", ".md", ".markdown", ".csv", ".json", ".yaml", ".yml", ".log",
    ".doc", ".docx", ".xls", ".xlsx", ".pdf",
}


def _should_auto_parse(filename: str, content_type: str) -> bool:
    """Return whether an upload belongs to the document parser path.

    Images stay in ``uploaded`` until the user invokes vision parsing; trying
    to decode arbitrary image bytes as text can create misleading evidence.
    """
    suffix = Path(filename).suffix.lower()
    return suffix in AUTO_PARSE_SUFFIXES or content_type.startswith("text/")


# Relevance is deliberately deterministic and explainable: it is a guardrail
# for whether a file may enter a stage run, not an attempt to infer business
# truth from a single upload.  The high-signal terms cover the bank scenarios
# the workbench evaluates; project-name and project-goal terms provide the
# project-specific match.  Files between the two thresholds remain visible
# but require a human decision before they can influence a StageResult.
_RELEVANCE_TERM_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9_-]{2,}|[\u4e00-\u9fff]{2,}")
_RELEVANCE_STOP_TERMS = {
    "项目", "场景", "需求", "报告", "生成", "分析", "系统", "平台", "业务",
    "数据", "文件", "流程", "当前", "材料", "智能", "助手", "任务", "阶段",
}
# HCR-P1-03：强信号与泛金融词分离。强信号单独驱动 ``related``，
# 泛词只升 ``needs_review``，删除脆弱的 blocklist 兜底（原 blocklist
# 漏 ``洗钱/贷后/贷款/预警``，致项目名含 ``洗钱`` + 文件含 ``洗钱`` 经
# project_matches 自动判 ``related``）。
_AML_STRONG_SIGNALS = {
    "反洗钱", "洗钱", "aml", "尽调", "尽职调查", "可疑交易", "制裁", "黑名单",
}
_GENERIC_FINANCIAL_TERMS = {
    "客户", "交易", "风险", "合规", "监管", "审计", "复核", "贷后", "贷款", "预警",
}
FILE_RELEVANCE_RULE_VERSION = "aml-project-relevance-v2"

# 敏感内容现走"脱敏 + 继续解析"路径：``security_rejected`` 不再阻断，
# 而是落 True 作为"已脱敏"标记（脱敏副本进入摘要/证据/Run，原始上传保留
# 供授权预览）。``rejected`` 仍为人工拒绝的终态，落定后不可经相关性复核
# 复活。校验器在 review_file_relevance 调用。
_RELEVANCE_STATUS_TRANSITIONS: dict[str, set[str]] = {
    "pending_parse": {"related", "unrelated", "needs_review", "rejected"},
    "needs_review": {"related", "unrelated", "needs_review", "rejected"},
    "related": {"related", "unrelated", "needs_review", "rejected"},
    "unrelated": {"related", "unrelated", "needs_review", "rejected"},
    "rejected": {"rejected"},
}


def _validate_relevance_transition(current: str, target: str) -> None:
    """Reject illegal relevance-state transitions with a 409.

    ``rejected`` is terminal — a human cannot resurrect a rejected file via the
    relevance review endpoint. Sensitive content is no longer quarantined; it is
    redacted and parsed, so a ``security_rejected`` flag does not lock the
    relevance state here.
    """
    allowed = _RELEVANCE_STATUS_TRANSITIONS.get(current, set())
    if target not in allowed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Relevance transition {current} -> {target} is not allowed.",
        )


def _relevance_terms(value: str) -> set[str]:
    return {
        term.lower()
        for term in _RELEVANCE_TERM_PATTERN.findall(value or "")
        if term.lower() not in _RELEVANCE_STOP_TERMS
    }


def assess_file_relevance(*, project: Project, filename: str, extracted_text: str) -> dict[str, object]:
    """Classify whether an uploaded file belongs to *project*.

    HCR-P1-03：判定由强 AML 信号驱动——文件含任一强信号即判 ``related``；
    仅含泛金融词升 ``needs_review``；无匹配判 ``unrelated``。hash 含项目
    名称与目标，使同一文件在不同项目下产出不同 hash（旧 Run 不重算）。
    结果完全可序列化，可同时持久化到 file 与 evidence 记录上。
    """
    project_context = f"{project.name}\n{project.goal}".lower()
    # 文件侧 searchable 仅含 filename+text，用于词匹配；项目上下文不参与
    # strong/generic 匹配，否则项目名含 ``反洗钱`` 或目标含 ``合规/复核``
    # 会让任意文件都被判 related/needs_review。
    file_searchable = f"{filename}\n{extracted_text[:20_000]}".lower()
    # hash 输入含项目上下文：同 filename+text 在不同项目下 hash 不同。
    hash_input = f"{project.name}\n{project.goal}\n{filename}\n{extracted_text[:20_000]}".lower()
    searchable_terms = _relevance_terms(file_searchable)
    project_terms = _relevance_terms(project_context)
    # 强信号与泛词作为子串匹配：中文无可靠词边界（如 ``反洗钱尽调``），
    # token-only 比较会漏掉本守卫需识别的文件。
    strong_matches = sorted(term for term in _AML_STRONG_SIGNALS if term in file_searchable)
    generic_matches = sorted(term for term in _GENERIC_FINANCIAL_TERMS if term in file_searchable)
    # project_matches 仅用于评分权重与理由 echo，不参与判定。
    project_matches = sorted(
        term
        for term in (strong_matches + generic_matches)
        if term in project_context
    )
    # 向后兼容：domain_matches = strong ∪ generic。
    domain_matches = sorted(set(strong_matches) | set(generic_matches))
    lexical_matches = sorted(
        project_term
        for project_term in project_terms
        if any(project_term in source_term or source_term in project_term for source_term in searchable_terms)
    )

    reasons: list[str] = []
    if project_matches:
        reasons.append("匹配项目名称或目标：" + "、".join(project_matches[:4]))
    if lexical_matches:
        reasons.append("匹配项目特征词：" + "、".join(lexical_matches[:4]))
    if strong_matches:
        reasons.append("强信号匹配：" + "、".join(strong_matches[:6]))
    if generic_matches:
        reasons.append("匹配业务领域词：" + "、".join(generic_matches[:6]))

    # 强信号权重高于泛词；项目特定词权重最高。上限 1.0 保持 API 契约稳定。
    score = min(
        1.0,
        round(
            len(project_matches) * 0.45
            + len(strong_matches) * 0.35
            + len(generic_matches) * 0.04
            + len(lexical_matches) * 0.08,
            2,
        ),
    )
    if strong_matches:
        relevance_status = "related"
    elif generic_matches:
        relevance_status = "needs_review"
    else:
        relevance_status = "unrelated"
        reasons.append("未识别到项目目标或银行业务领域匹配词")

    return {
        "status": relevance_status,
        "score": score,
        "reasons": reasons,
        "project_matches": project_matches,
        "strong_matches": strong_matches,
        "generic_matches": generic_matches,
        "domain_matches": domain_matches,
        "lexical_matches": lexical_matches,
        "rule_version": FILE_RELEVANCE_RULE_VERSION,
        "input_hash": hashlib.sha256(hash_input.encode("utf-8")).hexdigest(),
    }

def _file_storage() -> LocalFileStorage:
    return LocalFileStorage()


def create_project(*, name: str, goal: str) -> Project:
    """Create a project with default stages, or return the existing active one.

    Idempotent on ``(name, goal)``: if an active (non-deleted) project with the
    same name and goal already exists, return it instead of inserting a
    duplicate. Prevents test/acceptance scripts from flooding the shared
    MongoDB with identically-named junk projects.
    """
    normalized_name = name.strip() if name else name
    normalized_goal = goal.strip() if goal else goal
    for existing in _list_active_projects():
        if existing.name == normalized_name and existing.goal == normalized_goal:
            return existing

    project_id = f"project-{uuid4().hex[:8]}"
    project = Project(id=project_id, name=name, goal=goal)
    stages: list[Stage] = []
    for stage_slug, stage_name, objective in DEFAULT_STAGES:
        stage = Stage(
            id=f"{project_id}-{stage_slug}",
            project_id=project_id,
            name=stage_name,
            objective=objective,
        )
        save_stage(stage)
        stages.append(stage)
    project.stages = stages
    save_project(project)
    _file_storage().ensure_project_layout(project_id)
    ensure_default_settings(project_id)
    create_execution_log(
        project_id=project_id,
        action="project.created",
        resource_type="project",
        resource_id=project_id,
        details={"name": name},
    )
    create_version_log(
        project_id=project_id,
        resource_type="project",
        resource_id=project_id,
        change_type="created",
        summary="Project created with default stage layout.",
    )
    return project


def _list_active_projects() -> list[Project]:
    try:
        return [project for project in repo_list_projects() if project.status != "deleted"]
    except PyMongoError as exc:
        logger.warning(
            "MongoDB project list read failed; returning empty project list. error=%s",
            exc,
        )
        return []


def list_projects() -> list[Project]:
    return _list_active_projects()


def get_workspace_tree() -> list[dict[str, object]]:
    projects = _list_active_projects()
    project_ids = [project.id for project in projects]
    stages = list_stages_for_projects(project_ids)
    stage_ids = [stage.id for stage in stages]
    conversations = list_conversations_for_stages(stage_ids)
    # Drop soft-deleted conversations so the workspace tree matches the
    # per-stage list_conversations view (which filters status == "deleted").
    # Without this, deleted conversations keep showing in the left sidebar
    # even though the DELETE endpoint already marked them deleted.
    conversations = [conversation for conversation in conversations if conversation.status != "deleted"]
    conversation_ids = [conversation.id for conversation in conversations]
    run_events = list_run_events_for_conversations(conversation_ids)
    autoresearch_records = list_autoresearch_records_for_stages(stage_ids)

    stages_by_project: dict[str, list[Stage]] = {}
    for stage in stages:
        stages_by_project.setdefault(stage.project_id, []).append(stage)

    events_by_conversation: dict[str, list] = {}
    for event in run_events:
        if event.conversation_id:
            events_by_conversation.setdefault(event.conversation_id, []).append(event)

    conversations_by_stage: dict[str, list[Conversation]] = {}
    for conversation in conversations:
        conversations_by_stage.setdefault(conversation.stage_id, []).append(
            _hydrate_conversation_messages(conversation, events_by_conversation.get(conversation.id, []))
        )

    pending_by_stage: dict[str, int] = {}
    for record in autoresearch_records:
        if record.status == "pending":
            pending_by_stage[record.stage_id] = pending_by_stage.get(record.stage_id, 0) + 1

    file_counts_by_project = count_file_artifacts_for_projects(project_ids)

    items: list[dict[str, object]] = []
    for project in projects:
        stage_nodes: list[dict[str, object]] = []
        pending_count = 0
        for stage in stages_by_project.get(project.id, []):
            pending_confirmations = pending_by_stage.get(stage.id, 0)
            pending_count += pending_confirmations
            stage_nodes.append(
                {
                    **stage.__dict__,
                    "pending_confirmations": pending_confirmations,
                    "conversations": conversations_by_stage.get(stage.id, []),
                }
            )
        items.append(
            {
                **project.__dict__,
                "stages": stage_nodes,
                "pending_count": pending_count,
                "file_count": file_counts_by_project.get(project.id, 0),
            }
        )
    return items


def get_project(project_id: str) -> Project:
    project = repo_get_project(project_id)
    if project is None or project.status == "deleted":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    project.updated_at = utcnow()
    project.stages = repo_list_stages(project_id)
    save_project(project)
    return project


def soft_delete_project(project_id: str) -> None:
    project = repo_get_project(project_id)
    if project is None or project.status == "deleted":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    project.status = "deleted"
    project.updated_at = utcnow()
    save_project(project)
    create_execution_log(
        project_id=project_id,
        action="project.deleted",
        resource_type="project",
        resource_id=project_id,
        details={"name": project.name},
    )
    create_version_log(
        project_id=project_id,
        resource_type="project",
        resource_id=project_id,
        change_type="deleted",
        summary="Project removed from active workspace.",
    )


def update_project(project_id: str, name: str) -> Project:
    """Rename a project. Loads the persisted project, validates the new name is
    non-empty, persists, and records execution/version logs for the audit trail."""
    if not name or not name.strip():
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Project name must not be empty")
    project = repo_get_project(project_id)
    if project is None or project.status == "deleted":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    old_name = project.name
    project.name = name.strip()
    project.updated_at = utcnow()
    save_project(project)
    create_execution_log(
        project_id=project_id,
        action="project.renamed",
        resource_type="project",
        resource_id=project_id,
        details={"old_name": old_name, "new_name": project.name},
    )
    create_version_log(
        project_id=project_id,
        resource_type="project",
        resource_id=project_id,
        change_type="updated",
        summary=f"Project renamed from \"{old_name}\" to \"{project.name}\".",
    )
    return project


def get_stage(stage_id: str) -> Stage:
    stage = repo_get_stage(stage_id)
    if stage is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Stage not found")
    return stage


def list_stages(project_id: str) -> list[Stage]:
    _ = get_project(project_id)
    return repo_list_stages(project_id)


def list_stage_results(stage_id: str) -> list[StageResult]:
    _ = get_stage(stage_id)
    return repo_list_stage_results(stage_id)


def build_stage_completion_snapshot(*, stage_id: str, run_id: str) -> dict[str, object]:
    """Build the authoritative post-completion read model in one service call.

    The snapshot is read-only and deliberately uses the latest *valid* result;
    waiting, failed, or invalid drafts remain available through the normal
    audit endpoints but cannot hydrate the completed-result view.
    """
    stage = get_stage(stage_id)
    run = repo_get_run(run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    if run.stage_id != stage_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Run does not belong to stage")
    if run.status != "completed":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Completion snapshot requires a completed Run")
    latest_result = get_latest_valid_stage_result(stage_id)
    if latest_result is None or latest_result.run_id != run_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Run has no latest valid stage result")
    lock_check = build_stage_lock_checks(stage_id)
    files = list_files(stage.project_id)
    evidence = list_evidence(stage.project_id)
    suggestions = [
        item for item in repo_list_autoresearch_records(stage_id)
        if item.status == "pending"
    ]
    conversation = get_conversation(run.conversation_id) if run.conversation_id else None
    # HCR-P1-05：快照富集 version_log + vision_results，让前端完成 Run 后只读
    # 一次快照即可渲染右栏，不再触发连续的 /version-logs + /vision-results
    # 刷新。两块各包 try/except 降级——主读模型（completed Run）优先。
    version_log = None
    try:
        logs = get_version_logs(stage.project_id)
        matched = [
            item for item in logs
            if item.details.get("stage_id") == stage_id or item.resource_id == stage_id
        ]
        version_log = matched[-1] if matched else None
    except Exception:  # noqa: BLE001 — 副要数据，降级不破坏快照
        version_log = None
    vision_results: list[dict[str, Any]] = []
    try:
        # 延迟导入破循环：vision_service 模块级反向导入 project_service。
        from src.apps.api.app.services.vision_service import load_project_vision_results
        vision_results = load_project_vision_results(stage.project_id)
    except Exception:  # noqa: BLE001 — 副要数据，降级不破坏快照
        vision_results = []
    return {
        "run": run,
        "stage": stage,
        "latest_result": latest_result,
        "lock_check": lock_check,
        "files": files,
        "evidence": evidence,
        "suggestions": suggestions,
        "conversation": conversation,
        # Keep the sidebar in sync without a second workspace-tree request.
        "workspace": {"items": get_workspace_tree()},
        "version_log": version_log,
        "vision_results": vision_results,
    }


def _lock_check(
    key: str,
    label: str,
    *,
    passed: bool,
    code: str,
    hint: str,
    object_id: str | None,
) -> dict[str, object]:
    """One lock-check row.

    HCR-P0-03: ``ready`` remains ``all(item["passed"] for item in checks)``;
    this helper only enriches each row so a failing check carries a machine
    error code (``code`` for CI/frontend switching), a user-facing fix hint
    (``hint``) and the most specific traceable object id (``object_id``, which
    falls back to the stage id when the target object does not exist yet).
    """
    return {
        "key": key,
        "label": label,
        "passed": passed,
        "machine_code": code,
        "hint": hint,
        "object_id": object_id,
    }


def build_stage_lock_checks(stage_id: str) -> dict[str, object]:
    stage = get_stage(stage_id)
    # Lock evaluation must read the latest *valid* result. An invalid draft
    # (empty evidence, failed Run, waiting state) is not a lock candidate — it
    # is preserved for audit but must not surface its payload into the checks.
    stage_result = get_latest_valid_stage_result(stage_id)
    # Detect a newer invalid result that supersedes the valid one: the lock
    # must not pass while an un-reviewed invalid execution sits on top.
    newest_result = get_latest_stage_result(stage_id)
    has_newer_invalid = bool(
        newest_result
        and stage_result
        and newest_result.id != stage_result.id
        and not newest_result.valid_result
    )
    pending_records = [item.id for item in repo_list_autoresearch_records(stage_id) if item.status == "pending"]
    evidence_bound = bool(
        stage_result
        and stage_result.input_file_ids
        and stage_result.evidence_item_ids
    )

    # Base checks for all stages
    checks = [
        _lock_check(
            "stage_result_exists",
            "存在阶段结果草稿",
            passed=stage_result is not None,
            code="STAGE_RESULT_MISSING",
            hint="执行阶段 Run 生成阶段结果草稿后再锁定。",
            object_id=(stage_result.id if stage_result else stage_id),
        ),
        _lock_check(
            "evidence_bound",
            "必须完成输入材料与证据绑定",
            passed=evidence_bound,
            code="EVIDENCE_NOT_BOUND",
            hint="在阶段结果中绑定 input_file_ids 与 evidence_item_ids（至少各一条）。",
            object_id=(stage_result.id if stage_result else stage_id),
        ),
        _lock_check(
            "stage_result_valid",
            "阶段结果为有效执行结果且无更新失效结果",
            passed=bool(stage_result and stage_result.valid_result) and not has_newer_invalid,
            code="STAGE_RESULT_INVALID",
            hint="确保最新阶段结果 valid_result=true 且无更新失效结果覆盖。",
            object_id=(
                newest_result.id if has_newer_invalid and newest_result
                else (stage_result.id if stage_result else stage_id)
            ),
        ),
        _lock_check(
            "no_pending_autoresearch",
            "不存在待处理 autoResearch",
            passed=not pending_records,
            code="AUTORESEARCH_PENDING",
            hint="处理或关闭待处理 AutoResearch 记录后再锁定。",
            object_id=(pending_records[0] if pending_records else stage_id),
        ),
        _lock_check(
            "status_lockable",
            "阶段状态允许锁定",
            passed=stage.status != "failed",
            code="STAGE_STATUS_NOT_LOCKABLE",
            hint="阶段状态为 failed 不可锁定，需重新执行 Run。",
            object_id=stage_id,
        ),
    ]

    # Stage 1-specific checks
    if stage_id.endswith("stage-1") and stage_result is not None:
        scenario_summary = (stage_result.result_payload or {}).get("scenario_summary", {})
        quality_scores = (stage_result.result_payload or {}).get("stage1_validation", {}).get("quality", {})
        confirmation_ids = stage_result.confirmation_ids or []
        risk_level = scenario_summary.get("risk_level", "")
        hitl_level = scenario_summary.get("hitl_level", "")

        # 1. scenario_summary exists (hard blocker)
        checks.append(_lock_check(
            "s1_scenario_summary_exists",
            "阶段一场景摘要已生成",
            passed=bool(scenario_summary),
            code="S1_SCENARIO_SUMMARY_MISSING",
            hint="阶段一 Run 未生成 scenario_summary，重新执行并完成风险识别。",
            object_id=stage_result.id,
        ))

        evidence_refs = scenario_summary.get("evidence_refs", [])
        evidence_ref_set = {str(ref) for ref in evidence_refs if ref}
        bound_evidence_ids = set(stage_result.evidence_item_ids)

        # 2. Evidence refs must be present and bound to this result.
        checks.append(_lock_check(
            "s1_evidence_refs_nonempty",
            "场景摘要包含证据引用",
            passed=bool(evidence_ref_set),
            code="S1_EVIDENCE_REFS_EMPTY",
            hint="scenario_summary.evidence_refs 为空，补充证据引用。",
            object_id=stage_result.id,
        ))
        checks.append(_lock_check(
            "s1_evidence_refs_bound",
            "场景摘要证据引用均已绑定到阶段结果",
            passed=bool(evidence_ref_set) and evidence_ref_set.issubset(bound_evidence_ids),
            code="S1_EVIDENCE_REFS_UNBOUND",
            hint="scenario_summary.evidence_refs 中存在未绑定到阶段结果的引用，修正引用或补绑证据。",
            object_id=stage_result.id,
        ))

        # 3. risk_level valid enum (hard blocker)
        from src.apps.api.app.services.stage1_contract import RISK_LEVELS
        checks.append(_lock_check(
            "s1_risk_level_valid",
            "风险等级为有效枚举值（L1|L2|L3）",
            passed=risk_level in RISK_LEVELS,
            code="S1_RISK_LEVEL_INVALID",
            hint="risk_level 必须为 L1|L2|L3。",
            object_id=stage_result.id,
        ))

        # 4. hitl_level valid enum (hard blocker)
        from src.apps.api.app.services.stage1_contract import HITL_LEVELS
        checks.append(_lock_check(
            "s1_hitl_level_valid",
            "HITL 等级为有效枚举值",
            passed=hitl_level in HITL_LEVELS,
            code="S1_HITL_LEVEL_INVALID",
            hint="hitl_level 必须为 none|standard|strict|mandatory。",
            object_id=stage_result.id,
        ))

        # 5. L3 → HITL is strict or mandatory (hard blocker)
        if risk_level == "L3":
            checks.append(_lock_check(
                "s1_l3_hitl_strict_or_mandatory",
                "L3 风险等级必须 strict 或 mandatory HITL",
                passed=hitl_level in {"strict", "mandatory"},
                code="S1_L3_HITL_NOT_STRICT_OR_MANDATORY",
                hint="L3 风险必须配 strict 或 mandatory HITL。",
                object_id=stage_result.id,
            ))

        # 6. L3 → non-empty prohibited_conditions (hard blocker)
        if risk_level == "L3":
            checks.append(_lock_check(
                "s1_l3_prohibited_conditions",
                "L3 风险等级必须包含禁止条件",
                passed=bool(scenario_summary.get("prohibited_conditions")),
                code="S1_L3_PROHIBITED_CONDITIONS_EMPTY",
                hint="L3 风险必须包含禁止条件。",
                object_id=stage_result.id,
            ))

        # 7. L3 → non-empty fatal_errors (hard blocker)
        if risk_level == "L3":
            checks.append(_lock_check(
                "s1_l3_fatal_errors",
                "L3 风险等级必须包含致命错误场景",
                passed=bool(scenario_summary.get("fatal_errors")),
                code="S1_L3_FATAL_ERRORS_EMPTY",
                hint="L3 风险必须包含致命错误场景。",
                object_id=stage_result.id,
            ))

        # 8. No pending AutoResearch (already in base checks, but explicit for stage-1)
        # (already covered by no_pending_autoresearch above)

        # 9. L2/L3 → at least one confirmation_id (hard blocker)
        if risk_level in {"L2", "L3"}:
            checks.append(_lock_check(
                "s1_l2_l3_confirmation_required",
                "L2/L3 风险等级需要至少一条人工确认",
                passed=bool(confirmation_ids),
                code="S1_L2L3_CONFIRMATION_MISSING",
                hint="L2/L3 风险需要至少一条人工确认记录。",
                object_id=stage_result.id,
            ))

        # 10. Quality score thresholds are lock gates, not display advice.
        quality_thresholds = {
            "completeness_score": (0.70, "完整性 ≥ 0.70"),
            "evidence_coverage_score": (0.70, "证据覆盖度 ≥ 0.70"),
            "risk_consistency_score": (0.90, "风险一致性 ≥ 0.90"),
            "hitl_alignment_score": (0.90, "HITL 对齐度 ≥ 0.90"),
        }
        for score_name, (threshold, label) in quality_thresholds.items():
            score_val = quality_scores.get(score_name, 0.0)
            checks.append(_lock_check(
                f"s1_quality_{score_name}",
                f"阶段一质量：{label}",
                passed=score_val >= threshold,
                code=f"S1_QUALITY_{score_name.upper()}_BELOW_THRESHOLD",
                hint=f"提升 {label} 至阈值以上。",
                object_id=stage_result.id,
            ))

        # 11. Unresolved to_confirm items require an explicit confirmation
        # record before a Stage 1 draft can be locked.
        unresolved_to_confirm = scenario_summary.get("to_confirm", [])
        checks.append(_lock_check(
            "s1_pending_confirmations_resolved",
            "阶段一待人工确认事项已处理",
            passed=not unresolved_to_confirm or bool(confirmation_ids),
            code="S1_PENDING_CONFIRMATIONS_UNRESOLVED",
            hint="to_confirm 中仍有未处理项，补人工确认或清空。",
            object_id=stage_result.id,
        ))

    return {"stage_id": stage_id, "checks": checks, "ready": all(item["passed"] for item in checks)}


def list_conversations(stage_id: str) -> list[Conversation]:
    _ = get_stage(stage_id)
    items = repo_list_conversations(stage_id)
    visible = [item for item in items if item.status != "deleted"]
    return [_hydrate_conversation_messages(item) for item in visible]


def get_conversation(conversation_id: str) -> Conversation:
    conversation = repo_get_conversation(conversation_id)
    if conversation is None or conversation.status == "deleted":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    return _hydrate_conversation_messages(conversation)


def archive_conversation(conversation_id: str) -> Conversation:
    conversation = repo_get_conversation(conversation_id)
    if conversation is None or conversation.status == "deleted":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    if conversation.status == "archived":
        return conversation
    archived_at = utcnow()
    # Update only status fields atomically; the full-document replace in
    # save_conversation would clobber a concurrent $push message append.
    update_conversation_status(
        conversation_id,
        status="archived",
        archived_at=archived_at,
    )
    conversation.status = "archived"
    conversation.archived_at = archived_at
    conversation.updated_at = archived_at
    create_execution_log(
        project_id=conversation.project_id,
        action="conversation.archived",
        resource_type="conversation",
        resource_id=conversation.id,
        details={"stage_id": conversation.stage_id, "title": conversation.title},
    )
    return _hydrate_conversation_messages(conversation)


def restore_conversation(conversation_id: str) -> Conversation:
    conversation = repo_get_conversation(conversation_id)
    if conversation is None or conversation.status == "deleted":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    if conversation.status == "active":
        return conversation
    # Update only status fields atomically; the full-document replace in
    # save_conversation would clobber a concurrent $push message append.
    update_conversation_status(
        conversation_id,
        status="active",
    )
    conversation.status = "active"
    conversation.archived_at = None
    conversation.updated_at = utcnow()
    create_execution_log(
        project_id=conversation.project_id,
        action="conversation.restored",
        resource_type="conversation",
        resource_id=conversation.id,
        details={"stage_id": conversation.stage_id, "title": conversation.title},
    )
    return _hydrate_conversation_messages(conversation)


def soft_delete_conversation(conversation_id: str) -> None:
    conversation = repo_get_conversation(conversation_id)
    if conversation is None:
        return
    if conversation.status == "deleted":
        return
    # Update only status fields atomically; the full-document replace in
    # save_conversation would clobber a concurrent $push message append.
    update_conversation_status(
        conversation_id,
        status="deleted",
    )
    conversation.status = "deleted"
    conversation.updated_at = utcnow()
    create_execution_log(
        project_id=conversation.project_id,
        action="conversation.deleted",
        resource_type="conversation",
        resource_id=conversation.id,
        details={"stage_id": conversation.stage_id, "title": conversation.title},
    )


def _hydrate_conversation_messages(
    conversation: Conversation,
    run_events: Optional[list] = None,
) -> Conversation:
    if not conversation.project_id:
        # Backfill project_id from stage for legacy records.
        stage = repo_get_stage(conversation.stage_id)
        if stage is not None:
            conversation.project_id = stage.project_id
    messages: list[ConversationMessage] = list(conversation.messages)
    seen = {(item.role, item.content, item.source_event_id) for item in messages}
    # Conversations that already carry directly-persisted run messages
    # (run_id set by ``upsert_run_outcome_message``) skip event hydration
    # entirely — otherwise the legacy ``_run_event_to_conversation_message``
    # transcription would duplicate them on every read.
    has_persisted_run_messages = any(item.run_id for item in messages)
    if not has_persisted_run_messages:
        for event in run_events if run_events is not None else list_run_events_by_conversation(conversation.id):
            message = _run_event_to_conversation_message(event)
            if message is None or (message.role, message.content, message.source_event_id) in seen:
                continue
            messages.append(message)
            seen.add((message.role, message.content, message.source_event_id))
    conversation.messages = messages
    _hydrate_conversation_action_metadata(conversation)
    return conversation


def _hydrate_conversation_action_metadata(conversation: Conversation) -> None:
    """Refresh displayed proposal state without storing sensitive payloads in messages."""
    if not any(message.action_proposals for message in conversation.messages):
        return
    try:
        proposals_by_id = {
            proposal.id: proposal
            for proposal in list_conversation_action_proposals(conversation.id)
        }
    except PyMongoError:
        logger.warning("Conversation action proposal lookup failed for %s", conversation.id)
        return
    for message in conversation.messages:
        if not message.action_proposals:
            continue
        refreshed: list[dict] = []
        for summary in message.action_proposals:
            # Keep the conversation document and response deliberately
            # presentation-only; proposal payloads can include internal
            # execution inputs and must remain in the proposal record.
            proposal_id = summary.get("id")
            item = {
                key: summary[key]
                for key in (
                    "id",
                    "action_type",
                    "title",
                    "requires_confirmation",
                    "status",
                    "run_id",
                    "confirmation_id",
                )
                if key in summary
            }
            proposal = proposals_by_id.get(proposal_id)
            if proposal is not None:
                item["status"] = proposal.status
                item["run_id"] = proposal.run_id
                item["confirmation_id"] = proposal.confirmation_id
            refreshed.append(item)
        message.action_proposals = refreshed


def _action_proposal_summary(item: dict) -> dict:
    """Return the display-safe subset of a controlled action proposal."""
    return {
        key: item[key]
        for key in (
            "id",
            "action_type",
            "title",
            "requires_confirmation",
            "status",
            "run_id",
            "confirmation_id",
        )
        if key in item
    }


def _run_event_to_conversation_message(event) -> Optional[ConversationMessage]:
    event_type = getattr(event, "type", None)
    process_event_types = {
        "run.tool_completed",
        "run.tool_failed",
    }
    if event_type in process_event_types:
        payload = event.payload or {}
        node_name = payload.get("tool_name") or payload.get("skill_name") or payload.get("skill_id")
        if not isinstance(node_name, str) or not node_name.strip():
            node_name = "LangGraph Harness" if event_type.startswith("run.harness") else "tool"
        failed = event_type.endswith("_failed") or event_type == "run.harness_fallback" or payload.get("status") == "failed"
        summary = payload.get("summary")
        if not isinstance(summary, str) or not summary.strip():
            if failed:
                summary = "执行失败"
            elif event_type.endswith("_started"):
                summary = "正在执行"
            else:
                summary = "执行完成"
        raw_output = payload.get("raw_output")
        output = raw_output if isinstance(raw_output, dict) else {}
        evidence_refs = payload.get("evidence_refs")
        references = [item for item in evidence_refs if isinstance(item, str) and item] if isinstance(evidence_refs, list) else []
        return ConversationMessage(
            role="assistant",
            content=summary.strip(),
            created_at=getattr(event, "created_at", None) or utcnow(),
            source_event_id=getattr(event, "id", None),
            run_id=getattr(event, "run_id", None),
            process_only=True,
            tool_calls=[
                {
                    "tool_name": node_name.strip(),
                    "invocation_id": payload.get("invocation_id"),
                    "status": "failed" if failed else ("running" if event_type.endswith("_started") else "completed"),
                    "reason": summary.strip(),
                    "source": "stage_run",
                    "payload": {
                        "success": not failed,
                        "summary": summary.strip(),
                        "output": output,
                        "evidence_refs": references,
                    },
                }
            ],
        )
    # Routing steps belong to the execution timeline, not the assistant chat.
    # Waiting/HITL/terminal events are transcribed only for runs that predate
    # direct message persistence (``upsert_run_outcome_message``): those
    # messages already carry ``run_id``, so any conversation containing one is
    # excluded from hydration to avoid duplicated bubbles.
    if event_type not in {"run.suggestion", "run.waiting_inputs", "run.waiting_user", "run.completed", "run.failed"}:
        return None
    payload = event.payload or {}
    content = payload.get("message") or payload.get("summary") or payload.get("description") or payload.get("reason")
    if (
        event_type == "run.waiting_inputs"
        and payload.get("reason") == "missing_related_evidence"
        and (
            not isinstance(content, str)
            or content.startswith("阶段一需要至少一条已解析且已确认相关的证据材料")
        )
    ):
        # Legacy events used an internal gate description without telling the
        # operator how to recover. Keep old conversations useful after reload.
        content = (
            "当前无法重新运行：项目中没有已解析且确认相关的材料。"
            "请先在“阶段输入”中解析材料并确认相关性，然后重新运行。"
        )
    if content is None and event_type == "run.failed":
        content = payload.get("reason")
    if not isinstance(content, str) or not content.strip():
        return None
    return ConversationMessage(
        role="assistant",
        content=content.strip(),
        created_at=getattr(event, "created_at", None) or utcnow(),
        source_event_id=getattr(event, "id", None),
        run_id=getattr(event, "run_id", None),
    )


def create_conversation(stage_id: str, title: str, initial_message: Optional[str]) -> Conversation:
    stage = get_stage(stage_id)
    conversation = Conversation(
        id=f"conversation-{uuid4().hex[:8]}",
        stage_id=stage_id,
        project_id=stage.project_id,
        title=title,
    )
    if initial_message and not initial_message.startswith(RUN_TRIGGER_MESSAGE_PREFIX):
        conversation.messages.append(
            ConversationMessage(role="user", content=initial_message)
        )
    save_conversation(conversation)
    stage = get_stage(stage_id)
    create_execution_log(
        project_id=stage.project_id,
        action="conversation.created",
        resource_type="conversation",
        resource_id=conversation.id,
        details={"stage_id": stage_id, "title": title},
    )
    return conversation


def append_conversation_message(
    conversation_id: str,
    role: str,
    content: str,
    *,
    run_id: Optional[str] = None,
    source_event_id: Optional[str] = None,
    action_proposals: Optional[list[dict]] = None,
    citations: Optional[list[dict]] = None,
    harness_warnings: Optional[list[dict]] = None,
    tool_calls: Optional[list[dict]] = None,
) -> ConversationMessage:
    """Append a message to an existing conversation and persist it.

    Returns the newly created :class:`ConversationMessage`.
    Raises ``HTTPException(404)`` if the conversation does not exist, or
    ``HTTPException(409)`` if it is not active.
    """
    conversation = get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    if conversation.status != "active":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot append messages to a {conversation.status} conversation",
        )
    message = ConversationMessage(
        role=role,
        content=content,
        source_event_id=source_event_id,
        run_id=run_id,
        action_proposals=[_action_proposal_summary(item) for item in action_proposals or []],
        citations=list(citations or []),
        harness_warnings=list(harness_warnings or []),
        tool_calls=list(tool_calls or []),
    )
    conversation.messages.append(message)
    conversation.updated_at = utcnow()
    # Use the atomic $push store function for reliability
    add_conversation_message(conversation_id, message)
    return message


def upsert_run_outcome_message(
    conversation_id: str,
    *,
    run_id: str,
    content: str,
) -> ConversationMessage:
    """Idempotently write a Run's latest visible outcome message into its conversation.

    A single Run can surface more than one message over its lifetime — a
    ``waiting_user`` placeholder while paused, then a terminal
    ``completed``/``failed`` summary after resume. Exactly one message per
    ``run_id`` survives (older ones are atomically replaced) so the
    conversation never accumulates stale bubbles for one Run.
    """
    message = ConversationMessage(
        role="assistant",
        content=content,
        run_id=run_id,
    )
    upsert_conversation_message_by_run(conversation_id, message)
    return message


def delete_run_messages(conversation_id: str, run_id: str) -> None:
    """Remove every message a Run has written to its conversation.

    Called on resume/reject so a stale ``waiting_user`` placeholder is cleared
    before the resumed terminal outcome is persisted.
    """
    delete_conversation_messages_by_run(conversation_id, run_id)


def create_file(
    project_id: str,
    filename: str,
    content_type: str,
    content: Optional[str],
    content_base64: Optional[str] = None,
) -> FileArtifact:
    _ = get_project(project_id)
    artifact_id = f"file-{uuid4().hex[:8]}"
    storage_path = _file_storage().save_input_file(project_id, artifact_id, filename, content, content_base64)
    size_bytes = storage_path.stat().st_size
    artifact = FileArtifact(
        id=artifact_id,
        project_id=project_id,
        filename=filename,
        content_type=content_type,
        storage_path=str(storage_path),
        size_bytes=size_bytes,
    )
    save_file_artifact(artifact)
    create_execution_log(
        project_id=project_id,
        action="file.uploaded",
        resource_type="file",
        resource_id=artifact.id,
        details={"filename": filename, "storage_path": artifact.storage_path, "content_type": content_type},
    )
    if not _should_auto_parse(filename, content_type):
        return artifact
    # Auto-parse on upload so the file is immediately usable in a stage run
    # without a manual "解析" click. Document parsing (text extract +
    # relevance + summary) is local CPU, not an LLM call, so it is safe to
    # run synchronously. Vision parsing stays manual (LLM, slow).
    parse_status_code: Optional[int] = None
    parse_detail: Optional[str] = None
    try:
        parse_file(artifact.id)
    except HTTPException as exc:
        # Non-sensitive parse failures (empty text, unsupported format, parse
        # error) leave the artifact as "uploaded" so the user can retry via
        # the re-parse icon. Record the failure for auditability.
        parse_status_code = exc.status_code
        parse_detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
    except Exception as exc:  # noqa: BLE001 — upload must remain recoverable
        # Parser/library defects must not turn a successful upload into a lost
        # file. Keep the original artifact retryable and record only the error
        # type plus a bounded message for operators.
        logger.exception(
            "Automatic file parsing failed. project_id=%s file_id=%s filename=%s",
            project_id,
            artifact.id,
            filename,
        )
        parse_status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
        parse_detail = f"{type(exc).__name__}: {str(exc)[:300]}"
    # parse_file persisted whatever state it reached; read it back so the
    # returned artifact reflects the persisted record (parsed / rejected /
    # uploaded-on-failure) rather than a hand-copied subset of fields.
    persisted = get_file_artifact(artifact.id)
    if persisted is not None:
        artifact.status = persisted.status
        artifact.relevance_status = persisted.relevance_status
        artifact.relevance_score = persisted.relevance_score
        artifact.relevance_reasons = list(persisted.relevance_reasons)
        artifact.relevance_rule_version = persisted.relevance_rule_version
        artifact.relevance_input_hash = persisted.relevance_input_hash
        artifact.relevance_source = persisted.relevance_source
        artifact.security_rejected = persisted.security_rejected
    if parse_status_code is not None:
        create_execution_log(
            project_id=project_id,
            action="file.parse_failed",
            resource_type="file",
            resource_id=artifact.id,
            details={
                "filename": filename,
                "status_code": parse_status_code,
                "detail": parse_detail,
            },
        )
    return artifact


def list_files(project_id: Optional[str] = None) -> list[FileArtifact]:
    return list_file_artifacts(project_id)


PREVIEW_TEXT_LIMIT = 200_000
PREVIEW_BINARY_LIMIT = 8 * 1024 * 1024
TEXT_PREVIEW_SUFFIXES = {".txt", ".md", ".markdown", ".csv", ".json", ".yaml", ".yml", ".log"}
DOCUMENT_TEXT_PREVIEW_SUFFIXES = {".doc", ".docx", ".xls", ".xlsx"}
IMAGE_PREVIEW_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".heic"}
PDF_PREVIEW_SUFFIXES = {".pdf"}


def _guess_content_type(path: Path, fallback: str) -> str:
    guessed, _ = mimetypes.guess_type(path.name)
    if guessed:
        return guessed
    if fallback and fallback != "application/octet-stream":
        return fallback
    if path.suffix.lower() in {".md", ".markdown"}:
        return "text/markdown"
    if path.suffix.lower() == ".heic":
        return "image/heic"
    return fallback or "application/octet-stream"


def _extract_file_text(path: Path) -> str:
    try:
        return DocumentProcessor.process_file(path)
    except ValueError as exc:
        if path.suffix.lower() in {".txt", ".md", ".markdown"}:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
        try:
            return DocumentProcessor.parse_text(path)
        except ValueError:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except ImportError as exc:
        if path.suffix.lower() in {".txt", ".md", ".markdown"}:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
        try:
            return DocumentProcessor.parse_text(path)
        except ValueError:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


def get_file_preview(file_id: str) -> dict[str, object]:
    artifact = get_file_artifact(file_id)
    if artifact is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
    if not artifact.storage_path:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="File storage path is missing")
    path = Path(artifact.storage_path)
    if not path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Stored file not found")

    suffix = path.suffix.lower()
    content_type = _guess_content_type(path, artifact.content_type)

    if suffix in IMAGE_PREVIEW_SUFFIXES or suffix in PDF_PREVIEW_SUFFIXES or content_type.startswith("image/") or content_type == "application/pdf":
        size_bytes = path.stat().st_size
        if size_bytes > PREVIEW_BINARY_LIMIT:
            raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="File is too large to preview inline")
        preview_type = "image" if suffix in IMAGE_PREVIEW_SUFFIXES or content_type.startswith("image/") else "pdf"
        return {
            "id": artifact.id,
            "project_id": artifact.project_id,
            "filename": artifact.filename,
            "content_type": content_type,
            "preview_type": preview_type,
            "content": base64.b64encode(path.read_bytes()).decode("ascii"),
            "encoding": "base64",
            "size_bytes": size_bytes,
            "truncated": False,
        }

    if suffix in TEXT_PREVIEW_SUFFIXES or content_type.startswith("text/") or suffix in DOCUMENT_TEXT_PREVIEW_SUFFIXES:
        text = _extract_file_text(path)
        truncated = len(text) > PREVIEW_TEXT_LIMIT
        if truncated:
            text = text[:PREVIEW_TEXT_LIMIT]
        return {
            "id": artifact.id,
            "project_id": artifact.project_id,
            "filename": artifact.filename,
            "content_type": content_type,
            "preview_type": "text",
            "content": text,
            "encoding": "utf-8",
            "size_bytes": path.stat().st_size,
            "truncated": truncated,
        }

    raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="File type is not supported for preview")


def parse_file(file_id: str) -> FileArtifact:
    artifact = get_file_artifact(file_id)
    if artifact is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
    if not artifact.storage_path:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="File storage path is missing")
    storage_path = Path(artifact.storage_path)
    if not storage_path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Stored file not found")
    extracted_text = _extract_file_text(storage_path).strip()
    if not extracted_text:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="No parseable text found in file")
    safe_extracted_text, secret_findings = redact_document_for_analysis(extracted_text)
    if secret_findings:
        # The raw upload stays unchanged for authorized audit/preview, while
        # summaries, evidence, and Run context only receive this redacted copy.
        # Record categories only; never persist matched values.
        create_execution_log(
            project_id=artifact.project_id,
            action="file.sensitive_content_redacted",
            resource_type="file",
            resource_id=artifact.id,
            details={"finding_categories": secret_findings},
        )
    project = get_project(artifact.project_id)
    # Re-parse hygiene: keep the file-derived evidence ID stable so Run and
    # report references remain traceable after a manual re-parse. Vision
    # evidence is independent and remains available because the source file
    # bytes do not change during this operation.
    existing_evidence = [
        item
        for item in list_evidence_items(artifact.project_id)
        if item.source_file_id == artifact.id
    ]
    file_evidence = next(
        (item for item in existing_evidence if item.source_type == "file"),
        None,
    )
    delete_evidence_items_by_file(artifact.id, preserve_evidence_id=file_evidence.id if file_evidence else None)
    relevance = assess_file_relevance(
        project=project,
        filename=artifact.filename,
        extracted_text=safe_extracted_text,
    )
    summary = generate_document_summary(safe_extracted_text, max_length=500)
    artifact.status = "parsed"
    artifact.relevance_status = str(relevance["status"])
    artifact.relevance_score = float(relevance["score"])
    artifact.relevance_reasons = list(relevance["reasons"])
    if secret_findings:
        artifact.relevance_reasons.append("检测到敏感配置；进入分析、摘要和证据的内容已自动脱敏。")
    artifact.relevance_rule_version = str(relevance["rule_version"])
    artifact.relevance_input_hash = str(relevance["input_hash"])
    artifact.relevance_source = "machine"
    artifact.relevance_review_reason = None
    artifact.relevance_reviewed_by = None
    artifact.relevance_reviewed_at = None
    artifact.relevance_previous_status = None
    # 非阻断脱敏标记：命中敏感内容则置 True，但 status 仍为 parsed、
    # relevance_status 仍由 assess_file_relevance 决定，文件继续进入阶段分析。
    artifact.security_rejected = bool(secret_findings)
    evidence_id = file_evidence.id if file_evidence else f"evidence-{uuid4().hex[:8]}"
    attachment_path = _file_storage().save_evidence_attachment(
        artifact.project_id,
        evidence_id,
        artifact.filename,
        summary,
    )
    if file_evidence is None:
        evidence = EvidenceItem(
            id=evidence_id,
            project_id=artifact.project_id,
            name=f"{artifact.filename} 解析摘要",
            source_type="file",
            source_file_id=artifact.id,
            attachment_path=str(attachment_path),
            snippet=summary,
            status="parsed",
            relevance_status=artifact.relevance_status,
            relevance_score=artifact.relevance_score,
            relevance_reasons=list(artifact.relevance_reasons),
            relevance_rule_version=artifact.relevance_rule_version,
            relevance_input_hash=artifact.relevance_input_hash,
            relevance_source=artifact.relevance_source,
        )
    else:
        evidence = file_evidence
        evidence.name = f"{artifact.filename} 解析摘要"
        evidence.attachment_path = str(attachment_path)
        evidence.snippet = summary
        evidence.status = "parsed"
        evidence.review_note = None
        evidence.relevance_status = artifact.relevance_status
        evidence.relevance_score = artifact.relevance_score
        evidence.relevance_reasons = list(artifact.relevance_reasons)
        evidence.relevance_rule_version = artifact.relevance_rule_version
        evidence.relevance_input_hash = artifact.relevance_input_hash
        evidence.relevance_source = artifact.relevance_source
        evidence.relevance_review_reason = None
        evidence.relevance_reviewed_by = None
        evidence.relevance_reviewed_at = None
        evidence.relevance_previous_status = None
        evidence.updated_at = utcnow()
    _file_storage().save_parsed_summary(
        artifact.project_id,
        artifact.id,
        artifact.filename,
        summary,
    )
    save_file_artifact(artifact)
    save_evidence_item(evidence)
    create_execution_log(
        project_id=artifact.project_id,
        action="file.parsed",
        resource_type="file",
        resource_id=artifact.id,
        details={
            "evidence_id": evidence.id,
            "attachment_path": evidence.attachment_path,
            "text_length": len(extracted_text),
            "summary_length": len(summary),
            "relevance_status": artifact.relevance_status,
            "relevance_score": artifact.relevance_score,
            "relevance_reasons": artifact.relevance_reasons,
            "relevance_rule_version": artifact.relevance_rule_version,
            "relevance_input_hash": artifact.relevance_input_hash,
        },
    )
    return artifact


def review_file_relevance(
    file_id: str,
    *,
    decision: str,
    reason: str,
    reviewer: str = "workspace_user",
) -> FileArtifact:
    artifact = get_file_artifact(file_id)
    if artifact is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")

    normalized_reason = reason.strip()
    normalized_reviewer = reviewer.strip()
    if decision not in {"related", "unrelated", "rejected"}:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unsupported relevance decision")
    if len(normalized_reason) < 3:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Review reason must contain at least 3 characters")
    if not normalized_reviewer:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Reviewer is required")
    # 旧隔离遗留文件（status=="rejected"）仍锁死，只能显式 rejected。
    # security_rejected 现为"已脱敏"标记，不阻断相关性复核。
    if artifact.status == "rejected" and decision != "rejected":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Rejected files require a separate clearance workflow before review.",
        )
    if decision == "related" and artifact.status != "parsed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A file must be parsed successfully before it can be confirmed as related.",
        )
    # 相关性态转换合法性校验（rejected 终态不可复活）。
    _validate_relevance_transition(
        artifact.relevance_status,
        decision,
    )

    previous_status = artifact.relevance_status
    reviewed_at = utcnow()
    machine_reasons = [item for item in artifact.relevance_reasons if not item.startswith("人工复核：")]
    review_reason = f"人工复核：{normalized_reason}"
    artifact.relevance_status = decision
    # HCR-P1-03：first-class 前态字段，旧 doc 读 None（见 store.py）。
    artifact.relevance_previous_status = previous_status
    artifact.relevance_reasons = [*machine_reasons, review_reason]
    artifact.relevance_source = "human"
    artifact.relevance_review_reason = normalized_reason
    artifact.relevance_reviewed_by = normalized_reviewer
    artifact.relevance_reviewed_at = reviewed_at
    save_file_artifact(artifact)

    affected_evidence_ids: list[str] = []
    for evidence in list_evidence_items(artifact.project_id):
        if evidence.source_file_id != artifact.id:
            continue
        evidence.relevance_status = artifact.relevance_status
        evidence.relevance_score = artifact.relevance_score
        evidence.relevance_reasons = list(artifact.relevance_reasons)
        evidence.relevance_rule_version = artifact.relevance_rule_version
        evidence.relevance_input_hash = artifact.relevance_input_hash
        evidence.relevance_source = "human"
        # HCR-P1-03：级联前态到该 file 派生的 evidence（其它 evidence 不动）。
        evidence.relevance_previous_status = previous_status
        evidence.relevance_review_reason = normalized_reason
        evidence.relevance_reviewed_by = normalized_reviewer
        evidence.relevance_reviewed_at = reviewed_at
        evidence.updated_at = reviewed_at
        save_evidence_item(evidence)
        affected_evidence_ids.append(evidence.id)

    create_execution_log(
        project_id=artifact.project_id,
        action="file.relevance_reviewed",
        resource_type="file",
        resource_id=artifact.id,
        details={
            "previous_status": previous_status,
            "decision": decision,
            "reason": normalized_reason,
            "reviewer": normalized_reviewer,
            "reviewed_at": reviewed_at.isoformat(),
            "affected_evidence_ids": affected_evidence_ids,
            "machine_score": artifact.relevance_score,
            "rule_version": artifact.relevance_rule_version,
            "input_hash": artifact.relevance_input_hash,
        },
    )
    # HCR-P1-03：补版本日志，使人工改判进入版本可追溯链（与 file.parsed
    # 的 execution_log 并存——前者是审计轨迹，后者是版本谱）。
    create_version_log(
        project_id=artifact.project_id,
        resource_type="file",
        resource_id=artifact.id,
        change_type="relevance_reviewed",
        summary=f"Relevance reviewed: {previous_status} -> {decision} by {normalized_reviewer}.",
        details={
            "previous_status": previous_status,
            "decision": decision,
            "reason": normalized_reason,
            "reviewer": normalized_reviewer,
            "reviewed_at": reviewed_at.isoformat(),
            "affected_evidence_ids": affected_evidence_ids,
            "rule_version": artifact.relevance_rule_version,
            "input_hash": artifact.relevance_input_hash,
        },
    )
    return artifact


def list_evidence(project_id: Optional[str] = None) -> list[EvidenceItem]:
    return list_evidence_items(project_id)


def create_report(
    project_id: str,
    title: str,
    *,
    stage_result_ids: Optional[list[str]] = None,
    evidence_item_ids: Optional[list[str]] = None,
    enforce_export_gate: bool = True,
    approval_check_passed: bool = True,
    report_status: str = "report_ready",
) -> ReportArtifact:
    _ = get_project(project_id)
    stages = repo_list_stages(project_id)
    stage_results_by_stage = {stage.id: repo_list_stage_results(stage.id) for stage in stages}
    if enforce_export_gate:
        if not stages or any(not results for results in stage_results_by_stage.values()):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="All stages must have at least one stage result before report export")
        if any(results[-1].status != "locked" for results in stage_results_by_stage.values()):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="All stages must be locked before report export")
        if any(item.status == "pending" for stage in stages for item in repo_list_autoresearch_records(stage.id)):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Pending autoResearch suggestions must be cleared before report export")

    report_id = f"report-{uuid4().hex[:8]}"
    selected_stage_result_ids = stage_result_ids or []
    selected_evidence_item_ids = evidence_item_ids or []
    if not selected_stage_result_ids:
        selected_stage_result_ids = [item.id for stage in stages for item in stage_results_by_stage[stage.id]]
    if not selected_evidence_item_ids:
        selected_evidence_item_ids = [item.id for item in list_evidence_items(project_id)]
    stage_results = [item for stage in stages for item in stage_results_by_stage[stage.id] if item.id in selected_stage_result_ids]
    evidence_items = [item for item in list_evidence_items(project_id) if item.id in selected_evidence_item_ids]
    recommendation = "建议暂缓（补充论证）"
    if stage_results:
        recommendation = "建议立项" if len(stage_results) >= 1 and len(evidence_items) >= 1 else recommendation
    path = _file_storage().save_report_stub(project_id, report_id, title)
    decision_card_path = _file_storage().save_decision_card(project_id, report_id, title, recommendation)
    evidence_directory_path = _file_storage().save_evidence_directory(project_id, report_id, [item.name for item in evidence_items])
    bundle_export_path = _file_storage().save_export_bundle(
        project_id,
        report_id,
        {
            "report_path": str(path),
            "decision_card_path": str(decision_card_path),
            "evidence_directory_path": str(evidence_directory_path),
            "stage_result_ids": selected_stage_result_ids,
            "evidence_item_ids": selected_evidence_item_ids,
        },
    )
    report = ReportArtifact(
        id=report_id,
        project_id=project_id,
        title=title,
        approval_check_passed=approval_check_passed,
        export_path=str(path),
        decision_card_path=str(decision_card_path),
        evidence_directory_path=str(evidence_directory_path),
        bundle_export_path=str(bundle_export_path),
        stage_result_ids=selected_stage_result_ids,
        evidence_item_ids=selected_evidence_item_ids,
        status=report_status,
    )
    save_report(report)
    create_execution_log(
        project_id=project_id,
        action="report.generated",
        resource_type="report",
        resource_id=report.id,
        details={
            "title": title,
            "approval_check_passed": report.approval_check_passed,
            "export_path": report.export_path,
            "decision_card_path": report.decision_card_path,
            "evidence_directory_path": report.evidence_directory_path,
            "bundle_export_path": report.bundle_export_path,
            "stage_result_ids": report.stage_result_ids,
            "evidence_item_ids": report.evidence_item_ids,
        },
    )
    return report


def get_storage_path(file_id: str) -> Optional[Path]:
    artifact = get_file_artifact(file_id)
    if artifact is None or artifact.storage_path is None:
        return None
    return Path(artifact.storage_path)


def get_report(report_id: str) -> ReportArtifact:
    report = repo_get_report(report_id)
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found")
    return report


def get_report_content(report_id: str) -> tuple[ReportArtifact, str]:
    report = get_report(report_id)
    if not report.export_path:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report file not found")
    path = Path(report.export_path)
    if not path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report file not found")
    return report, path.read_text(encoding="utf-8")


def lock_stage(stage_id: str) -> tuple[Stage, str]:
    stage = get_stage(stage_id)
    # Lock must operate on the latest *valid* result. An invalid draft (empty
    # evidence, failed Run, waiting state) is never a lock candidate.
    stage_result = get_latest_valid_stage_result(stage_id)
    if stage_result is None or not stage_result.valid_result:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No valid stage result available for lock",
        )
    if stage.status == "locked" and stage_result.status == "locked":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Stage already locked")
    pending_records = [item.id for item in repo_list_autoresearch_records(stage_id) if item.status == "pending"]
    if pending_records:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Pending autoResearch suggestions must be processed before lock",
        )
    lock_checks = build_stage_lock_checks(stage_id)
    if not lock_checks["ready"]:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Stage lock checks not passed")
    stage.status = "locked"
    previous_state = StageResult(
        id=stage_result.id,
        project_id=stage_result.project_id,
        stage_id=stage_result.stage_id,
        version_id=stage_result.version_id,
        base_version_id=stage_result.base_version_id,
        run_id=stage_result.run_id,
        status=stage_result.status,
        input_file_ids=list(stage_result.input_file_ids),
        evidence_item_ids=list(stage_result.evidence_item_ids),
        model_config=dict(stage_result.model_config),
        skill_versions=dict(stage_result.skill_versions),
        autoresearch_record_ids=list(stage_result.autoresearch_record_ids),
        confirmation_ids=list(stage_result.confirmation_ids),
        result_payload=dict(stage_result.result_payload),
        valid_result=stage_result.valid_result,
        invalid_reason=stage_result.invalid_reason,
        summary=stage_result.summary,
        created_at=stage_result.created_at,
        updated_at=stage_result.updated_at,
        locked_at=stage_result.locked_at,
        # HCR-P1-02：复制 first-class 溯源字段，diff 快照保持可追溯。
        skill_name=stage_result.skill_name,
        config_version_id=stage_result.config_version_id,
    )
    stage_result.status = "locked"
    stage_result.locked_at = utcnow()
    stage_result.updated_at = stage_result.locked_at
    save_stage_result(stage_result)
    save_stage(stage)
    diff_summary = build_stage_result_diff(stage_result, previous_state, trigger="stage.locked")
    create_execution_log(
        project_id=stage.project_id,
        action="stage.locked",
        resource_type="stage",
        resource_id=stage.id,
        run_id=stage_result.run_id,
        details={"stage_name": stage.name, "stage_result_id": stage_result.id, "version_id": stage_result.version_id},
    )
    version_log = create_version_log(
        project_id=stage.project_id,
        resource_type="stage",
        resource_id=stage.id,
        change_type="locked",
        summary=f"Stage {stage.name} locked.",
        run_id=stage_result.run_id,
        details={
            "status": "locked",
            "stage_result_id": stage_result.id,
            "version_id": stage_result.version_id,
            "diff_summary": diff_summary,
        },
    )
    return stage, version_log.id


def get_execution_logs(project_id: Optional[str] = None):
    return list_execution_logs(project_id)


def get_version_logs(project_id: Optional[str] = None):
    return list_version_logs(project_id)
