from __future__ import annotations

from pathlib import Path

from .models import ExecutionLogEntry, VersionLogEntry, to_dict
from .storage import JsonStore


class VersionRecorder:
    def __init__(self, base_dir: str | Path) -> None:
        self.store = JsonStore(base_dir)

    def record(self, entry: VersionLogEntry) -> Path:
        return self.store.append_jsonl("version_log.jsonl", to_dict(entry))

    def record_project_version(self, project_id: str, entry: VersionLogEntry) -> Path:
        return self.store.append_project_jsonl(project_id, "version_log.jsonl", to_dict(entry))

    def record_execution(self, project_id: str, entry: ExecutionLogEntry) -> Path:
        return self.store.append_project_jsonl(project_id, "execution_log.jsonl", to_dict(entry))
