from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from .collector import DataCollector
from .models import (
    ExecutionLogEntry,
    ProbeRecord,
    ProjectMeta,
    ScenarioRecord,
    ValueRecord,
    VersionLogEntry,
    utc_now_iso,
)
from .processor import DataProcessor
from .qa import QASupport
from .reporter import ReportBuilder
from .sample_data import build_demo_project
from .versioning import VersionRecorder


DEFAULT_BASE_DIR = Path("outputs/bank_gai_eval_workbench")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Bank GAI evaluation workbench MVP CLI")
    parser.add_argument("--base-dir", default=str(DEFAULT_BASE_DIR))
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init-demo", help="Create a demo project and sample records")

    process = subparsers.add_parser("process", help="Process one project")
    process.add_argument("project_id")

    ask = subparsers.add_parser("ask", help="Answer one question for one project")
    ask.add_argument("project_id")
    ask.add_argument("question")

    status = subparsers.add_parser("status", help="Show current files and processing status")
    status.add_argument("project_id")

    export = subparsers.add_parser("export-report", help="Export markdown report for one project")
    export.add_argument("project_id")
    export.add_argument("--output")

    subparsers.add_parser("list-projects", help="List local projects")

    collect = subparsers.add_parser("collect", help="Create project files from one JSON payload")
    collect.add_argument("payload_path")

    return parser


def _record(
    base_dir: str,
    role: str,
    task: str,
    notes: str,
    model: str = "gpt-5",
    project_id: str | None = None,
    input_refs: list[str] | None = None,
    output_refs: list[str] | None = None,
) -> None:
    recorder = VersionRecorder(base_dir)
    version_entry = VersionLogEntry(
        timestamp=utc_now_iso(),
        model=model,
        role=role,
        task=task,
        notes=notes,
    )
    recorder.record(version_entry)
    if project_id:
        recorder.record_project_version(project_id, version_entry)
        recorder.record_execution(
            project_id,
            ExecutionLogEntry(
                timestamp=utc_now_iso(),
                actor_type="model",
                actor_name=model,
                action=task,
                project_id=project_id,
                input_refs=input_refs or [],
                output_refs=output_refs or [],
                note=notes,
            ),
        )

def _collect_from_payload(base_dir: str, payload_path: str) -> dict:
    payload = json.loads(Path(payload_path).read_text(encoding="utf-8"))
    collector = DataCollector(base_dir)
    meta = ProjectMeta(**payload["project_meta"])
    scenario = ScenarioRecord(**payload["scenario_record"])
    value = ValueRecord(**payload["value_record"])
    probe = ProbeRecord(
        atomic_tasks=payload["probe_record"]["atomic_tasks"],
        rubric=payload["probe_record"]["rubric"],
        samples=[],
    )
    for item in payload["probe_record"]["samples"]:
        from .models import ProbeSample

        probe.samples.append(ProbeSample(**item))

    collector.create_project(meta)
    collector.save_scenario(meta.project_id, scenario)
    collector.save_value(meta.project_id, value)
    collector.save_probe(meta.project_id, probe)
    _record(
        base_dir,
        "collector",
        "collect",
        f"collected project={meta.project_id}",
        project_id=meta.project_id,
        output_refs=[
            "project_meta.json",
            "scenario_record.json",
            "value_record.json",
            "probe_record.json",
        ],
    )
    return {"project_id": meta.project_id, "status": "collected"}


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    base_dir = args.base_dir

    if args.command == "init-demo":
        collector = DataCollector(base_dir)
        meta, scenario, value, probe = build_demo_project()
        collector.create_project(meta)
        collector.save_scenario(meta.project_id, scenario)
        collector.save_value(meta.project_id, value)
        collector.save_probe(meta.project_id, probe)
        _record(
            base_dir,
            "collector",
            "init-demo",
            f"initialized demo project={meta.project_id}",
            project_id=meta.project_id,
            output_refs=[
                "project_meta.json",
                "scenario_record.json",
                "value_record.json",
                "probe_record.json",
            ],
        )
        print(json.dumps({"project_id": meta.project_id, "status": "initialized"}, ensure_ascii=False))
        return 0

    if args.command == "collect":
        print(json.dumps(_collect_from_payload(base_dir, args.payload_path), ensure_ascii=False))
        return 0

    if args.command == "process":
        processor = DataProcessor(base_dir)
        result = processor.process_project(args.project_id)
        _record(
            base_dir,
            "processor",
            "process",
            f"processed project={args.project_id}",
            project_id=args.project_id,
            input_refs=[
                "scenario_record.json",
                "value_record.json",
                "probe_record.json",
            ],
            output_refs=[
                "stage_1_result.json",
                "stage_2_result.json",
                "stage_3_result.json",
                "stage_4_result.json",
                "processing_result.json",
            ],
        )
        print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
        return 0

    if args.command == "ask":
        answer = QASupport(base_dir).answer(args.project_id, args.question)
        _record(
            base_dir,
            "qa",
            "ask",
            f"asked project={args.project_id}; question={args.question}",
            project_id=args.project_id,
            input_refs=["processing_result.json"],
        )
        print(answer)
        return 0

    if args.command == "status":
        from .storage import JsonStore

        store = JsonStore(base_dir)
        payload = {
            "project_id": args.project_id,
            "files": store.list_project_files(args.project_id),
            "has_result": store.exists(args.project_id, "processing_result"),
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if args.command == "export-report":
        path = ReportBuilder(base_dir).export(args.project_id, args.output)
        _record(
            base_dir,
            "reporter",
            "export-report",
            f"exported report for project={args.project_id}",
            project_id=args.project_id,
            input_refs=["processing_result.json"],
            output_refs=["report.md"],
        )
        print(json.dumps({"project_id": args.project_id, "report_path": str(path)}, ensure_ascii=False, indent=2))
        return 0

    if args.command == "list-projects":
        from .storage import JsonStore

        store = JsonStore(base_dir)
        print(json.dumps({"projects": store.list_projects()}, ensure_ascii=False, indent=2))
        return 0

    parser.print_help()
    return 1
