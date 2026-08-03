"""Repository helpers backed by MongoDB."""

from __future__ import annotations

import logging
from datetime import datetime
from dataclasses import asdict
from typing import Any, Callable, Optional, TypeVar

from pymongo.errors import PyMongoError

from src.apps.api.app.core.harness_constants import (
    DEFAULT_AGENT_HARNESS_VERSION,
    DEFAULT_CONVERSATION_HARNESS_VERSION,
)
from src.apps.api.app.domain.models import (
    utcnow,
    AutoResearchCandidate,
    AutoResearchRecord,
    CapabilityMutabilityContract,
    Conversation,
    ConversationActionProposalRecord,
    ConversationMessage,
    EvidenceItem,
    ExecutionLog,
    FileArtifact,
    FrozenEvalContract,
    ModelProfile,
    Project,
    ProjectSettings,
    PromptTemplate,
    RejectedCandidate,
    ReportArtifact,
    RuleProposal,
    Run,
    RunEvent,
    RunPolicy,
    SkillRunComparison,
    Stage,
    StageResult,
    StageSkillProfile,
    VersionLog,
)
from src.apps.api.app.repositories.mongodb import get_mongo_database

T = TypeVar("T")
logger = logging.getLogger(__name__)


class RepositoryUnavailableError(PyMongoError):
    """Raised when MongoDB cannot be reached for a repository operation."""

    def __init__(self, operation: str, collection_name: str, query: dict[str, Any] | None = None) -> None:
        self.operation = operation
        self.collection_name = collection_name
        self.query = query or {}
        super().__init__(
            "MongoDB {operation} failed for collection={collection} query={query}".format(
                operation=operation,
                collection=collection_name,
                query=self.query,
            )
        )


def _serialize(item: Any) -> dict[str, Any]:
    return asdict(item)


def _conversation_message_from_doc(doc: dict[str, Any]) -> ConversationMessage:
    return ConversationMessage(
        role=doc["role"],
        content=doc["content"],
        created_at=doc.get("created_at") or utcnow(),
        source_event_id=doc.get("source_event_id"),
        run_id=doc.get("run_id"),
        action_proposals=list(doc.get("action_proposals", [])),
        harness_warnings=list(doc.get("harness_warnings", [])),
        tool_calls=list(doc.get("tool_calls", [])),
        process_only=bool(doc.get("process_only", False)),
    )


def _conversation_from_doc(doc: dict[str, Any]) -> Conversation:
    project_id = doc.get("project_id")
    if not project_id:
        # Legacy records before project_id was added; backfill via stage.
        stage = _get_mongo("stages", {"id": doc["stage_id"]}, _stage_from_doc)
        project_id = stage.project_id if stage else ""
    return Conversation(
        id=doc["id"],
        stage_id=doc["stage_id"],
        project_id=project_id,
        title=doc["title"],
        status=doc.get("status", "active"),
        created_at=doc["created_at"],
        updated_at=doc.get("updated_at", doc["created_at"]),
        archived_at=doc.get("archived_at"),
        messages=[_conversation_message_from_doc(item) for item in doc.get("messages", [])],
    )


def list_active_conversations(stage_id: str) -> list[Conversation]:
    items = _list_mongo(
        "conversations",
        {"stage_id": stage_id, "status": {"$ne": "deleted"}},
        _conversation_from_doc,
    )
    return sorted(items, key=lambda item: item.created_at)



def _stage_from_doc(doc: dict[str, Any]) -> Stage:
    return Stage(
        id=doc["id"],
        project_id=doc["project_id"],
        name=doc["name"],
        status=doc["status"],
        created_at=doc["created_at"],
        objective=doc.get("objective"),
    )


def _project_from_doc(doc: dict[str, Any]) -> Project:
    return Project(
        id=doc["id"],
        name=doc["name"],
        goal=doc["goal"],
        status=doc["status"],
        created_at=doc["created_at"],
        updated_at=doc["updated_at"],
        stages=[],
    )


def _run_event_from_doc(doc: dict[str, Any]) -> RunEvent:
    return RunEvent(
        id=doc["id"],
        run_id=doc["run_id"],
        project_id=doc["project_id"],
        stage_id=doc.get("stage_id"),
        conversation_id=doc.get("conversation_id"),
        type=doc["type"],
        payload=doc["payload"],
        created_at=doc["created_at"],
        updated_at=doc.get("updated_at", doc["created_at"]),
    )


