"""Review and audit layer for Observatory action handoffs (Stage 4.8).

Handoff review reads handoff/action metadata and produces deterministic
classifications before broader handoff use. It never executes suggested
commands, calls models, creates loops/jobs, imports completions, resumes work,
commits, or reads protected file contents. Writes are limited to review metadata
and optional Markdown reports under observatory_action_handoff_review_reports/.
"""

import datetime
import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from typing import List

import database


PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
REPORTS_DIR = os.path.join(PROJECT_ROOT, "observatory_action_handoff_review_reports")
GROUP_BY = {"status", "type", "workspace"}
REVIEW_STATUSES = {
    "safe_dry_run",
    "needs_review",
    "confirmed_loop_created",
    "confirmed_external_job_created",
    "blocked",
    "suspicious",
    "unknown",
}


@dataclass
class ActionHandoffReviewItem:
    handoff_id: int
    action_id: int
    handoff_type: str
    status: str
    target_loop_type: str
    target_workspace: str
    external_coder: str
    created_loop_id: int = None
    created_external_job_id: int = None
    generated_task_preview: str = ""
    risk_level: str = ""
    safety_notes: List[str] = field(default_factory=list)
    review_status: str = "unknown"
    review_score: int = 0
    rationale: str = ""
    recommended_action: str = ""
    created_at: str = ""


@dataclass
class ActionHandoffReviewGroup:
    group_key: str
    group_type: str
    count: int
    handoff_ids: List[int] = field(default_factory=list)
    summary: str = ""
    recommended_action: str = ""


@dataclass
class ActionHandoffReviewReport:
    generated_at: str
    total_handoffs_reviewed: int
    filters_json: str
    groups: List[ActionHandoffReviewGroup] = field(default_factory=list)
    items: List[ActionHandoffReviewItem] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)
    next_steps: List[str] = field(default_factory=list)


@dataclass
class ActionHandoffReviewMarkdownReport:
    handoff_review_id: int
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


def group_to_dict(group):
    return asdict(group)


def item_from_dict(data):
    return ActionHandoffReviewItem(**data)


def group_from_dict(data):
    return ActionHandoffReviewGroup(**data)


def report_from_row(row):
    return ActionHandoffReviewReport(
        generated_at=row["generated_at"],
        total_handoffs_reviewed=row["total_handoffs_reviewed"] or 0,
        filters_json=row["filters_json"] or "{}",
        groups=[group_from_dict(g) for g in _safe_json_loads(row["groups_json"], [])],
        items=[item_from_dict(i) for i in _safe_json_loads(row["items_json"], [])],
        recommendations=_safe_json_loads(row["recommendations_json"], []),
        next_steps=_safe_json_loads(row["next_steps_json"], []),
    )


def is_markdown_report_path(path):
    if not path:
        return False
    target = os.path.realpath(path)
    base = os.path.realpath(REPORTS_DIR)
    return target != base and target.startswith(base + os.sep)


