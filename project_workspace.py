"""Project Workspaces (Stage 2.0): controlled access to a target directory.

A ProjectWorkspace bounds where a loop may read, write, and run commands, and
whether git is allowed. The default (unregistered) workspace reproduces the
Stage 1.9 behavior exactly: root = the framework dir, writes/commands confined
to `workspace/`.

Resolution model: coder file paths resolve relative to the *primary write base*
(root/allowed_write_paths[0]) — so a bare `calc.py` lands in `workspace/calc.py`
just like before. A write is rejected if it escapes that base, is absolute, uses
`~`/null bytes, or matches a protected pattern.
"""

import datetime
import fnmatch
import os
from dataclasses import dataclass, field
from typing import List, Optional

import config
import workspace_profiles

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

# Generated / cache artifacts: ignorable as external-agent deltas (they are not
# a security concern), but still never written by the local coder.
GENERATED_IGNORED_COMPONENTS = {"__pycache__"}
GENERATED_IGNORED_BASENAMES = {".DS_Store"}
GENERATED_IGNORED_GLOBS = ["*.pyc", "*.pyo"]

# Sensitive paths that are a real security concern if changed (block always).
SENSITIVE_COMPONENTS = {".git", "node_modules", ".venv", "venv", "env"}
SENSITIVE_BASENAMES = {"id_rsa", "id_ed25519"}
SENSITIVE_GLOBS = [".env", ".env.*", "secrets*", "*.pem", "*.key"]

# Path patterns that may never be WRITTEN, even inside an allowed write path
# (union of sensitive + generated — the local coder writes none of these).
PROTECTED_COMPONENTS = SENSITIVE_COMPONENTS | GENERATED_IGNORED_COMPONENTS
PROTECTED_BASENAMES = SENSITIVE_BASENAMES | GENERATED_IGNORED_BASENAMES
PROTECTED_GLOBS = SENSITIVE_GLOBS + GENERATED_IGNORED_GLOBS


class UnsafePathError(ValueError):
    """Raised when a requested path is structurally unsafe (abs/traversal/etc)."""


def _now() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def is_protected_path(rel_path: str) -> bool:
    """True if rel_path (relative, POSIX-ish) matches any protected pattern."""
    rel = str(rel_path).replace("\\", "/").strip("/")
    if not rel:
        return False
    parts = rel.split("/")
    for p in parts:
        if p in PROTECTED_COMPONENTS:
            return True
    base = parts[-1]
    if base in PROTECTED_BASENAMES:
        return True
    for pat in PROTECTED_GLOBS:
        if fnmatch.fnmatch(base, pat):
            return True
    return False


def is_generated_ignored_path(rel_path: str) -> bool:
    """True for generated/cache artifacts (e.g. __pycache__, *.pyc, .DS_Store)
    that should be ignored when computing external-agent deltas."""
    rel = str(rel_path).replace("\\", "/").strip("/")
    if not rel:
        return False
    parts = rel.split("/")
    if any(p in GENERATED_IGNORED_COMPONENTS for p in parts):
        return True
    base = parts[-1]
    if base in GENERATED_IGNORED_BASENAMES:
        return True
    return any(fnmatch.fnmatch(base, pat) for pat in GENERATED_IGNORED_GLOBS)


def is_sensitive_protected_path(rel_path: str) -> bool:
    """True only for sensitive paths (.git/.env/keys/node_modules/...) — the set
    that must BLOCK an external-agent change. Excludes generated artifacts."""
    rel = str(rel_path).replace("\\", "/").strip("/")
    if not rel:
        return False
    parts = rel.split("/")
    if any(p in SENSITIVE_COMPONENTS for p in parts):
        return True
    base = parts[-1]
    if base in SENSITIVE_BASENAMES:
        return True
    return any(fnmatch.fnmatch(base, pat) for pat in SENSITIVE_GLOBS)


@dataclass
class ProjectWorkspace:
    name: str
    root_path: str
    allowed_write_paths: List[str] = field(default_factory=lambda: ["workspace"])
    allowed_read_paths: List[str] = field(default_factory=lambda: ["."])
    allowed_command_paths: List[str] = field(default_factory=lambda: ["workspace"])
    allow_git: bool = True
    created_at: str = ""
    updated_at: str = ""
    profile_name: str = "sandbox"
    profile_version: str = "1.0"


