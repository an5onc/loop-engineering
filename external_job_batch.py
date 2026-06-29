"""External Agent Batch Operations (Stage 3.7).

Run controlled batch actions over a *selection* of external agent jobs: sync
completions, archive/unarchive, cancel, change priority/labels, clear errors,
flag for attention, or just list the selection.

SAFETY: batches never touch jobs outside the selection, never delete files /
reports / DB rows, never auto-commit, never run external agents, and never bypass
the ResumeEngine. Sync/resume actions skip archived/cancelled jobs and jobs
without a valid completion file. Every action supports --dry-run (no DB writes,
no resume, no Ollama).
"""

import datetime
import json
from dataclasses import dataclass, field
from typing import List, Optional

import database
import external_agent_jobs as eaj

# Actions that, when run for real, change the workspace/loop via ResumeEngine.
SYNC_ACTIONS = ("sync_completions",)
# Actions that should never operate on archived/cancelled jobs.
SKIP_ARCHIVED_CANCELLED = ("sync_completions",)

ACTIONS = (
    "sync_completions", "archive", "unarchive", "cancel", "set_priority",
    "add_label", "remove_label", "set_labels", "clear_error",
    "mark_needs_attention", "list_selected",
)
LABEL_ACTIONS = ("add_label", "remove_label", "set_labels")
JOBIDS_REQUIRED = ()  # job_ids never strictly required; filters may select instead


@dataclass
class ExternalJobBatchRequest:
    action: str
    job_ids: Optional[List[int]] = None
    status_filter: Optional[str] = None
    agent_filter: Optional[str] = None
    workspace_filter: Optional[str] = None
    priority_filter: Optional[str] = None
    label_filter: Optional[str] = None
    archived: Optional[bool] = None
    dry_run: bool = False
    limit: int = 100
    # Action payloads
    priority: Optional[str] = None
    label: Optional[str] = None
    labels: Optional[str] = None
    created_at: str = ""


@dataclass
class ExternalJobBatchItemResult:
    job_id: Optional[int]
    loop_id: Optional[int]
    action: str
    status_before: Optional[str] = None
    status_after: Optional[str] = None
    success: bool = False
    skipped: bool = False
    error: Optional[str] = None
    details_json: str = "{}"


@dataclass
class ExternalJobBatchResult:
    action: str
    batch_id: str = ""
    total_selected: int = 0
    total_success: int = 0
    total_skipped: int = 0
    total_failed: int = 0
    dry_run: bool = False
    valid_selection: bool = True
    invalid_reason: Optional[str] = None
    item_results: List[ExternalJobBatchItemResult] = field(default_factory=list)
    created_at: str = ""


def _now():
    return datetime.datetime.now().isoformat(timespec="seconds")


def _batch_id():
    return "batch_" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")


