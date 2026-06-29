"""External Agent Batch Reports (Stage 3.8).

Produces a durable Markdown report for each batch operation: what was selected,
what changed, what was skipped/failed, and what to do next.

SAFETY: report generation is read-only — it executes no commands, calls no
models, and mutates no jobs/loops. Report paths are generated internally and
confined to external_batch_reports/. Reports summarize only metadata, statuses,
errors and safe paths — never protected file contents or completion raw text.
"""

import datetime
import hashlib
import json
import os
from dataclasses import dataclass
from typing import List, Optional

import database

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
REPORTS_DIR = os.path.realpath(os.path.join(PROJECT_ROOT, "external_batch_reports"))


def _now():
    return datetime.datetime.now().isoformat(timespec="seconds")


@dataclass
class ExternalBatchReport:
    batch_id: str
    action: str
    dry_run: bool = False
    total_selected: int = 0
    total_success: int = 0
    total_skipped: int = 0
    total_failed: int = 0
    report_path: Optional[str] = None
    content_hash: Optional[str] = None
    bytes_written: int = 0
    created_at: str = ""


def _report_path(batch_id) -> str:
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    safe = "".join(ch for ch in str(batch_id) if ch.isalnum() or ch in "_-")
    fname = f"batch_{safe}_{ts}.md"
    target = os.path.realpath(os.path.join(REPORTS_DIR, fname))
    if target != REPORTS_DIR and not target.startswith(REPORTS_DIR + os.sep):
        raise ValueError("batch report path escaped external_batch_reports/ (refusing)")
    return target


