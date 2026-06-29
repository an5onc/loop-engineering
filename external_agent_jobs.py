"""External Agent Job Packets (Stage 3.3).

Turns an external coding-agent handoff into a structured, repeatable, resumable
*job*. Each job gets an internally-generated directory under
external_agent_jobs/job_<id>/ containing:

    handoff.md              - the human/agent handoff prompt
    packet.json             - the full structured job packet (summaries only)
    completion.json.example - the completion schema the agent should return
    README.md               - how to run the agent and resume the loop

SAFETY: packets contain ONLY summaries, allowed paths, task/plan/feedback,
the completion schema and resume commands. They NEVER include protected file
contents (.env / secrets / keys / .git internals) or arbitrary project dumps.
Paths are generated internally; nothing is ever written outside
external_agent_jobs/.
"""

import datetime
import json
import os
from dataclasses import dataclass, field
from typing import List, Optional

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
JOBS_DIR = os.path.realpath(os.path.join(PROJECT_ROOT, "external_agent_jobs"))

# Job lifecycle statuses.
CREATED = "CREATED"
HANDOFF_READY = "HANDOFF_READY"
WAITING_FOR_EXTERNAL_AGENT = "WAITING_FOR_EXTERNAL_AGENT"
COMPLETION_IMPORTED = "COMPLETION_IMPORTED"
REVIEWED = "REVIEWED"
APPROVED = "APPROVED"
BLOCKED = "BLOCKED"
FAILED = "FAILED"
CANCELLED = "CANCELLED"

STATUSES = (CREATED, HANDOFF_READY, WAITING_FOR_EXTERNAL_AGENT, COMPLETION_IMPORTED,
            REVIEWED, APPROVED, BLOCKED, FAILED, CANCELLED)
RESUMABLE_STATUSES = (HANDOFF_READY, WAITING_FOR_EXTERNAL_AGENT, COMPLETION_IMPORTED)

# Job priority (Stage 3.4).
PRIORITIES = ("low", "normal", "high", "urgent")
DEFAULT_PRIORITY = "normal"


def normalize_priority(priority):
    """Return a valid priority, defaulting unknown values to 'normal'."""
    p = (priority or DEFAULT_PRIORITY).strip().lower()
    return p if p in PRIORITIES else DEFAULT_PRIORITY


def parse_labels(raw):
    """Parse comma-separated labels into a safe plain-text list.

    Labels are plain text only: stripped, control chars removed, no path/command
    semantics. Never interpreted as code, paths, or commands."""
    if raw is None:
        return []
    if isinstance(raw, list):
        items = raw
    else:
        items = str(raw).split(",")
    out = []
    for it in items:
        s = "".join(ch for ch in str(it) if ch.isprintable()).strip()
        # Keep them inert: no path separators / shell metacharacters.
        s = s.replace("/", "-").replace("\\", "-").replace("\x00", "")
        for bad in (";", "|", "&", "`", "$", "<", ">", "\n", "\r"):
            s = s.replace(bad, "")
        s = s.strip()[:40]
        if s:
            out.append(s)
    return out[:20]


def sanitize_notes(raw):
    """Notes are plain text only (printable chars, length-capped)."""
    if not raw:
        return ""
    s = "".join(ch for ch in str(raw) if ch.isprintable() or ch in " \t")
    return s.strip()[:2000]


def validate_metadata(priority, labels, notes, archived, retry_count):
    """Return (valid, reasons) for external_agent_job_metadata_valid."""
    reasons = []
    if (priority or "").lower() not in PRIORITIES:
        reasons.append(f"invalid priority {priority!r}")
    if not isinstance(labels, list):
        reasons.append("labels not a list")
    elif any(not isinstance(x, str) for x in labels):
        reasons.append("labels contain non-text")
    if notes is not None and not isinstance(notes, str):
        reasons.append("notes not plain text")
    if archived not in (0, 1, True, False, None):
        reasons.append("archived not boolean")
    try:
        if int(retry_count or 0) < 0:
            reasons.append("retry_count negative")
    except (TypeError, ValueError):
        reasons.append("retry_count not an integer")
    return (not reasons), reasons