def _run_from_doc(doc: dict[str, Any]) -> Run:
    return Run(
        id=doc["id"],
        project_id=doc["project_id"],
        stage_id=doc.get("stage_id"),
        conversation_id=doc.get("conversation_id"),
        goal=doc["goal"],
        status=doc["status"],
        created_at=doc["created_at"],
        failure_reason=doc.get("failure_reason"),
        failure_context=doc.get("failure_context", {}),
        events=[_run_event_from_doc(item) for item in doc.get("events", [])],
        config_version_id=doc.get("config_version_id"),
    )


def _conversation_action_proposal_from_doc(doc: dict[str, Any]) -> ConversationActionProposalRecord:
    created_at = doc.get("created_at") or utcnow()
    return ConversationActionProposalRecord(
        id=doc["id"],
        project_id=doc["project_id"],
        stage_id=doc["stage_id"],
        conversation_id=doc["conversation_id"],
        conversation_harness_version=doc.get(
            "conversation_harness_version", DEFAULT_CONVERSATION_HARNESS_VERSION
        ),
        action_type=doc["action_type"],
        title=doc["title"],
        payload=doc.get("payload", {}),
        status=doc.get("status", "pending"),
        requires_confirmation=doc.get("requires_confirmation", True),
        run_id=doc.get("run_id"),
        created_at=created_at,
        updated_at=doc.get("updated_at", created_at),
    )


def _file_from_doc(doc: dict[str, Any]) -> FileArtifact:
    return FileArtifact(
        id=doc["id"],
        project_id=doc["project_id"],
        filename=doc["filename"],
        content_type=doc["content_type"],
        status=doc["status"],
        storage_path=doc.get("storage_path"),
        size_bytes=doc.get("size_bytes", 0),
        created_at=doc["created_at"],
    )


def _stage_result_from_doc(doc: dict[str, Any]) -> StageResult:
    return StageResult(
        id=doc["id"],
        project_id=doc["project_id"],
        stage_id=doc["stage_id"],
        version_id=doc["version_id"],
        base_version_id=doc.get("base_version_id"),
        run_id=doc["run_id"],
        status=doc["status"],
        input_file_ids=doc.get("input_file_ids", []),
        evidence_item_ids=doc.get("evidence_item_ids", []),
        model_config=doc.get("model_config", {}),
        skill_versions=doc.get("skill_versions", {}),
        autoresearch_record_ids=doc.get("autoresearch_record_ids", []),
        confirmation_ids=doc.get("confirmation_ids", []),
        result_payload=doc.get("result_payload", {}),
        summary=doc.get("summary", ""),
        created_at=doc["created_at"],
        updated_at=doc.get("updated_at", doc["created_at"]),
        locked_at=doc.get("locked_at"),
        # L1-A: prompt audit fields — default to {} for legacy docs that
        # pre-date this migration.
        prompt_hashes=doc.get("prompt_hashes", {}) or {},
        prompt_versions=doc.get("prompt_versions", {}) or {},
    )


def _autoresearch_record_from_doc(doc: dict[str, Any]) -> AutoResearchRecord:
    return AutoResearchRecord(
        id=doc["id"],
        project_id=doc["project_id"],
        stage_id=doc["stage_id"],
        run_id=doc["run_id"],
        stage_result_id=doc["stage_result_id"],
        title=doc["title"],
        source=doc["source"],
        impact=doc["impact"],
        risk=doc["risk"],
        description=doc["description"],
        action=doc["action"],
        context=doc.get("context", {}),
        status=doc["status"],
        note=doc.get("note"),
        edited_description=doc.get("edited_description"),
        created_at=doc["created_at"],
        updated_at=doc.get("updated_at", doc["created_at"]),
        confirmed_at=doc.get("confirmed_at"),
    )


def _evidence_from_doc(doc: dict[str, Any]) -> EvidenceItem:
    return EvidenceItem(
        id=doc["id"],
        project_id=doc["project_id"],
        name=doc["name"],
        source_type=doc["source_type"],
        source_file_id=doc.get("source_file_id"),
        attachment_path=doc.get("attachment_path"),
        snippet=doc.get("snippet"),
        created_at=doc["created_at"],
        status=doc.get("status", "parsed"),
        review_note=doc.get("review_note"),
        updated_at=doc.get("updated_at", doc["created_at"]),
    )


def _report_from_doc(doc: dict[str, Any]) -> ReportArtifact:
    return ReportArtifact(
        id=doc["id"],
        project_id=doc["project_id"],
        title=doc["title"],
        status=doc["status"],
        approval_check_passed=doc.get("approval_check_passed", False),
        export_path=doc.get("export_path"),
        decision_card_path=doc.get("decision_card_path"),
        evidence_directory_path=doc.get("evidence_directory_path"),
        bundle_export_path=doc.get("bundle_export_path"),
        stage_result_ids=doc.get("stage_result_ids", []),
        evidence_item_ids=doc.get("evidence_item_ids", []),
        created_at=doc["created_at"],
    )