class ExternalJobBatchManager:
    def __init__(self, conn):
        self.conn = conn
        self.mgr = eaj.ExternalAgentJobManager(conn)

    # --- selection --------------------------------------------------------- #
    def select_jobs(self, req: ExternalJobBatchRequest):
        if req.job_ids:
            jobs = [self.mgr.get_job(jid) for jid in req.job_ids]
            jobs = [j for j in jobs if j is not None]
        else:
            jobs = self.mgr._list(
                archived=req.archived, agent_name=req.agent_filter,
                workspace_name=req.workspace_filter, status=req.status_filter,
                limit=1000)
        if req.priority_filter:
            pf = req.priority_filter.lower()
            jobs = [j for j in jobs if (j.priority or "normal").lower() == pf]
        if req.label_filter:
            lf = req.label_filter.strip()
            jobs = [j for j in jobs if lf in (j.labels or [])]
        return jobs[: max(0, req.limit)]

    # --- validation -------------------------------------------------------- #
    def validate(self, req: ExternalJobBatchRequest):
        """Return (valid, reason)."""
        if req.action not in ACTIONS:
            return False, f"unknown action {req.action!r}"
        if req.action == "set_priority":
            if not req.priority or req.priority.lower() not in eaj.PRIORITIES:
                return False, f"invalid priority {req.priority!r}"
        if req.action in ("add_label", "remove_label"):
            if not req.label or not eaj.parse_labels(req.label):
                return False, f"invalid label input {req.label!r}"
        if req.action == "set_labels":
            if req.labels is None:
                return False, "set_labels requires --labels"
        if req.job_ids is not None:
            missing = [jid for jid in req.job_ids
                       if self.mgr.get_job(jid) is None]
            if missing:
                return False, f"job IDs do not exist: {missing}"
        return True, None

    # --- execution --------------------------------------------------------- #
    def run(self, req: ExternalJobBatchRequest) -> ExternalJobBatchResult:
        batch_id = _batch_id()
        res = ExternalJobBatchResult(action=req.action, batch_id=batch_id,
                                     dry_run=req.dry_run, created_at=_now())
        valid, reason = self.validate(req)
        if not valid:
            res.valid_selection = False
            res.invalid_reason = reason
            return res

        jobs = self.select_jobs(req)
        res.total_selected = len(jobs)
        for job in jobs:
            item = self._apply(req, job, batch_id)
            res.item_results.append(item)
            if item.skipped:
                res.total_skipped += 1
            elif item.success:
                res.total_success += 1
            else:
                res.total_failed += 1
        return res

    def _record(self, batch_id, item: ExternalJobBatchItemResult, dry_run):
        database.save_external_job_batch_event(
            self.conn, batch_id, item.action, item.job_id, item.loop_id,
            item.status_before, item.status_after, item.success, item.skipped,
            item.error, item.details_json, dry_run)

    def _apply(self, req, job, batch_id) -> ExternalJobBatchItemResult:
        item = ExternalJobBatchItemResult(
            job_id=job.id, loop_id=job.loop_id, action=req.action,
            status_before=job.status)
        action = req.action

        # Resume/sync actions never touch archived/cancelled jobs.
        if action in SKIP_ARCHIVED_CANCELLED and (job.archived
                                                  or job.status == eaj.CANCELLED):
            item.skipped = True
            item.error = "archived/cancelled job skipped"
            item.status_after = job.status
            self._record(batch_id, item, req.dry_run)
            return item

        if req.dry_run:
            item.success = True  # would-succeed
            item.status_after = job.status
            item.details_json = json.dumps({"dry_run": True, "planned": action})
            self._record(batch_id, item, True)
            return item

        try:
            self._do(action, req, job, item)
        except Exception as exc:  # defensive: one bad item never aborts the batch
            item.success = False
            item.error = f"{type(exc).__name__}: {exc}"
            item.status_after = job.status
        self._record(batch_id, item, False)
        return item

    def _do(self, action, req, job, item):
        jid = job.id
        if action == "list_selected":
            item.success = True
            item.status_after = job.status
            item.details_json = json.dumps({
                "agent": job.external_agent_name, "priority": job.priority,
                "labels": job.labels, "archived": job.archived})
            return

        if action == "sync_completions":
            import external_completion_inbox as inbox
            sc = inbox.ExternalCompletionInboxScanner(self.conn)
            path, _ct, _ig = sc.find_completion_for_job(jid)
            if not path:
                item.skipped = True
                item.error = "no completion file"
                item.status_after = job.status
                return
            r = sc.import_completion_for_job(jid, path, dry_run=False)
            item.status_after = r.get("job_status") or job.status
            item.details_json = json.dumps({"resume_status": r.get("status")})
            if r.get("imported"):
                item.success = True
            elif r.get("status") in ("skipped",):
                item.skipped = True
                item.error = r.get("error")
            else:
                item.success = False
                item.error = r.get("error") or f"resume {r.get('status')}"
            return

        if action == "archive":
            self.mgr.archive_job(jid)
            item.success = True
            item.status_after = job.status
            return
        if action == "unarchive":
            self.mgr.unarchive_job(jid)
            item.success = True
            item.status_after = job.status
            return
        if action == "cancel":
            self.mgr.update_job_status(jid, eaj.CANCELLED)
            database.update_external_agent_job(self.conn, jid,
                                               cancelled_at=database._now_iso())
            item.success = True
            item.status_after = eaj.CANCELLED
            return
        if action == "set_priority":
            pr = self.mgr.update_job_priority(jid, req.priority)
            item.success = True
            item.status_after = job.status
            item.details_json = json.dumps({"priority": pr})
            return
        if action == "set_labels":
            lbls = self.mgr.update_job_labels(jid, req.labels)
            item.success = True
            item.status_after = job.status
            item.details_json = json.dumps({"labels": lbls})
            return
        if action == "add_label":
            new = list(job.labels or [])
            for lb in eaj.parse_labels(req.label):
                if lb not in new:
                    new.append(lb)
            lbls = self.mgr.update_job_labels(jid, new)
            item.success = True
            item.status_after = job.status
            item.details_json = json.dumps({"labels": lbls})
            return
        if action == "remove_label":
            drop = set(eaj.parse_labels(req.label))
            new = [lb for lb in (job.labels or []) if lb not in drop]
            lbls = self.mgr.update_job_labels(jid, new)
            item.success = True
            item.status_after = job.status
            item.details_json = json.dumps({"labels": lbls})
            return
        if action == "clear_error":
            database.update_external_agent_job(self.conn, jid, last_error=None)
            self.mgr._event(jid, "error_cleared", None, None, {})
            item.success = True
            item.status_after = job.status
            return
        if action == "mark_needs_attention":
            new = list(job.labels or [])
            if "needs-attention" not in new:
                new.append("needs-attention")
            self.mgr.update_job_labels(jid, new)
            item.success = True
            item.status_after = job.status
            return
        item.error = f"unhandled action {action}"
