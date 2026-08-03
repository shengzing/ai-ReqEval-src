"""autoResearch routers."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, status
from fastapi import Query

from src.apps.api.app.api.v1.schemas.autoresearch import (
    ABCompareRequest,
    AutoResearchCandidateListResponse,
    AutoResearchCandidateResponse,
    AutoResearchConfirmResponse,
    AutoResearchRecordListResponse,
    AutoResearchRecordResponse,
    CapabilityMutabilityContractResponse,
    ConfirmAutoResearchRequest,
    CreateAutoResearchRequest,
    CreateManualAutoResearchRequest,
    FrozenEvalContractResponse,
    RejectedCandidateListResponse,
    RejectedCandidateResponse,
    RuleProposalDecisionRequest,
    RuleProposalListResponse,
    RuleProposalResponse,
    SkillRunComparisonListResponse,
    SkillRunComparisonResponse,
)
from src.apps.api.app.api.v1.schemas.projects import StageResultResponse
from src.apps.api.app.services.autoresearch_service import (
    accept_rule_proposal,
    compare_skill_runs,
    create_autoresearch_record,
    create_manual_autoresearch_record,
    confirm_autoresearch_record,
    list_autoresearch_records,
    reject_rule_proposal,
    run_skill_ab_comparison,
    seed_capability_mutability_contract,
    seed_frozen_eval_contract,
)

router = APIRouter()


@router.get("/autoresearch", response_model=AutoResearchRecordListResponse)
def get_autoresearch_records(stage_id: Optional[str] = Query(default=None)) -> AutoResearchRecordListResponse:
    items = list_autoresearch_records(stage_id)
    return AutoResearchRecordListResponse(
        items=[AutoResearchRecordResponse.model_validate(item, from_attributes=True) for item in items]
    )


@router.post("/autoresearch/run", response_model=AutoResearchRecordResponse, status_code=status.HTTP_201_CREATED)
def post_autoresearch_run(request: CreateAutoResearchRequest) -> AutoResearchRecordResponse:
    record = create_autoresearch_record(stage_id=request.stage_id, run_id=request.run_id)
    return AutoResearchRecordResponse.model_validate(record, from_attributes=True)


@router.post("/autoresearch/manual", response_model=AutoResearchRecordResponse, status_code=status.HTTP_201_CREATED)
def post_manual_autoresearch(request: CreateManualAutoResearchRequest) -> AutoResearchRecordResponse:
    record = create_manual_autoresearch_record(
        stage_id=request.stage_id,
        title=request.title,
        description=request.description,
        action=request.action,
        impact=request.impact,
        risk=request.risk,
        source=request.source,
        run_id=request.run_id,
        context=request.context,
    )
    return AutoResearchRecordResponse.model_validate(record, from_attributes=True)


@router.post("/autoresearch/{record_id}/confirm", response_model=AutoResearchConfirmResponse)
def post_autoresearch_confirm(record_id: str, request: ConfirmAutoResearchRequest) -> AutoResearchConfirmResponse:
    record, stage_result = confirm_autoresearch_record(
        record_id=record_id,
        decision=request.decision,
        note=request.note,
        edited_description=request.edited_description,
    )
    return AutoResearchConfirmResponse(
        record=AutoResearchRecordResponse.model_validate(record, from_attributes=True),
        stage_result=StageResultResponse.model_validate(stage_result, from_attributes=True) if stage_result is not None else None,
    )


# ── Candidate / Rejected / Frozen Contract endpoints ──


@router.get("/autoresearch/candidates", response_model=AutoResearchCandidateListResponse)
def get_autoresearch_candidates(
    stage_id: str = Query(..., description="Stage ID to filter candidates"),
    run_id: Optional[str] = Query(default=None, description="Optional run ID filter"),
) -> AutoResearchCandidateListResponse:
    from src.apps.api.app.repositories.store import list_autoresearch_candidates
    items = list_autoresearch_candidates(stage_id=stage_id, run_id=run_id)
    return AutoResearchCandidateListResponse(
        items=[AutoResearchCandidateResponse.model_validate(item, from_attributes=True) for item in items]
    )


@router.get("/autoresearch/rejected", response_model=RejectedCandidateListResponse)
def get_rejected_candidates(
    stage_id: str = Query(..., description="Stage ID to filter rejected candidates"),
) -> RejectedCandidateListResponse:
    from src.apps.api.app.repositories.store import list_rejected_candidates
    items = list_rejected_candidates(stage_id=stage_id)
    return RejectedCandidateListResponse(
        items=[RejectedCandidateResponse.model_validate(item, from_attributes=True) for item in items]
    )


@router.get("/autoresearch/frozen-contract", response_model=FrozenEvalContractResponse)
def get_frozen_eval_contract(
    stage_id: str = Query(..., description="Stage ID to get/seed frozen eval contract"),
) -> FrozenEvalContractResponse:
    from src.apps.api.app.repositories.store import get_latest_frozen_eval_contract
    contract = get_latest_frozen_eval_contract(stage_id)
    if contract is None:
        # Auto-seed on first access
        contract = seed_frozen_eval_contract(stage_id=stage_id)
    return FrozenEvalContractResponse.model_validate(contract, from_attributes=True)


# ── L2: Rule proposal & capability mutability contract ────────────────────


@router.get("/autoresearch/rule-proposals", response_model=RuleProposalListResponse)
def list_rule_proposals_endpoint(
    stage_id: str = Query(...),
    status_filter: Optional[str] = Query(None, alias="status"),
) -> RuleProposalListResponse:
    from src.apps.api.app.repositories.store import list_rule_proposals

    # FastAPI's Query default is a sentinel Query object, not None.
    # Pass status only when caller actually supplied it.
    items = list_rule_proposals(
        stage_id=stage_id,
        status=status_filter if isinstance(status_filter, str) else None,
    )
    return RuleProposalListResponse(
        items=[RuleProposalResponse.model_validate(item, from_attributes=True) for item in items]
    )


@router.post(
    "/autoresearch/rule-proposals/{proposal_id}/accept",
    response_model=RuleProposalResponse,
)
def accept_rule_proposal_endpoint(
    proposal_id: str,
    payload: RuleProposalDecisionRequest = RuleProposalDecisionRequest(),
) -> RuleProposalResponse:
    proposal = accept_rule_proposal(proposal_id, reviewer=payload.reviewer)
    return RuleProposalResponse.model_validate(proposal, from_attributes=True)


@router.post(
    "/autoresearch/rule-proposals/{proposal_id}/reject",
    response_model=RuleProposalResponse,
)
def reject_rule_proposal_endpoint(
    proposal_id: str,
    payload: RuleProposalDecisionRequest = RuleProposalDecisionRequest(),
) -> RuleProposalResponse:
    proposal = reject_rule_proposal(
        proposal_id,
        reviewer=payload.reviewer,
        rationale=payload.rationale,
    )
    return RuleProposalResponse.model_validate(proposal, from_attributes=True)


@router.get(
    "/autoresearch/capability-contract",
    response_model=CapabilityMutabilityContractResponse,
)
def get_capability_mutability_contract_endpoint(
    stage_id: str = Query(...),
) -> CapabilityMutabilityContractResponse:
    from src.apps.api.app.repositories.store import get_latest_capability_mutability_contract
    contract = get_latest_capability_mutability_contract(stage_id)
    if contract is None:
        contract = seed_capability_mutability_contract(stage_id=stage_id)
    return CapabilityMutabilityContractResponse.model_validate(contract, from_attributes=True)


# ── L4: Skill run A/B comparison ──────────────────────────────────────────


@router.post(
    "/skills/{skill_name}/ab-compare",
    response_model=SkillRunComparisonResponse,
)
def ab_compare_endpoint(
    skill_name: str,
    payload: ABCompareRequest,
) -> SkillRunComparisonResponse:
    comparison = run_skill_ab_comparison(
        project_id=payload.project_id,
        stage_id=payload.stage_id,
        skill_name=skill_name,
        version_v1=payload.version_v1,
        version_v2=payload.version_v2,
        input_payload=payload.input_payload,
    )
    return SkillRunComparisonResponse.model_validate(comparison, from_attributes=True)


@router.get(
    "/autoresearch/skill-comparisons",
    response_model=SkillRunComparisonListResponse,
)
def list_skill_comparisons_endpoint(
    stage_id: Optional[str] = Query(None),
    skill_name: Optional[str] = Query(None),
) -> SkillRunComparisonListResponse:
    from src.apps.api.app.repositories.store import list_skill_run_comparisons

    items = list_skill_run_comparisons(stage_id=stage_id, skill_name=skill_name)
    return SkillRunComparisonListResponse(
        items=[SkillRunComparisonResponse.model_validate(item, from_attributes=True) for item in items]
    )