def _execution_log_from_doc(doc: dict[str, Any]) -> ExecutionLog:
    return ExecutionLog(
        id=doc["id"],
        project_id=doc["project_id"],
        action=doc["action"],
        resource_type=doc["resource_type"],
        resource_id=doc["resource_id"],
        run_id=doc.get("run_id"),
        details=doc.get("details", {}),
        created_at=doc["created_at"],
    )


def _version_log_from_doc(doc: dict[str, Any]) -> VersionLog:
    return VersionLog(
        id=doc["id"],
        project_id=doc["project_id"],
        resource_type=doc["resource_type"],
        resource_id=doc["resource_id"],
        change_type=doc["change_type"],
        summary=doc["summary"],
        run_id=doc.get("run_id"),
        details=doc.get("details", {}),
        created_at=doc["created_at"],
    )


def _list_mongo(
    collection_name: str,
    query: Optional[dict[str, Any]],
    factory: Callable[[dict[str, Any]], T],
    *,
    log_traceback: bool = True,
) -> list[T]:
    try:
        database = get_mongo_database()
        cursor = database[collection_name].find(query or {}, {"_id": 0})
        return [factory(doc) for doc in cursor]
    except PyMongoError as exc:
        log = logger.exception if log_traceback else logger.warning
        log("MongoDB list read failed. collection=%s query=%s", collection_name, query or {})
        raise RepositoryUnavailableError("list read", collection_name, query or {}) from exc


def _list_mongo_in(collection_name: str, field: str, values: list[str], factory: Callable[[dict[str, Any]], T]) -> list[T]:
    if not values:
        return []
    return _list_mongo(collection_name, {field: {"$in": values}}, factory)


def _get_mongo(collection_name: str, query: dict[str, Any], factory: Callable[[dict[str, Any]], T]) -> Optional[T]:
    try:
        database = get_mongo_database()
        doc = database[collection_name].find_one(query, {"_id": 0})
    except PyMongoError as exc:
        logger.exception(
            "MongoDB item read failed. collection=%s query=%s",
            collection_name,
            query,
        )
        raise RepositoryUnavailableError("item read", collection_name, query) from exc
    if doc is None:
        return None
    return factory(doc)


def _save_mongo(collection_name: str, item_id: str, payload: dict[str, Any]) -> None:
    query = {"id": item_id}
    try:
        database = get_mongo_database()
        database[collection_name].replace_one(query, payload, upsert=True)
    except PyMongoError as exc:
        logger.exception(
            "MongoDB write failed. collection=%s query=%s",
            collection_name,
            query,
        )
        raise RepositoryUnavailableError("write", collection_name, query) from exc


def save_project(project: Project) -> None:
    payload = _serialize(project)
    payload["stages"] = []
    _save_mongo("projects", project.id, payload)


def list_projects() -> list[Project]:
    return _list_mongo("projects", None, _project_from_doc, log_traceback=False)


def get_project(project_id: str) -> Optional[Project]:
    return _get_mongo("projects", {"id": project_id}, _project_from_doc)


def save_stage(stage: Stage) -> None:
    _save_mongo("stages", stage.id, _serialize(stage))


def list_stages(project_id: str) -> list[Stage]:
    return _list_mongo("stages", {"project_id": project_id}, _stage_from_doc)


def list_stages_for_projects(project_ids: list[str]) -> list[Stage]:
    stages = _list_mongo_in("stages", "project_id", project_ids, _stage_from_doc)
    return sorted(stages, key=lambda item: item.created_at)


def get_stage(stage_id: str) -> Optional[Stage]:
    return _get_mongo("stages", {"id": stage_id}, _stage_from_doc)


def save_conversation(conversation: Conversation) -> None:
    _save_mongo("conversations", conversation.id, _serialize(conversation))


def update_conversation_status(
    conversation_id: str,
    *,
    status: str,
    archived_at: Optional[datetime] = None,
) -> None:
    """Atomically update only the status fields of a conversation.

    Avoids the full-document ``replace_one`` in :func:`save_conversation`, which
    would clobber the embedded ``messages`` array when racing an concurrent
    ``$push`` from :func:`add_conversation_message`.
    """
    database = get_mongo_database()
    update_set: dict[str, Any] = {"status": status, "updated_at": utcnow()}
    if archived_at is not None:
        update_set["archived_at"] = archived_at
    database["conversations"].update_one(
        {"id": conversation_id},
        {"$set": update_set},
    )


