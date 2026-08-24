"""Project, stage, file, evidence, and report routers."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Response, status

from src.apps.api.app.api.v1.schemas.projects import (
    AppendMessageRequest,
    AppendMessageResponse,
    AssistantHarnessMessageResponse,
    ActionProposalResponse,
    ActionProposalSummary,
    ConfirmActionProposalResponse,
    HarnessSummary,
    ConversationListResponse,
    ConversationResponse,
    CreateConversationRequest,
    CreateProjectRequest,
    UpdateProjectRequest,
    EvidenceItemResponse,
    EvidenceListResponse,
    ExecutionLogListResponse,
    ExecutionLogResponse,
    FileArtifactListResponse,
    FileRelevanceReviewRequest,
    FileArtifactResponse,
    FilePreviewResponse,
    FileUploadRequest,
    GenerateReportRequest,
    LockStageResponse,
    ProjectListResponse,
    ProjectResponse,
    ReportContentResponse,
    ReportResponse,
    StageLockCheckResponse,
    StageListResponse,
    StageResultListResponse,
    StageResultResponse,
    StageResponse,
    VisionParseRequest,
    VisionParseResponse,
    VersionLogListResponse,
    VersionLogResponse,
    VisionResultSummaryListResponse,
    VisionResultSummaryResponse,
    WorkspaceProjectNodeResponse,
    WorkspaceTreeResponse,
)
from src.apps.api.app.services import conversation_action_service, conversation_harness_service, run_service
from src.apps.api.app.services.project_service import (
    append_conversation_message,
    create_conversation,
    create_file,
    create_project,
    create_report,
    build_stage_lock_checks,
    archive_conversation,
    restore_conversation,
    soft_delete_conversation,
    soft_delete_project,
    update_project,
    get_execution_logs,
    get_file_preview,
    list_files,
    get_project,
    get_conversation,
    get_report_content,
    get_report,
    get_stage,
    get_version_logs,
    get_workspace_tree,
    lock_stage,
    list_conversations,
    list_evidence,
    list_projects,
    list_stage_results,
    list_stages,
    parse_file,
    review_file_relevance,
)
from src.apps.api.app.services.vision_service import load_project_vision_results, parse_file_with_vision

router = APIRouter()


@router.get("/workspace/tree", response_model=WorkspaceTreeResponse)
def get_workspace_tree_route() -> WorkspaceTreeResponse:
    return WorkspaceTreeResponse(
        items=[
            WorkspaceProjectNodeResponse.model_validate(item, from_attributes=True)
            for item in get_workspace_tree()
        ]
    )


@router.get("/projects", response_model=ProjectListResponse)
def get_projects() -> ProjectListResponse:
    return ProjectListResponse(items=[ProjectResponse.model_validate(item, from_attributes=True) for item in list_projects()])


@router.post("/projects", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
def post_project(request: CreateProjectRequest) -> ProjectResponse:
    project = create_project(name=request.name, goal=request.goal)
    return ProjectResponse.model_validate(project, from_attributes=True)


@router.get("/projects/{project_id}", response_model=ProjectResponse)
def get_project_detail(project_id: str) -> ProjectResponse:
    project = get_project(project_id)
    return ProjectResponse.model_validate(project, from_attributes=True)


@router.delete(
    "/projects/{project_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_project(project_id: str) -> Response:
    soft_delete_project(project_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch("/projects/{project_id}", response_model=ProjectResponse)
def patch_project(project_id: str, request: UpdateProjectRequest) -> ProjectResponse:
    project = update_project(project_id, request.name)
    return ProjectResponse.model_validate(project, from_attributes=True)


@router.get("/projects/{project_id}/stages", response_model=StageListResponse)
def get_project_stages(project_id: str) -> StageListResponse:
    stages = list_stages(project_id)
    return StageListResponse(items=[StageResponse.model_validate(item, from_attributes=True) for item in stages])


@router.get("/stages/{stage_id}", response_model=StageResponse)
def get_stage_detail(stage_id: str) -> StageResponse:
    stage = get_stage(stage_id)
    return StageResponse.model_validate(stage, from_attributes=True)


@router.get("/stages/{stage_id}/results", response_model=StageResultListResponse)
def get_stage_result_list(stage_id: str) -> StageResultListResponse:
    items = list_stage_results(stage_id)
    return StageResultListResponse(items=[StageResultResponse.model_validate(item, from_attributes=True) for item in items])


@router.post("/stages/{stage_id}/lock", response_model=LockStageResponse)
def post_stage_lock(stage_id: str) -> LockStageResponse:
    stage, version_log_id = lock_stage(stage_id)
    return LockStageResponse(
        stage=StageResponse.model_validate(stage, from_attributes=True),
        version_log_id=version_log_id,
        checks=build_stage_lock_checks(stage_id)["checks"],
    )


@router.get("/stages/{stage_id}/lock-check", response_model=StageLockCheckResponse)
def get_stage_lock_check(stage_id: str) -> StageLockCheckResponse:
    payload = build_stage_lock_checks(stage_id)
    return StageLockCheckResponse(
        stage_id=payload["stage_id"],
        checks=payload["checks"],
        ready=payload["ready"],
    )


@router.get("/stages/{stage_id}/conversations", response_model=ConversationListResponse)
def get_stage_conversations(stage_id: str) -> ConversationListResponse:
    items = list_conversations(stage_id)
    return ConversationListResponse(items=[ConversationResponse.model_validate(item, from_attributes=True) for item in items])


@router.post("/stages/{stage_id}/conversations", response_model=ConversationResponse, status_code=status.HTTP_201_CREATED)
def post_stage_conversation(stage_id: str, request: CreateConversationRequest) -> ConversationResponse:
    conversation = create_conversation(stage_id, request.title, request.initial_message)
    return ConversationResponse.model_validate(conversation, from_attributes=True)


@router.get("/conversations/{conversation_id}", response_model=ConversationResponse)
def get_conversation_detail(conversation_id: str) -> ConversationResponse:
    conversation = get_conversation(conversation_id)
    return ConversationResponse.model_validate(conversation, from_attributes=True)


@router.post(
    "/conversations/{conversation_id}/archive",
    response_model=ConversationResponse,
    status_code=status.HTTP_200_OK,
)
def post_conversation_archive(conversation_id: str) -> ConversationResponse:
    conversation = archive_conversation(conversation_id)
    return ConversationResponse.model_validate(conversation, from_attributes=True)


@router.post(
    "/conversations/{conversation_id}/restore",
    response_model=ConversationResponse,
    status_code=status.HTTP_200_OK,
)
def post_conversation_restore(conversation_id: str) -> ConversationResponse:
    conversation = restore_conversation(conversation_id)
    return ConversationResponse.model_validate(conversation, from_attributes=True)


@router.delete(
    "/conversations/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_conversation(conversation_id: str) -> Response:
    soft_delete_conversation(conversation_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/conversations/{conversation_id}/messages",
    response_model=AppendMessageResponse,
    status_code=status.HTTP_201_CREATED,
)
def post_conversation_message(conversation_id: str, request: AppendMessageRequest) -> AppendMessageResponse:
    """Append a message to an existing conversation.

    This endpoint enables the user to reply in the conversation thread.
    If a run is in ``waiting_user`` status and the conversation is linked
    to that run, the reply may also trigger a run resume.
    """
    if request.run_harness and request.role != "user":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="run_harness can only be used with user messages",
        )

    message = append_conversation_message(
        conversation_id=conversation_id,
        role=request.role,
        content=request.content,
    )
    if request.run_harness:
        try:
            invocation = conversation_harness_service.invoke_conversation_harness(
                conversation_id=conversation_id,
                user_message=request.content,
                config_version_id=request.config_version_id,
            )
        except HTTPException as exc:
            # P0-2 补偿：harness 失败时追加 assistant 失败消息，保持会话"有问有答"一致状态，
            # 避免出现只有 user、没有 assistant 的孤悬消息；router 仍抛错让前端知道失败。
            _append_harness_failure_assistant_message(conversation_id, exc)
            raise
        except Exception as exc:
            _append_harness_failure_assistant_message(conversation_id, exc)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Conversation harness failed",
            ) from exc
        return AppendMessageResponse(
            role=message.role,
            content=message.content,
            created_at=message.created_at,
            assistant_message=AssistantHarnessMessageResponse(
                role=invocation.assistant_message.role,
                content=invocation.assistant_message.content,
                created_at=invocation.assistant_message.created_at,
                tool_calls=list(invocation.assistant_message.tool_calls),
                citations=list(invocation.assistant_message.citations),
            ),
            harness=HarnessSummary(
                conversation_harness_version=invocation.result.conversation_harness_version,
                intent=invocation.result.intent,
                citations=invocation.result.citations,
                warnings=invocation.result.warnings,
                action_proposals=[
                    ActionProposalSummary(
                        id=pid,
                        action_type=p.get("action_type", ""),
                        title=p.get("title", ""),
                        requires_confirmation=p.get("requires_confirmation", True),
                        status="pending",
                        confirmation_id=None,
                    )
                    for pid, p in zip(invocation.action_proposal_ids, invocation.result.action_proposals)
                ],
            ),
        )
    return AppendMessageResponse(
        role=message.role,
        content=message.content,
        created_at=message.created_at,
    )


def _harness_failure_content(exc: Exception) -> str:
    """Build a user-facing assistant failure message for a harness exception."""
    if isinstance(exc, HTTPException):
        return f"[对话 Harness 执行失败] 状态 {exc.status_code}：{exc.detail}"
    return f"[对话 Harness 执行失败] 内部错误：{exc.__class__.__name__}"


def _append_harness_failure_assistant_message(conversation_id: str, exc: Exception) -> None:
    """Best-effort 补偿：追加 assistant 失败消息消除孤悬；不掩盖原始失败。"""
    try:
        append_conversation_message(
            conversation_id=conversation_id,
            role="assistant",
            content=_harness_failure_content(exc),
        )
    except Exception:
        # 补偿失败不影响原始异常抛出
        pass


@router.post(
    "/conversations/{conversation_id}/action-proposals/{proposal_id}/confirm",
    response_model=ConfirmActionProposalResponse,
    status_code=status.HTTP_200_OK,
)
async def post_conversation_action_proposal_confirm(
    conversation_id: str, proposal_id: str
) -> ConfirmActionProposalResponse:
    """Confirm a controlled proposal, creating a Run only when required."""
    proposal, run = conversation_action_service.confirm_action_proposal(
        proposal_id, conversation_id=conversation_id
    )
    if run is not None:
        run_service.start_run_background(run)
    return ConfirmActionProposalResponse(
        proposal=ActionProposalResponse.model_validate(proposal, from_attributes=True),
        run_id=run.id if run else None,
        confirmation_id=proposal.confirmation_id,
    )


@router.post(
    "/conversations/{conversation_id}/action-proposals/{proposal_id}/reject",
    response_model=ActionProposalResponse,
    status_code=status.HTTP_200_OK,
)
def post_conversation_action_proposal_reject(
    conversation_id: str, proposal_id: str
) -> ActionProposalResponse:
    """Reject a conversation action proposal; no Run is created."""
    proposal = conversation_action_service.reject_action_proposal(
        proposal_id, conversation_id=conversation_id
    )
    return ActionProposalResponse.model_validate(proposal, from_attributes=True)


@router.post("/files/upload", response_model=FileArtifactResponse, status_code=status.HTTP_201_CREATED)
def post_file_upload(request: FileUploadRequest) -> FileArtifactResponse:
    artifact = create_file(
        request.project_id,
        request.filename,
        request.content_type,
        request.content,
        request.content_base64,
    )
    return FileArtifactResponse.model_validate(artifact, from_attributes=True)


@router.get("/files", response_model=FileArtifactListResponse)
def get_files(project_id: Optional[str] = Query(default=None)) -> FileArtifactListResponse:
    items = list_files(project_id)
    return FileArtifactListResponse(items=[FileArtifactResponse.model_validate(item, from_attributes=True) for item in items])


@router.get("/files/{file_id}/preview", response_model=FilePreviewResponse)
def get_file_preview_route(file_id: str) -> FilePreviewResponse:
    return FilePreviewResponse(**get_file_preview(file_id))


@router.post("/files/{file_id}/parse", response_model=FileArtifactResponse)
def post_file_parse(file_id: str) -> FileArtifactResponse:
    artifact = parse_file(file_id)
    return FileArtifactResponse.model_validate(artifact, from_attributes=True)


@router.post("/files/{file_id}/relevance-review", response_model=FileArtifactResponse)
def post_file_relevance_review(file_id: str, request: FileRelevanceReviewRequest) -> FileArtifactResponse:
    artifact = review_file_relevance(
        file_id,
        decision=request.decision,
        reason=request.reason,
        reviewer=request.reviewer,
    )
    return FileArtifactResponse.model_validate(artifact, from_attributes=True)


@router.post("/files/{file_id}/vision-parse", response_model=VisionParseResponse)
def post_file_vision_parse(file_id: str, request: VisionParseRequest) -> VisionParseResponse:
    result = parse_file_with_vision(
        file_id=file_id,
        prompt=request.prompt,
        target_schema=request.target_schema,
        project_context=request.project_context,
    )
    return VisionParseResponse.model_validate(result, from_attributes=True)


@router.get("/vision-results", response_model=VisionResultSummaryListResponse)
def get_vision_results(project_id: str = Query(...)) -> VisionResultSummaryListResponse:
    items = load_project_vision_results(project_id)
    return VisionResultSummaryListResponse(
        items=[
            VisionResultSummaryResponse(
                file_id=item["file_id"],
                model=item["model"],
                structured_fields=item.get("structured_fields", {}),
                evidence_fragments=item.get("evidence_fragments", []),
                uncertainties=item.get("uncertainties", []),
                to_confirm=item.get("to_confirm", []),
            )
            for item in items
        ]
    )


@router.get("/evidence", response_model=EvidenceListResponse)
def get_evidence(project_id: Optional[str] = Query(default=None)) -> EvidenceListResponse:
    items = list_evidence(project_id)
    return EvidenceListResponse(items=[EvidenceItemResponse.model_validate(item, from_attributes=True) for item in items])


@router.post("/reports/generate", response_model=ReportResponse, status_code=status.HTTP_201_CREATED)
def post_report_generate(request: GenerateReportRequest) -> ReportResponse:
    report = create_report(request.project_id, request.title)
    return ReportResponse.model_validate(report, from_attributes=True)


@router.get("/reports/{report_id}", response_model=ReportResponse)
def get_report_detail(report_id: str) -> ReportResponse:
    report = get_report(report_id)
    return ReportResponse.model_validate(report, from_attributes=True)


@router.get("/reports/{report_id}/content", response_model=ReportContentResponse)
def get_report_content_route(report_id: str) -> ReportContentResponse:
    report, content = get_report_content(report_id)
    return ReportContentResponse(
        id=report.id,
        title=report.title,
        status=report.status,
        content=content,
    )

@router.get("/execution-logs", response_model=ExecutionLogListResponse)
def get_execution_logs_route(project_id: Optional[str] = Query(default=None)) -> ExecutionLogListResponse:
    items = get_execution_logs(project_id)
    return ExecutionLogListResponse(items=[ExecutionLogResponse.model_validate(item, from_attributes=True) for item in items])


@router.get("/version-logs", response_model=VersionLogListResponse)
def get_version_logs_route(project_id: Optional[str] = Query(default=None)) -> VersionLogListResponse:
    items = get_version_logs(project_id)
    return VersionLogListResponse(items=[VersionLogResponse.model_validate(item, from_attributes=True) for item in items])
