"""Loop Observatory foundation (Stage 4.0).

Read-only observability over the local SQLite database. The engine never calls
models, executes commands, reads protected file contents, mutates loops/jobs, or
creates project files. The only write in Stage 4.0 is saving an observatory
snapshot row when the CLI asks for a summary.
"""

import datetime
import json
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional

import external_agent_dashboard as external_dash


WINDOWS = {"all", "today", "24h", "7d", "30d"}


@dataclass
class ObservatoryTimeWindow:
    name: str = "all"
    start_at: Optional[str] = None
    end_at: str = ""


@dataclass
class ObservatoryMetric:
    name: str
    value: float
    unit: str = "count"
    details_json: str = "{}"


@dataclass
class ObservatoryAlert:
    severity: str
    alert_type: str
    message: str
    recommended_action: str
    details_json: str = "{}"


@dataclass
class ObservatorySummary:
    generated_at: str = ""
    time_window: ObservatoryTimeWindow = field(default_factory=ObservatoryTimeWindow)
    total_loops: int = 0
    approved_loops: int = 0
    failed_loops: int = 0
    blocked_loops: int = 0
    needs_human_loops: int = 0
    paused_external_loops: int = 0
    total_external_jobs: int = 0
    waiting_external_jobs: int = 0
    completed_external_jobs: int = 0
    blocked_external_jobs: int = 0
    failed_external_jobs: int = 0
    total_reports: int = 0
    total_approvals: int = 0
    declined_approvals: int = 0
    quality_gate_failures: int = 0
    stop_condition_triggers: int = 0
    top_failure_reasons: List[dict] = field(default_factory=list)
    top_loop_types: List[dict] = field(default_factory=list)
    top_agents: List[dict] = field(default_factory=list)
    top_workspaces: List[dict] = field(default_factory=list)
    external_job_health: Dict[str, int] = field(default_factory=dict)
    alerts: List[ObservatoryAlert] = field(default_factory=list)


def _now():
    return datetime.datetime.now().isoformat(timespec="seconds")


def _parse_window(name):
    name = (name or "all").lower()
    if name not in WINDOWS:
        raise ValueError(f"unknown observatory window '{name}'")
    now = datetime.datetime.now()
    if name == "all":
        start = None
    elif name == "today":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif name == "24h":
        start = now - datetime.timedelta(hours=24)
    elif name == "7d":
        start = now - datetime.timedelta(days=7)
    else:
        start = now - datetime.timedelta(days=30)
    return ObservatoryTimeWindow(
        name=name,
        start_at=start.isoformat(timespec="seconds") if start else None,
        end_at=now.isoformat(timespec="seconds"),
    )


def _where_time(alias, window):
    if not window.start_at:
        return "", []
    return f"datetime({alias}.created_at) >= datetime(?)", [window.start_at]


def _append_filter(parts, vals, condition, *params):
    parts.append(condition)
    vals.extend(params)


def _loop_where(window, workspace=None, loop_type=None, agent=None):
    parts, vals = [], []
    t, tv = _where_time("l", window)
    if t:
        parts.append(t)
        vals.extend(tv)
    if workspace:
        _append_filter(parts, vals, "l.workspace_name=?", workspace)
    if loop_type:
        _append_filter(parts, vals, "l.loop_type=?", loop_type)
    if agent:
        _append_filter(
            parts,
            vals,
            "(EXISTS (SELECT 1 FROM external_agent_events e "
            "WHERE e.loop_id=l.id AND e.external_agent_name=?) "
            "OR EXISTS (SELECT 1 FROM agent_events a "
            "WHERE a.loop_id=l.id AND a.agent_name=?))",
            agent,
            agent,
        )
    return (" WHERE " + " AND ".join(parts) if parts else ""), vals


def _job_where(window, workspace=None, agent=None):
    parts, vals = [], []
    t, tv = _where_time("j", window)
    if t:
        parts.append(t)
        vals.extend(tv)
    if workspace:
        _append_filter(parts, vals, "j.workspace_name=?", workspace)
    if agent:
        _append_filter(parts, vals, "j.external_agent_name=?", agent)
    return (" WHERE " + " AND ".join(parts) if parts else ""), vals


def _count(conn, sql, params=()):
    return int(conn.execute(sql, params).fetchone()[0] or 0)


def _rate(num, den):
    return round((float(num) / float(den)) * 100.0, 1) if den else 0.0