def get_conversation(conversation_id: str) -> Optional[Conversation]:
    return _get_mongo("conversations", {"id": conversation_id}, _conversation_from_doc)


def list_conversations(stage_id: str) -> list[Conversation]:
    return _list_mongo("conversations", {"stage_id": stage_id}, _conversation_from_doc)


def list_conversations_for_stages(stage_ids: list[str]) -> list[Conversation]:
    conversations = _list_mongo_in("conversations", "stage_id", stage_ids, _conversation_from_doc)
    return sorted(conversations, key=lambda item: item.created_at)


def add_conversation_message(conversation_id: str, message: ConversationMessage) -> None:
    """Atomically append a message to a conversation's embedded messages list."""
    database = get_mongo_database()
    serialized = _serialize(message)
    database["conversations"].update_one(
        {"id": conversation_id},
        {
            "$push": {"messages": serialized},
            "$set": {"updated_at": utcnow()},
        },
    )


def save_run(run: Run) -> None:
    _save_mongo("runs", run.id, _serialize(run))


def get_run(run_id: str) -> Optional[Run]:
    return _get_mongo("runs", {"id": run_id}, _run_from_doc)


def save_run_event(event: RunEvent) -> None:
    _save_mongo("run_events", event.id, _serialize(event))


def list_run_events(run_id: str) -> list[RunEvent]:
    events = _list_mongo("run_events", {"run_id": run_id}, _run_event_from_doc)
    return sorted(events, key=lambda item: item.created_at)


def list_run_events_by_conversation(conversation_id: str) -> list[RunEvent]:
    events = _list_mongo("run_events", {"conversation_id": conversation_id}, _run_event_from_doc)
    return sorted(events, key=lambda item: item.created_at)


def list_run_events_for_conversations(conversation_ids: list[str]) -> list[RunEvent]:
    events = _list_mongo_in("run_events", "conversation_id", conversation_ids, _run_event_from_doc)
    return sorted(events, key=lambda item: item.created_at)


def save_conversation_action_proposal(proposal: ConversationActionProposalRecord) -> None:
    _save_mongo("conversation_action_proposals", proposal.id, _serialize(proposal))


def claim_conversation_action_proposal(proposal_id: str) -> bool:
    """Atomically transition a proposal from ``pending`` to ``accepting``.

    Returns True when the claim was taken (matched a pending proposal) and
    False when another caller already claimed it, the proposal is not
    pending, or it no longer exists. Callers that receive False should
    surface a 409 to the client.
    """
    database = get_mongo_database()
    result = database["conversation_action_proposals"].update_one(
        {"id": proposal_id, "status": "pending"},
        {"$set": {"status": "accepting", "updated_at": utcnow()}},
    )
    return result.matched_count == 1


def release_conversation_action_proposal(proposal_id: str) -> None:
    """Revert an in-flight claim back to ``pending``.

    Used when ``create_run_sync`` fails after the proposal was claimed but
    before it was marked ``accepted``. Restores the proposal so the client
    can retry confirm without creating an orphan Run.
    """
    database = get_mongo_database()
    database["conversation_action_proposals"].update_one(
        {"id": proposal_id, "status": "accepting"},
        {"$set": {"status": "pending", "updated_at": utcnow()}},
    )


def get_conversation_action_proposal(
    proposal_id: str,
) -> Optional[ConversationActionProposalRecord]:
    return _get_mongo(
        "conversation_action_proposals",
        {"id": proposal_id},
        _conversation_action_proposal_from_doc,
    )


def list_conversation_action_proposals(
    conversation_id: str,
) -> list[ConversationActionProposalRecord]:
    proposals = _list_mongo(
        "conversation_action_proposals",
        {"conversation_id": conversation_id},
        _conversation_action_proposal_from_doc,
    )
    return sorted(proposals, key=lambda item: item.created_at)


def save_file_artifact(file_artifact: FileArtifact) -> None:
    _save_mongo("files", file_artifact.id, _serialize(file_artifact))


def get_file_artifact(file_id: str) -> Optional[FileArtifact]:
    return _get_mongo("files", {"id": file_id}, _file_from_doc)


def list_file_artifacts(project_id: Optional[str] = None) -> list[FileArtifact]:
    query = {"project_id": project_id} if project_id else None
    files = _list_mongo("files", query, _file_from_doc)
    return sorted(files, key=lambda item: item.created_at)


