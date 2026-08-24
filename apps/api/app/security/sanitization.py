"""Small, conservative sanitizers for logs and generated text artifacts."""

from __future__ import annotations

import re
from typing import Any


_INTERNAL_IP_PATTERN = re.compile(
    r"\b(?:10\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])|192\.168\.\d{1,3})\.\d{1,3}\b"
)


_SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("mongodb_uri", re.compile(r"mongodb(?:\+srv)?://[^\s\"']+", re.IGNORECASE)),
    ("bearer_token", re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/-]{12,}")),
    ("openai_key", re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b")),
    (
        "credential_assignment",
        re.compile(
            r"(?im)((?:[\"']?(?:api[_-]?key|apikey|access[_-]?token|accesstoken|agent[_-]?auth[_-]?token|secret|password)[\"']?)\s*[:=]\s*)(?:\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|[^\s,}\]]+)"
        ),
    ),
    # Detect bare RFC1918 internal IPs. Generic audit sanitization reports them
    # without rewriting; document analysis uses the stricter helper below.
    ("internal_ip", _INTERNAL_IP_PATTERN),
)
_SENSITIVE_KEY_PATTERN = re.compile(
    r"^(?:api[_-]?key|apikey|access[_-]?token|accesstoken|agent[_-]?auth[_-]?token|authorization|secret|password)$",
    re.IGNORECASE,
)


def redact_secrets(value: str) -> tuple[str, list[str]]:
    """Return display-safe text and non-sensitive finding categories."""
    redacted = value or ""
    findings: list[str] = []
    for name, pattern in _SECRET_PATTERNS:
        if not pattern.search(redacted):
            continue
        findings.append(name)
        if name == "bearer_token":
            redacted = pattern.sub(r"\1[REDACTED]", redacted)
        elif name == "credential_assignment":
            redacted = pattern.sub(r"\1[REDACTED]", redacted)
        elif name == "internal_ip":
            # Report only — IPs are often legitimate configuration values;
            # redacting them destroys readability. Quarantine decides blocking.
            pass
        else:
            redacted = pattern.sub("[REDACTED]", redacted)
    return redacted, list(dict.fromkeys(findings))


def redact_document_for_analysis(value: str) -> tuple[str, list[str]]:
    """Return a document copy safe for summaries, evidence, and Run context.

    The generic sanitizer keeps RFC1918 addresses readable for operator logs,
    but document analysis is a broader trust boundary: internal topology must
    not be copied into generated artifacts. Credential values and internal IPs
    are therefore both masked in this analysis-only copy. The original upload
    remains unchanged for authorized preview and audit.
    """
    redacted, findings = redact_secrets(value)
    if "internal_ip" in findings:
        redacted = _INTERNAL_IP_PATTERN.sub("[REDACTED_INTERNAL_IP]", redacted)
    return redacted, findings


def redact_value(value: Any) -> Any:
    """Recursively redact strings before durable audit/event persistence."""
    if isinstance(value, str):
        return redact_secrets(value)[0]
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_value(item) for item in value)
    if isinstance(value, dict):
        return {
            str(key): "[REDACTED]" if _SENSITIVE_KEY_PATTERN.fullmatch(str(key)) else redact_value(item)
            for key, item in value.items()
        }
    return value
