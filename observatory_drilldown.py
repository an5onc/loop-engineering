"""Failure drilldown for Loop Observatory (Stage 4.3).

This module reads SQLite metadata to explain failed, blocked, paused, or
human-needed loops. It never calls models, executes commands, resumes jobs,
imports completions, commits, mutates loop/job rows, or reads protected file
contents. Writes are limited to drilldown metadata and optional generated
Markdown under observatory_failure_reports/.
"""

import datetime
import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from typing import List, Optional

import database


PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
REPORTS_DIR = os.path.join(PROJECT_ROOT, "observatory_failure_reports")

FAILURE_STATUSES = {
    "FAILED",
    "BLOCKED",
    "NEEDS_HUMAN",
    "NEEDS_CLARIFICATION",
    "NEEDS_EXTERNAL_AGENT",
    "PAUSED_EXTERNAL_AGENT",
    "REVIEW_INCONSISTENT",
    "FAILED_REVIEW",
    "REJECTED",
    "ERROR",
}
CLUSTER_BY = {"category", "stop_reason", "quality_gate", "workspace", "agent"}

RECOMMENDATIONS = [
    "python3 main.py --external-health",
    "python3 main.py --observatory",
    "python3 main.py --observatory-trends",
]


@dataclass
class FailureDrilldownItem:
    loop_id: int
    created_at: str
    task_preview: str
    loop_type: str
    workspace_name: str
    status: str
    stop_reason: str
    failure_category: str
    root_cause_hint: str
    agent_role: str
    agent_name: str
    model: str
    failed_quality_gates: List[str] = field(default_factory=list)
    triggered_stop_conditions: List[str] = field(default_factory=list)
    external_job_status: str = ""
    report_path: str = ""
    recommended_action: str = ""


@dataclass
class FailureCluster:
    cluster_key: str
    cluster_type: str
    count: int
    loop_ids: List[int] = field(default_factory=list)
    representative_reason: str = ""
    recommended_action: str = ""


@dataclass
class FailureDrilldownReport:
    generated_at: str
    total_failures: int
    filters_json: str
    items: List[FailureDrilldownItem] = field(default_factory=list)
    clusters: List[FailureCluster] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=lambda: list(RECOMMENDATIONS))


@dataclass
class FailureMarkdownReport:
    drilldown_id: int
    report_path: str
    report_format: str
    content_hash: str
    bytes_written: int
    created_at: str


def _now_iso():
    return datetime.datetime.now().isoformat(timespec="seconds")


def _now_stamp():
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


def _safe_json_loads(blob, default):
    try:
        return json.loads(blob or "")
    except (TypeError, ValueError):
        return default


def _csv(items):
    return ", ".join(items) if items else "(none)"


def item_to_dict(item):
    return asdict(item)


def cluster_to_dict(cluster):
    return asdict(cluster)


def item_from_dict(data):
    return FailureDrilldownItem(**data)


def cluster_from_dict(data):
    return FailureCluster(**data)


def report_from_row(row):
    return FailureDrilldownReport(
        generated_at=row["generated_at"],
        total_failures=row["total_failures"] or 0,
        filters_json=row["filters_json"] or "{}",
        items=[item_from_dict(i) for i in _safe_json_loads(row["items_json"], [])],
        clusters=[cluster_from_dict(c) for c in _safe_json_loads(row["clusters_json"], [])],
        recommendations=_safe_json_loads(row["recommendations_json"], list(RECOMMENDATIONS)),
    )


def is_markdown_report_path(path):
    if not path:
        return False
    target = os.path.realpath(path)
    base = os.path.realpath(REPORTS_DIR)
    return target != base and target.startswith(base + os.sep)