def count_file_artifacts_for_projects(project_ids: list[str]) -> dict[str, int]:
    """Return {project_id: file_count} for the given project IDs."""
    if not project_ids:
        return {}
    try:
        database = get_mongo_database()
        pipeline = [
            {"$match": {"project_id": {"$in": project_ids}}},
            {"$group": {"_id": "$project_id", "count": {"$sum": 1}}},
        ]
        result = database["files"].aggregate(pipeline)
        return {str(doc["_id"]): doc["count"] for doc in result}
    except PyMongoError as exc:
        logger.warning("MongoDB file count aggregation failed: %s", exc)
        return {}


def save_stage_result(stage_result: StageResult) -> None:
    _save_mongo("stage_results", stage_result.id, _serialize(stage_result))


def get_stage_result(stage_result_id: str) -> Optional[StageResult]:
    return _get_mongo("stage_results", {"id": stage_result_id}, _stage_result_from_doc)


def list_stage_results(stage_id: str) -> list[StageResult]:
    results = _list_mongo("stage_results", {"stage_id": stage_id}, _stage_result_from_doc)
    return sorted(results, key=lambda item: item.created_at)


def get_latest_stage_result(stage_id: str) -> Optional[StageResult]:
    results = list_stage_results(stage_id)
    if not results:
        return None
    return results[-1]


def save_evidence_item(evidence_item: EvidenceItem) -> None:
    _save_mongo("evidence_items", evidence_item.id, _serialize(evidence_item))


def list_evidence_items(project_id: Optional[str]) -> list[EvidenceItem]:
    return _list_mongo("evidence_items", {"project_id": project_id} if project_id else None, _evidence_from_doc)


def save_report(report: ReportArtifact) -> None:
    _save_mongo("reports", report.id, _serialize(report))


def get_report(report_id: str) -> Optional[ReportArtifact]:
    return _get_mongo("reports", {"id": report_id}, _report_from_doc)


def save_autoresearch_record(record: AutoResearchRecord) -> None:
    _save_mongo("autoresearch_records", record.id, _serialize(record))


def get_autoresearch_record(record_id: str) -> Optional[AutoResearchRecord]:
    return _get_mongo("autoresearch_records", {"id": record_id}, _autoresearch_record_from_doc)


def list_autoresearch_records(stage_id: Optional[str] = None) -> list[AutoResearchRecord]:
    query = {"stage_id": stage_id} if stage_id else None
    records = _list_mongo("autoresearch_records", query, _autoresearch_record_from_doc)
    return sorted(records, key=lambda item: item.created_at)


def list_autoresearch_records_for_stages(stage_ids: list[str]) -> list[AutoResearchRecord]:
    records = _list_mongo_in("autoresearch_records", "stage_id", stage_ids, _autoresearch_record_from_doc)
    return sorted(records, key=lambda item: item.created_at)


def save_execution_log(log: ExecutionLog) -> None:
    _save_mongo("execution_logs", log.id, _serialize(log))


def list_execution_logs(project_id: Optional[str]) -> list[ExecutionLog]:
    return _list_mongo("execution_logs", {"project_id": project_id} if project_id else None, _execution_log_from_doc)


def save_version_log(log: VersionLog) -> None:
    _save_mongo("version_logs", log.id, _serialize(log))


def list_version_logs(project_id: Optional[str]) -> list[VersionLog]:
    return _list_mongo("version_logs", {"project_id": project_id} if project_id else None, _version_log_from_doc)


def _model_profile_from_doc(doc: dict[str, Any]) -> ModelProfile:
    return ModelProfile(
        role=doc["role"],
        provider=doc.get("provider", "openai"),
        model_name=doc.get("model_name", "gpt-4o-mini"),
        base_url=doc.get("base_url", ""),
        api_key=doc.get("api_key", ""),
        enabled=doc.get("enabled", True),
    )


def _prompt_template_from_doc(doc: dict[str, Any]) -> PromptTemplate:
    return PromptTemplate(
        id=doc["id"],
        category=doc.get("category", "system"),
        scope=doc.get("scope", ""),
        title=doc.get("title", ""),
        body=doc.get("body", ""),
        required_variables=list(doc.get("required_variables", [])),
        skill_name=doc.get("skill_name"),
        version=doc.get("version", "v1"),
    )


def _stage_skill_profile_from_doc(doc: dict[str, Any]) -> StageSkillProfile:
    return StageSkillProfile(
        stage_id=doc["stage_id"],
        primary_skill=doc["primary_skill"],
        enabled_tools=list(doc.get("enabled_tools", [])),
        enabled_subagents=list(doc.get("enabled_subagents", [])),
        auto_run_condition=doc.get("auto_run_condition", "manual"),
        harness_version=doc.get("harness_version", DEFAULT_AGENT_HARNESS_VERSION),
        conversation_harness_version=doc.get("conversation_harness_version", DEFAULT_CONVERSATION_HARNESS_VERSION),
        skill_versions=dict(doc.get("skill_versions", {})),
    )


