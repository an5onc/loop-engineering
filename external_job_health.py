"""External Agent Job Health Checks (Stage 3.9).

Read-only auditing of the external agent job queue: detects stale jobs, missing
packet files, invalid metadata, broken report links, pending completions, unsafe
job folders, and queue inconsistencies.

SAFETY: the checker executes no commands, calls no models, reads no arbitrary
files, follows no symlinks outside the expected directories, never resumes jobs
or imports completions, never commits or deletes. It only inspects known
generated paths under external_agent_jobs/ and the allowed report directories.
`--fix-safe` performs only metadata-only safe fixes (never file/loop mutations).
"""

import datetime
import json
import os
from dataclasses import dataclass, field
from typing import List, Optional

import database
import external_agent_jobs as eaj
import external_agent_dashboard as dash

# Severities
INFO, WARNING, ERROR, CRITICAL = "info", "warning", "error", "critical"

# Markers that should never appear in a packet/handoff (protected_content_risk).
_PROTECTED_MARKERS = ["-----BEGIN", "PRIVATE KEY", "password=", "secret=",
                      "api_key=", "id_rsa", "id_ed25519",
                      "PROTECTED_CONTENT_MARKER_FOR_TEST_ONLY"]
_MAX_SCAN_BYTES = 256 * 1024


def _now():
    return datetime.datetime.now().isoformat(timespec="seconds")


def _within(path, base) -> bool:
    if not path:
        return False
    real = os.path.realpath(path)
    base = os.path.realpath(base)
    return real == base or real.startswith(base + os.sep)


@dataclass
class ExternalJobHealthIssue:
    job_id: Optional[int]
    loop_id: Optional[int]
    severity: str
    issue_type: str
    message: str
    recommended_action: str
    details_json: str = "{}"
    detected_at: str = ""
    fixed: bool = False
    fix_action: Optional[str] = None


@dataclass
class ExternalJobHealthReport:
    generated_at: str = ""
    total_jobs_checked: int = 0
    healthy_jobs: int = 0
    warning_jobs: int = 0
    failed_jobs: int = 0          # jobs with error/critical issues
    issues: List[ExternalJobHealthIssue] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)
    # convenience counters
    critical_jobs: int = 0
    stale_waiting: int = 0
    pending_completions: int = 0
    missing_files_jobs: int = 0
    broken_reference_jobs: int = 0


