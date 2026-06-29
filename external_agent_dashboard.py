"""External Agent Job Dashboard (Stage 3.5).

A read-only terminal dashboard + triage layer over the external agent job queue.
It never creates loops, never calls Ollama, and never writes project files — it
only reads the job queue (and may record a few dashboard metrics on the most
recent existing job, never a new loop).
"""

import datetime
from dataclasses import dataclass, field
from typing import List, Optional

import external_agent_jobs as eaj

STALE_THRESHOLD_SECONDS = 24 * 3600
ATTENTION_PRIORITIES = ("high", "urgent")


def _parse_ts(ts):
    """Parse an ISO-ish timestamp ('YYYY-MM-DDTHH:MM:SS' or space-separated)."""
    if not ts:
        return None
    try:
        return datetime.datetime.fromisoformat(str(ts).strip().replace("Z", ""))
    except (ValueError, TypeError):
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.datetime.strptime(str(ts).strip()[:19], fmt)
            except ValueError:
                continue
    return None


def age_seconds(ts, now=None):
    """Seconds since ts, or None if unparseable. Clamped at >= 0."""
    dt = _parse_ts(ts)
    if dt is None:
        return None
    now = now or datetime.datetime.now()
    return max(0.0, (now - dt).total_seconds())


def human_age(ts, now=None):
    """Human-readable age string (s/m/h/d), or 'unknown'."""
    secs = age_seconds(ts, now)
    if secs is None:
        return "unknown"
    if secs < 60:
        return f"{int(secs)}s"
    if secs < 3600:
        return f"{int(secs // 60)}m"
    if secs < 86400:
        return f"{int(secs // 3600)}h"
    return f"{int(secs // 86400)}d"


def is_stale(job, now=None):
    """Waiting job whose created_at is older than 24h."""
    if job.status != eaj.WAITING_FOR_EXTERNAL_AGENT:
        return False
    secs = age_seconds(job.created_at, now)
    return secs is not None and secs > STALE_THRESHOLD_SECONDS


def needs_attention(job, now=None):
    """A job needing operator attention."""
    if job.status in (eaj.FAILED, eaj.BLOCKED):
        return True
    if job.last_error:
        return True
    if (job.status == eaj.WAITING_FOR_EXTERNAL_AGENT
            and (job.priority or "").lower() in ATTENTION_PRIORITIES):
        return True
    return is_stale(job, now)


def attention_reason(job, now=None):
    reasons = []
    if job.status == eaj.FAILED:
        reasons.append("failed")
    if job.status == eaj.BLOCKED:
        reasons.append("blocked")
    if job.last_error:
        reasons.append("has error")
    if (job.status == eaj.WAITING_FOR_EXTERNAL_AGENT
            and (job.priority or "").lower() in ATTENTION_PRIORITIES):
        reasons.append(f"{job.priority} waiting")
    if is_stale(job, now):
        reasons.append("stale (>24h waiting)")
    return ", ".join(reasons) or "needs review"


def suggested_command(job):
    """Exact next action for an attention item."""
    jid = job.id
    if job.status == eaj.WAITING_FOR_EXTERNAL_AGENT:
        return (f"python3 main.py --resume-external-job {jid} "
                f"--external-completion-file completion.json")
    if job.status in (eaj.FAILED, eaj.BLOCKED):
        return f"python3 main.py --external-job {jid}   # inspect, then cancel/archive"
    return f"python3 main.py --external-job {jid}"


@dataclass
class ExternalJobDashboardSummary:
    total: int = 0
    active: int = 0
    archived: int = 0
    waiting: int = 0
    completed: int = 0
    cancelled: int = 0
    blocked: int = 0
    failed: int = 0
    by_agent: dict = field(default_factory=dict)
    by_workspace: dict = field(default_factory=dict)
    by_priority: dict = field(default_factory=dict)
    oldest_waiting: Optional[object] = None
    newest: Optional[object] = None
    high_urgent_waiting: int = 0
    with_errors: int = 0
    needing_attention: int = 0
    stale: int = 0


