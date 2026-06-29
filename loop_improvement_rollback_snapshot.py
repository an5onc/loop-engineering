"""Loop Improvement Rollback Snapshot and Restore Preview (Stage 6.5).

This stage captures rollback snapshots for approved application attempts and
provides restore previews. Snapshot creation reads only allowlisted target files
from the application attempt and stores their content in the local ignored
SQLite database. It does not apply patches, restore files, execute commands,
commit, call Ollama, or create loops/jobs. Markdown reports include metadata and
hashes only, not file contents.
"""

import base64
import datetime
import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from typing import List

import database
import loop_improvement_patch_application


PROJECT_ROOT = os.environ.get(
    "ROLLBACK_PROJECT_ROOT",
    os.path.dirname(os.path.abspath(__file__)),
)
REPORTS_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "loop_improvement_rollback_snapshot_reports",
)
PROTECTED_PATH_FRAGMENTS = (
    ".env",
    "secret",
    "secrets",
    "private_key",
    "id_rsa",
    ".ssh",
)


@dataclass
class LoopImprovementRollbackSnapshotFile:
    target_file: str
    file_exists: bool
    size_bytes: int
    content_sha256: str
    content_base64: str
    encoding: str = "base64"


@dataclass
class LoopImprovementRollbackSnapshot:
    generated_at: str
    application_attempt_id: int
    approval_id: int
    patch_proposal_id: int
    application_plan_id: int
    status: str
    total_files: int
    captured_files: int
    missing_files: int
    target_files: List[str] = field(default_factory=list)
    manifest: List[dict] = field(default_factory=list)
    files: List[LoopImprovementRollbackSnapshotFile] = field(default_factory=list)
    safety_notes: List[str] = field(default_factory=list)
    restore_instructions: List[str] = field(default_factory=list)
    applies_changes: bool = False
    restores_files: bool = False
    executes_commands: bool = False
    commits_changes: bool = False


@dataclass
class LoopImprovementRollbackRestorePreview:
    snapshot_id: int
    status: str
    total_files: int
    missing_files: int
    target_files: List[str] = field(default_factory=list)
    restores_files: bool = False
    applies_changes: bool = False
    executes_commands: bool = False
    safety_notes: List[str] = field(default_factory=list)


@dataclass
class LoopImprovementRollbackSnapshotMarkdownReport:
    snapshot_id: int
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


def snapshot_file_to_dict(item):
    return asdict(item)


def snapshot_file_from_row(row):
    return LoopImprovementRollbackSnapshotFile(
        target_file=row["target_file"] or "",
        file_exists=bool(row["file_exists"]),
        size_bytes=row["size_bytes"] or 0,
        content_sha256=row["content_sha256"] or "",
        content_base64=row["content_base64"] or "",
        encoding=row["encoding"] or "base64",
    )


def snapshot_from_row(row):
    files = [
        LoopImprovementRollbackSnapshotFile(**item)
        for item in _safe_json_loads(row["manifest_json"], [])
    ]
    return LoopImprovementRollbackSnapshot(
        generated_at=row["generated_at"] or "",
        application_attempt_id=row["application_attempt_id"],
        approval_id=row["approval_id"],
        patch_proposal_id=row["patch_proposal_id"],
        application_plan_id=row["application_plan_id"],
        status=row["status"] or "",
        total_files=row["total_files"] or 0,
        captured_files=row["captured_files"] or 0,
        missing_files=row["missing_files"] or 0,
        target_files=_safe_json_loads(row["target_files_json"], []),
        manifest=_safe_json_loads(row["manifest_json"], []),
        files=files,
        safety_notes=_safe_json_loads(row["safety_notes_json"], []),
        restore_instructions=_safe_json_loads(row["restore_instructions_json"], []),
        applies_changes=bool(row["applies_changes"]),
        restores_files=bool(row["restores_files"]),
        executes_commands=bool(row["executes_commands"]),
        commits_changes=bool(row["commits_changes"]),
    )


def is_markdown_report_path(path):
    if not path:
        return False
    target = os.path.realpath(path)
    base = os.path.realpath(REPORTS_DIR)
    return target != base and target.startswith(base + os.sep)