class WorkspaceManager:
    def __init__(self, conn=None):
        self.conn = conn

    # --- construction / registry ----------------------------------------- #
    @staticmethod
    def default_workspace() -> ProjectWorkspace:
        return ProjectWorkspace(
            name="default", root_path=PROJECT_ROOT,
            allowed_write_paths=[config.WORKSPACE_DIR],
            allowed_read_paths=["."],
            allowed_command_paths=[config.WORKSPACE_DIR],
            allow_git=True,
            created_at="builtin", updated_at="builtin",
        )

    def create_workspace(self, name, root_path, profile_name=None) -> ProjectWorkspace:
        registry = workspace_profiles.WorkspaceProfileRegistry()
        pname = profile_name or workspace_profiles.DEFAULT_PROFILE
        profile = registry.get_profile(pname)
        if profile is None:
            raise ValueError(f"unknown profile '{pname}'. "
                             f"Available: {registry.names()}")
        ws = ProjectWorkspace(
            name=name, root_path=os.path.realpath(os.path.expanduser(root_path)),
            allowed_read_paths=list(profile.allowed_read_paths),
            allowed_write_paths=list(profile.allowed_write_paths),
            allowed_command_paths=list(profile.allowed_command_paths),
            allow_git=profile.allow_git,
            created_at=_now(), updated_at=_now(),
            profile_name=profile.name, profile_version=profile.version,
        )
        errors = self.validate_workspace(ws)
        if errors:
            raise ValueError(f"invalid workspace '{name}': {errors}")
        if self.conn is not None:
            import database
            database.save_project_workspace(self.conn, ws)
        return ws

    def set_workspace_profile(self, name, profile_name) -> ProjectWorkspace:
        """Apply a profile's permissions to an existing workspace (keeps root)."""
        ws = self.get_workspace(name)
        if ws is None:
            raise ValueError(f"unknown workspace '{name}'")
        registry = workspace_profiles.WorkspaceProfileRegistry()
        profile = registry.get_profile(profile_name)
        if profile is None:
            raise ValueError(f"unknown profile '{profile_name}'. "
                             f"Available: {registry.names()}")
        ws.allowed_read_paths = list(profile.allowed_read_paths)
        ws.allowed_write_paths = list(profile.allowed_write_paths)
        ws.allowed_command_paths = list(profile.allowed_command_paths)
        ws.allow_git = profile.allow_git
        ws.profile_name = profile.name
        ws.profile_version = profile.version
        ws.updated_at = _now()
        if self.conn is not None:
            import database
            database.save_project_workspace(self.conn, ws)
        return ws

    def get_workspace(self, name) -> Optional[ProjectWorkspace]:
        if name in (None, "", "default"):
            return self.default_workspace()
        if self.conn is not None:
            import database
            row = database.get_project_workspace(self.conn, name)
            if row is not None:
                return _row_to_workspace(row)
        return None

    def list_workspaces(self) -> List[ProjectWorkspace]:
        out = [self.default_workspace()]
        if self.conn is not None:
            import database
            for row in database.list_project_workspaces(self.conn):
                out.append(_row_to_workspace(row))
        return out

    def validate_workspace(self, ws: ProjectWorkspace) -> List[str]:
        errors = []
        if not ws.name:
            errors.append("name is required")
        if not ws.root_path or not os.path.isdir(ws.root_path):
            errors.append(f"root_path is not a directory: {ws.root_path}")
        # read/command must be non-empty; write MAY be empty (read_only profile).
        for label, lst in (("allowed_read_paths", ws.allowed_read_paths),
                           ("allowed_command_paths", ws.allowed_command_paths)):
            if not isinstance(lst, list) or not lst:
                errors.append(f"{label} must be a non-empty list")
        if not isinstance(ws.allowed_write_paths, list):
            errors.append("allowed_write_paths must be a list")
        return errors

    # --- path bases ------------------------------------------------------- #
    def write_base(self, ws: ProjectWorkspace) -> Optional[str]:
        if not ws.allowed_write_paths:
            return None  # read-only workspace: no writable base
        base = os.path.realpath(os.path.join(ws.root_path, ws.allowed_write_paths[0]))
        # Only create the write dir inside an EXISTING root — never materialize a
        # missing/invalid workspace (that would mask a blocked replay).
        if os.path.isdir(ws.root_path):
            os.makedirs(base, exist_ok=True)
        return base

    def command_base(self, ws: ProjectWorkspace) -> str:
        base = os.path.realpath(os.path.join(ws.root_path, ws.allowed_command_paths[0]))
        os.makedirs(base, exist_ok=True)
        return base

    def _abs_allowed_dirs(self, ws, rel_list) -> List[str]:
        return [os.path.realpath(os.path.join(ws.root_path, p)) for p in rel_list]

    # --- safe resolution / permission checks ------------------------------ #
    def resolve_safe_path(self, ws: ProjectWorkspace, relative_path: str) -> str:
        """Resolve a coder path to a safe absolute path. Raises on unsafe/disallowed.

        Single write path (e.g. sandbox): paths nest under that write base, so a
        bare `calc.py` -> `workspace/calc.py`. Multiple write paths: paths are
        root-relative and must land inside one of the allowed write dirs (no
        implicit prefix), so `src/app.py` only works if `src` is allowed.
        """
        if relative_path is None or str(relative_path).strip() == "":
            raise UnsafePathError("empty path is not allowed")
        rel = str(relative_path).strip()
        if "\x00" in rel:
            raise UnsafePathError("null byte in path")
        if os.path.isabs(rel):
            raise UnsafePathError(f"absolute path not allowed: {rel!r}")
        if rel.startswith("~"):
            raise UnsafePathError(f"home path not allowed: {rel!r}")
        if not ws.allowed_write_paths:
            raise UnsafePathError("outside allowed write path: no write paths permitted")

        if len(ws.allowed_write_paths) == 1:
            base = self.write_base(ws)
            target = os.path.realpath(os.path.join(base, rel))
            if target == base or target.startswith(base + os.sep):
                return target
            raise UnsafePathError(f"outside allowed write path: {rel!r}")

        # Multiple write paths: resolve from root, require membership.
        target = os.path.realpath(os.path.join(ws.root_path, rel))
        if self._within_any(target, self._abs_allowed_dirs(ws, ws.allowed_write_paths)):
            return target
        raise UnsafePathError(f"outside allowed write path: {rel!r}")

    def _within_any(self, abs_path, dirs) -> bool:
        for d in dirs:
            if abs_path == d or abs_path.startswith(d + os.sep):
                return True
        return False

    def is_path_allowed_for_read(self, ws, path) -> bool:
        ap = os.path.realpath(path)
        return self._within_any(ap, self._abs_allowed_dirs(ws, ws.allowed_read_paths))

    def is_path_allowed_for_write(self, ws, path) -> bool:
        ap = os.path.realpath(path)
        if not self._within_any(ap, self._abs_allowed_dirs(ws, ws.allowed_write_paths)):
            return False
        rel = os.path.relpath(ap, ws.root_path)
        return not is_protected_path(rel)

    def is_path_allowed_for_command(self, ws, path) -> bool:
        ap = os.path.realpath(path)
        return self._within_any(ap, self._abs_allowed_dirs(ws, ws.allowed_command_paths))


def _row_to_workspace(row) -> ProjectWorkspace:
    import json
    return ProjectWorkspace(
        name=row["name"], root_path=row["root_path"],
        allowed_write_paths=json.loads(row["allowed_write_paths_json"] or "[]"),
        allowed_read_paths=json.loads(row["allowed_read_paths_json"] or "[]"),
        allowed_command_paths=json.loads(row["allowed_command_paths_json"] or "[]"),
        allow_git=bool(row["allow_git"]),
        created_at=row["created_at"] or "", updated_at=row["updated_at"] or "",
        profile_name=(row["profile_name"] if "profile_name" in row.keys() else "sandbox") or "sandbox",
        profile_version=(row["profile_version"] if "profile_version" in row.keys() else "1.0") or "1.0",
    )