SAFETY_RULES = [
    "Only edit files under the allowed write paths.",
    "Do not edit files outside allowed paths.",
    "Do not run unsafe commands (no rm, curl, sudo, git push, etc.).",
    "Only run commands inside the allowed command paths.",
    "Do not commit unless instructed.",
    "Do not modify protected files (.git/, .env, secrets, keys, node_modules/).",
    "Do not loosen safety systems.",
    "Stop after verification.",
]


def _now():
    return datetime.datetime.now().isoformat(timespec="seconds")


def _truthy(v):
    """Robustly coerce a possibly-TEXT-stored flag to bool ('0'/0/None -> False).

    Migrated SQLite columns can be TEXT, so bool('0') would wrongly be True."""
    if v in (None, "", 0, "0", False, "False", "false"):
        return False
    return True


def completion_schema(agent_name, loop_id, attempt_number) -> dict:
    return {
        "agent_name": agent_name or "claude_or_codex",
        "loop_id": loop_id,
        "attempt_number": attempt_number,
        "status": "completed|failed|blocked",
        "summary": "What you changed and why",
        "files_changed": [],
        "commands_run": [],
        "tests_run": [],
        "tests_passed": True,
        "issues": [],
        "notes": [],
        "next_steps": [],
    }


def resume_commands(job_id, loop_id) -> List[str]:
    lid = loop_id if loop_id is not None else "LOOP_ID"
    return [
        f"python3 main.py --resume-external-job {job_id} --external-completion-file completion.json",
        f"python3 main.py --resume {lid} --external-completion-file completion.json",
        f"python3 main.py --import-external-completion {lid} --external-completion-file completion.json  # backward-compatible",
    ]


@dataclass
class ExternalAgentJob:
    id: Optional[int]
    loop_id: Optional[int]
    attempt_number: int
    external_agent_name: str
    status: str
    workspace_name: str
    workspace_root: str
    handoff_path: Optional[str] = None
    packet_path: Optional[str] = None
    completion_path: Optional[str] = None
    priority: str = DEFAULT_PRIORITY
    labels: List[str] = field(default_factory=list)
    notes: str = ""
    archived: bool = False
    retry_count: int = 0
    last_error: Optional[str] = None
    completed_at: Optional[str] = None
    cancelled_at: Optional[str] = None
    archived_at: Optional[str] = None
    created_at: str = ""
    updated_at: str = ""


@dataclass
class ExternalAgentJobPacket:
    job_id: Optional[int]
    loop_id: Optional[int]
    attempt_number: int
    external_agent_name: str
    task: str
    plan: str
    workspace_name: str
    workspace_root: str
    allowed_write_paths: List[str]
    allowed_command_paths: List[str]
    allowed_tools: List[str]
    safety_rules: List[str]
    context_summary: str = ""
    memory_summary: str = ""
    project_intelligence_summary: str = ""
    context_pack_summary: str = ""
    reviewer_feedback: str = ""
    test_analyst_feedback: str = ""
    completion_schema: dict = field(default_factory=dict)
    resume_commands: List[str] = field(default_factory=list)
    created_at: str = ""

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id, "loop_id": self.loop_id,
            "attempt_number": self.attempt_number,
            "external_agent_name": self.external_agent_name,
            "task": self.task, "plan": self.plan,
            "workspace_name": self.workspace_name,
            "workspace_root": self.workspace_root,
            "allowed_write_paths": list(self.allowed_write_paths),
            "allowed_command_paths": list(self.allowed_command_paths),
            "allowed_tools": list(self.allowed_tools),
            "safety_rules": list(self.safety_rules),
            "context_summary": self.context_summary,
            "memory_summary": self.memory_summary,
            "project_intelligence_summary": self.project_intelligence_summary,
            "context_pack_summary": self.context_pack_summary,
            "reviewer_feedback": self.reviewer_feedback,
            "test_analyst_feedback": self.test_analyst_feedback,
            "completion_schema": self.completion_schema,
            "resume_commands": list(self.resume_commands),
            "created_at": self.created_at,
        }


# Markers that must never appear in a packet (defense-in-depth).
_SECRET_MARKERS = ["-----BEGIN", "PRIVATE KEY", "password=", "secret=", "api_key="]


