"""Trend analysis for Loop Observatory snapshots (Stage 4.2).

Trend analysis reads persisted observatory snapshot JSON only. It never calls
models, executes commands, resumes jobs, imports completions, commits, or mutates
loop/job tables. Writes are limited to trend metadata and optional generated
Markdown under observatory_trend_reports/.
"""

import datetime
import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from typing import List, Optional

import database


PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
REPORTS_DIR = os.path.join(PROJECT_ROOT, "observatory_trend_reports")

TREND_METRICS = [
    "total_loops",
    "approved_loops",
    "failed_loops",
    "blocked_loops",
    "needs_human_loops",
    "paused_external_loops",
    "total_external_jobs",
    "waiting_external_jobs",
    "blocked_external_jobs",
    "failed_external_jobs",
    "total_reports",
    "total_approvals",
    "declined_approvals",
    "quality_gate_failures",
    "stop_condition_triggers",
    "alert_count",
    "critical_alert_count",
    "warning_alert_count",
]

POSITIVE_UP = {"approved_loops", "total_reports"}
NEGATIVE_UP = {
    "failed_loops",
    "blocked_loops",
    "needs_human_loops",
    "paused_external_loops",
    "waiting_external_jobs",
    "blocked_external_jobs",
    "failed_external_jobs",
    "declined_approvals",
    "quality_gate_failures",
    "stop_condition_triggers",
    "alert_count",
    "critical_alert_count",
    "warning_alert_count",
}
WARNING_UP = {"total_external_jobs"}

RECOMMENDATIONS = [
    "python3 main.py --observatory",
    "python3 main.py --observatory --save-report",
    "python3 main.py --external-health",
    "python3 main.py --external-dashboard",
    "python3 main.py --history --limit 10",
    "python3 main.py --reports",
]


@dataclass
class ObservatoryTrendPoint:
    snapshot_id: int
    generated_at: str
    time_window: str
    metric_name: str
    metric_value: float


@dataclass
class ObservatoryTrend:
    metric_name: str
    points: List[ObservatoryTrendPoint] = field(default_factory=list)
    first_value: float = 0
    last_value: float = 0
    delta: float = 0
    percent_change: Optional[float] = None
    direction: str = "insufficient_data"
    interpretation: str = "insufficient_data"


@dataclass
class ObservatoryTrendReport:
    generated_at: str
    snapshot_count: int
    start_snapshot_id: Optional[int]
    end_snapshot_id: Optional[int]
    trends: List[ObservatoryTrend] = field(default_factory=list)
    alerts: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=lambda: list(RECOMMENDATIONS))


@dataclass
class ObservatoryTrendMarkdownReport:
    trend_report_id: int
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


def _value(row, summary, metric):
    if metric in ("alert_count", "critical_alert_count", "warning_alert_count"):
        return float(row[metric] or 0)
    return float(summary.get(metric, 0) or 0)


def _clean_number(value):
    if value is None:
        return None
    if float(value).is_integer():
        return int(value)
    return round(float(value), 3)


def _direction(delta, point_count):
    if point_count < 2:
        return "insufficient_data"
    if delta > 0:
        return "up"
    if delta < 0:
        return "down"
    return "flat"


def _interpret(metric, direction):
    if direction == "insufficient_data":
        return "insufficient_data"
    if direction == "flat":
        return "neutral: unchanged"
    if metric in POSITIVE_UP:
        return "positive: improving" if direction == "up" else "warning: decreasing"
    if metric in NEGATIVE_UP:
        return "negative: worsening" if direction == "up" else "positive: improving"
    if metric in WARNING_UP:
        return "warning: increasing" if direction == "up" else "neutral: decreasing"
    return "neutral: informational"


def trend_to_dict(trend):
    return asdict(trend)


def report_to_dict(report):
    return asdict(report)


def trend_from_dict(data):
    points = [ObservatoryTrendPoint(**p) for p in data.get("points", [])]
    data = dict(data)
    data["points"] = points
    return ObservatoryTrend(**data)


def report_from_row(row):
    trends = [trend_from_dict(t) for t in _safe_json_loads(row["trends_json"], [])]
    alerts = _safe_json_loads(row["alerts_json"], [])
    recs = _safe_json_loads(row["recommendations_json"], [])
    return ObservatoryTrendReport(
        generated_at=row["generated_at"],
        snapshot_count=row["snapshot_count"] or 0,
        start_snapshot_id=row["start_snapshot_id"],
        end_snapshot_id=row["end_snapshot_id"],
        trends=trends,
        alerts=alerts,
        recommendations=recs,
    )


def is_markdown_report_path(path):
    if not path:
        return False
    target = os.path.realpath(path)
    base = os.path.realpath(REPORTS_DIR)
    return target != base and target.startswith(base + os.sep)