class ExternalJobDashboardRenderer:
    def __init__(self, conn):
        self.conn = conn
        self.mgr = eaj.ExternalAgentJobManager(conn)

    def _orphan_paused_loops(self):
        """Paused external loops that have no matching job row."""
        import database
        out = []
        for r in database.list_paused_external_loops(self.conn, 50):
            if database.get_external_agent_job_for_loop(self.conn, r["id"]) is None:
                out.append(r)
        return out

    def build_summary(self, jobs, now=None) -> ExternalJobDashboardSummary:
        now = now or datetime.datetime.now()
        s = ExternalJobDashboardSummary(total=len(jobs))
        oldest_secs = -1.0
        for j in jobs:
            if j.archived:
                s.archived += 1
            else:
                s.active += 1
            if j.status == eaj.WAITING_FOR_EXTERNAL_AGENT:
                s.waiting += 1
            elif j.status == eaj.APPROVED:
                s.completed += 1
            elif j.status == eaj.CANCELLED:
                s.cancelled += 1
            elif j.status == eaj.BLOCKED:
                s.blocked += 1
            elif j.status == eaj.FAILED:
                s.failed += 1
            s.by_agent[j.external_agent_name] = s.by_agent.get(j.external_agent_name, 0) + 1
            s.by_workspace[j.workspace_name] = s.by_workspace.get(j.workspace_name, 0) + 1
            pr = (j.priority or "normal").lower()
            s.by_priority[pr] = s.by_priority.get(pr, 0) + 1
            if j.last_error:
                s.with_errors += 1
            if (j.status == eaj.WAITING_FOR_EXTERNAL_AGENT
                    and pr in ATTENTION_PRIORITIES):
                s.high_urgent_waiting += 1
            if is_stale(j, now):
                s.stale += 1
            if needs_attention(j, now):
                s.needing_attention += 1
            if j.status == eaj.WAITING_FOR_EXTERNAL_AGENT:
                secs = age_seconds(j.created_at, now) or 0.0
                if secs > oldest_secs:
                    oldest_secs = secs
                    s.oldest_waiting = j
        if jobs:
            s.newest = jobs[0]  # listings are ordered id DESC
        return s

    def render(self, workspace=None, agent=None, archived=None, now=None):
        """Render the dashboard. Returns the summary (for optional metrics)."""
        now = now or datetime.datetime.now()
        jobs = self.mgr._list(archived=archived, agent_name=agent,
                              workspace_name=workspace, limit=1000)
        summary = self.build_summary(jobs, now)
        orphans = self._orphan_paused_loops()

        out = []
        a = out.append
        bar = "=" * 70
        a(bar)
        a("EXTERNAL AGENT JOB DASHBOARD")
        filt = ", ".join(f for f in [
            f"workspace={workspace}" if workspace else "",
            f"agent={agent}" if agent else "",
            "archived" if archived is True else ("active" if archived is False else "")]
            if f)
        if filt:
            a(f"(filter: {filt})")
        a(bar)

        a("\nSUMMARY")
        a(f"- Total jobs : {summary.total}")
        a(f"- Active     : {summary.active}")
        a(f"- Waiting    : {summary.waiting}")
        a(f"- Completed  : {summary.completed}")
        a(f"- Blocked    : {summary.blocked}")
        a(f"- Failed     : {summary.failed}")
        a(f"- Cancelled  : {summary.cancelled}")
        a(f"- Archived   : {summary.archived}")
        if summary.oldest_waiting is not None:
            j = summary.oldest_waiting
            a(f"- Oldest waiting: job #{j.id} ({human_age(j.created_at, now)} old)")
        if summary.newest is not None:
            a(f"- Newest job : job #{summary.newest.id} "
              f"({human_age(summary.newest.created_at, now)} old)")

        a("\nBY AGENT")
        if summary.by_agent:
            for name, n in sorted(summary.by_agent.items()):
                a(f"- {name}: {n}")
        else:
            a("- (none)")

        a("\nBY PRIORITY")
        for pr in ("urgent", "high", "normal", "low"):
            a(f"- {pr}: {summary.by_priority.get(pr, 0)}")

        a("\nBY WORKSPACE")
        if summary.by_workspace:
            for name, n in sorted(summary.by_workspace.items()):
                a(f"- {name}: {n}")
        else:
            a("- (none)")

        a("\nNEEDS ATTENTION")
        attn = [j for j in jobs if needs_attention(j, now)]
        if not attn and not orphans:
            a("- (nothing needs attention)")
        for j in attn:
            a(f"- job #{j.id} [{j.status}] {j.external_agent_name} "
              f"priority={j.priority} age={human_age(j.created_at, now)} "
              f"-> {attention_reason(j, now)}")
        for r in orphans:
            a(f"- loop #{r['id']} [{r['status']}] paused with NO matching job "
              f"-> import completion or cancel the loop")

        a("\nRECENT JOBS")
        if not jobs:
            a("- (none)")
        for j in jobs[:10]:
            a(f"- job #{j.id} loop=#{j.loop_id} {j.external_agent_name} "
              f"[{j.status}] priority={j.priority} "
              f"labels={','.join(j.labels) or '-'} ws={j.workspace_name} "
              f"age={human_age(j.created_at, now)} "
              f"archived={'yes' if j.archived else 'no'}")
            a(f"    handoff: {j.handoff_path or '-'}")

        a("\nNEXT ACTIONS")
        if not attn and not orphans:
            a("- (no actions suggested)")
        for j in attn:
            a(f"- job #{j.id}: {suggested_command(j)}")
            a(f"    inspect: python3 main.py --external-job {j.id}")
            if j.status == eaj.WAITING_FOR_EXTERNAL_AGENT:
                a(f"    cancel : python3 main.py --cancel-external-job {j.id}")
            a(f"    archive: python3 main.py --archive-external-job {j.id}")
        for r in orphans:
            a(f"- loop #{r['id']}: python3 main.py --resume {r['id']} "
              f"--external-completion-file completion.json")

        print("\n".join(out))
        return summary