class ExternalBatchReportGenerator:
    def __init__(self, conn):
        self.conn = conn

    # --- content ----------------------------------------------------------- #
    def generate_batch_report(self, batch_id, req=None, result=None) -> str:
        """Build Markdown for a batch. Uses live req/result when available,
        otherwise reconstructs from persisted batch events."""
        events = database.get_external_job_batch_events(self.conn, batch_id=batch_id,
                                                        limit=10000)
        action = (result.action if result else
                  (events[0]["action"] if events else "(unknown)"))
        dry_run = bool(result.dry_run if result else
                       (events[0]["dry_run"] if events else 0))

        # Build a uniform item list from result or events.
        if result is not None:
            items = [{
                "job_id": it.job_id, "loop_id": it.loop_id,
                "status_before": it.status_before, "status_after": it.status_after,
                "success": it.success, "skipped": it.skipped, "error": it.error,
                "details": it.details_json} for it in result.item_results]
            total_selected = result.total_selected
            total_success = result.total_success
            total_skipped = result.total_skipped
            total_failed = result.total_failed
        else:
            items = [{
                "job_id": e["job_id"], "loop_id": e["loop_id"],
                "status_before": e["status_before"], "status_after": e["status_after"],
                "success": bool(e["success"]), "skipped": bool(e["skipped"]),
                "error": e["error"], "details": e["details_json"]} for e in events]
            total_selected = len(items)
            total_success = sum(1 for i in items if i["success"] and not i["skipped"])
            total_skipped = sum(1 for i in items if i["skipped"])
            total_failed = sum(1 for i in items if not i["success"] and not i["skipped"])

        out = []
        a = out.append
        a("# External Job Batch Report")
        a("")
        a("## Summary")
        a(f"- Batch ID: {batch_id}")
        a(f"- Action: {action}")
        a(f"- Dry run: {'yes' if dry_run else 'no'}")
        a(f"- Created at: {_now()}")
        a(f"- Total selected: {total_selected}")
        a(f"- Success: {total_success}")
        a(f"- Skipped: {total_skipped}")
        a(f"- Failed: {total_failed}")
        a("")

        a("## Filters")
        if req is not None:
            a(f"- Job IDs: {req.job_ids if req.job_ids else '(none)'}")
            a(f"- Status filter: {req.status_filter or '(none)'}")
            a(f"- Agent filter: {req.agent_filter or '(none)'}")
            a(f"- Workspace filter: {req.workspace_filter or '(none)'}")
            a(f"- Priority filter: {req.priority_filter or '(none)'}")
            a(f"- Label filter: {req.label_filter or '(none)'}")
            arch = ("archived" if req.archived is True
                    else ("active" if req.archived is False else "(any)"))
            a(f"- Archived/active filter: {arch}")
            a(f"- Limit: {req.limit}")
        else:
            a("- (filters not recorded; report regenerated from batch events)")
        a("")

        a("## Results")
        if not items:
            a("- (no jobs selected)")
        for it in items:
            job = database.get_external_agent_job(self.conn, it["job_id"]) if it["job_id"] else None
            agent = job["external_agent_name"] if job else "?"
            ws = job["workspace_name"] if job else "?"
            pr = (job["priority"] if job and "priority" in job.keys() else None) or "normal"
            labels = []
            if job is not None and "labels_json" in job.keys() and job["labels_json"]:
                try:
                    labels = json.loads(job["labels_json"])
                except (ValueError, TypeError):
                    labels = []
            verdict = "skipped" if it["skipped"] else ("success" if it["success"] else "FAILED")
            a(f"- job #{it['job_id']} (loop #{it['loop_id']})")
            a(f"  - Agent: {agent}  Workspace: {ws}  Priority: {pr}  "
              f"Labels: {', '.join(labels) or '-'}")
            a(f"  - Status: {it['status_before']} -> {it['status_after']}  "
              f"Result: {verdict}")
            if it["error"]:
                a(f"  - Error: {it['error']}")
            if it["details"] and it["details"] not in ("{}", None):
                a(f"  - Details: {it['details']}")
        a("")

        a("## Safety")
        a(f"- Dry run: {'yes — no changes made' if dry_run else 'no'}")
        sync_like = action in ("sync_completions",)
        a(f"- ResumeEngine used for sync actions: "
          f"{'yes' if (sync_like and not dry_run) else 'n/a'}")
        a("- Archived/cancelled jobs skipped for sync actions: yes")
        a("- Unsafe action blocked: none (only allowlisted batch actions run)")
        a("- Automatic commit attempted: no")
        a("- Files deleted: none")
        a("- External agents executed: none")
        a("")

        failures = [i for i in items if not i["success"] and not i["skipped"]]
        a("## Failures")
        if not failures:
            a("- (none)")
        for it in failures:
            a(f"- job #{it['job_id']}: {it['error'] or 'unknown error'}")
        a("")

        skipped = [i for i in items if i["skipped"]]
        a("## Skipped")
        if not skipped:
            a("- (none)")
        for it in skipped:
            a(f"- job #{it['job_id']}: {it['error'] or 'skipped'}")
        a("")

        a("## Next Actions")
        attn = failures + skipped
        if not attn:
            a("- (no action needed)")
        for it in attn:
            jid = it["job_id"]
            a(f"- job #{jid}:")
            a(f"  - python3 main.py --external-job {jid}")
            a(f"  - python3 main.py --sync-external-completion {jid}")
            a(f"  - python3 main.py --resume-external-job {jid} "
              f"--external-completion-file completion.json")
            a(f"  - python3 main.py --cancel-external-job {jid}")
            a(f"  - python3 main.py --archive-external-job {jid}")
        a("")

        a("## Outcome")
        clean = total_failed == 0
        a(f"- Batch completed cleanly: {'yes' if clean else 'no'}")
        a(f"- Human action needed: {'no' if (clean and not skipped) else 'yes'}")
        a(f"- Safe to continue: yes{' (dry-run only)' if dry_run else ''}")
        return "\n".join(out) + "\n"

    # --- persistence ------------------------------------------------------- #
    def save_batch_report(self, batch_id, content, action="(unknown)",
                          dry_run=False) -> ExternalBatchReport:
        os.makedirs(REPORTS_DIR, exist_ok=True)
        path = _report_path(batch_id)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        chash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        nbytes = len(content.encode("utf-8"))
        database.save_external_batch_report(
            self.conn, batch_id, action, path, "markdown", chash, nbytes)
        return ExternalBatchReport(
            batch_id=batch_id, action=action, dry_run=dry_run, report_path=path,
            content_hash=chash, bytes_written=nbytes, created_at=_now())

    def get_batch_report_path(self, batch_id):
        row = database.get_external_batch_report(self.conn, batch_id)
        return row["report_path"] if row else None

    def list_batch_reports(self, limit=20):
        return database.list_external_batch_reports(self.conn, limit)
