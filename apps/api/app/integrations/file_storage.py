"""Local filesystem storage for project artifacts."""

from __future__ import annotations

from pathlib import Path
from typing import Optional
import json
import base64

from src.apps.api.app.core.config import get_settings


class LocalFileStorage:
    def __init__(self) -> None:
        self._settings = get_settings()

    def ensure_project_layout(self, project_id: str) -> None:
        for path in self.project_input_dir(project_id), self.project_parsed_dir(project_id), self.project_samples_dir(project_id), self.project_evidence_dir(project_id), self.project_run_output_dir(project_id), self.project_report_output_dir(project_id), self.project_export_output_dir(project_id):
            path.mkdir(parents=True, exist_ok=True)

    def project_root(self, project_id: str) -> Path:
        return self._settings.data_root / project_id

    def project_input_dir(self, project_id: str) -> Path:
        return self.project_root(project_id) / "inputs"

    def project_parsed_dir(self, project_id: str) -> Path:
        return self.project_root(project_id) / "parsed"

    def project_samples_dir(self, project_id: str) -> Path:
        return self.project_root(project_id) / "samples"

    def project_evidence_dir(self, project_id: str) -> Path:
        return self.project_root(project_id) / "evidence"

    def project_output_root(self, project_id: str) -> Path:
        return self._settings.output_root / project_id

    def project_run_output_dir(self, project_id: str) -> Path:
        return self.project_output_root(project_id) / "runs"

    def project_report_output_dir(self, project_id: str) -> Path:
        return self.project_output_root(project_id) / "reports"

    def project_export_output_dir(self, project_id: str) -> Path:
        return self.project_output_root(project_id) / "exports"

    def save_input_file(
        self,
        project_id: str,
        file_id: str,
        filename: str,
        content: Optional[str],
        content_base64: Optional[str] = None,
    ) -> Path:
        self.ensure_project_layout(project_id)
        path = self.project_input_dir(project_id) / f"{file_id}-{filename}"
        if content_base64:
            path.write_bytes(base64.b64decode(content_base64))
        else:
            path.write_text(content or "", encoding="utf-8")
        return path

    def save_evidence_attachment(self, project_id: str, evidence_id: str, filename: str, content: str) -> Path:
        self.ensure_project_layout(project_id)
        path = self.project_evidence_dir(project_id) / f"{evidence_id}-{filename}.txt"
        path.write_text(content, encoding="utf-8")
        return path

    def save_parsed_summary(self, project_id: str, file_id: str, filename: str, summary: str) -> Path:
        self.ensure_project_layout(project_id)
        path = self.project_parsed_dir(project_id) / f"{file_id}-{filename}.summary.txt"
        path.write_text(summary, encoding="utf-8")
        return path

    def save_report_stub(self, project_id: str, report_id: str, title: str) -> Path:
        self.ensure_project_layout(project_id)
        path = self.project_report_output_dir(project_id) / f"{report_id}.md"
        path.write_text(f"# {title}\n\nMVP report draft.\n", encoding="utf-8")
        return path

    def save_decision_card(self, project_id: str, report_id: str, title: str, recommendation: str) -> Path:
        self.ensure_project_layout(project_id)
        path = self.project_report_output_dir(project_id) / f"{report_id}.decision.md"
        path.write_text(f"# 决策卡：{title}\n\n- 建议：{recommendation}\n", encoding="utf-8")
        return path

    def save_evidence_directory(self, project_id: str, report_id: str, evidence_names: list[str]) -> Path:
        self.ensure_project_layout(project_id)
        path = self.project_report_output_dir(project_id) / f"{report_id}.evidence.md"
        lines = ["# 证据目录", ""]
        lines.extend(f"- {name}" for name in evidence_names)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    def save_export_bundle(self, project_id: str, report_id: str, payload: dict) -> Path:
        self.ensure_project_layout(project_id)
        path = self.project_export_output_dir(project_id) / f"{report_id}.bundle.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def save_vision_parse_result(self, project_id: str, file_id: str, payload: dict) -> Path:
        self.ensure_project_layout(project_id)
        path = self.project_parsed_dir(project_id) / f"{file_id}.vision.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path