def _run_policy_from_doc(doc: dict[str, Any]) -> RunPolicy:
    return RunPolicy(
        require_change_reason=doc.get("require_change_reason", True),
        allow_locked_stage_rerun=doc.get("allow_locked_stage_rerun", True),
        min_audit_requirements=list(
            doc.get(
                "min_audit_requirements",
                ["config_version_id", "model_alias", "prompt_hash", "skill_version"],
            )
        ),
        # P3-b: 老数据缺 limit 字段时回退默认 20/50/500/30
        conversation_message_limit=doc.get("conversation_message_limit", 20),
        conversation_evidence_item_limit=doc.get("conversation_evidence_item_limit", 50),
        conversation_evidence_snippet_limit=doc.get("conversation_evidence_snippet_limit", 500),
        conversation_run_event_limit=doc.get("conversation_run_event_limit", 30),
    )


def _project_settings_from_doc(doc: dict[str, Any]) -> ProjectSettings:
    return ProjectSettings(
        id=doc["id"],
        project_id=doc["project_id"],
        version_id=doc["version_id"],
        base_version_id=doc.get("base_version_id"),
        status=doc.get("status", "draft"),
        config_hash=doc.get("config_hash", ""),
        change_reason=doc.get("change_reason", ""),
        models=[_model_profile_from_doc(item) for item in doc.get("models", [])],
        prompts=[_prompt_template_from_doc(item) for item in doc.get("prompts", [])],
        stage_skill_profiles=[
            _stage_skill_profile_from_doc(item) for item in doc.get("stage_skill_profiles", [])
        ],
        run_policy=_run_policy_from_doc(doc.get("run_policy", {})),
        created_at=doc.get("created_at"),
        updated_at=doc.get("updated_at", doc.get("created_at")),
        published_at=doc.get("published_at"),
        created_by=doc.get("created_by", "system"),
    )


def save_project_settings(settings: ProjectSettings) -> None:
    _save_mongo("project_settings", settings.id, _serialize(settings))


def get_project_settings(settings_id: str) -> Optional[ProjectSettings]:
    return _get_mongo("project_settings", {"id": settings_id}, _project_settings_from_doc)


def list_project_settings(project_id: str) -> list[ProjectSettings]:
    items = _list_mongo("project_settings", {"project_id": project_id}, _project_settings_from_doc)
    return sorted(items, key=lambda item: item.created_at)


def get_latest_published_settings(project_id: str) -> Optional[ProjectSettings]:
    items = [item for item in list_project_settings(project_id) if item.status == "published"]
    if not items:
        return None
    return items[-1]


def get_latest_draft_settings(project_id: str) -> Optional[ProjectSettings]:
    items = [item for item in list_project_settings(project_id) if item.status == "draft"]
    if not items:
        return None
    return items[-1]


# ── Frozen eval contract ─────────────────────────────────────────────────


def _frozen_eval_contract_from_doc(doc: dict[str, Any]) -> FrozenEvalContract:
    return FrozenEvalContract(
        id=doc["id"],
        version=doc["version"],
        stage_id=doc["stage_id"],
        frozen_fields=list(doc.get("frozen_fields", [])),
        mutable_fields=list(doc.get("mutable_fields", [])),
        created_at=doc.get("created_at") or utcnow(),
        created_by=doc.get("created_by", "system"),
    )


def save_frozen_eval_contract(contract: FrozenEvalContract) -> None:
    _save_mongo("frozen_eval_contracts", contract.id, _serialize(contract))


def get_frozen_eval_contract(contract_id: str) -> Optional[FrozenEvalContract]:
    return _get_mongo("frozen_eval_contracts", {"id": contract_id}, _frozen_eval_contract_from_doc)


def list_frozen_eval_contracts(stage_id: str) -> list[FrozenEvalContract]:
    items = _list_mongo("frozen_eval_contracts", {"stage_id": stage_id}, _frozen_eval_contract_from_doc)
    return sorted(items, key=lambda item: item.created_at)


def get_latest_frozen_eval_contract(stage_id: str) -> Optional[FrozenEvalContract]:
    items = list_frozen_eval_contracts(stage_id)
    if not items:
        return None
    return items[-1]


# ── AutoResearch candidate ────────────────────────────────────────────────