class ObservatoryEngine:
    def __init__(self, conn):
        self.conn = conn

    def build_summary(self, window="all", workspace=None, loop_type=None,
                      agent=None) -> ObservatorySummary:
        tw = _parse_window(window)
        generated_at = _now()
        lwhere, lvals = _loop_where(tw, workspace, loop_type, agent)
        jwhere, jvals = _job_where(tw, workspace, agent)

        s = ObservatorySummary(generated_at=generated_at, time_window=tw)
        s.total_loops = _count(self.conn, f"SELECT COUNT(*) FROM loops l{lwhere}", lvals)
        for attr, status in (
            ("approved_loops", "APPROVED"),
            ("failed_loops", "FAILED"),
            ("blocked_loops", "BLOCKED"),
            ("needs_human_loops", "NEEDS_HUMAN"),
            ("paused_external_loops", "PAUSED_EXTERNAL_AGENT"),
        ):
            setattr(
                s,
                attr,
                _count(self.conn, f"SELECT COUNT(*) FROM loops l{lwhere}"
                      + (" AND " if lwhere else " WHERE ") + "l.status=?",
                       lvals + [status]),
            )

        s.total_external_jobs = _count(
            self.conn, f"SELECT COUNT(*) FROM external_agent_jobs j{jwhere}", jvals)
        for attr, status in (
            ("waiting_external_jobs", "WAITING_FOR_EXTERNAL_AGENT"),
            ("completed_external_jobs", "APPROVED"),
            ("blocked_external_jobs", "BLOCKED"),
            ("failed_external_jobs", "FAILED"),
        ):
            setattr(
                s,
                attr,
                _count(self.conn, f"SELECT COUNT(*) FROM external_agent_jobs j{jwhere}"
                      + (" AND " if jwhere else " WHERE ")
                      + "j.status=? AND COALESCE(j.archived,0) NOT IN (1,'1','true','yes')",
                       jvals + [status]),
            )

        s.total_reports = self._count_joined("run_reports", "r", "loop_id", lwhere, lvals)
        s.total_approvals = self._count_joined("approval_events", "a", "loop_id", lwhere, lvals)
        s.declined_approvals = self._count_joined(
            "approval_events", "a", "loop_id", lwhere, lvals, "COALESCE(a.approved,0)=0")
        s.quality_gate_failures = self._count_joined(
            "quality_gate_results", "q", "loop_id", lwhere, lvals, "COALESCE(q.passed,0)=0")
        s.stop_condition_triggers = self._count_joined(
            "stop_condition_results", "sc", "loop_id", lwhere, lvals,
            "COALESCE(sc.triggered,0)=1")

        s.top_failure_reasons = self._top_failure_reasons(lwhere, lvals)
        s.top_loop_types = self._top_loop_types(lwhere, lvals)
        s.top_agents = self._top_agents(tw, workspace, agent)
        s.top_workspaces = self._top_workspaces(lwhere, lvals)
        s.external_job_health = self._external_job_health(jwhere, jvals)
        s.alerts = self._alerts(s)
        return s

    def _count_joined(self, table, alias, loop_col, lwhere, lvals, extra=None):
        where = lwhere
        vals = list(lvals)
        if extra:
            where += (" AND " if where else " WHERE ") + extra
        sql = (f"SELECT COUNT(*) FROM {table} {alias} "
               f"JOIN loops l ON l.id={alias}.{loop_col}{where}")
        return _count(self.conn, sql, vals)

    def _top_failure_reasons(self, lwhere, lvals):
        rows = self.conn.execute(
            "SELECT COALESCE(l.stop_reason, '(none)') AS reason, COUNT(*) AS n "
            f"FROM loops l{lwhere}"
            + (" AND " if lwhere else " WHERE ")
            + "l.status IN ('FAILED','BLOCKED','REJECTED','ERROR') "
            "GROUP BY reason ORDER BY n DESC, reason LIMIT 10",
            lvals,
        ).fetchall()
        return [{"stop_reason": r["reason"], "count": r["n"]} for r in rows]

    def _top_loop_types(self, lwhere, lvals):
        rows = self.conn.execute(
            "SELECT COALESCE(l.loop_type, '(unknown)') AS loop_type, COUNT(*) AS n, "
            "SUM(CASE WHEN l.status='APPROVED' THEN 1 ELSE 0 END) AS approved, "
            "SUM(CASE WHEN l.status IN ('FAILED','BLOCKED','REJECTED','ERROR') "
            "THEN 1 ELSE 0 END) AS failed "
            f"FROM loops l{lwhere} GROUP BY loop_type ORDER BY n DESC, loop_type LIMIT 10",
            lvals,
        ).fetchall()
        return [
            {
                "loop_type": r["loop_type"],
                "count": r["n"],
                "approval_rate": _rate(r["approved"] or 0, r["n"]),
                "failure_rate": _rate(r["failed"] or 0, r["n"]),
            }
            for r in rows
        ]

    def _top_agents(self, tw, workspace=None, agent=None):
        parts, vals = [], []
        t, tv = _where_time("e", tw)
        if t:
            parts.append(t)
            vals.extend(tv)
        if workspace:
            parts.append("l.workspace_name=?")
            vals.append(workspace)
        if agent:
            parts.append("e.external_agent_name=?")
            vals.append(agent)
        where = (" WHERE " + " AND ".join(parts)) if parts else ""
        rows = self.conn.execute(
            "SELECT e.external_agent_name AS agent, COUNT(*) AS n, "
            "SUM(CASE WHEN COALESCE(e.success,0)=1 THEN 1 ELSE 0 END) AS success "
            "FROM external_agent_events e JOIN loops l ON l.id=e.loop_id"
            f"{where} GROUP BY agent ORDER BY n DESC, agent LIMIT 10",
            vals,
        ).fetchall()
        return [
            {"agent": r["agent"] or "(unknown)", "count": r["n"],
             "success_rate": _rate(r["success"] or 0, r["n"])}
            for r in rows
        ]

    def _top_workspaces(self, lwhere, lvals):
        rows = self.conn.execute(
            "SELECT COALESCE(l.workspace_name, '(unknown)') AS workspace, COUNT(*) AS n, "
            "SUM(CASE WHEN l.status='BLOCKED' THEN 1 ELSE 0 END) AS blocked "
            f"FROM loops l{lwhere} GROUP BY workspace ORDER BY n DESC, workspace LIMIT 10",
            lvals,
        ).fetchall()
        return [
            {"workspace": r["workspace"], "loop_count": r["n"],
             "blocked_count": r["blocked"] or 0}
            for r in rows
        ]

    def _external_job_health(self, jwhere, jvals):
        jobs = self.conn.execute(
            f"SELECT * FROM external_agent_jobs j{jwhere} ORDER BY j.id DESC", jvals
        ).fetchall()
        active_jobs = [
            j for j in jobs
            if str(j["archived"]).lower() not in ("1", "true", "yes")
        ]
        waiting = sum(1 for j in active_jobs if j["status"] == "WAITING_FOR_EXTERNAL_AGENT")
        stale = 0
        needs_attention = 0
        for j in active_jobs:
            obj = type("Job", (), dict(j))()
            if external_dash.is_stale(obj):
                stale += 1
            if external_dash.needs_attention(obj):
                needs_attention += 1
        archived = sum(1 for j in jobs if str(j["archived"]).lower() in ("1", "true", "yes"))
        cancelled = sum(1 for j in jobs if j["status"] == "CANCELLED")
        return {
            "waiting": waiting,
            "stale": stale,
            "needs_attention": needs_attention,
            "archived": archived,
            "cancelled": cancelled,
        }

    def _alerts(self, s: ObservatorySummary) -> List[ObservatoryAlert]:
        alerts = []
        if s.blocked_loops >= 3 or (s.total_loops and s.blocked_loops / s.total_loops >= 0.25):
            alerts.append(ObservatoryAlert(
                "warning", "blocked_loops",
                f"{s.blocked_loops} blocked loop(s) in this view",
                "python3 main.py --history --limit 10",
                json.dumps({"blocked_loops": s.blocked_loops}),
            ))
        if s.external_job_health.get("stale", 0):
            alerts.append(ObservatoryAlert(
                "warning", "stale_external_jobs",
                f"{s.external_job_health['stale']} external job(s) waiting longer than 24h",
                "python3 main.py --external-jobs --needs-attention",
                json.dumps({"stale": s.external_job_health["stale"]}),
            ))
        if s.quality_gate_failures >= 3:
            alerts.append(ObservatoryAlert(
                "warning", "quality_gate_failures",
                f"{s.quality_gate_failures} quality gate failure(s)",
                "python3 main.py --history --limit 10",
                json.dumps({"quality_gate_failures": s.quality_gate_failures}),
            ))
        if s.declined_approvals >= 3:
            alerts.append(ObservatoryAlert(
                "warning", "approval_declines",
                f"{s.declined_approvals} declined approval(s)",
                "python3 main.py --history --limit 10",
                json.dumps({"declined_approvals": s.declined_approvals}),
            ))
        if self._health_critical_count(s.time_window) > 0:
            alerts.append(ObservatoryAlert(
                "critical", "health_critical_issues",
                "critical external job health events exist",
                "python3 main.py --external-health",
                "{}",
            ))
        return alerts

    def _health_critical_count(self, tw):
        parts, vals = [], []
        if tw.start_at:
            parts.append("datetime(h.created_at) >= datetime(?)")
            vals.append(tw.start_at)
        parts.append("h.severity='critical'")
        parts.append("(j.id IS NULL OR COALESCE(j.archived,0) NOT IN (1,'1','true','yes'))")
        where = " WHERE " + " AND ".join(parts)
        return _count(
            self.conn,
            "SELECT COUNT(*) FROM external_job_health_events h "
            "LEFT JOIN external_agent_jobs j ON j.id=h.job_id" + where,
            vals,
        )


def summary_to_dict(summary: ObservatorySummary) -> dict:
    return asdict(summary)
