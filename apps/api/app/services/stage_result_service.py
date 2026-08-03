"""Stage result diff helpers."""

from __future__ import annotations

from typing import Optional

from src.apps.api.app.domain.models import StageResult


def build_stage_result_diff(
    current: StageResult,
    base: Optional[StageResult],
    *,
    trigger: str,
) -> dict:
    if base is None:
        return {
            "trigger": trigger,
            "base_version_id": None,
            "current_version_id": current.version_id,
            "field_changes": sorted(current.result_payload.keys()),
            "evidence_added": list(current.evidence_item_ids),
            "confirmation_added": list(current.confirmation_ids),
            "autoresearch_added": list(current.autoresearch_record_ids),
        }

    changed_fields = sorted(
        key
        for key in set(base.result_payload.keys()) | set(current.result_payload.keys())
        if base.result_payload.get(key) != current.result_payload.get(key)
    )
    return {
        "trigger": trigger,
        "base_version_id": base.version_id,
        "current_version_id": current.version_id,
        "field_changes": changed_fields,
        "evidence_added": sorted(set(current.evidence_item_ids) - set(base.evidence_item_ids)),
        "confirmation_added": sorted(set(current.confirmation_ids) - set(base.confirmation_ids)),
        "autoresearch_added": sorted(set(current.autoresearch_record_ids) - set(base.autoresearch_record_ids)),
    }
