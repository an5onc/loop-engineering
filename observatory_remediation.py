"""Remediation plans for Loop Observatory findings (Stage 4.4).

Remediation planning turns existing observatory metadata into reviewable manual
improvement plans. It never calls models, executes suggested commands, mutates
loops/jobs, imports completions, resumes work, commits, or reads protected file
contents. Writes are limited to remediation metadata and optional Markdown under
observatory_remediation_reports/.
"""

import datetime
import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from typing import List, Optional

import database


PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
REPORTS_DIR = os.path.join(PROJECT_ROOT, "observatory_remediation_reports")

PRIORITIES = {"urgent", "high", "medium", "low"}
CATEGORIES = {
    "safety",
    "reliability",
    "model_quality",
    "reviewer_quality",
    "workspace_configuration",
    "approval_flow",
    "external_agent_queue",
    "external_agent_health",
    "reporting",
    "observability",
    "database_integrity",
    "documentation",
    "testing",
    "unknown",
}


@dataclass
class RemediationPlanItem:
    id: int
    priority: str
    category: str
    title: str
    problem_summary: str
    evidence: str
    affected_loop_ids: List[int] = field(default_factory=list)
    affected_job_ids: List[int] = field(default_factory=list)
    recommended_action: str = ""
    suggested_command: str = ""
    expected_impact: str = ""
    risk_level: str = "low"
    effort_level: str = "low"
    status: str = "proposed"


@dataclass
class RemediationPlan:
    generated_at: str
    source_type: str
    source_id: Optional[int]
    total_items: int
    high_priority_count: int
    medium_priority_count: int
    low_priority_count: int
    items: List[RemediationPlanItem] = field(default_factory=list)
    summary: str = ""
    next_steps: List[str] = field(default_factory=list)
    urgent_count: int = 0


@dataclass
class RemediationMarkdownReport:
    remediation_plan_id: int
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


def item_to_dict(item):
    return asdict(item)


def item_from_dict(data):
    return RemediationPlanItem(**data)


def plan_from_row(row):
    summary = _safe_json_loads(row["summary_json"], {})
    items = [item_from_dict(i) for i in _safe_json_loads(row["items_json"], [])]
    return RemediationPlan(
        generated_at=row["generated_at"],
        source_type=row["source_type"],
        source_id=row["source_id"],
        total_items=row["total_items"] or 0,
        urgent_count=row["urgent_count"] or 0,
        high_priority_count=row["high_priority_count"] or 0,
        medium_priority_count=row["medium_priority_count"] or 0,
        low_priority_count=row["low_priority_count"] or 0,
        items=items,
        summary=summary.get("summary", ""),
        next_steps=summary.get("next_steps", []),
    )


def is_markdown_report_path(path):
    if not path:
        return False
    target = os.path.realpath(path)
    base = os.path.realpath(REPORTS_DIR)
    return target != base and target.startswith(base + os.sep)


