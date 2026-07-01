"""Stage 9.1 — Cross-Project Execution Readiness Resolver."""

import datetime
import hashlib
import json
import os
from dataclasses import dataclass, field
from typing import Optional

import database
import cross_project_execution_intents as intents_mod
import multi_project_registry as registry_mod


PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
REPORTS_DIR = os.path.join(PROJECT_ROOT, "cross_project_execution_readiness_reports")


@dataclass
class ExecutionReadinessMarkdownReport:
    report_id: int
    report_path: str
    report_format: str
    content_hash: str
    bytes_written: int
    created_at: str


@dataclass
class CrossProjectExecutionReadinessReport:
    id: int
    intent_id: int
    generated_at: str
    overall_status: str
    summary: dict = field(default_factory=dict)
    project_results: list = field(default_factory=list)
    safety_notes: list = field(default_factory=list)


def _now_iso():
    return datetime.datetime.now().isoformat(timespec="seconds")


def _now_stamp():
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


def _safe_json_loads(blob, default):
    try:
        return json.loads(blob or "")
    except (TypeError, ValueError):
        return default


def is_report_path(path) -> bool:
    if not path:
        return False
    target = os.path.realpath(path)
    base = os.path.realpath(REPORTS_DIR)
    return target != base and target.startswith(base + os.sep)


def report_from_row(row) -> CrossProjectExecutionReadinessReport:
    return CrossProjectExecutionReadinessReport(
        id=row["id"], intent_id=row["intent_id"],
        generated_at=row["generated_at"] or "",
        overall_status=row["overall_status"] or "UNKNOWN",
        summary=_safe_json_loads(row["summary_json"], {}),
        project_results=_safe_json_loads(row["project_results_json"], []),
        safety_notes=_safe_json_loads(row["safety_notes_json"], []))


class CrossProjectExecutionReadinessResolver:
    def __init__(self, conn):
        self.conn = conn
        self.registry = registry_mod.ProjectRegistry(conn)
        self.intents = intents_mod.CrossProjectExecutionIntentRegistry(conn)

    def resolve(self, intent_id, persist=True) -> CrossProjectExecutionReadinessReport:
        intent = self.intents.get_intent(intent_id)
        if intent is None:
            raise ValueError(f"no cross-project execution intent {intent_id}")
        results = []
        latest_eval = database.list_governance_policy_evaluations(self.conn, limit=1)
        fail_subjects = set()
        if latest_eval:
            for finding in database.list_governance_policy_findings(
                    self.conn, latest_eval[0]["id"]):
                if finding["status"] == "FAIL":
                    fail_subjects.add(finding["subject"])
        for project in self.registry.list_projects():
            blockers = []
            warnings = []
            if project.status == "blocked":
                blockers.append("project status is blocked")
            elif project.status != "active":
                warnings.append(f"project status is {project.status}")
            if not project.root_path or not os.path.isdir(project.root_path):
                blockers.append("project root is missing")
            latest = database.latest_project_validation_report(
                self.conn, project.project_key)
            if latest and latest["overall_status"] in ("FAIL", "BLOCKED"):
                blockers.append(
                    f"latest validation status is {latest['overall_status']}")
            if project.project_key in fail_subjects:
                blockers.append("unresolved fail-level governance finding")
            status = "blocked" if blockers else "ready"
            results.append({
                "project_key": project.project_key,
                "status": status,
                "root_exists": bool(project.root_path)
                and os.path.isdir(project.root_path),
                "project_status": project.status,
                "latest_validation": latest["overall_status"] if latest else "(none)",
                "blockers": blockers,
                "warnings": warnings,
            })
        ready = sum(1 for r in results if r["status"] == "ready")
        blocked = sum(1 for r in results if r["status"] == "blocked")
        overall = "BLOCKED" if blocked else "READY"
        generated_at = _now_iso()
        report = CrossProjectExecutionReadinessReport(
            id=0, intent_id=intent.id, generated_at=generated_at,
            overall_status=overall,
            summary={
                "intent_id": intent.id,
                "total_projects": len(results),
                "ready_projects": ready,
                "blocked_projects": blocked,
            },
            project_results=results,
            safety_notes=[
                "Readiness reads registry, validation, and governance metadata only.",
                "No project file contents are read.",
                "No commands, model calls, loops, jobs, or project writes occur.",
            ])
        if persist:
            report.id = database.save_cross_project_execution_readiness_report(
                self.conn, report.intent_id, report.generated_at,
                report.overall_status, json.dumps(report.summary, sort_keys=True),
                json.dumps(report.project_results, sort_keys=True),
                json.dumps(report.safety_notes, sort_keys=True))
        return report

    def get_report(self, report_id) -> Optional[CrossProjectExecutionReadinessReport]:
        row = database.get_cross_project_execution_readiness_report(
            self.conn, report_id)
        return report_from_row(row) if row else None

    def save_markdown_report(self, report_id) -> ExecutionReadinessMarkdownReport:
        report = self.get_report(report_id)
        if report is None:
            raise ValueError(f"no execution readiness report {report_id}")
        content = self.render_markdown(report)
        os.makedirs(REPORTS_DIR, exist_ok=True)
        path = os.path.realpath(os.path.join(
            REPORTS_DIR, f"cross_project_execution_readiness_{int(report_id)}_{_now_stamp()}.md"))
        if not is_report_path(path):
            raise ValueError("readiness report path escaped directory")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        encoded = content.encode("utf-8")
        chash = hashlib.sha256(encoded).hexdigest()
        database.save_cross_project_execution_readiness_markdown_report(
            self.conn, report_id, path, "markdown", chash, len(encoded))
        return ExecutionReadinessMarkdownReport(
            report_id, path, "markdown", chash, len(encoded), _now_iso())

    def render_markdown(self, report) -> str:
        lines = ["# Cross-Project Execution Readiness", "",
                 f"- Report ID: {report.id}",
                 f"- Intent ID: {report.intent_id}",
                 f"- Overall status: {report.overall_status}", "",
                 "## Projects"]
        for item in report.project_results:
            lines.append(
                f"- {item['project_key']}: {item['status']} "
                f"blockers={item.get('blockers', [])}")
        lines.extend(["", "## Safety Notes"])
        lines.extend(f"- {n}" for n in report.safety_notes)
        return "\n".join(lines)
