"""Stage 14.0/14.1 — Multi-Run Orchestration Sessions and Membership."""

from dataclasses import dataclass

import database


SESSION_STATUSES = ("defined", "active", "blocked", "completed", "closed")
SAFETY_SUMMARY = (
    "Stage 14 sessions coordinate existing orchestration runs as metadata. "
    "They have no executor: execution flows only through Stage 12 gated "
    "advancement, which delegates to Stage 11 and Stage 10.")


@dataclass
class MultiRunSession:
    id: int
    title: str
    status: str
    created_by: str = ""
    notes: str = ""
    safety_summary: str = ""


@dataclass
class MultiRunSessionMember:
    id: int
    session_id: int
    run_id: int
    status: str


def session_from_row(row):
    return MultiRunSession(
        id=row["id"], title=row["title"] or "", status=row["status"] or "",
        created_by=row["created_by"] or "", notes=row["notes"] or "",
        safety_summary=row["safety_summary"] or "")


def member_from_row(row):
    return MultiRunSessionMember(
        id=row["id"], session_id=row["session_id"], run_id=row["run_id"],
        status=row["status"] or "")


class MultiRunSessionManager:
    def __init__(self, conn):
        self.conn = conn

    def create_session(self, title, created_by=None, notes=None):
        if not title or not str(title).strip():
            raise ValueError("multi-run session requires a non-empty title")
        session_id = database.save_multi_run_session(
            self.conn, str(title).strip(), "defined", created_by or "operator",
            notes, SAFETY_SUMMARY)
        database.save_multi_run_session_event(
            self.conn, session_id, "created", f"title={str(title).strip()}")
        return self.get_session(session_id)

    def get_session(self, session_id):
        row = database.get_multi_run_session(self.conn, int(session_id))
        return session_from_row(row) if row else None

    def list_sessions(self, limit=50):
        return [session_from_row(row) for row in
                database.list_multi_run_sessions(self.conn, limit=limit)]

    def close_session(self, session_id):
        session = self._require_session(session_id)
        if session.status == "closed":
            raise ValueError(f"multi-run session {session.id} is already closed")
        database.update_multi_run_session_status(self.conn, session.id, "closed")
        database.save_multi_run_session_event(
            self.conn, session.id, "closed", None)
        return self.get_session(session.id)

    def add_run(self, session_id, run_id):
        session = self._require_session(session_id)
        if session.status in ("closed", "completed"):
            raise ValueError(
                f"multi-run session {session.id} is '{session.status}' and "
                "cannot accept new members")
        run = database.get_cross_project_orchestration_run(self.conn, int(run_id))
        if run is None:
            raise ValueError(f"no cross-project orchestration run {run_id}")
        for member in self.active_members(session.id):
            if member.run_id == run["id"]:
                raise ValueError(
                    f"run {run['id']} is already a member of session "
                    f"{session.id}")
        other = self._active_session_for_run(run["id"], exclude_session=session.id)
        if other is not None:
            raise ValueError(
                f"run {run['id']} is already active in multi-run session "
                f"{other}")
        member_id = database.save_multi_run_session_member(
            self.conn, session.id, run["id"], "active")
        if session.status == "defined":
            database.update_multi_run_session_status(
                self.conn, session.id, "active")
        database.save_multi_run_session_event(
            self.conn, session.id, "run_added", f"run={run['id']}")
        self.refresh_status(session.id)
        return member_from_row(database.get_multi_run_session_member(
            self.conn, member_id))

    def remove_run(self, session_id, run_id):
        session = self._require_session(session_id)
        if session.status == "closed":
            raise ValueError(
                f"multi-run session {session.id} is closed and immutable")
        member = None
        for candidate in self.active_members(session.id):
            if candidate.run_id == int(run_id):
                member = candidate
                break
        if member is None:
            raise ValueError(
                f"run {run_id} is not an active member of session {session.id}")
        database.update_multi_run_session_member_status(
            self.conn, member.id, "removed")
        database.save_multi_run_session_event(
            self.conn, session.id, "run_removed", f"run={member.run_id}")
        self.refresh_status(session.id)
        return member_from_row(database.get_multi_run_session_member(
            self.conn, member.id))

    def active_members(self, session_id):
        return [member_from_row(row) for row in
                database.list_multi_run_session_members(
                    self.conn, session_id=int(session_id))
                if row["status"] == "active"]

    def list_members(self, session_id):
        return [member_from_row(row) for row in
                database.list_multi_run_session_members(
                    self.conn, session_id=int(session_id))]

    def refresh_status(self, session_id):
        """Derive active/blocked/completed from member run statuses.

        Metadata-only; never touches Stage 10-13 records. Closed is sticky.
        """
        session = self._require_session(session_id)
        if session.status in ("closed", "defined"):
            return session
        members = self.active_members(session.id)
        if not members:
            return session
        statuses = []
        for member in members:
            run = database.get_cross_project_orchestration_run(
                self.conn, member.run_id)
            statuses.append(run["status"] if run else "missing")
        if statuses and all(s == "succeeded" for s in statuses):
            derived = "completed"
        elif any(s == "blocked" for s in statuses):
            derived = "blocked"
        else:
            derived = "active"
        if derived != session.status:
            database.update_multi_run_session_status(
                self.conn, session.id, derived)
        return self.get_session(session.id)

    def _require_session(self, session_id):
        session = self.get_session(session_id)
        if session is None:
            raise ValueError(f"no multi-run session {session_id}")
        return session

    def _active_session_for_run(self, run_id, exclude_session=None):
        for row in database.list_multi_run_session_members(
                self.conn, run_id=int(run_id)):
            if row["status"] != "active":
                continue
            if exclude_session is not None and row["session_id"] == exclude_session:
                continue
            session = database.get_multi_run_session(
                self.conn, row["session_id"])
            if session is not None and session["status"] != "closed":
                return session["id"]
        return None
