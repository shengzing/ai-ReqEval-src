from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from .models import DecisionRecord, ProcessingResult
from .storage import JsonStore


class DataProcessor:
    def __init__(self, base_dir: str | Path) -> None:
        self.store = JsonStore(base_dir)

    def process_project(self, project_id: str) -> ProcessingResult:
        scenario = self.store.read(project_id, "scenario_record")
        value = self.store.read(project_id, "value_record")
        probe = self.store.read(project_id, "probe_record")

        stage_1_result = self._build_stage_1_result(scenario)
        implementation_tax_total = round(
            sum(float(item.get("cost", 0.0)) for item in value["implementation_tax_items"]),
            4,
        )
        net_value = round(
            float(value["expected_benefit"])
            - float(value["manual_baseline_cost"])
            - float(value["ai_operating_cost"])
            - implementation_tax_total,
            4,
        )

        quality_scores = [float(sample["score"]) for sample in probe["samples"]]
        passed_scores = [1.0 if sample["passed"] else 0.0 for sample in probe["samples"]]
        review_minutes = [float(sample["manual_review_minutes"]) for sample in probe["samples"]]
        governance_flags = [0.0 if sample["severity"] == "critical" else 1.0 for sample in probe["samples"]]

        quality_score = round(sum(quality_scores) / len(quality_scores), 4) if quality_scores else 0.0
        actual_sla = round(sum(passed_scores) / len(passed_scores), 4) if passed_scores else 0.0
        avg_review_minutes = round(sum(review_minutes) / len(review_minutes), 4) if review_minutes else 0.0
        efficiency_score = max(0.0, round(1.0 - avg_review_minutes / 60.0, 4))
        governance_score = round(sum(governance_flags) / len(governance_flags), 4) if governance_flags else 0.0

        target_sla = value.get("target_sla")
        if target_sla is None:
            target_sla = self._infer_target_sla(scenario["risk_level"], implementation_tax_total, net_value)
            value["target_sla"] = target_sla
            self.store.write(project_id, "value_record", value)
        target_sla = float(target_sla)
        stage_2_result = {
            "implementation_tax_total": implementation_tax_total,
            "net_value": net_value,
            "target_sla": target_sla,
            "expected_benefit": float(value["expected_benefit"]),
            "manual_baseline_cost": float(value["manual_baseline_cost"]),
            "ai_operating_cost": float(value["ai_operating_cost"]),
            "stakeholder_count": len(value.get("stakeholders", [])),
        }

        hard_constraints_passed = (
            governance_score >= self._governance_floor(scenario["risk_level"])
            and quality_score >= self._quality_floor(scenario["risk_level"])
        )
        recommendation = self._make_recommendation(
            hard_constraints_passed=hard_constraints_passed,
            target_sla=target_sla,
            actual_sla=actual_sla,
            net_value=net_value,
        )
        reason = self._build_reason(
            recommendation=recommendation,
            target_sla=target_sla,
            actual_sla=actual_sla,
            net_value=net_value,
            quality_score=quality_score,
            governance_score=governance_score,
        )
        failed_samples = [
            {
                "sample_id": sample["sample_id"],
                "task_name": sample["task_name"],
                "severity": sample["severity"],
                "score": float(sample["score"]),
            }
            for sample in probe["samples"]
            if not sample["passed"]
        ]
        task_pass_rates = self._build_task_pass_rates(probe["samples"])
        stage_3_result = {
            "actual_sla": actual_sla,
            "quality_score": quality_score,
            "efficiency_score": efficiency_score,
            "governance_score": governance_score,
            "sample_count": len(probe["samples"]),
            "average_review_minutes": avg_review_minutes,
            "task_pass_rates": task_pass_rates,
            "failed_samples": failed_samples,
        }

        decision = DecisionRecord(
            recommendation=recommendation,
            reason=reason,
            hard_constraints_passed=hard_constraints_passed,
            quality_score=quality_score,
            efficiency_score=efficiency_score,
            governance_score=governance_score,
            target_sla=target_sla,
            actual_sla=actual_sla,
        )
        stage_4_result = {
            "recommendation": recommendation,
            "reason": reason,
            "hard_constraints_passed": hard_constraints_passed,
            "target_sla": target_sla,
            "actual_sla": actual_sla,
            "gap": round(actual_sla - target_sla, 4),
        }
        result = ProcessingResult(
            implementation_tax_total=implementation_tax_total,
            net_value=net_value,
            target_sla=target_sla,
            actual_sla=actual_sla,
            quality_score=quality_score,
            efficiency_score=efficiency_score,
            governance_score=governance_score,
            decision=decision,
        )
        self.store.write(project_id, "stage_1_result", stage_1_result)
        self.store.write(project_id, "stage_2_result", stage_2_result)
        self.store.write(project_id, "stage_3_result", stage_3_result)
        self.store.write(project_id, "stage_4_result", stage_4_result)
        self.store.write(project_id, "processing_result", asdict(result))
        return result

    @staticmethod
    def _build_stage_1_result(scenario: dict) -> dict:
        return {
            "scenario_name": scenario["scenario_name"],
            "scenario_type": scenario["scenario_type"],
            "risk_level": scenario["risk_level"],
            "hitl_level": scenario["hitl_level"],
            "participants": scenario.get("participants", []),
            "responsibilities": scenario.get("responsibilities", []),
            "audit_requirements": scenario.get("audit_requirements", []),
        }

    @staticmethod
    def _build_task_pass_rates(samples: list[dict]) -> dict[str, float]:
        task_total: dict[str, int] = {}
        task_pass: dict[str, int] = {}
        for sample in samples:
            task_name = sample["task_name"]
            task_total[task_name] = task_total.get(task_name, 0) + 1
            if sample["passed"]:
                task_pass[task_name] = task_pass.get(task_name, 0) + 1
        return {
            task_name: round(task_pass.get(task_name, 0) / total, 4)
            for task_name, total in sorted(task_total.items())
        }

    @staticmethod
    def _infer_target_sla(risk_level: str, implementation_tax_total: float, net_value: float) -> float:
        base = {"L1": 0.85, "L2": 0.92, "L3": 0.97}.get(risk_level, 0.9)
        tax_penalty = min(0.03, implementation_tax_total / 1000000.0 * 0.01)
        value_bonus = 0.0 if net_value < 0 else 0.005
        return round(min(0.995, max(0.8, base + tax_penalty + value_bonus)), 4)

    @staticmethod
    def _quality_floor(risk_level: str) -> float:
        return {"L1": 0.75, "L2": 0.82, "L3": 0.9}.get(risk_level, 0.8)

    @staticmethod
    def _governance_floor(risk_level: str) -> float:
        return {"L1": 0.7, "L2": 0.85, "L3": 0.95}.get(risk_level, 0.8)

    @staticmethod
    def _make_recommendation(
        *,
        hard_constraints_passed: bool,
        target_sla: float,
        actual_sla: float,
        net_value: float,
    ) -> str:
        if not hard_constraints_passed or actual_sla < target_sla - 0.05 or net_value < -10000:
            return "不建议立项"
        if actual_sla < target_sla or net_value < 0:
            return "建议暂缓（补充论证）"
        return "建议立项"

    @staticmethod
    def _build_reason(
        *,
        recommendation: str,
        target_sla: float,
        actual_sla: float,
        net_value: float,
        quality_score: float,
        governance_score: float,
    ) -> str:
        return (
            f"建议={recommendation}；"
            f"target_sla={target_sla:.4f}；actual_sla={actual_sla:.4f}；"
            f"net_value={net_value:.2f}；quality={quality_score:.4f}；"
            f"governance={governance_score:.4f}"
        )
