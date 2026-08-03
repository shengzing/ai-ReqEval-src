"""Semantic risk-artifact extractor — LLM-augmented risk item / fatal error /
evidence-binding / scenario-type extraction.

When the LLM client is configured, sends (RiskBrief, evidence_snippets) to the
LLM for semantic extraction. When unconfigured (or on LLM error), falls back to
the deterministic regex/keyword logic used by the pre-upgrade ``registry.py`` —
so ``_NoLLM()`` runs produce field-for-field identical output.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from src.apps.api.app.agents.risk_semantic.extractor_prompts import (
    RISK_EXTRACTION_SYSTEM_PROMPT,
)
from src.apps.api.app.agents.risk_semantic.models import (
    RiskArtifactsReport,
    RiskBrief,
)

logger = logging.getLogger(__name__)

# Frozen fallback constants — lifted verbatim from the pre-upgrade
# ``agents/tools/registry.py`` so that the fallback path is byte-identical.
_FATAL_KEYWORDS: tuple[str, ...] = ("漏报风险", "误伤客户", "审计追责", "延误处置")

_SCENARIO_TYPE_KEYWORDS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("摘要", "生成", "草拟", "撰写", "文案"), "content_generation"),
    (("汇总", "提取", "识别", "分析", "问答"), "understanding_analysis"),
    (("预测", "预警", "预测性维护", "故障预测"), "predictive_analysis"),
)

# Re-exported so registry.py can import the shared fallback helper instead of
# keeping its own copy.
RISK_ITEM_LABEL_RE = re.compile(
    r"^(常见异常|出错最严重后果)[：:]\s*(.+)$", re.MULTILINE
)


def extract_risk_artifacts(
    brief: RiskBrief,
    evidence_snippets: dict[str, str],
    *,
    llm_client: Any = None,
    risk_level: str = "L1",
    primary_evidence_id: str = "ev-unknown",
) -> RiskArtifactsReport:
    """Extract risk items / fatal errors / evidence bindings / scenario_type.

    Args:
        brief: RiskBrief carrying combined_text + known_risk_points +
            prohibited_conditions.
        evidence_snippets: Mapping evidence_id -> snippet text.
        llm_client: Optional HarnessLLMClient. When None or unconfigured,
            deterministic fallback is used.
        risk_level: Resolved risk_level (used to set risk_item.risk_level and
            severity in both LLM normalization and fallback).
        primary_evidence_id: Fallback evidence id when no semantic binding
            matches.

    Returns:
        RiskArtifactsReport with source="llm" or source="fallback".
    """
    llm_result = _try_llm_extract(
        brief,
        evidence_snippets=evidence_snippets,
        llm_client=llm_client,
        risk_level=risk_level,
    )
    if llm_result is not None:
        return llm_result

    return _fallback_extract(
        brief,
        evidence_snippets=evidence_snippets,
        risk_level=risk_level,
        primary_evidence_id=primary_evidence_id,
    )


# ── LLM path ───────────────────────────────────────────────────────────────


def _try_llm_extract(
    brief: RiskBrief,
    *,
    evidence_snippets: dict[str, str],
    llm_client: Any = None,
    risk_level: str = "L1",
) -> RiskArtifactsReport | None:
    """Attempt LLM-based extraction. Returns None on failure (→ fallback)."""
    if llm_client is None:
        return None

    # Truncate snippets to keep the payload bounded.
    evidence_summary = {
        ev_id: (snippet[:500] if isinstance(snippet, str) else "")
        for ev_id, snippet in evidence_snippets.items()
    }

    user_payload = {
        "scenario_name": brief.scenario_name,
        "combined_text": brief.combined_text[:3000],
        "known_risk_points": brief.known_risk_points,
        "prohibited_conditions": brief.prohibited_conditions,
        "evidence_keys": list(evidence_snippets.keys()),
        "evidence_snippets": evidence_summary,
        "resolved_risk_level": risk_level,
    }

    try:
        response = llm_client.complete_json(
            system_prompt=RISK_EXTRACTION_SYSTEM_PROMPT,
            user_payload=user_payload,
        )
    except Exception:
        logger.warning("LLM risk-artifact extraction failed, using fallback", exc_info=True)
        return None

    if not response:
        return None

    return _normalize_llm_output(
        response,
        evidence_keys=list(evidence_snippets.keys()),
        risk_level=risk_level,
        combined_text=brief.combined_text,
    )


def _normalize_llm_output(
    response: dict[str, Any],
    *,
    evidence_keys: list[str],
    risk_level: str = "L1",
    combined_text: str = "",
) -> RiskArtifactsReport | None:
    """Normalize LLM JSON response into a RiskArtifactsReport.

    Returns None if the output cannot be normalized — caller falls back.
    """
    from src.apps.api.app.services.stage1_contract import normalize_risk_level

    evidence_set = set(evidence_keys)
    valid_evidence_keys = evidence_keys  # preserve order

    # ── risk_items ──────────────────────────────────────────────────────
    raw_items = response.get("risk_items", [])
    if not isinstance(raw_items, list):
        raw_items = []

    risk_items: list[dict[str, Any]] = []
    used_risk_ids: set[str] = set()
    for idx, raw in enumerate(raw_items, start=1):
        if not isinstance(raw, dict):
            continue
        description = str(raw.get("description", "")).strip()
        if not description:
            continue  # skip empty / fabricated items
        raw_level = raw.get("risk_level", risk_level)
        try:
            item_level = normalize_risk_level(raw_level)
        except (ValueError, TypeError):
            item_level = risk_level  # keep resolved level rather than dropping

        risk_id = str(raw.get("risk_id", "")).strip() or f"risk-{idx}"
        # ensure uniqueness
        if risk_id in used_risk_ids or not risk_id.startswith("risk-"):
            risk_id = f"risk-{idx}"
        used_risk_ids.add(risk_id)

        severity = str(raw.get("severity", "medium")).strip().lower()
        if severity not in {"low", "medium", "high"}:
            severity = "high" if item_level == "L3" else "medium"
        likelihood = str(raw.get("likelihood", "medium")).strip().lower()
        if likelihood not in {"low", "medium", "high"}:
            likelihood = "medium"

        risk_items.append({
            "risk_id": risk_id,
            "node_id": "",
            "description": description,
            "severity": severity,
            "likelihood": likelihood,
            "impact": str(raw.get("impact", "")),
            "owner_role": "",
            "mitigation": "",
            "audit_need": "",
            "risk_level": item_level,
            "evidence_refs": [],  # filled from evidence_bindings below
        })

    # ── fatal_errors ────────────────────────────────────────────────────
    raw_fatal = response.get("fatal_errors", [])
    if not isinstance(raw_fatal, list):
        raw_fatal = []
    fatal_errors: list[dict[str, Any]] = []
    for raw in raw_fatal:
        if not isinstance(raw, dict):
            continue
        error = str(raw.get("error", "")).strip()
        if not error:
            continue
        fatal_errors.append({
            "error": error,
            "impact": str(raw.get("impact", f"{error}将导致严重后果")),
            "evidence_refs": [],
        })

    # ── evidence_bindings ───────────────────────────────────────────────
    raw_bindings = response.get("evidence_bindings", {})
    if not isinstance(raw_bindings, dict):
        raw_bindings = {}
    evidence_bindings: dict[str, list[str]] = {}
    for rid, ev_list in raw_bindings.items():
        if not isinstance(ev_list, list):
            continue
        clean = [
            str(ev) for ev in ev_list
            if isinstance(ev, str) and ev in evidence_set
        ]
        # de-duplicate while preserving order
        seen: set[str] = set()
        deduped = [e for e in clean if not (e in seen or seen.add(e))]
        if deduped:
            evidence_bindings[str(rid)] = deduped

    # attach evidence_refs back onto risk_items (caller also reads the map)
    bindings_map = {rid: list(evs) for rid, evs in evidence_bindings.items()}
    for item in risk_items:
        rid = item.get("risk_id", "")
        item["evidence_refs"] = list(bindings_map.get(rid, []))

    # ── scenario_type ───────────────────────────────────────────────────
    scenario_type = _normalize_scenario_type(
        response.get("scenario_type", ""), combined_text
    )

    reasoning = str(response.get("reasoning", ""))

    return RiskArtifactsReport(
        risk_items=risk_items,
        fatal_errors=fatal_errors,
        evidence_bindings=evidence_bindings,
        scenario_type=scenario_type,
        reasoning=reasoning,
        source="llm",
    )


# ── Fallback path (field-for-field identical to pre-upgrade registry.py) ──


def _fallback_extract(
    brief: RiskBrief,
    *,
    evidence_snippets: dict[str, str],
    risk_level: str = "L1",
    primary_evidence_id: str = "ev-unknown",
) -> RiskArtifactsReport:
    """Deterministic fallback: regex `常见异常|出错最严重后果`, fatal_keywords,
    keyword-overlap evidence binding, keyword scenario_type inference.

    Mirrors the pre-upgrade ``registry.risk_identify_tool`` block at the
    old lines 657/776/103-125 and ``document_parse_tool`` scenario_type block
    at line 400 — so unconfigured-LLM runs are byte-identical.
    """
    from src.apps.api.app.agents.tools.registry import _find_best_evidence

    combined_text = brief.combined_text
    evidence_items = [
        {"id": ev_id, "snippet": snippet}
        for ev_id, snippet in evidence_snippets.items()
    ]

    risk_items: list[dict[str, Any]] = []
    risk_counter = 0
    for match in RISK_ITEM_LABEL_RE.finditer(combined_text):
        label_kind = match.group(1)
        body = match.group(2)
        for desc in _split_semicolon_list(body):
            risk_counter += 1
            best_ev = _find_best_evidence(desc, evidence_items, evidence_snippets)
            risk_id = f"risk-{risk_counter}"
            if label_kind == "出错最严重后果":
                risk_items.append({
                    "risk_id": risk_id,
                    "node_id": "",
                    "description": desc,
                    "severity": "high" if risk_level == "L3" else "medium",
                    "likelihood": "low",
                    "impact": desc,
                    "owner_role": "",
                    "mitigation": "",
                    "audit_need": "",
                    "risk_level": risk_level,
                    "evidence_refs": [best_ev],
                })
            else:
                risk_items.append({
                    "risk_id": risk_id,
                    "node_id": "",
                    "description": desc,
                    "severity": "medium",
                    "likelihood": "medium",
                    "impact": "",
                    "owner_role": "",
                    "mitigation": "",
                    "audit_need": "",
                    "risk_level": risk_level,
                    "evidence_refs": [best_ev],
                })

    # Ensure at least one risk item exists
    if not risk_items:
        risk_items.append({
            "risk_id": "risk-1",
            "node_id": "",
            "description": "通用风险识别",
            "severity": "low",
            "likelihood": "low",
            "impact": "",
            "owner_role": "",
            "mitigation": "",
            "audit_need": "",
            "risk_level": risk_level,
            "evidence_refs": [primary_evidence_id] if primary_evidence_id != "ev-unknown" else [],
        })

    # evidence_bindings map mirrors the per-item evidence_refs above
    evidence_bindings = {
        item["risk_id"]: list(item.get("evidence_refs", []))
        for item in risk_items
    }

    # fatal_errors — only when risk_level == L3, matching pre-upgrade behavior
    fatal_errors: list[dict[str, Any]] = []
    if risk_level == "L3":
        for kw in _FATAL_KEYWORDS:
            if kw in combined_text:
                best_ev = _find_best_evidence(kw, evidence_items, evidence_snippets)
                fatal_errors.append({
                    "error": kw,
                    "impact": f"{kw}将导致严重后果",
                    "evidence_refs": [best_ev],
                })

    scenario_type = _infer_scenario_type_fallback(combined_text)

    return RiskArtifactsReport(
        risk_items=risk_items,
        fatal_errors=fatal_errors,
        evidence_bindings=evidence_bindings,
        scenario_type=scenario_type,
        reasoning="fallback: 正则/关键词提取",
        source="fallback",
    )


# ── Shared helpers ─────────────────────────────────────────────────────────


_VALID_SCENARIO_TYPES = (
    "decision_support",
    "predictive_analysis",
    "understanding_analysis",
    "content_generation",
)


def _normalize_scenario_type(raw: str, combined_text: str) -> str:
    """Validate LLM-returned scenario_type; fall back to keyword inference
    when the LLM value is not one of the four canonical task types."""
    value = str(raw).strip().lower()
    if value in _VALID_SCENARIO_TYPES:
        return value
    return _infer_scenario_type_fallback(combined_text)


def _infer_scenario_type_fallback(combined_text: str) -> str:
    """Keyword-based scenario_type inference — identical to pre-upgrade
    ``document_parse_tool`` line 400 logic."""
    for keywords, scenario_type in _SCENARIO_TYPE_KEYWORDS:
        if any(kw in combined_text for kw in keywords):
            return scenario_type
    return "decision_support"


def _split_semicolon_list(text: str) -> list[str]:
    """Local copy of registry._split_semicolon_list to avoid a circular import
    when registry imports this module for the LLM path."""
    from src.apps.api.app.agents.tools.registry import _split_semicolon_list as _ssl
    return _ssl(text)