class ObservatoryRemediationEngine:
    def __init__(self, conn):
        self.conn = conn

    def build_plan(self, source_type=None, source_id=None, priority=None,
                   category=None, limit=25):
        if priority and priority not in PRIORITIES:
            raise ValueError(f"unknown remediation priority '{priority}'")
        if category and category not in CATEGORIES:
            raise ValueError(f"unknown remediation category '{category}'")
        source_type, source_id = self._resolve_source(source_type, source_id)
        raw_items = self._items_for_source(source_type, source_id)
        filtered = []
        for item in raw_items:
            if priority and item.priority != priority:
                continue
            if category and item.category != category:
                continue
            filtered.append(item)
            if len(filtered) >= int(limit or 25):
                break
        for idx, item in enumerate(filtered, start=1):
            item.id = idx
        urgent = sum(1 for i in filtered if i.priority == "urgent")
        high = sum(1 for i in filtered if i.priority == "high")
        medium = sum(1 for i in filtered if i.priority == "medium")
        low = sum(1 for i in filtered if i.priority == "low")
        next_steps = []
        for item in filtered:
            if item.suggested_command and item.suggested_command not in next_steps:
                next_steps.append(item.suggested_command)
        for cmd in (
            "python3 main.py --observatory",
            "python3 main.py --observatory-trends",
            "python3 main.py --observatory-failures",
            "python3 main.py --external-health",
        ):
            if cmd not in next_steps:
                next_steps.append(cmd)
        return RemediationPlan(
            generated_at=_now_iso(),
            source_type=source_type,
            source_id=source_id,
            total_items=len(filtered),
            urgent_count=urgent,
            high_priority_count=high,
            medium_priority_count=medium,
            low_priority_count=low,
            items=filtered,
            summary=f"{len(filtered)} remediation item(s) from {source_type}",
            next_steps=next_steps,
        )

    def save_plan(self, plan, filters):
        return database.save_observatory_remediation_plan(
            self.conn,
            plan.generated_at,
            plan.source_type,
            plan.source_id,
            json.dumps(filters or {}, sort_keys=True),
            json.dumps({"summary": plan.summary, "next_steps": plan.next_steps},
                       sort_keys=True),
            json.dumps([item_to_dict(i) for i in plan.items], sort_keys=True),
            plan.total_items,
            plan.urgent_count,
            plan.high_priority_count,
            plan.medium_priority_count,
            plan.low_priority_count,
        )

    def save_markdown_report(self, plan_id, plan):
        content = self.render_markdown(plan, plan_id=plan_id)
        path = self._new_markdown_path(plan_id)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        encoded = content.encode("utf-8")
        chash = hashlib.sha256(encoded).hexdigest()
        nbytes = len(encoded)
        database.save_observatory_remediation_markdown_report(
            self.conn, plan_id, path, "markdown", chash, nbytes)
        return RemediationMarkdownReport(
            remediation_plan_id=plan_id,
            report_path=path,
            report_format="markdown",
            content_hash=chash,
            bytes_written=nbytes,
            created_at=_now_iso(),
        )

    def _resolve_source(self, source_type, source_id):
        if source_type is None:
            rows = database.list_observatory_failure_drilldowns(self.conn, 1)
            if rows:
                return "failure_drilldown", rows[0]["id"]
            rows = database.list_observatory_snapshots(self.conn, 1)
            return ("snapshot", rows[0]["id"] if rows else None)
        if source_id is not None:
            return source_type, int(source_id)
        if source_type == "snapshot":
            rows = database.list_observatory_snapshots(self.conn, 1)
        elif source_type == "trend":
            rows = database.list_observatory_trend_reports(self.conn, 1)
        elif source_type == "failure_drilldown":
            rows = database.list_observatory_failure_drilldowns(self.conn, 1)
        else:
            raise ValueError(f"unknown remediation source '{source_type}'")
        return source_type, (rows[0]["id"] if rows else None)

    def _items_for_source(self, source_type, source_id):
        if source_id is None:
            return [self._item("low", "observability", "No source data available",
                               "No observatory source rows exist yet.",
                               "source_id is missing",
                               "python3 main.py --observatory --save-report")]
        if source_type == "snapshot":
            return self._items_from_snapshot(source_id)
        if source_type == "trend":
            return self._items_from_trend(source_id)
        if source_type == "failure_drilldown":
            return self._items_from_failure_drilldown(source_id)
        raise ValueError(f"unknown remediation source '{source_type}'")

    def _items_from_snapshot(self, snapshot_id):
        row = database.get_observatory_snapshot(self.conn, snapshot_id)
        if row is None:
            raise ValueError(f"no observatory snapshot {snapshot_id}")
        summary = _safe_json_loads(row["summary_json"], {})
        items = []
        if (row["critical_alert_count"] or 0) > 0:
            items.append(self._item(
                "urgent", "external_agent_health",
                "Investigate critical observatory alerts",
                "Critical alerts exist in the latest observatory snapshot.",
                f"critical_alert_count={row['critical_alert_count']}",
                "python3 main.py --external-health",
                expected="Reduce critical health and safety risk.",
                risk="high",
                effort="medium",
            ))
        if (summary.get("quality_gate_failures") or 0) >= 3:
            items.append(self._item(
                "high", "testing",
                "Review repeated quality gate failures",
                "Quality gate failures are repeated in the observatory summary.",
                f"quality_gate_failures={summary.get('quality_gate_failures')}",
                "python3 main.py --observatory-failures --category quality_gate_failed",
                expected="Improve gate pass rate and reduce blocked loops.",
                risk="medium",
                effort="medium",
            ))
        if (summary.get("blocked_loops") or 0) >= 3:
            items.append(self._item(
                "high", "reliability",
                "Triage repeated blocked loops",
                "Blocked loops are accumulating.",
                f"blocked_loops={summary.get('blocked_loops')}",
                "python3 main.py --observatory-failures --cluster-by stop_reason",
                expected="Identify dominant blocking reasons.",
                risk="medium",
                effort="medium",
            ))
        if (summary.get("waiting_external_jobs") or 0) >= 1:
            items.append(self._item(
                "high", "external_agent_queue",
                "Review waiting external jobs",
                "External jobs are waiting and may need manual follow-up.",
                f"waiting_external_jobs={summary.get('waiting_external_jobs')}",
                "python3 main.py --external-jobs --needs-attention",
                expected="Reduce stuck or stale external-agent queue.",
                risk="medium",
                effort="low",
            ))
        return items or [self._item(
            "low", "observability", "Refresh observatory baseline",
            "No high-signal remediation item was detected from this snapshot.",
            f"snapshot_id={snapshot_id}",
            "python3 main.py --observatory --save-report")]

    def _items_from_trend(self, report_id):
        row = database.get_observatory_trend_report(self.conn, report_id)
        if row is None:
            raise ValueError(f"no observatory trend report {report_id}")
        trends = _safe_json_loads(row["trends_json"], [])
        alerts = _safe_json_loads(row["alerts_json"], [])
        items = []
        for trend in trends:
            metric = trend.get("metric_name")
            direction = trend.get("direction")
            if direction != "up":
                continue
            if metric in ("blocked_loops", "failed_loops", "quality_gate_failures"):
                items.append(self._item(
                    "high", "reliability",
                    f"Investigate increasing {metric}",
                    "A trend report shows this failure metric increasing.",
                    f"{metric}: delta={trend.get('delta')} percent_change={trend.get('percent_change')}",
                    "python3 main.py --observatory-failures",
                    expected="Reverse worsening reliability trend.",
                    risk="medium",
                    effort="medium",
                ))
            elif metric in ("declined_approvals",):
                items.append(self._item(
                    "medium", "approval_flow",
                    "Review rising approval declines",
                    "Trend report shows approval declines increasing.",
                    f"declined_approvals delta={trend.get('delta')}",
                    "python3 main.py --history --limit 10",
                    expected="Clarify high-risk workflows and approval criteria.",
                    risk="medium",
                    effort="low",
                ))
        for alert in alerts:
            if "waiting" in str(alert):
                items.append(self._item(
                    "high", "external_agent_queue",
                    "Address increasing external queue wait",
                    str(alert),
                    str(alert),
                    "python3 main.py --external-jobs --needs-attention",
                    expected="Reduce stale external work.",
                    risk="medium",
                    effort="low",
                ))
        return items or [self._item(
            "low", "observability", "Continue trend monitoring",
            "No worsening trend requiring remediation was detected.",
            f"trend_report_id={report_id}",
            "python3 main.py --observatory-trends")]

    def _items_from_failure_drilldown(self, drilldown_id):
        row = database.get_observatory_failure_drilldown(self.conn, drilldown_id)
        if row is None:
            raise ValueError(f"no observatory failure drilldown {drilldown_id}")
        clusters = _safe_json_loads(row["clusters_json"], [])
        items_json = _safe_json_loads(row["items_json"], [])
        items = []
        for cluster in clusters:
            key = cluster.get("cluster_key", "unknown")
            count = int(cluster.get("count") or 0)
            loop_ids = [int(x) for x in cluster.get("loop_ids", [])]
            if key == "quality_gate_failed":
                items.append(self._item(
                    "high", "testing",
                    "Fix repeated quality gate failures",
                    cluster.get("representative_reason") or "Quality gate failures repeat.",
                    f"count={count} loop_ids={loop_ids}",
                    "python3 main.py --observatory-failures --category quality_gate_failed",
                    loops=loop_ids,
                    expected="Reduce repeated blocked or rejected loops.",
                    risk="medium",
                    effort="medium",
                ))
            elif key in ("workspace_violation", "filesystem_blocked"):
                items.append(self._item(
                    "urgent" if key == "workspace_violation" else "high",
                    "workspace_configuration",
                    "Review workspace safety failures",
                    cluster.get("representative_reason") or "Workspace safety failures repeat.",
                    f"count={count} loop_ids={loop_ids}",
                    "python3 main.py --observatory-failures --cluster-by workspace",
                    loops=loop_ids,
                    expected="Preserve workspace boundary safety.",
                    risk="high",
                    effort="medium",
                ))
            elif key in ("external_agent_waiting", "external_agent_failed", "external_job_health"):
                items.append(self._item(
                    "high", "external_agent_queue",
                    "Triage external agent failures",
                    cluster.get("representative_reason") or "External-agent failures repeat.",
                    f"count={count} loop_ids={loop_ids}",
                    "python3 main.py --external-health",
                    loops=loop_ids,
                    expected="Unblock external-agent work.",
                    risk="medium",
                    effort="low",
                ))
        if not items and items_json:
            first = items_json[0]
            items.append(self._item(
                "medium", "unknown",
                "Inspect failure drilldown",
                first.get("root_cause_hint") or "Failure drilldown has unresolved items.",
                f"loop_id={first.get('loop_id')}",
                f"python3 main.py --show {first.get('loop_id')}",
                loops=[first.get("loop_id")],
                expected="Clarify remediation target.",
                risk="low",
                effort="low",
            ))
        return items or [self._item(
            "low", "observability", "Refresh failure drilldown",
            "No remediation item was detected from this drilldown.",
            f"failure_drilldown_id={drilldown_id}",
            "python3 main.py --observatory-failures")]

    def _item(self, priority, category, title, problem, evidence, command,
              loops=None, jobs=None, expected="", risk="low", effort="low"):
        return RemediationPlanItem(
            id=0,
            priority=priority,
            category=category,
            title=title,
            problem_summary=problem,
            evidence=evidence,
            affected_loop_ids=[int(x) for x in (loops or []) if x is not None],
            affected_job_ids=[int(x) for x in (jobs or []) if x is not None],
            recommended_action=problem,
            suggested_command=command,
            expected_impact=expected or "Improve Loop Engineering reliability.",
            risk_level=risk,
            effort_level=effort,
            status="proposed",
        )

    def _new_markdown_path(self, plan_id):
        os.makedirs(REPORTS_DIR, exist_ok=True)
        filename = f"observatory_remediation_{int(plan_id)}_{_now_stamp()}.md"
        target = os.path.realpath(os.path.join(REPORTS_DIR, filename))
        base = os.path.realpath(REPORTS_DIR)
        if target != base and not target.startswith(base + os.sep):
            raise ValueError("remediation report path escaped observatory_remediation_reports/")
        return target

    def render_markdown(self, plan, plan_id=None):
        lines = []
        a = lines.append
        a("# Loop Engineering Remediation Plan")
        a("")
        a("## Summary")
        if plan_id is not None:
            a(f"- Plan ID: {plan_id}")
        a(f"- Source type: {plan.source_type}")
        a(f"- Source ID: {plan.source_id}")
        a(f"- Generated at: {plan.generated_at}")
        a(f"- Total items: {plan.total_items}")
        a(f"- Urgent: {plan.urgent_count}")
        a(f"- High: {plan.high_priority_count}")
        a(f"- Medium: {plan.medium_priority_count}")
        a(f"- Low: {plan.low_priority_count}")
        a("")
        a("## Plan Items")
        if not plan.items:
            a("- (none)")
        for item in plan.items:
            a(f"- [{item.priority}] {item.category}: {item.title}")
            a(f"  problem: {item.problem_summary}")
            a(f"  evidence: {item.evidence}")
            a(f"  loops: {item.affected_loop_ids or []}")
            a(f"  jobs: {item.affected_job_ids or []}")
            a(f"  action: {item.recommended_action}")
            a(f"  command: {item.suggested_command}")
            a(f"  impact: {item.expected_impact}")
            a(f"  risk: {item.risk_level}")
            a(f"  effort: {item.effort_level}")
            a(f"  status: {item.status}")
        a("")
        a("## Evidence")
        for item in plan.items:
            a(f"- item {item.id}: {item.evidence}")
        a("")
        a("## Next Steps")
        for step in plan.next_steps:
            a(f"- {step}")
        a("")
        a("## Safety Notes")
        a("- Remediation planning only reads observatory metadata")
        a("- Suggested commands are not executed")
        a("- No model calls")
        a("- No command execution")
        a("- No job mutation")
        a("- No loop mutation")
        a("")
        return "\n".join(lines)
