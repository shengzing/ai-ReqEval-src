from __future__ import annotations

from pathlib import Path

from .storage import JsonStore


class ReportBuilder:
    def __init__(self, base_dir: str | Path) -> None:
        self.store = JsonStore(base_dir)

    def build(self, project_id: str) -> str:
        project = self.store.read(project_id, "project_meta")
        scenario = self.store.read(project_id, "scenario_record")
        value = self.store.read(project_id, "value_record")
        result = self.store.read(project_id, "processing_result")
        stage_3 = self.store.read_or_none(project_id, "stage_3_result") or {}

        lines = [
            f"# {project['name']} 评估底稿",
            "",
            "## 项目概览",
            f"- 项目ID：`{project['project_id']}`",
            f"- 项目说明：{project['description']}",
            f"- 标签：{', '.join(project.get('tags', [])) or '无'}",
            "",
            "## 阶段1 场景与风险",
            f"- 场景名称：{scenario['scenario_name']}",
            f"- 场景类型：{scenario['scenario_type']}",
            f"- 风险等级：{scenario['risk_level']}",
            f"- HITL：{scenario['hitl_level']}",
            f"- 审计要求：{', '.join(scenario['audit_requirements'])}",
            "",
            "## 阶段2 价值与门槛",
            f"- 实施税合计：{result['implementation_tax_total']:.2f}",
            f"- 净价值：{result['net_value']:.2f}",
            f"- 目标SLA：{result['target_sla']:.4f}",
            f"- 利益相关方：{', '.join(value['stakeholders'])}",
            "",
            "## 阶段3 测试与能力",
            f"- Actual SLA：{result['actual_sla']:.4f}",
            f"- 质量得分：{result['quality_score']:.4f}",
            f"- 治理得分：{result['governance_score']:.4f}",
            f"- 效率得分：{result['efficiency_score']:.4f}",
            f"- 任务通过率：{stage_3.get('task_pass_rates', {})}",
            "",
            "## 阶段4 综合判定",
            f"- 建议：{result['decision']['recommendation']}",
            f"- 原因：{result['decision']['reason']}",
            "",
            "## 证据文件",
        ]
        for file_name in self.store.list_project_files(project_id):
            lines.append(f"- {file_name}")
        return "\n".join(lines) + "\n"

    def export(self, project_id: str, output_path: str | Path | None = None) -> Path:
        project_dir = self.store.project_dir(project_id)
        path = Path(output_path) if output_path else project_dir / "report.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.build(project_id), encoding="utf-8")
        return path
