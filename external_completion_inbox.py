"""External Agent Completion Inbox (Stage 3.6).

Lets the user resume completed external agent jobs by dropping a completion file
into the job's generated directory, then running one sync command:

    external_agent_jobs/job_<id>/completion.json   (structured JSON, preferred)
    external_agent_jobs/job_<id>/completion.txt     (plain-text fallback)

SAFETY: the scanner ONLY looks inside external_agent_jobs/job_<id>/ for jobs that
exist in the DB; it refuses files whose realpath escapes that directory (symlink
defense), only accepts the two known filenames, never executes or interprets
completion contents, and always routes the actual import through ResumeEngine
(which re-validates the workspace and runs the Reviewer). Archived/cancelled jobs
are never imported.
"""

import json
import os
from dataclasses import dataclass, field
from typing import List, Optional

import database
import external_agent_jobs as eaj
import external_agents as ea

COMPLETION_JSON = "completion.json"
COMPLETION_TXT = "completion.txt"


@dataclass
class ExternalCompletionInboxItem:
    job_id: Optional[int]
    loop_id: Optional[int]
    agent_name: str
    job_status: str
    completion_path: Optional[str]
    completion_type: Optional[str]      # "json" | "txt" | None
    exists: bool = False
    parseable: bool = False
    imported: bool = False
    error: Optional[str] = None
    created_at: str = ""
    archived: bool = False
    cancelled: bool = False
    ignored_txt: bool = False           # completion.txt ignored in favor of .json


def _within_jobs_dir(path) -> bool:
    real = os.path.realpath(path)
    base = os.path.realpath(eaj.JOBS_DIR)
    return real == base or real.startswith(base + os.sep)


