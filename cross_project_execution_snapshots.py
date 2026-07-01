"""Stage 10.3 — Rollback Snapshot Builder for Cross-Project Execution."""

import base64
import datetime
import hashlib
import json
import os
from dataclasses import asdict, dataclass, field

import database
import cross_project_execution_confirmations as confirmations_mod
import cross_project_execution_sessions as sessions_mod
import multi_project_registry
import project_workspace


PROTECTED_FRAGMENTS = (".env", "secret", "secrets", "id_rsa", "id_ed25519",
                       ".ssh", ".git")


@dataclass
class CrossProjectExecutionSnapshotFile:
    target_file: str
    file_exists: bool
    size_bytes: int
    content_sha256: str
    content_base64: str
    encoding: str = "base64"


@dataclass
class CrossProjectExecutionSnapshot:
    id: int
    session_id: int
    confirmation_id: int
    generated_at: str
    status: str
    total_files: int
    captured_files: int
    missing_files: int
    target_files: list = field(default_factory=list)
    files: list = field(default_factory=list)
    safety_notes: list = field(default_factory=list)


def _now_iso():
    return datetime.datetime.now().isoformat(timespec="seconds")


def _sha256_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _safe_json_loads(blob, default):
    try:
        return json.loads(blob or "")
    except (TypeError, ValueError):
        return default


def _snapshot_file_from_row(row):
    return CrossProjectExecutionSnapshotFile(
        target_file=row["target_file"] or "", file_exists=bool(row["file_exists"]),
        size_bytes=row["size_bytes"] or 0,
        content_sha256=row["content_sha256"] or "",
        content_base64=row["content_base64"] or "",
        encoding=row["encoding"] or "base64")


def snapshot_from_row(conn, row):
    files = [_snapshot_file_from_row(r)
             for r in database.list_cross_project_execution_snapshot_files(
                 conn, row["id"])]
    return CrossProjectExecutionSnapshot(
        id=row["id"], session_id=row["session_id"],
        confirmation_id=row["confirmation_id"],
        generated_at=row["generated_at"] or "", status=row["status"] or "",
        total_files=row["total_files"] or 0,
        captured_files=row["captured_files"] or 0,
        missing_files=row["missing_files"] or 0,
        target_files=_safe_json_loads(row["target_files_json"], []),
        files=files,
        safety_notes=_safe_json_loads(row["safety_notes_json"], []))


class CrossProjectExecutionSnapshotBuilder:
    def __init__(self, conn):
        self.conn = conn
        self.sessions = sessions_mod.CrossProjectExecutionSessionManager(conn)
        self.confirmations = confirmations_mod.CrossProjectExecutionConfirmationGate(conn)
        self.registry = multi_project_registry.ProjectRegistry(conn)

    def create_snapshot(self, session_id, confirmation_id, target_files=None):
        session = self.sessions.get_session(int(session_id))
        if session is None:
            raise ValueError(f"no cross-project execution session {session_id}")
        confirmation = self.confirmations.get_confirmation(int(confirmation_id))
        if confirmation is None:
            raise ValueError(f"no cross-project execution confirmation {confirmation_id}")
        if confirmation.session_id != session.id:
            raise ValueError("snapshot confirmation does not match session")
        if not confirmations_mod.is_usable(confirmation):
            raise ValueError("snapshot requires approved Stage 10 confirmation")
        project = self.registry.get_project(confirmation.project_key)
        if project is None:
            raise ValueError(f"no registered project {confirmation.project_key}")
        files = []
        for target in list(target_files or []):
            files.append(_capture_file(project, target))
        captured = sum(1 for item in files if item.file_exists)
        missing = len(files) - captured
        manifest = [asdict(item) for item in files]
        sid = database.save_cross_project_execution_snapshot(
            self.conn, session.id, confirmation.id, _now_iso(), "snapshot_created",
            len(files), captured, missing, json.dumps(list(target_files or []),
                                                     sort_keys=True),
            json.dumps(manifest, sort_keys=True),
            json.dumps(_safety_notes(), sort_keys=True))
        for item in files:
            database.save_cross_project_execution_snapshot_file(
                self.conn, sid, item.target_file, item.file_exists, item.size_bytes,
                item.content_sha256, item.content_base64, item.encoding)
        database.save_cross_project_execution_snapshot_event(
            self.conn, sid, "created",
            json.dumps({"session_id": session.id, "confirmation_id": confirmation.id,
                        "captured_files": captured}, sort_keys=True))
        return self.get_snapshot(sid)

    def get_snapshot(self, snapshot_id):
        row = database.get_cross_project_execution_snapshot(self.conn, int(snapshot_id))
        return snapshot_from_row(self.conn, row) if row else None


def _capture_file(project, rel_path):
    rel = _validate_target_file(rel_path)
    root = os.path.realpath(project.root_path)
    target = os.path.realpath(os.path.join(root, rel))
    allowed = list(project.allowed_write_paths or ["."])
    allowed_dirs = [os.path.realpath(os.path.join(root, p)) for p in allowed]
    if not any(target == d or target.startswith(d + os.sep) for d in allowed_dirs):
        raise ValueError(f"snapshot target outside allowed write paths: {rel}")
    if not os.path.exists(target):
        return CrossProjectExecutionSnapshotFile(rel, False, 0, "", "")
    with open(target, "rb") as fh:
        content = fh.read()
    return CrossProjectExecutionSnapshotFile(
        rel, True, len(content), hashlib.sha256(content).hexdigest(),
        base64.b64encode(content).decode("ascii"))


def _validate_target_file(path):
    rel = str(path or "").replace("\\", "/").strip()
    if not rel:
        raise ValueError("empty snapshot target")
    if os.path.isabs(rel) or rel.startswith("~") or "\x00" in rel:
        raise ValueError(f"unsafe snapshot target: {path!r}")
    if ".." in rel.split("/"):
        raise ValueError(f"snapshot target escapes project root: {path!r}")
    if project_workspace.is_protected_path(rel):
        raise ValueError(f"snapshot target is protected: {path!r}")
    lowered = rel.lower()
    if any(fragment in lowered for fragment in PROTECTED_FRAGMENTS):
        raise ValueError(f"snapshot target may contain protected content: {path!r}")
    return rel


def _safety_notes():
    return [
        "snapshot captures only explicit allowlisted target files",
        "protected paths and path traversal are rejected",
        "snapshot creation does not execute commands or commit changes",
    ]