class ObservatoryTrendEngine:
    def __init__(self, conn):
        self.conn = conn

    def build_report(self, limit=10, window=None, workspace=None, metric=None):
        metrics = self._metrics(metric)
        rows = self._snapshot_rows(limit=limit, window=window, workspace=workspace)
        snapshot_count = len(rows)
        trends = [self._build_metric_trend(rows, name) for name in metrics]
        alerts = self._alerts(trends, snapshot_count)
        return ObservatoryTrendReport(
            generated_at=_now_iso(),
            snapshot_count=snapshot_count,
            start_snapshot_id=rows[0]["id"] if rows else None,
            end_snapshot_id=rows[-1]["id"] if rows else None,
            trends=trends,
            alerts=alerts,
            recommendations=list(RECOMMENDATIONS),
        )

    def save_trend_report(self, report, filters):
        return database.save_observatory_trend_report(
            self.conn,
            report.generated_at,
            report.snapshot_count,
            report.start_snapshot_id,
            report.end_snapshot_id,
            json.dumps(filters or {}, sort_keys=True),
            json.dumps([trend_to_dict(t) for t in report.trends], sort_keys=True),
            json.dumps(report.alerts, sort_keys=True),
            json.dumps(report.recommendations, sort_keys=True),
        )

    def save_markdown_report(self, trend_report_id, report):
        content = self.render_markdown(report, trend_report_id=trend_report_id)
        path = self._new_markdown_path(trend_report_id)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        encoded = content.encode("utf-8")
        chash = hashlib.sha256(encoded).hexdigest()
        nbytes = len(encoded)
        database.save_observatory_trend_markdown_report(
            self.conn, trend_report_id, path, "markdown", chash, nbytes)
        return ObservatoryTrendMarkdownReport(
            trend_report_id=trend_report_id,
            report_path=path,
            report_format="markdown",
            content_hash=chash,
            bytes_written=nbytes,
            created_at=_now_iso(),
        )

    def list_reports(self, limit=20):
        return database.list_observatory_trend_reports(self.conn, limit)

    def _metrics(self, metric):
        if not metric:
            return list(TREND_METRICS)
        if metric not in TREND_METRICS:
            raise ValueError(f"unknown observatory trend metric '{metric}'")
        return [metric]

    def _snapshot_rows(self, limit=10, window=None, workspace=None):
        rows = self.conn.execute(
            "SELECT * FROM observatory_snapshots ORDER BY id DESC"
        ).fetchall()
        filtered = []
        for row in rows:
            if window and row["time_window"] != window:
                continue
            filters = _safe_json_loads(row["filters_json"], {})
            if workspace and filters.get("workspace") != workspace:
                continue
            filtered.append(row)
            if len(filtered) >= int(limit or 10):
                break
        return list(reversed(filtered))

    def _build_metric_trend(self, rows, metric):
        points = []
        for row in rows:
            summary = _safe_json_loads(row["summary_json"], {})
            points.append(ObservatoryTrendPoint(
                snapshot_id=row["id"],
                generated_at=row["generated_at"],
                time_window=row["time_window"],
                metric_name=metric,
                metric_value=_clean_number(_value(row, summary, metric)),
            ))
        if not points:
            return ObservatoryTrend(metric_name=metric, points=[])
        first = points[0].metric_value
        last = points[-1].metric_value
        delta = last - first
        pct = None if first == 0 else round((delta / first) * 100.0, 1)
        direction = _direction(delta, len(points))
        return ObservatoryTrend(
            metric_name=metric,
            points=points,
            first_value=_clean_number(first),
            last_value=_clean_number(last),
            delta=_clean_number(delta),
            percent_change=pct,
            direction=direction,
            interpretation=_interpret(metric, direction),
        )

    def _alerts(self, trends, snapshot_count):
        if snapshot_count < 2:
            return ["not enough snapshots for trend analysis"]
        alerts = []
        labels = {
            "blocked_loops": "blocked loops increased",
            "failed_loops": "failed loops increased",
            "waiting_external_jobs": "external waiting jobs increased",
            "quality_gate_failures": "quality gate failures increased",
            "declined_approvals": "declined approvals increased",
            "failed_external_jobs": "failed external jobs increased",
            "critical_alert_count": "critical alerts increased",
        }
        for trend in trends:
            if trend.direction == "up" and trend.metric_name in labels:
                alerts.append(labels[trend.metric_name])
        return alerts

    def _new_markdown_path(self, trend_report_id):
        os.makedirs(REPORTS_DIR, exist_ok=True)
        filename = f"observatory_trends_{int(trend_report_id)}_{_now_stamp()}.md"
        target = os.path.realpath(os.path.join(REPORTS_DIR, filename))
        base = os.path.realpath(REPORTS_DIR)
        if target != base and not target.startswith(base + os.sep):
            raise ValueError("trend report path escaped observatory_trend_reports/")
        return target

    def render_markdown(self, report, trend_report_id=None):
        lines = []
        a = lines.append
        a("# Loop Engineering Observatory Trend Report")
        a("")
        a("## Summary")
        if trend_report_id is not None:
            a(f"- Trend report ID: {trend_report_id}")
        a(f"- Generated at: {report.generated_at}")
        a(f"- Snapshots analyzed: {report.snapshot_count}")
        a(f"- Start snapshot: {report.start_snapshot_id or '(none)'}")
        a(f"- End snapshot: {report.end_snapshot_id or '(none)'}")
        a("")
        a("## Key Trends")
        if not report.trends:
            a("- (none)")
        for trend in report.trends:
            pct = "n/a" if trend.percent_change is None else f"{trend.percent_change}%"
            a(f"- {trend.metric_name}: first={trend.first_value}, "
              f"last={trend.last_value}, delta={trend.delta}, "
              f"percent_change={pct}, direction={trend.direction}, "
              f"interpretation={trend.interpretation}")
        a("")
        a("## Alerts")
        if not report.alerts:
            a("- (none)")
        for alert in report.alerts:
            a(f"- {alert}")
        a("")
        a("## Recommendations")
        for rec in report.recommendations:
            a(f"- {rec}")
        a("")
        a("## Safety Notes")
        a("- Trend analysis only reads observatory snapshots")
        a("- No model calls")
        a("- No command execution")
        a("- No job mutation")
        a("- No loop mutation")
        a("")
        return "\n".join(lines)