class ExternalJobHealthChecker:
    def __init__(self, conn):
        self.conn = conn
        self.mgr = eaj.ExternalAgentJobManager(conn)

    def _scan_for_markers(self, path):
        """Read a known generated file (size-capped) and return markers found.
        Only ever called on files confirmed inside external_agent_jobs/."""
        try:
            if os.path.getsize(path) > _MAX_SCAN_BYTES:
                return []
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                blob = fh.read().lower()
        except OSError:
            return []
        return [m for m in _PROTECTED_MARKERS if m.lower() in blob]

    def check_job(self, job, now=None) -> List[ExternalJobHealthIssue]:
        now = now or datetime.datetime.now()
        issues = []

        def add(sev, itype, msg, action, details=None):
            issues.append(ExternalJobHealthIssue(
                job_id=job.id, loop_id=job.loop_id, severity=sev, issue_type=itype,
                message=msg, recommended_action=action,
                details_json=json.dumps(details or {}), detected_at=_now()))

        # --- metadata validity ---
        if job.status not in eaj.STATUSES:
            add(ERROR, "job_status_invalid", f"status {job.status!r} not allowed",
                f"python3 main.py --external-job {job.id}")
        if (job.priority or "normal").lower() not in eaj.PRIORITIES:
            add(WARNING, "priority_invalid", f"priority {job.priority!r} invalid",
                f"python3 main.py --set-external-job-priority {job.id} normal")
        # labels_json validity (raw column check)
        row = database.get_external_agent_job(self.conn, job.id)
        lj = row["labels_json"] if row and "labels_json" in row.keys() else None
        if lj:
            try:
                v = json.loads(lj)
                if not isinstance(v, list):
                    raise ValueError("not a list")
            except (ValueError, TypeError):
                add(WARNING, "labels_invalid", "labels_json malformed / not list-like",
                    f"python3 main.py --set-external-job-labels {job.id} \"\"")

        # --- loop existence ---
        if job.loop_id is None or database.get_loop(self.conn, job.loop_id) is None:
            add(ERROR, "loop_missing_for_job",
                f"job references missing loop {job.loop_id}",
                f"python3 main.py --external-job {job.id}")

        # --- path safety + directory/files ---
        try:
            d = eaj._job_dir(job.id)
        except ValueError:
            d = None
        for label, p in (("handoff_path", job.handoff_path),
                         ("packet_path", job.packet_path)):
            if p and not _within(p, eaj.JOBS_DIR):
                add(CRITICAL, "job_path_outside_allowed_dir",
                    f"{label} points outside external_agent_jobs/: {p}",
                    f"python3 main.py --external-job {job.id}")

        if d is None or not os.path.isdir(d):
            add(ERROR, "missing_job_directory",
                f"job directory external_agent_jobs/job_{job.id}/ is missing",
                f"python3 main.py --external-job {job.id}")
        else:
            checks = [("handoff.md", "missing_handoff", ERROR),
                      ("packet.json", "missing_packet", ERROR),
                      ("README.md", "missing_readme", WARNING),
                      ("completion.json.example", "missing_completion_example", WARNING)]
            for fname, itype, sev in checks:
                fpath = os.path.join(d, fname)
                if not (os.path.isfile(fpath) and _within(fpath, eaj.JOBS_DIR)):
                    add(sev, itype, f"{fname} missing in job_{job.id}/",
                        f"python3 main.py --external-job {job.id}")
            # invalid packet json
            pj = os.path.join(d, "packet.json")
            if os.path.isfile(pj) and _within(pj, eaj.JOBS_DIR):
                try:
                    with open(pj, "r", encoding="utf-8") as fh:
                        json.load(fh)
                except (ValueError, OSError):
                    add(ERROR, "invalid_packet_json",
                        f"packet.json in job_{job.id}/ cannot be parsed",
                        f"python3 main.py --external-job {job.id}")
            # protected content risk (handoff + packet only)
            for fname in ("handoff.md", "packet.json"):
                fpath = os.path.join(d, fname)
                if os.path.isfile(fpath) and _within(fpath, eaj.JOBS_DIR):
                    found = self._scan_for_markers(fpath)
                    if found:
                        add(CRITICAL, "protected_content_risk",
                            f"{fname} in job_{job.id}/ contains protected markers: {found}",
                            f"python3 main.py --external-job {job.id}",
                            {"markers": found})

        # --- completion presence vs status ---
        comp_path, _ct, _ig = self._find_completion(job.id)
        has_completion = comp_path is not None
        imported = job.status not in (eaj.CREATED, eaj.HANDOFF_READY,
                                      eaj.WAITING_FOR_EXTERNAL_AGENT)

        if job.status == eaj.WAITING_FOR_EXTERNAL_AGENT and dash.is_stale(job, now):
            add(WARNING, "stale_waiting_job",
                f"waiting > 24h (age {dash.human_age(job.created_at, now)})",
                f"python3 main.py --sync-external-completion {job.id}  # or cancel")
        if job.archived and job.status == eaj.WAITING_FOR_EXTERNAL_AGENT:
            add(WARNING, "archived_waiting_job",
                "archived job still marked WAITING_FOR_EXTERNAL_AGENT",
                f"python3 main.py --cancel-external-job {job.id} (after unarchive)")
        if job.status == eaj.CANCELLED and has_completion:
            add(INFO, "cancelled_with_completion",
                "cancelled job has a completion file present (ignored)",
                f"python3 main.py --external-job {job.id}")
        if (job.status == eaj.WAITING_FOR_EXTERNAL_AGENT and has_completion
                and not job.archived):
            add(WARNING, "completion_waiting_import",
                "completion file ready but not imported",
                f"python3 main.py --sync-external-completion {job.id}")

        # --- broken report references ---
        if job.loop_id is not None:
            rr = database.get_run_report(self.conn, job.loop_id)
            if rr is not None and rr["report_path"]:
                rp = rr["report_path"]
                import reports as _rep
                if not (os.path.exists(rp) and (_within(rp, _rep.REPORTS_DIR))):
                    add(WARNING, "broken_report_reference",
                        f"run report missing/outside reports/: {rp}",
                        f"python3 main.py --report {job.loop_id}")
        bevs = database.get_external_job_batch_events(self.conn, job_id=job.id, limit=20)
        seen = set()
        import external_batch_reports as _ebr
        for be in bevs:
            bid = be["batch_id"]
            if not bid or bid in seen:
                continue
            seen.add(bid)
            br = database.get_external_batch_report(self.conn, bid)
            if br is not None and br["report_path"]:
                bp = br["report_path"]
                if not (os.path.exists(bp) and _within(bp, _ebr.REPORTS_DIR)):
                    add(WARNING, "broken_report_reference",
                        f"batch report missing/outside external_batch_reports/: {bp}",
                        f"python3 main.py --external-batch-report {bid}")
        return issues

    def _find_completion(self, job_id):
        try:
            import external_completion_inbox as inbox
            return inbox.ExternalCompletionInboxScanner(self.conn).find_completion_for_job(job_id)
        except Exception:
            return None, None, False

    # --- whole-queue check ------------------------------------------------- #
    def run(self, agent=None, workspace=None, status=None, include_archived=False,
            fix_safe=False, now=None) -> ExternalJobHealthReport:
        now = now or datetime.datetime.now()
        archived = None if include_archived else False
        jobs = self.mgr._list(archived=archived, agent_name=agent,
                              workspace_name=workspace, status=status, limit=1000)
        rep = ExternalJobHealthReport(generated_at=_now(), total_jobs_checked=len(jobs))
        for job in jobs:
            issues = self.check_job(job, now)
            sevs = {i.severity for i in issues}
            if not issues:
                rep.healthy_jobs += 1
            elif CRITICAL in sevs or ERROR in sevs:
                rep.failed_jobs += 1
                if CRITICAL in sevs:
                    rep.critical_jobs += 1
            elif WARNING in sevs:
                rep.warning_jobs += 1
            else:
                rep.healthy_jobs += 1  # info-only
            types = {i.issue_type for i in issues}
            if "stale_waiting_job" in types:
                rep.stale_waiting += 1
            if "completion_waiting_import" in types:
                rep.pending_completions += 1
            if types & {"missing_job_directory", "missing_handoff", "missing_packet",
                        "missing_readme", "missing_completion_example"}:
                rep.missing_files_jobs += 1
            if "broken_report_reference" in types:
                rep.broken_reference_jobs += 1

            if fix_safe:
                self._apply_safe_fixes(job, issues)

            for it in issues:
                rep.issues.append(it)
                # Persist each detected issue as a health event (+ loop metrics).
                database.save_external_job_health_event(
                    self.conn, it.job_id, it.loop_id, it.severity, it.issue_type,
                    it.message, it.recommended_action, it.details_json,
                    fixed=it.fixed, fix_action=it.fix_action)
            if job.loop_id is not None and issues:
                rec = database.LoopRecorder(self.conn, job.loop_id)
                rec.save_metric("external_health_issue_detected", 1, "bool")
                rec.save_metric("external_health_issue_count", len(issues), "count")
                rec.save_metric("external_health_critical_count",
                                sum(1 for i in issues if i.severity == CRITICAL), "count")
                rec.save_metric("external_health_pending_completion_count",
                                sum(1 for i in issues
                                    if i.issue_type == "completion_waiting_import"), "count")
                if CRITICAL in sevs:
                    rec.save_stop_condition_result(
                        0, "external_job_health_critical", True, "critical",
                        f"critical health issue on job #{job.id}")
                # Health-check safety gate (read-only unless fix-safe; never unsafe).
                rec.save_quality_gate_result(
                    0, "external_job_health_check_safe", True, True, "info",
                    "read-only health check; no commands/model/unsafe reads"
                    + ("; metadata-only safe fixes applied" if fix_safe else ""))

        rep.recommendations = sorted({i.recommended_action for i in rep.issues})
        return rep

    def _apply_safe_fixes(self, job, issues):
        """Metadata-only safe fixes. Never deletes/creates files, resumes, imports,
        commits, or calls models."""
        for it in issues:
            # Archived + WAITING mismatch with no completion -> mark CANCELLED.
            if it.issue_type == "archived_waiting_job":
                comp, _t, _i = self._find_completion(job.id)
                if comp is None:
                    database.update_external_agent_job(
                        self.conn, job.id, status=eaj.CANCELLED,
                        cancelled_at=database._now_iso())
                    self.mgr._event(job.id, "health_safe_fix",
                                    eaj.WAITING_FOR_EXTERNAL_AGENT, eaj.CANCELLED,
                                    {"fix": "archived_waiting_job"})
                    it.fixed = True
                    it.fix_action = "archived WAITING job set to CANCELLED (no completion)"