class LoopImprovementRollbackSnapshotEngine:
    def __init__(self, conn):
        self.conn = conn

    def create_snapshot(self, application_attempt_id):
        row = database.get_loop_improvement_patch_application_attempt(
            self.conn, int(application_attempt_id))
        if row is None:
            raise ValueError(
                f"no loop improvement patch application attempt {application_attempt_id}"
            )
        attempt = loop_improvement_patch_application.application_attempt_from_row(row)
        files = []
        for target_file in attempt.target_files:
            _validate_target_file(target_file)
            files.append(_capture_file(target_file))
        captured = sum(1 for item in files if item.file_exists)
        missing = len(files) - captured
        manifest = [snapshot_file_to_dict(item) for item in files]
        return LoopImprovementRollbackSnapshot(
            generated_at=_now_iso(),
            application_attempt_id=int(application_attempt_id),
            approval_id=attempt.approval_id,
            patch_proposal_id=attempt.patch_proposal_id,
            application_plan_id=attempt.application_plan_id,
            status="snapshot_created",
            total_files=len(files),
            captured_files=captured,
            missing_files=missing,
            target_files=list(attempt.target_files),
            manifest=manifest,
            files=files,
            safety_notes=_safety_notes(),
            restore_instructions=_restore_instructions(),
            applies_changes=False,
            restores_files=False,
            executes_commands=False,
            commits_changes=False,
        )

    def save_snapshot(self, snapshot):
        snapshot_id = database.save_loop_improvement_rollback_snapshot(
            self.conn,
            snapshot.generated_at,
            snapshot.application_attempt_id,
            snapshot.approval_id,
            snapshot.patch_proposal_id,
            snapshot.application_plan_id,
            snapshot.status,
            snapshot.total_files,
            snapshot.captured_files,
            snapshot.missing_files,
            json.dumps(snapshot.target_files, sort_keys=True),
            json.dumps([snapshot_file_to_dict(f) for f in snapshot.files],
                       sort_keys=True),
            json.dumps(snapshot.safety_notes, sort_keys=True),
            json.dumps(snapshot.restore_instructions, sort_keys=True),
            snapshot.applies_changes,
            snapshot.restores_files,
            snapshot.executes_commands,
            snapshot.commits_changes,
        )
        for item in snapshot.files:
            database.save_loop_improvement_rollback_snapshot_file(
                self.conn,
                snapshot_id,
                item.target_file,
                item.file_exists,
                item.size_bytes,
                item.content_sha256,
                item.content_base64,
                item.encoding,
            )
        database.save_loop_improvement_rollback_snapshot_event(
            self.conn,
            snapshot_id,
            "created",
            json.dumps({
                "application_attempt_id": snapshot.application_attempt_id,
                "captured_files": snapshot.captured_files,
                "missing_files": snapshot.missing_files,
                "restores_files": False,
            }, sort_keys=True),
        )
        return snapshot_id

    def preview_restore(self, snapshot_id):
        row = database.get_loop_improvement_rollback_snapshot(
            self.conn, int(snapshot_id))
        if row is None:
            raise ValueError(f"no loop improvement rollback snapshot {snapshot_id}")
        snapshot = snapshot_from_row(row)
        preview = LoopImprovementRollbackRestorePreview(
            snapshot_id=int(snapshot_id),
            status="restore_preview",
            total_files=snapshot.total_files,
            missing_files=snapshot.missing_files,
            target_files=list(snapshot.target_files),
            restores_files=False,
            applies_changes=False,
            executes_commands=False,
            safety_notes=[
                "Restore preview only.",
                "No files are restored by this command.",
                "No commands are executed.",
            ],
        )
        database.save_loop_improvement_rollback_snapshot_event(
            self.conn,
            int(snapshot_id),
            "restore_previewed",
            json.dumps({
                "total_files": preview.total_files,
                "missing_files": preview.missing_files,
                "restores_files": preview.restores_files,
            }, sort_keys=True),
        )
        return preview

    def save_markdown_report(self, snapshot_id, snapshot):
        content = self.render_markdown(snapshot, snapshot_id)
        path = self._new_report_path(snapshot_id)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        encoded = content.encode("utf-8")
        chash = hashlib.sha256(encoded).hexdigest()
        nbytes = len(encoded)
        database.save_loop_improvement_rollback_snapshot_markdown_report(
            self.conn, snapshot_id, path, "markdown", chash, nbytes)
        return LoopImprovementRollbackSnapshotMarkdownReport(
            snapshot_id=snapshot_id,
            report_path=path,
            report_format="markdown",
            content_hash=chash,
            bytes_written=nbytes,
            created_at=_now_iso(),
        )

    def _new_report_path(self, snapshot_id):
        os.makedirs(REPORTS_DIR, exist_ok=True)
        filename = (
            f"loop_improvement_rollback_snapshot_{int(snapshot_id)}_{_now_stamp()}.md"
        )
        target = os.path.realpath(os.path.join(REPORTS_DIR, filename))
        base = os.path.realpath(REPORTS_DIR)
        if target != base and not target.startswith(base + os.sep):
            raise ValueError(
                "rollback snapshot report path escaped "
                "loop_improvement_rollback_snapshot_reports/")
        return target

    def render_markdown(self, snapshot, snapshot_id=None):
        lines = []
        a = lines.append
        a("# Loop Improvement Rollback Snapshot")
        a("")
        a("## Summary")
        if snapshot_id is not None:
            a(f"- Snapshot ID: {snapshot_id}")
        a(f"- Generated at: {snapshot.generated_at}")
        a(f"- Application attempt ID: {snapshot.application_attempt_id}")
        a(f"- Status: {snapshot.status}")
        a(f"- Total files: {snapshot.total_files}")
        a(f"- Captured files: {snapshot.captured_files}")
        a(f"- Missing files: {snapshot.missing_files}")
        a(f"- Applies changes: {snapshot.applies_changes}")
        a(f"- Restores files: {snapshot.restores_files}")
        a(f"- Executes commands: {snapshot.executes_commands}")
        a("")
        a("## Snapshot Files")
        if not snapshot.files:
            a("- (none)")
        for item in snapshot.files:
            a(f"- {item.target_file}")
            a(f"  exists: {item.file_exists}")
            a(f"  size: {item.size_bytes}")
            a(f"  sha256: {item.content_sha256 or '(none)'}")
        a("")
        a("## Restore Instructions")
        _append_list(lines, snapshot.restore_instructions)
        a("## Safety Notes")
        _append_list(lines, snapshot.safety_notes)
        return "\n".join(lines)