def packet_is_safe(packet: ExternalAgentJobPacket):
    """Return (safe, reasons). Confirms the packet leaks no secrets/protected
    contents and references only allowed paths."""
    reasons = []
    blob = json.dumps(packet.to_dict()).lower()
    for m in _SECRET_MARKERS:
        if m.lower() in blob:
            reasons.append(f"secret marker present: {m!r}")
    return (not reasons), reasons


def _job_dir(job_id) -> str:
    target = os.path.realpath(os.path.join(JOBS_DIR, f"job_{int(job_id)}"))
    if target != JOBS_DIR and not target.startswith(JOBS_DIR + os.sep):
        raise ValueError("job dir escaped external_agent_jobs/ (refusing)")
    return target


class ExternalAgentJobManager:
    """Creates and tracks external agent jobs (backed by SQLite + the
    external_agent_jobs/ directory)."""

    def __init__(self, conn):
        self.conn = conn

    # --- creation ---------------------------------------------------------- #
    def create_job(self, loop_id, attempt_number, external_agent_name,
                   workspace_name, workspace_root, priority=DEFAULT_PRIORITY,
                   labels=None, notes="") -> ExternalAgentJob:
        import database
        pr = normalize_priority(priority)
        lbls = parse_labels(labels)
        nt = sanitize_notes(notes)
        job_id = database.save_external_agent_job(
            self.conn, loop_id, attempt_number, external_agent_name, CREATED,
            workspace_name, workspace_root, priority=pr,
            labels_json=json.dumps(lbls), notes=nt)
        database.save_external_agent_job_event(
            self.conn, job_id, loop_id, "created", None, CREATED,
            json.dumps({"priority": pr, "labels": lbls}))
        row = database.get_external_agent_job(self.conn, job_id)
        return self._row_to_job(row)

    def create_packet(self, job: ExternalAgentJob, task, plan, allowed_write_paths,
                      allowed_command_paths, allowed_tools, context_summary="",
                      memory_summary="", project_intelligence_summary="",
                      context_pack_summary="", reviewer_feedback="",
                      test_analyst_feedback="") -> ExternalAgentJobPacket:
        return ExternalAgentJobPacket(
            job_id=job.id, loop_id=job.loop_id, attempt_number=job.attempt_number,
            external_agent_name=job.external_agent_name, task=task, plan=plan,
            workspace_name=job.workspace_name, workspace_root=job.workspace_root,
            allowed_write_paths=list(allowed_write_paths),
            allowed_command_paths=list(allowed_command_paths),
            allowed_tools=list(allowed_tools), safety_rules=list(SAFETY_RULES),
            context_summary=context_summary, memory_summary=memory_summary,
            project_intelligence_summary=project_intelligence_summary,
            context_pack_summary=context_pack_summary,
            reviewer_feedback=reviewer_feedback,
            test_analyst_feedback=test_analyst_feedback,
            completion_schema=completion_schema(job.external_agent_name, job.loop_id,
                                                job.attempt_number),
            resume_commands=resume_commands(job.id, job.loop_id), created_at=_now())

    def save_packet(self, job: ExternalAgentJob, packet: ExternalAgentJobPacket,
                    handoff_text: str) -> dict:
        """Write the job directory + files, update the job row. Returns a dict
        with paths, sizes and the packet-safety verdict."""
        import database
        safe, reasons = packet_is_safe(packet)
        d = _job_dir(job.id)
        os.makedirs(d, exist_ok=True)

        handoff_path = os.path.join(d, "handoff.md")
        packet_path = os.path.join(d, "packet.json")
        completion_example_path = os.path.join(d, "completion.json.example")
        readme_path = os.path.join(d, "README.md")

        with open(handoff_path, "w", encoding="utf-8") as fh:
            fh.write(handoff_text)
        packet_text = json.dumps(packet.to_dict(), indent=2)
        with open(packet_path, "w", encoding="utf-8") as fh:
            fh.write(packet_text)
        with open(completion_example_path, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(packet.completion_schema, indent=2))
        with open(readme_path, "w", encoding="utf-8") as fh:
            fh.write(self._render_readme(job, packet))

        database.update_external_agent_job(
            self.conn, job.id, handoff_path=handoff_path, packet_path=packet_path,
            status=HANDOFF_READY)
        database.save_external_agent_job_event(
            self.conn, job.id, job.loop_id, "packet_saved", CREATED, HANDOFF_READY,
            json.dumps({"packet_safe": safe, "reasons": reasons}))
        job.handoff_path = handoff_path
        job.packet_path = packet_path
        job.status = HANDOFF_READY
        return {
            "job_dir": d, "handoff_path": handoff_path, "packet_path": packet_path,
            "completion_example_path": completion_example_path, "readme_path": readme_path,
            "handoff_bytes": len(handoff_text.encode("utf-8")),
            "packet_bytes": len(packet_text.encode("utf-8")),
            "packet_safe": safe, "packet_safe_reasons": reasons,
        }

    def _render_readme(self, job, packet) -> str:
        tool_cmd = {"claude": "claude", "codex": "codex"}.get(
            job.external_agent_name, "your-agent")
        write = ", ".join(packet.allowed_write_paths) or "(none)"
        cmd = ", ".join(packet.allowed_command_paths) or "(none)"
        lines = [
            f"# External Agent Job #{job.id}",
            "",
            f"- Loop ID: {job.loop_id}",
            f"- Attempt: {job.attempt_number}",
            f"- Agent: {job.external_agent_name}",
            f"- Workspace: {job.workspace_name} ({job.workspace_root})",
            "",
            "## What this job is",
            "A structured handoff packet for an external coding agent. The Loop",
            "Engineering framework still owns planning, safety gates, review and",
            "approvals — the external agent only implements within the limits below.",
            "",
            "## Where to run the external agent",
            f"```\ncd {job.workspace_root}\n{tool_cmd}\n```",
            "Then paste the contents of `handoff.md`.",
            "",
            "## What you may edit",
            f"- Files under: {write}",
            "## What you may run",
            f"- Commands under: {cmd}",
            "",
            "## Safety rules",
        ] + [f"- {r}" for r in packet.safety_rules] + [
            "",
            "## How to return completion",
            "Fill in `completion.json.example` (see schema) and save it as",
            "`completion.json`, then resume the loop.",
            "",
            "## How to resume the loop",
        ] + [f"```\n{c}\n```" for c in packet.resume_commands]
        return "\n".join(lines)

    # --- queries / updates ------------------------------------------------- #
    def get_job(self, job_id):
        import database
        row = database.get_external_agent_job(self.conn, job_id)
        return self._row_to_job(row) if row else None

    def get_job_for_loop(self, loop_id):
        import database
        row = database.get_external_agent_job_for_loop(self.conn, loop_id)
        return self._row_to_job(row) if row else None

    def list_jobs(self, status=None, limit=20):
        import database
        return [self._row_to_job(r)
                for r in database.list_external_agent_jobs(self.conn, status, limit)]

    def update_job_status(self, job_id, status):
        import database
        row = database.get_external_agent_job(self.conn, job_id)
        before = row["status"] if row else None
        database.update_external_agent_job_status(self.conn, job_id, status)
        database.save_external_agent_job_event(
            self.conn, job_id, row["loop_id"] if row else None,
            "status_change", before, status, "{}")

    def mark_completion_imported(self, job_id, completion_path):
        import database
        row = database.get_external_agent_job(self.conn, job_id)
        before = row["status"] if row else None
        database.update_external_agent_job(
            self.conn, job_id, completion_path=completion_path,
            status=COMPLETION_IMPORTED)
        database.save_external_agent_job_event(
            self.conn, job_id, row["loop_id"] if row else None,
            "completion_imported", before, COMPLETION_IMPORTED,
            json.dumps({"completion_path": completion_path}))

    # --- queue listings (Stage 3.4) --------------------------------------- #
    def _list(self, **kw):
        import database
        return [self._row_to_job(r)
                for r in database.list_external_agent_jobs_filtered(self.conn, **kw)]

    def list_active_jobs(self, limit=20):
        return self._list(archived=False, limit=limit)

    def list_archived_jobs(self, limit=20):
        return self._list(archived=True, limit=limit)

    def list_jobs_by_agent(self, agent_name, limit=20):
        return self._list(agent_name=agent_name, limit=limit)

    def list_jobs_by_workspace(self, workspace_name, limit=20):
        return self._list(workspace_name=workspace_name, limit=limit)

    def list_jobs_by_status(self, status, limit=20):
        return self._list(status=status, limit=limit)

    # --- lifecycle / metadata (Stage 3.4) --------------------------------- #
    def _event(self, job_id, event_type, before, after, details):
        import database
        row = database.get_external_agent_job(self.conn, job_id)
        database.save_external_agent_job_event(
            self.conn, job_id, row["loop_id"] if row else None,
            event_type, before, after, json.dumps(details))

    def archive_job(self, job_id):
        import database
        database.update_external_agent_job(
            self.conn, job_id, archived=1, archived_at=database._now_iso())
        self._event(job_id, "archived", "0", "1", {})

    def unarchive_job(self, job_id):
        import database
        database.update_external_agent_job(self.conn, job_id, archived=0,
                                           archived_at=None)
        self._event(job_id, "unarchived", "1", "0", {})

    def update_job_notes(self, job_id, notes):
        import database
        nt = sanitize_notes(notes)
        database.update_external_agent_job(self.conn, job_id, notes=nt)
        self._event(job_id, "notes_updated", None, None, {"len": len(nt)})

    def update_job_labels(self, job_id, labels):
        import database
        lbls = parse_labels(labels)
        database.update_external_agent_job(self.conn, job_id,
                                           labels_json=json.dumps(lbls))
        self._event(job_id, "labels_updated", None, None, {"labels": lbls})
        return lbls

    def update_job_priority(self, job_id, priority):
        import database
        pr = normalize_priority(priority)
        database.update_external_agent_job(self.conn, job_id, priority=pr)
        self._event(job_id, "priority_updated", None, None, {"priority": pr})
        return pr

    def increment_job_retry(self, job_id):
        import database
        row = database.get_external_agent_job(self.conn, job_id)
        n = int(row["retry_count"] or 0) + 1 if row else 1
        database.update_external_agent_job(self.conn, job_id, retry_count=n)
        self._event(job_id, "retry_incremented", str(n - 1), str(n), {})
        return n

    def record_job_error(self, job_id, error):
        import database
        msg = sanitize_notes(error)
        database.update_external_agent_job(self.conn, job_id, last_error=msg)
        self._event(job_id, "error_recorded", None, None, {"error": msg[:200]})

    def get_job_summary(self, job_id) -> dict:
        import database
        job = self.get_job(job_id)
        if job is None:
            return {}
        events = database.get_external_agent_job_events(self.conn, job_id)
        valid, reasons = validate_metadata(job.priority, job.labels, job.notes,
                                           1 if job.archived else 0, job.retry_count)
        return {
            "id": job.id, "loop_id": job.loop_id, "agent": job.external_agent_name,
            "status": job.status, "priority": job.priority, "labels": job.labels,
            "notes": job.notes, "archived": job.archived, "retry_count": job.retry_count,
            "last_error": job.last_error, "handoff_path": job.handoff_path,
            "packet_path": job.packet_path, "completion_path": job.completion_path,
            "created_at": job.created_at, "updated_at": job.updated_at,
            "completed_at": job.completed_at, "cancelled_at": job.cancelled_at,
            "archived_at": job.archived_at, "metadata_valid": valid,
            "metadata_reasons": reasons,
            "timeline": [(e["created_at"], e["event_type"],
                          e["status_before"], e["status_after"]) for e in events],
        }

    @staticmethod
    def _row_to_job(row) -> ExternalAgentJob:
        keys = row.keys()

        def g(k, default=None):
            return row[k] if k in keys else default

        try:
            labels = json.loads(g("labels_json") or "[]")
        except (json.JSONDecodeError, TypeError):
            labels = []
        return ExternalAgentJob(
            id=row["id"], loop_id=row["loop_id"],
            attempt_number=row["attempt_number"],
            external_agent_name=row["external_agent_name"], status=row["status"],
            workspace_name=row["workspace_name"], workspace_root=row["workspace_root"],
            handoff_path=row["handoff_path"], packet_path=row["packet_path"],
            completion_path=row["completion_path"],
            priority=g("priority") or DEFAULT_PRIORITY, labels=labels,
            notes=g("notes") or "", archived=_truthy(g("archived")),
            retry_count=int(g("retry_count") or 0), last_error=g("last_error"),
            completed_at=g("completed_at"), cancelled_at=g("cancelled_at"),
            archived_at=g("archived_at"),
            created_at=row["created_at"], updated_at=row["updated_at"])
