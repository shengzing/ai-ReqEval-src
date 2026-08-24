"""Execution and version log services."""

from __future__ import annotations

from typing import Any, Optional
from uuid import uuid4

from src.apps.api.app.domain.models import ExecutionLog, VersionLog
from src.apps.api.app.security.sanitization import redact_value
from src.apps.api.app.repositories.store import (
    list_execution_logs as repo_list_execution_logs,
    list_version_logs as repo_list_version_logs,
    save_execution_log,
    save_version_log,
)


def create_execution_log(
    *,
    project_id: str,
    action: str,
    resource_type: str,
    resource_id: str,
    run_id: Optional[str] = None,
    details: Optional[dict[str, Any]] = None,
) -> ExecutionLog:
    log = ExecutionLog(
        id=f"elog-{uuid4().hex[:8]}",
        project_id=project_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        run_id=run_id,
        details=redact_value(details or {}),
    )
    save_execution_log(log)
    return log


def create_version_log(
    *,
    project_id: str,
    resource_type: str,
    resource_id: str,
    change_type: str,
    summary: str,
    run_id: Optional[str] = None,
    details: Optional[dict[str, Any]] = None,
) -> VersionLog:
    log = VersionLog(
        id=f"vlog-{uuid4().hex[:8]}",
        project_id=project_id,
        resource_type=resource_type,
        resource_id=resource_id,
        change_type=change_type,
        summary=summary,
        run_id=run_id,
        details=redact_value(details or {}),
    )
    save_version_log(log)
    return log


def list_execution_logs(project_id: Optional[str] = None) -> list[ExecutionLog]:
    return repo_list_execution_logs(project_id)


def list_version_logs(project_id: Optional[str] = None) -> list[VersionLog]:
    return repo_list_version_logs(project_id)