def _autoresearch_candidate_from_doc(doc: dict[str, Any]) -> AutoResearchCandidate:
    return AutoResearchCandidate(
        id=doc["id"],
        project_id=doc["project_id"],
        stage_id=doc["stage_id"],
        run_id=doc["run_id"],
        change_type=doc["change_type"],
        target_stage=doc.get("target_stage", "stage-1"),
        hypothesis=doc.get("hypothesis", ""),
        changed_refs=list(doc.get("changed_refs", [])),
        expected_effect=doc.get("expected_effect", ""),
        must_not_change=list(doc.get("must_not_change", [])),
        status=doc.get("status", "proposed"),
        iteration=doc.get("iteration", 0),
        metrics_before=dict(doc.get("metrics_before", {})),
        metrics_after=dict(doc.get("metrics_after", {})),
        gate_result=doc.get("gate_result", ""),
        gate_reason=doc.get("gate_reason", ""),
        human_review_status=doc.get("human_review_status", "not_required"),
        created_at=doc.get("created_at") or utcnow(),
    )


def save_autoresearch_candidate(candidate: AutoResearchCandidate) -> None:
    _save_mongo("autoresearch_candidates", candidate.id, _serialize(candidate))


def get_autoresearch_candidate(candidate_id: str) -> Optional[AutoResearchCandidate]:
    return _get_mongo("autoresearch_candidates", {"id": candidate_id}, _autoresearch_candidate_from_doc)


def list_autoresearch_candidates(
    stage_id: Optional[str] = None,
    run_id: Optional[str] = None,
) -> list[AutoResearchCandidate]:
    query: dict[str, Any] = {}
    if stage_id:
        query["stage_id"] = stage_id
    if run_id:
        query["run_id"] = run_id
    items = _list_mongo("autoresearch_candidates", query or None, _autoresearch_candidate_from_doc)
    return sorted(items, key=lambda item: item.created_at)


# ── Rejected candidate ────────────────────────────────────────────────────


def _rejected_candidate_from_doc(doc: dict[str, Any]) -> RejectedCandidate:
    return RejectedCandidate(
        id=doc["id"],
        project_id=doc["project_id"],
        stage_id=doc["stage_id"],
        candidate_id=doc["candidate_id"],
        rejection_reason=doc["rejection_reason"],
        failed_metrics=dict(doc.get("failed_metrics", {})),
        hard_constraint_triggered=doc.get("hard_constraint_triggered", ""),
        reusable_insights=list(doc.get("reusable_insights", [])),
        retry_allowed=doc.get("retry_allowed", True),
        created_at=doc.get("created_at") or utcnow(),
    )


def save_rejected_candidate(rejected: RejectedCandidate) -> None:
    _save_mongo("rejected_candidates", rejected.id, _serialize(rejected))


def get_rejected_candidate(rejected_id: str) -> Optional[RejectedCandidate]:
    return _get_mongo("rejected_candidates", {"id": rejected_id}, _rejected_candidate_from_doc)


def list_rejected_candidates(stage_id: Optional[str] = None) -> list[RejectedCandidate]:
    query = {"stage_id": stage_id} if stage_id else None
    items = _list_mongo("rejected_candidates", query, _rejected_candidate_from_doc)
    return sorted(items, key=lambda item: item.created_at)


# ── L2: Rule proposal ─────────────────────────────────────────────────────


def _rule_proposal_from_doc(doc: dict[str, Any]) -> RuleProposal:
    return RuleProposal(
        id=doc["id"],
        project_id=doc["project_id"],
        stage_id=doc["stage_id"],
        run_id=doc["run_id"],
        proposal_kind=doc["proposal_kind"],
        target_rule_id=doc["target_rule_id"],
        new_rule=doc.get("new_rule"),
        rationale=doc.get("rationale", ""),
        supporting_metrics=dict(doc.get("supporting_metrics", {})),
        status=doc.get("status", "proposed"),
        human_review_status=doc.get("human_review_status", "pending"),
        created_at=doc.get("created_at") or utcnow(),
        accepted_at=doc.get("accepted_at"),
        rejected_at=doc.get("rejected_at"),
        rejection_rationale=doc.get("rejection_rationale", ""),
    )


def save_rule_proposal(proposal: RuleProposal) -> None:
    _save_mongo("rule_proposals", proposal.id, _serialize(proposal))


def get_rule_proposal(proposal_id: str) -> Optional[RuleProposal]:
    return _get_mongo("rule_proposals", {"id": proposal_id}, _rule_proposal_from_doc)


def list_rule_proposals(
    stage_id: Optional[str] = None,
    status: Optional[str] = None,
) -> list[RuleProposal]:
    query: dict[str, Any] = {}
    if stage_id:
        query["stage_id"] = stage_id
    if status:
        query["status"] = status
    items = _list_mongo("rule_proposals", query or None, _rule_proposal_from_doc)
    return sorted(items, key=lambda item: item.created_at)