def _preview(text, limit=180):
    cleaned = " ".join((text or "").split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[:limit - 3] + "..."


def _unsafe_command_text(text):
    lowered = (text or "").lower()
    dangerous = (
        "rm -rf",
        "sudo ",
        "curl ",
        "wget ",
        "bash -c",
        "sh -c",
        "python3 -c",
        "python -c",
        ">",
        "<",
        "`",
        "$(",
        "&&",
        "||",
        ";",
        "|",
    )
    return any(token in lowered for token in dangerous)


class ActionHandoffReviewEngine:
    def __init__(self, conn):
        self.conn = conn

    def build_report(self, status=None, handoff_type=None, workspace=None,
                     external_coder=None, group_by="status", limit=25):
        if group_by not in GROUP_BY:
            raise ValueError(f"unknown handoff review group '{group_by}'")
        limit = int(limit or 25)
        rows = database.list_observatory_action_handoffs(self.conn, 1000)
        reviewed = [self._review_handoff(row) for row in rows]
        reviewed = self._filter_items(
            reviewed,
            status=status,
            handoff_type=handoff_type,
            workspace=workspace,
            external_coder=external_coder,
        )[:limit]
        groups = self._groups(reviewed, group_by)
        recommendations, next_steps = self._recommendations(reviewed)
        filters = {
            "status": status,
            "type": handoff_type,
            "workspace": workspace,
            "external_coder": external_coder,
            "group_by": group_by,
            "limit": limit,
        }
        return ActionHandoffReviewReport(
            generated_at=_now_iso(),
            total_handoffs_reviewed=len(reviewed),
            filters_json=json.dumps(filters, sort_keys=True),
            groups=groups,
            items=reviewed,
            recommendations=recommendations,
            next_steps=next_steps,
        )

    def save_review(self, report, group_by="status"):
        return database.save_observatory_action_handoff_review(
            self.conn,
            report.generated_at,
            report.filters_json,
            group_by,
            report.total_handoffs_reviewed,
            json.dumps([group_to_dict(g) for g in report.groups], sort_keys=True),
            json.dumps([item_to_dict(i) for i in report.items], sort_keys=True),
            json.dumps(report.recommendations, sort_keys=True),
            json.dumps(report.next_steps, sort_keys=True),
        )

    def save_markdown_report(self, review_id, report):
        content = self.render_markdown(report, review_id)
        path = self._new_report_path(review_id)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        encoded = content.encode("utf-8")
        chash = hashlib.sha256(encoded).hexdigest()
        nbytes = len(encoded)
        database.save_observatory_action_handoff_review_markdown_report(
            self.conn, review_id, path, "markdown", chash, nbytes)
        return ActionHandoffReviewMarkdownReport(
            handoff_review_id=review_id,
            report_path=path,
            report_format="markdown",
            content_hash=chash,
            bytes_written=nbytes,
            created_at=_now_iso(),
        )

    def _review_handoff(self, row):
        status = row["status"] or ""
        handoff_type = row["handoff_type"] or ""
        generated_task = row["generated_task"] or ""
        external_coder = row["external_coder"] or ""
        target_workspace = row["target_workspace"] or ""
        suggested_command = row["suggested_command"] or ""
        created_loop_id = row["created_loop_id"]
        created_external_job_id = row["created_external_job_id"]
        safety_notes = _safe_json_loads(row["safety_notes_json"], [])

        review_status = "unknown"
        rationale = []
        if status.lower() in ("failed", "blocked") or status.upper() in ("FAILED", "BLOCKED"):
            review_status = "blocked"
            rationale.append(f"handoff status is {status}")
        elif not generated_task.strip():
            review_status = "suspicious"
            rationale.append("generated task is missing")
        elif _unsafe_command_text(suggested_command):
            review_status = "suspicious"
            rationale.append("suggested command contains unsafe-looking text")
        elif handoff_type == "external_agent_job" and not external_coder:
            review_status = "needs_review"
            rationale.append("external agent job handoff is missing external coder")
        elif target_workspace and not self._workspace_known(target_workspace):
            review_status = "needs_review"
            rationale.append(f"target workspace {target_workspace!r} is not registered")
        elif handoff_type == "loop_task" and created_loop_id:
            review_status = "confirmed_loop_created"
            rationale.append(f"created loop #{created_loop_id}")
        elif handoff_type == "external_agent_job" and created_external_job_id:
            review_status = "confirmed_external_job_created"
            rationale.append(f"created external job #{created_external_job_id}")
        elif row["dry_run"]:
            review_status = "safe_dry_run"
            rationale.append("dry-run handoff only")
        else:
            review_status = "needs_review"
            rationale.append("non-dry-run handoff needs manual review")

        risk_level = self._risk_for(review_status)
        return ActionHandoffReviewItem(
            handoff_id=row["id"],
            action_id=row["action_id"],
            handoff_type=handoff_type,
            status=status,
            target_loop_type=row["target_loop_type"] or "",
            target_workspace=target_workspace,
            external_coder=external_coder,
            created_loop_id=created_loop_id,
            created_external_job_id=created_external_job_id,
            generated_task_preview=_preview(generated_task),
            risk_level=risk_level,
            safety_notes=safety_notes,
            review_status=review_status,
            review_score=self._score_for(review_status),
            rationale="; ".join(rationale),
            recommended_action=self._recommended_action(row["id"], row["action_id"],
                                                        created_loop_id,
                                                        created_external_job_id,
                                                        review_status),
            created_at=row["created_at"] or "",
        )

    def _workspace_known(self, name):
        if name == "default":
            return True
        return database.get_project_workspace(self.conn, name) is not None

    def _filter_items(self, items, status=None, handoff_type=None,
                      workspace=None, external_coder=None):
        out = []
        for item in items:
            if status is not None and item.review_status != status:
                continue
            if handoff_type is not None and item.handoff_type != handoff_type:
                continue
            if workspace is not None and item.target_workspace != workspace:
                continue
            if external_coder is not None and item.external_coder != external_coder:
                continue
            out.append(item)
        out.sort(key=lambda item: (-item.review_score, item.handoff_id))
        return out

    def _groups(self, items, group_by):
        grouped = {}
        for item in items:
            key = self._group_key(item, group_by)
            grouped.setdefault(key, []).append(item)
        out = []
        for key, vals in grouped.items():
            vals.sort(key=lambda item: (-item.review_score, item.handoff_id))
            out.append(ActionHandoffReviewGroup(
                group_key=key,
                group_type=group_by,
                count=len(vals),
                handoff_ids=[v.handoff_id for v in vals[:10]],
                summary=f"{len(vals)} handoff(s) grouped by {group_by}={key}",
                recommended_action=vals[0].recommended_action,
            ))
        out.sort(key=lambda group: (-group.count, group.group_key))
        return out

    def _group_key(self, item, group_by):
        if group_by == "status":
            return item.review_status or "(unknown)"
        if group_by == "type":
            return item.handoff_type or "(unknown)"
        if group_by == "workspace":
            return item.target_workspace or "(unknown)"
        return "(unknown)"

    def _recommendations(self, items):
        recs = []
        next_steps = ["python3 main.py --observatory-action-handoffs"]
        for item in items[:5]:
            recs.append(f"python3 main.py --observatory-action-handoff {item.handoff_id}")
            recs.append(f"python3 main.py --observatory-action {item.action_id}")
            if item.created_loop_id:
                recs.append(f"python3 main.py --show {item.created_loop_id}")
            if item.created_external_job_id:
                recs.append(f"python3 main.py --external-job {item.created_external_job_id}")
        for cmd in recs:
            if cmd not in next_steps:
                next_steps.append(cmd)
        return _dedupe(recs), next_steps

    def _new_report_path(self, review_id):
        os.makedirs(REPORTS_DIR, exist_ok=True)
        filename = f"observatory_action_handoff_review_{int(review_id)}_{_now_stamp()}.md"
        target = os.path.realpath(os.path.join(REPORTS_DIR, filename))
        base = os.path.realpath(REPORTS_DIR)
        if target != base and not target.startswith(base + os.sep):
            raise ValueError(
                "handoff review report path escaped observatory_action_handoff_review_reports/")
        return target

    def render_markdown(self, report, review_id=None):
        lines = []
        a = lines.append
        a("# Observatory Action Handoff Review")
        a("")
        a("## Summary")
        if review_id is not None:
            a(f"- Review ID: {review_id}")
        a(f"- Generated at: {report.generated_at}")
        a(f"- Handoffs reviewed: {report.total_handoffs_reviewed}")
        a(f"- Filters: {report.filters_json}")
        a("")
        a("## Groups")
        if not report.groups:
            a("- (none)")
        for group in report.groups:
            a(f"- {group.group_type}={group.group_key} count={group.count} "
              f"handoffs={group.handoff_ids}")
            a(f"  action: {group.recommended_action}")
        a("")
        a("## Handoffs")
        if not report.items:
            a("- (none)")
        for item in report.items:
            a(f"- handoff #{item.handoff_id} action=#{item.action_id} "
              f"type={item.handoff_type} status={item.status} "
              f"review={item.review_status} score={item.review_score}")
            a(f"  target: loop={item.target_loop_type} workspace={item.target_workspace} "
              f"external={item.external_coder}")
            a(f"  created: loop={item.created_loop_id or '(none)'} "
              f"job={item.created_external_job_id or '(none)'}")
            a(f"  task: {item.generated_task_preview}")
            a(f"  rationale: {item.rationale}")
            a(f"  recommended: {item.recommended_action}")
        a("")
        a("## Recommendations")
        if not report.recommendations:
            a("- (none)")
        for rec in report.recommendations:
            a(f"- {rec}")
        a("")
        a("## Next Steps")
        if not report.next_steps:
            a("- (none)")
        for step in report.next_steps:
            a(f"- {step}")
        a("")
        a("## Safety Notes")
        a("- Handoff review only reads handoff and action metadata")
        a("- Suggested commands are not executed")
        a("- No model calls")
        a("- No command execution")
        a("- No loop or external-job creation")
        a("- No completion imports or resumes")
        a("")
        return "\n".join(lines)

    def _risk_for(self, review_status):
        return {
            "safe_dry_run": "low",
            "confirmed_loop_created": "medium",
            "confirmed_external_job_created": "medium",
            "needs_review": "medium",
            "blocked": "high",
            "suspicious": "high",
            "unknown": "medium",
        }.get(review_status, "medium")

    def _score_for(self, review_status):
        return {
            "suspicious": 100,
            "blocked": 90,
            "needs_review": 70,
            "confirmed_external_job_created": 50,
            "confirmed_loop_created": 45,
            "unknown": 40,
            "safe_dry_run": 10,
        }.get(review_status, 40)

    def _recommended_action(self, handoff_id, action_id, created_loop_id,
                            created_external_job_id, review_status):
        if created_loop_id:
            return f"python3 main.py --show {created_loop_id}"
        if created_external_job_id:
            return f"python3 main.py --external-job {created_external_job_id}"
        if review_status in ("suspicious", "blocked", "needs_review", "unknown"):
            return f"python3 main.py --observatory-action-handoff {handoff_id}"
        return f"python3 main.py --observatory-action {action_id}"


def _dedupe(items):
    out = []
    for item in items:
        if item not in out:
            out.append(item)
    return out