class ExternalCompletionInboxScanner:
    def __init__(self, conn):
        self.conn = conn
        self.mgr = eaj.ExternalAgentJobManager(conn)

    # --- discovery --------------------------------------------------------- #
    def find_completion_for_job(self, job_id):
        """Return (path, type, ignored_txt) for a job, preferring completion.json.
        Only files INSIDE the job's generated dir are considered."""
        try:
            d = eaj._job_dir(job_id)
        except ValueError:
            return None, None, False
        json_path = os.path.join(d, COMPLETION_JSON)
        txt_path = os.path.join(d, COMPLETION_TXT)
        has_json = os.path.isfile(json_path) and _within_jobs_dir(json_path)
        has_txt = os.path.isfile(txt_path) and _within_jobs_dir(txt_path)
        if has_json:
            return json_path, "json", has_txt  # ignored_txt True if .txt also present
        if has_txt:
            return txt_path, "txt", False
        return None, None, False

    def validate_completion_file(self, path):
        """Return (valid, completion_type, parseable, error, completion_obj)."""
        if not path or not os.path.isfile(path):
            return False, None, False, "completion file not found", None
        if not _within_jobs_dir(path):
            return False, None, False, "completion path outside external_agent_jobs/", None
        base = os.path.basename(path)
        if base not in (COMPLETION_JSON, COMPLETION_TXT):
            return False, None, False, f"unexpected completion filename: {base}", None
        ctype = "json" if base == COMPLETION_JSON else "txt"
        try:
            comp = ea.load_completion_file(path)
        except ValueError as exc:
            return False, ctype, False, str(exc), None
        if ctype == "json" and not comp.parsed:
            # A .json file that did not parse as JSON is invalid.
            return False, "json", False, "completion.json is not valid JSON", None
        # .txt may be raw (parsed False) and is still acceptable.
        return True, ctype, comp.parsed, None, comp

    def _job_is_importable(self, job):
        if job is None:
            return False, "no such job"
        if job.loop_id is None:
            return False, "job has no linked loop"
        if job.archived:
            return False, "job is archived (unarchive first)"
        if job.status == eaj.CANCELLED:
            return False, "job is cancelled"
        if job.status not in eaj.RESUMABLE_STATUSES:
            return False, f"job not resumable (status={job.status})"
        return True, None

    def scan_inbox(self, status=None, include_imported=False) -> List[ExternalCompletionInboxItem]:
        items = []
        jobs = self.mgr._list(status=status, limit=1000)
        for job in jobs:
            path, ctype, ignored_txt = self.find_completion_for_job(job.id)
            imported = job.status not in (
                eaj.CREATED, eaj.HANDOFF_READY, eaj.WAITING_FOR_EXTERNAL_AGENT)
            parseable = False
            error = None
            if path:
                valid, _ct, parseable, error, _c = self.validate_completion_file(path)
            it = ExternalCompletionInboxItem(
                job_id=job.id, loop_id=job.loop_id, agent_name=job.external_agent_name,
                job_status=job.status, completion_path=path, completion_type=ctype,
                exists=bool(path), parseable=parseable, imported=imported,
                error=error, created_at=job.created_at, archived=job.archived,
                cancelled=(job.status == eaj.CANCELLED), ignored_txt=ignored_txt)
            if path or include_imported:
                if include_imported or not imported:
                    items.append(it)
        return items

    def list_pending_completions(self) -> List[ExternalCompletionInboxItem]:
        """Items with a completion file, not yet imported, on importable jobs."""
        out = []
        for it in self.scan_inbox(include_imported=False):
            if not it.exists:
                continue
            job = self.mgr.get_job(it.job_id)
            ok, _why = self._job_is_importable(job)
            if ok:
                out.append(it)
        return out

    # --- import ------------------------------------------------------------ #
    def import_completion_for_job(self, job_id, path=None, dry_run=False,
                                  commit=False) -> dict:
        job = self.mgr.get_job(job_id)
        loop_id = job.loop_id if job else None
        if path is None and job is not None:
            path, _ctype, _ignored = self.find_completion_for_job(job_id)

        def rec_event(action, status, error=None, ctype=None):
            database.save_external_completion_inbox_event(
                self.conn, job_id, loop_id, path, ctype, action, status, error, dry_run)

        def gate(valid, reason):
            if loop_id is not None:
                r = database.LoopRecorder(self.conn, loop_id)
                r.save_quality_gate_result(
                    0, "external_completion_inbox_valid", valid, True,
                    "info" if valid else "error",
                    "inbox completion valid" if valid else reason)
                if not valid:
                    r.save_stop_condition_result(
                        0, "external_completion_inbox_invalid", True, "high", reason)

        importable, why = self._job_is_importable(job)
        if not importable:
            rec_event("skipped", "skipped", why)
            gate(False, why)
            return {"job_id": job_id, "loop_id": loop_id, "imported": False,
                    "status": "skipped", "error": why, "dry_run": dry_run}

        if not path:
            rec_event("skipped", "skipped", "no completion file found")
            gate(False, "no completion file found")
            return {"job_id": job_id, "loop_id": loop_id, "imported": False,
                    "status": "skipped", "error": "no completion file", "dry_run": dry_run}

        valid, ctype, _parseable, error, _comp = self.validate_completion_file(path)
        rec_event("discovered", "pending", None, ctype)
        if not valid:
            rec_event("failed", "failed", error, ctype)
            gate(False, error or "invalid completion file")
            return {"job_id": job_id, "loop_id": loop_id, "imported": False,
                    "status": "failed", "error": error, "completion_type": ctype,
                    "dry_run": dry_run}
        rec_event("validated", "valid", None, ctype)
        gate(True, "ok")

        if dry_run:
            rec_event("skipped", "dry_run", "dry-run: not imported", ctype)
            return {"job_id": job_id, "loop_id": loop_id, "imported": False,
                    "status": "dry_run", "error": None, "completion_type": ctype,
                    "dry_run": True, "completion_path": path}

        # Real import: route through the ResumeEngine (re-validates workspace +
        # runs the Reviewer; no bypass).
        import resume as resume_mod
        self.mgr.mark_completion_imported(job_id, path)
        database.save_external_agent_job_event(
            self.conn, job_id, loop_id, "completion_inbox_imported",
            job.status, eaj.COMPLETION_IMPORTED, json.dumps({"path": path}))
        req = resume_mod.ResumeRequest(loop_id=loop_id, completion_file=path,
                                       commit=commit)
        res = resume_mod.ResumeEngine().resume(
            self.conn, req, resume_type="completion_inbox")
        status_map = {"APPROVED": eaj.APPROVED, "BLOCKED": eaj.BLOCKED,
                      "REJECTED": eaj.REVIEWED, "REVIEW_INCONSISTENT": eaj.REVIEWED,
                      "FAILED": eaj.FAILED}
        final_job_status = status_map.get(res.status, eaj.REVIEWED)
        self.mgr.update_job_status(job_id, final_job_status)
        if res.status == "APPROVED":
            database.update_external_agent_job(
                self.conn, job_id, completed_at=database._now_iso())
        elif res.status in ("FAILED", "BLOCKED", "REVIEW_INCONSISTENT"):
            self.mgr.record_job_error(job_id, f"inbox resume ended {res.status}: {res.stop_reason}")
        rec_event("imported", res.status, None, ctype)
        return {"job_id": job_id, "loop_id": loop_id, "imported": True,
                "status": res.status, "job_status": final_job_status,
                "error": None, "completion_type": ctype,
                "report_path": res.report_path, "dry_run": False,
                "completion_path": path}

    def import_all_pending(self, limit=20, dry_run=False) -> List[dict]:
        results = []
        for it in self.list_pending_completions()[:limit]:
            results.append(self.import_completion_for_job(
                it.job_id, it.completion_path, dry_run=dry_run))
        return results