def list_pending_rule_proposals(stage_id: str) -> list[RuleProposal]:
    """Return proposals still awaiting human review."""
    items = _list_mongo(
        "rule_proposals",
        {"stage_id": stage_id, "human_review_status": "pending"},
        _rule_proposal_from_doc,
    )
    return sorted(items, key=lambda item: item.created_at)


# ── L2: Capability mutability contract ────────────────────────────────────


def _capability_contract_from_doc(doc: dict[str, Any]) -> CapabilityMutabilityContract:
    return CapabilityMutabilityContract(
        id=doc["id"],
        version=doc["version"],
        stage_id=doc["stage_id"],
        mutable_capabilities=list(doc.get("mutable_capabilities", [])),
        capability_gates=list(doc.get("capability_gates", [])),
        created_at=doc.get("created_at") or utcnow(),
        created_by=doc.get("created_by", "system"),
    )


def save_capability_mutability_contract(contract: CapabilityMutabilityContract) -> None:
    _save_mongo(
        "capability_mutability_contracts",
        contract.id,
        _serialize(contract),
    )


def get_capability_mutability_contract(contract_id: str) -> Optional[CapabilityMutabilityContract]:
    return _get_mongo(
        "capability_mutability_contracts",
        {"id": contract_id},
        _capability_contract_from_doc,
    )


def get_latest_capability_mutability_contract(stage_id: str) -> Optional[CapabilityMutabilityContract]:
    items = list_capability_mutability_contracts(stage_id)
    return items[-1] if items else None


def list_capability_mutability_contracts(stage_id: str) -> list[CapabilityMutabilityContract]:
    items = _list_mongo(
        "capability_mutability_contracts",
        {"stage_id": stage_id},
        _capability_contract_from_doc,
    )
    return sorted(items, key=lambda item: item.created_at)


# ── L4: Skill run comparison ──────────────────────────────────────────────


def _skill_run_comparison_from_doc(doc: dict[str, Any]) -> SkillRunComparison:
    return SkillRunComparison(
        id=doc["id"],
        project_id=doc["project_id"],
        stage_id=doc["stage_id"],
        skill_name=doc["skill_name"],
        run_id_v1=doc["run_id_v1"],
        version_v1=doc["version_v1"],
        run_id_v2=doc["run_id_v2"],
        version_v2=doc["version_v2"],
        input_payload_hash=doc["input_payload_hash"],
        quality_v1=dict(doc.get("quality_v1", {})),
        quality_v2=dict(doc.get("quality_v2", {})),
        quality_delta=dict(doc.get("quality_delta", {})),
        issue_count_v1=int(doc.get("issue_count_v1", 0)),
        issue_count_v2=int(doc.get("issue_count_v2", 0)),
        tool_call_diff=dict(doc.get("tool_call_diff", {})),
        prompt_hashes_v1=dict(doc.get("prompt_hashes_v1", {})),
        prompt_hashes_v2=dict(doc.get("prompt_hashes_v2", {})),
        verdict=doc.get("verdict", "neutral"),
        verdict_reason=doc.get("verdict_reason", ""),
        created_at=doc.get("created_at") or utcnow(),
    )


def save_skill_run_comparison(comparison: SkillRunComparison) -> None:
    _save_mongo("skill_run_comparisons", comparison.id, _serialize(comparison))


def get_skill_run_comparison(comparison_id: str) -> Optional[SkillRunComparison]:
    return _get_mongo(
        "skill_run_comparisons",
        {"id": comparison_id},
        _skill_run_comparison_from_doc,
    )


def list_skill_run_comparisons(
    stage_id: Optional[str] = None,
    skill_name: Optional[str] = None,
) -> list[SkillRunComparison]:
    query: dict[str, Any] = {}
    if stage_id:
        query["stage_id"] = stage_id
    if skill_name:
        query["skill_name"] = skill_name
    items = _list_mongo(
        "skill_run_comparisons",
        query or None,
        _skill_run_comparison_from_doc,
    )
    return sorted(items, key=lambda item: item.created_at)


def latest_comparison_for_version(
    stage_id: str, skill_name: str, version_v2: str
) -> Optional[SkillRunComparison]:
    """Return the most recent comparison that produced *version_v2*."""
    candidates = [
        c for c in list_skill_run_comparisons(stage_id=stage_id, skill_name=skill_name)
        if c.version_v2 == version_v2
    ]
    return candidates[-1] if candidates else None
