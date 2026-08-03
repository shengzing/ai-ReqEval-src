from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from .models import ProjectMeta, ProbeRecord, ScenarioRecord, ValueRecord, to_dict, utc_now_iso
from .storage import JsonStore


class DataCollector:
    def __init__(self, base_dir: str | Path) -> None:
        self.store = JsonStore(base_dir)

    def create_project(self, meta: ProjectMeta) -> ProjectMeta:
        saved = replace(meta, updated_at=utc_now_iso())
        self.store.write(saved.project_id, "project_meta", to_dict(saved))
        return saved

    def save_scenario(self, project_id: str, record: ScenarioRecord) -> None:
        self.store.write(project_id, "scenario_record", to_dict(record))

    def save_value(self, project_id: str, record: ValueRecord) -> None:
        self.store.write(project_id, "value_record", to_dict(record))

    def save_probe(self, project_id: str, record: ProbeRecord) -> None:
        self.store.write(project_id, "probe_record", to_dict(record))