def _capture_file(target_file):
    path = os.path.join(PROJECT_ROOT, os.path.normpath(target_file))
    if not os.path.exists(path):
        return LoopImprovementRollbackSnapshotFile(
            target_file=target_file,
            file_exists=False,
            size_bytes=0,
            content_sha256="",
            content_base64="",
        )
    with open(path, "rb") as fh:
        content = fh.read()
    return LoopImprovementRollbackSnapshotFile(
        target_file=target_file,
        file_exists=True,
        size_bytes=len(content),
        content_sha256=hashlib.sha256(content).hexdigest(),
        content_base64=base64.b64encode(content).decode("ascii"),
    )


def _validate_target_file(path):
    if not path:
        raise ValueError("target file is empty")
    if os.path.isabs(path):
        raise ValueError(f"target file is outside the allowed relative workspace: {path}")
    normalized = os.path.normpath(path)
    if normalized == "." or normalized.startswith("..") or ".." in normalized.split(os.sep):
        raise ValueError(f"target file is outside the allowed relative workspace: {path}")
    lowered = normalized.lower()
    for fragment in PROTECTED_PATH_FRAGMENTS:
        if fragment in lowered:
            raise ValueError(f"target file references protected content: {path}")
    real_root = os.path.realpath(PROJECT_ROOT)
    real_target = os.path.realpath(os.path.join(real_root, normalized))
    if real_target != real_root and not real_target.startswith(real_root + os.sep):
        raise ValueError(f"target file is outside the allowed relative workspace: {path}")


def _restore_instructions():
    return [
        "Use restore preview before any restore execution.",
        "Restoring files remains manual/future-stage controlled.",
        "Verify target files still pass workspace and protected-path checks.",
    ]


def _safety_notes():
    return [
        "Snapshot reads only allowlisted target files from the application attempt.",
        "No patches are generated.",
        "No changes are applied.",
        "No files are restored by snapshot creation or preview.",
        "No commands are executed.",
        "No git commits are created.",
        "No Ollama or external-agent calls are made.",
    ]


def _append_list(lines, items):
    if not items:
        lines.append("- (none)")
    for item in items:
        lines.append(f"- {item}")
    lines.append("")