class ObservatoryDrilldownEngine:
    def __init__(self, conn):
        self.conn = conn

    def build_report(self, limit=25, workspace=None, loop_type=None, category=None,
                     status=None, include_approved=False, cluster_by="category"):
        if cluster_by not in CLUSTER_BY:
            raise ValueError(f"unknown failure cluster '{cluster_by}'")
        filters = {
            "limit": int(limit or 25),
            "workspace": workspace,
            "loop_type": loop_type,
            "category": category,
            "status": status,
            "include_approved": bool(include_approved),
            "cluster_by": cluster_by,
        }
        rows = self._loop_rows(filters)
        items = []
        for row in rows:
            item = self._build_item(row)
            if category and item.failure_category != category:
                continue
            items.append(item)
            if len(items) >= filters["limit"]:
                break
        clusters = self._clusters(items, cluster_by)
        return FailureDrilldownReport(
            generated_at=_now_iso(),
            total_failures=len(items),
            filters_json=json.dumps(filters, sort_keys=True),
            items=items,
            clusters=clusters,
            recommendations=self._recommendations(items),
        )

    def save_drilldown(self, report, cluster_by="category"):
        return database.save_observatory_failure_drilldown(
            self.conn,
            report.generated_at,
            report.filters_json,
            cluster_by,
            report.total_failures,
            json.dumps([item_to_dict(i) for i in report.items], sort_keys=True),
            json.dumps([cluster_to_dict(c) for c in report.clusters], sort_keys=True),
            json.dumps(report.recommendations, sort_keys=True),
        )

    def save_markdown_report(self, drilldown_id, report):
        content = self.render_markdown(report, drilldown_id=drilldown_id)
        path = self._new_markdown_path(drilldown_id)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        encoded = content.encode("utf-8")
        chash = hashlib.sha256(encoded).hexdigest()
        nbytes = len(encoded)
        database.save_observatory_failure_markdown_report(
            self.conn, drilldown_id, path, "markdown", chash, nbytes)
        return FailureMarkdownReport(
            drilldown_id=drilldown_id,
            report_path=path,
            report_format="markdown",
            content_hash=chash,
            bytes_written=nbytes,
            created_at=_now_iso(),
        )

    def _loop_rows(self, filters):
        where, params = [], []
        if filters["workspace"]:
            where.append("workspace_name=?")
            params.append(filters["workspace"])
        if filters["loop_type"]:
            where.append("loop_type=?")
            params.append(filters["loop_type"])
        if filters["status"]:
            where.append("status=?")
            params.append(filters["status"])
        elif not filters["include_approved"]:
            where.append("(status IS NULL OR status NOT IN ('APPROVED','SUCCESS'))")
        clause = (" WHERE " + " AND ".join(where)) if where else ""
        rows = self.conn.execute(
            f"SELECT * FROM loops{clause} ORDER BY id DESC LIMIT ?",
            params + [max(filters["limit"] * 5, filters["limit"])],
        ).fetchall()
        return rows

    def _build_item(self, loop):
        loop_id = loop["id"]
        failed_gates = [
            r["gate_name"] for r in self.conn.execute(
                "SELECT gate_name FROM quality_gate_results "
                "WHERE loop_id=? AND COALESCE(passed,0)=0 ORDER BY id",
                (loop_id,),
            ).fetchall()
        ]
        triggered = [
            r["condition_name"] for r in self.conn.execute(
                "SELECT condition_name FROM stop_condition_results "
                "WHERE loop_id=? AND COALESCE(triggered,0)=1 ORDER BY id",
                (loop_id,),
            ).fetchall()
        ]
        agent = self.conn.execute(
            "SELECT * FROM agent_events WHERE loop_id=? ORDER BY id DESC LIMIT 1",
            (loop_id,),
        ).fetchone()
        review = self.conn.execute(
            "SELECT * FROM reviews WHERE loop_id=? ORDER BY id DESC LIMIT 1",
            (loop_id,),
        ).fetchone()
        job = database.get_external_agent_job_for_loop(self.conn, loop_id)
        report = database.get_run_report(self.conn, loop_id)
        category, hint = self._classify(loop, failed_gates, triggered, review, job)
        return FailureDrilldownItem(
            loop_id=loop_id,
            created_at=loop["created_at"],
            task_preview=(loop["task"] or "")[:100],
            loop_type=loop["loop_type"] or "(unknown)",
            workspace_name=loop["workspace_name"] or "(unknown)",
            status=loop["status"] or "(unknown)",
            stop_reason=loop["stop_reason"] or "(none)",
            failure_category=category,
            root_cause_hint=hint,
            agent_role=(agent["agent_role"] if agent else "") or
                       ("reviewer" if review is not None else ""),
            agent_name=(agent["agent_name"] if agent else "") or "",
            model=(agent["model"] if agent else "") or "",
            failed_quality_gates=failed_gates,
            triggered_stop_conditions=triggered,
            external_job_status=(job["status"] if job is not None else "") or "",
            report_path=(report["report_path"] if report is not None else "") or "",
            recommended_action=self._recommended_action(loop_id, category, job),
        )

    def _classify(self, loop, failed_gates, triggered, review, job):
        status = (loop["status"] or "").upper()
        stop_reason = (loop["stop_reason"] or "").lower()
        if status == "NEEDS_CLARIFICATION" or "clarification" in stop_reason:
            return "needs_clarification", "task intake or prompt needs clarification"
        if status == "REVIEW_INCONSISTENT" or "review_inconsistent" in stop_reason:
            return "reviewer_inconsistent", "reviewer output was contradictory"
        if "workspace" in stop_reason and "violation" in stop_reason:
            return "workspace_violation", "workspace validation or boundary violation"
        if self._has_declined_approval(loop["id"]) or "approval" in stop_reason:
            return "approval_declined", "human approval was declined or required"
        if failed_gates:
            return "quality_gate_failed", f"failed quality gate: {failed_gates[0]}"
        if triggered:
            return "stop_condition_triggered", f"triggered stop condition: {triggered[0]}"
        if self._has_command_failed(loop["id"]):
            return "command_failed", "an allowed command exited non-zero or timed out"
        if self._has_command_blocked(loop["id"]):
            return "command_blocked", "a terminal safety rule blocked a command"
        if self._has_file_blocked(loop["id"]):
            return "filesystem_blocked", "a filesystem safety rule blocked a write"
        if job is not None and job["status"] == "WAITING_FOR_EXTERNAL_AGENT":
            return "external_agent_waiting", "external job is still waiting"
        if job is not None and job["status"] in ("FAILED", "BLOCKED", "CANCELLED"):
            return "external_agent_failed", f"external job status is {job['status']}"
        if self._has_external_health(loop["id"]):
            return "external_job_health", "external job health event exists"
        if "report" in stop_reason:
            return "report_generation_failed", "report generation failed"
        if review is not None and not bool(review["approved"]):
            return "reviewer_rejected", "reviewer rejected the attempted changes"
        if "json" in stop_reason or "parse" in stop_reason or "invalid" in stop_reason:
            return "model_output_invalid", "model output was invalid or unparseable"
        return "unknown", "no specific failure evidence found"

    def _has_declined_approval(self, loop_id):
        return bool(self.conn.execute(
            "SELECT 1 FROM approval_events WHERE loop_id=? "
            "AND COALESCE(approved,0)=0 LIMIT 1",
            (loop_id,),
        ).fetchone())

    def _has_command_failed(self, loop_id):
        return bool(self.conn.execute(
            "SELECT 1 FROM command_results WHERE loop_id=? AND COALESCE(allowed,0)=1 "
            "AND (COALESCE(timed_out,0)=1 OR COALESCE(exit_code,0)<>0) LIMIT 1",
            (loop_id,),
        ).fetchone())

    def _has_command_blocked(self, loop_id):
        return bool(self.conn.execute(
            "SELECT 1 FROM command_results WHERE loop_id=? "
            "AND COALESCE(allowed,0)=0 LIMIT 1",
            (loop_id,),
        ).fetchone())

    def _has_file_blocked(self, loop_id):
        return bool(self.conn.execute(
            "SELECT 1 FROM file_operations WHERE loop_id=? "
            "AND COALESCE(allowed,0)=0 LIMIT 1",
            (loop_id,),
        ).fetchone())

    def _has_external_health(self, loop_id):
        return bool(self.conn.execute(
            "SELECT 1 FROM external_job_health_events WHERE loop_id=? LIMIT 1",
            (loop_id,),
        ).fetchone())

    def _recommended_action(self, loop_id, category, job):
        if job is not None:
            return f"python3 main.py --external-job {job['id']}"
        if category in ("quality_gate_failed", "stop_condition_triggered",
                        "command_failed", "reviewer_rejected"):
            return f"python3 main.py --report {loop_id}"
        return f"python3 main.py --show {loop_id}"

    def _clusters(self, items, cluster_by):
        groups = {}
        for item in items:
            key = self._cluster_key(item, cluster_by)
            groups.setdefault(key, []).append(item)
        clusters = []
        for key, vals in groups.items():
            clusters.append(FailureCluster(
                cluster_key=key,
                cluster_type=cluster_by,
                count=len(vals),
                loop_ids=[v.loop_id for v in vals[:10]],
                representative_reason=vals[0].root_cause_hint,
                recommended_action=vals[0].recommended_action,
            ))
        clusters.sort(key=lambda c: (-c.count, c.cluster_key))
        return clusters

    def _cluster_key(self, item, cluster_by):
        if cluster_by == "category":
            return item.failure_category
        if cluster_by == "stop_reason":
            return item.stop_reason or "(none)"
        if cluster_by == "quality_gate":
            return item.failed_quality_gates[0] if item.failed_quality_gates else "(none)"
        if cluster_by == "workspace":
            return item.workspace_name or "(unknown)"
        if cluster_by == "agent":
            return item.agent_name or "(unknown)"
        return "(unknown)"

    def _recommendations(self, items):
        recs = []
        for item in items[:5]:
            for cmd in (
                f"python3 main.py --show {item.loop_id}",
                f"python3 main.py --report {item.loop_id}",
                f"python3 main.py --replay {item.loop_id} --dry-run",
            ):
                if cmd not in recs:
                    recs.append(cmd)
            if item.external_job_status:
                job = database.get_external_agent_job_for_loop(self.conn, item.loop_id)
                if job is not None:
                    cmd = f"python3 main.py --external-job {job['id']}"
                    if cmd not in recs:
                        recs.append(cmd)
        for cmd in RECOMMENDATIONS:
            if cmd not in recs:
                recs.append(cmd)
        return recs

    def _new_markdown_path(self, drilldown_id):
        os.makedirs(REPORTS_DIR, exist_ok=True)
        filename = f"observatory_failures_{int(drilldown_id)}_{_now_stamp()}.md"
        target = os.path.realpath(os.path.join(REPORTS_DIR, filename))
        base = os.path.realpath(REPORTS_DIR)
        if target != base and not target.startswith(base + os.sep):
            raise ValueError("failure report path escaped observatory_failure_reports/")
        return target

    def render_markdown(self, report, drilldown_id=None):
        lines = []
        a = lines.append
        a("# Loop Failure Drilldown")
        a("")
        a("## Summary")
        if drilldown_id is not None:
            a(f"- Drilldown ID: {drilldown_id}")
        a(f"- Generated at: {report.generated_at}")
        a(f"- Total failures: {report.total_failures}")
        a(f"- Filters: {report.filters_json}")
        a("")
        a("## Clusters")
        if not report.clusters:
            a("- (none)")
        for cluster in report.clusters:
            a(f"- {cluster.cluster_type}: {cluster.cluster_key} "
              f"count={cluster.count} loops={cluster.loop_ids}")
            a(f"  reason: {cluster.representative_reason}")
            a(f"  action: {cluster.recommended_action}")
        a("")
        a("## Failures")
        if not report.items:
            a("- (none)")
        for item in report.items:
            a(f"- loop #{item.loop_id}: status={item.status} "
              f"type={item.loop_type} workspace={item.workspace_name}")
            a(f"  stop reason: {item.stop_reason}")
            a(f"  category: {item.failure_category}")
            a(f"  root cause: {item.root_cause_hint}")
            a(f"  failed gates: {_csv(item.failed_quality_gates)}")
            a(f"  triggered stops: {_csv(item.triggered_stop_conditions)}")
            a(f"  external job status: {item.external_job_status or '(none)'}")
            a(f"  report path: {item.report_path or '(none)'}")
            a(f"  action: {item.recommended_action}")
        a("")
        a("## Next Actions")
        for rec in report.recommendations:
            a(f"- {rec}")
        a("")
        a("## Safety Notes")
        a("- Failure drilldown only reads SQLite and known report metadata")
        a("- No model calls")
        a("- No command execution")
        a("- No job mutation")
        a("- No loop mutation")
        a("")
        return "\n".join(lines)
