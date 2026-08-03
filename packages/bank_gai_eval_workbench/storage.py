from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class JsonStore:
    def __init__(self, base_dir: str | Path) -> None:
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def project_dir(self, project_id: str) -> Path:
        path = self.base_dir / project_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def write(self, project_id: str, name: str, payload: dict[str, Any]) -> Path:
        path = self.project_dir(project_id) / f"{name}.json"
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return path

    def read(self, project_id: str, name: str) -> dict[str, Any]:
        path = self.project_dir(project_id) / f"{name}.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def read_or_none(self, project_id: str, name: str) -> dict[str, Any] | None:
        path = self.project_dir(project_id) / f"{name}.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def exists(self, project_id: str, name: str) -> bool:
        return (self.project_dir(project_id) / f"{name}.json").exists()

    def list_projects(self) -> list[str]:
        if not self.base_dir.exists():
            return []
        return sorted(path.name for path in self.base_dir.iterdir() if path.is_dir())

    def list_project_files(self, project_id: str) -> list[str]:
        project_dir = self.project_dir(project_id)
        return sorted(path.name for path in project_dir.glob("*.json"))

    def append_jsonl(self, name: str, payload: dict[str, Any]) -> Path:
        path = self.base_dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
        return path

    def append_project_jsonl(self, project_id: str, name: str, payload: dict[str, Any]) -> Path:
        path = self.project_dir(project_id) / name
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
        return path
