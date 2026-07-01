"""Stage 7.0 — Multi-Project Registry Foundation.

A durable, metadata-only registry of the projects Loop Engineering may operate
on. Registering or inspecting a project NEVER executes a command, calls a model,
reads project file contents, or mutates an external repository. The registry
only records resolved paths and safety metadata in the local SQLite database.
"""

import json
import os
import re
from dataclasses import dataclass, field
from typing import List, Optional

import database


VALID_STATUSES = ("active", "paused", "archived", "blocked")
_KEY_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}$")

# System / dangerous roots a project must never be registered at or inside.
PROTECTED_SYSTEM_ROOTS = ("/", "/etc", "/bin", "/sbin", "/usr", "/var", "/boot",
                          "/dev", "/proc", "/sys", "/System", "/Library")


@dataclass
class ProjectSafetyProfile:
    profile_name: str
    description: str = ""
    default_allowed_write_paths: List[str] = field(default_factory=list)
    default_protected_paths: List[str] = field(default_factory=list)
    requires_explicit_approval: bool = True


@dataclass
class RegisteredProject:
    id: int
    project_key: str
    name: str
    root_path: str
    repo_url: Optional[str]
    default_branch: Optional[str]
    status: str
    safety_profile_name: Optional[str]
    allowed_write_paths: List[str] = field(default_factory=list)
    protected_paths: List[str] = field(default_factory=list)
    labels: List[str] = field(default_factory=list)
    notes: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


@dataclass
class ProjectRegistrySummary:
    total: int
    active: int
    paused: int
    archived: int
    blocked: int
    by_status: dict = field(default_factory=dict)
    projects: List[RegisteredProject] = field(default_factory=list)


def _safe_json_loads(blob, default):
    try:
        return json.loads(blob or "")
    except (TypeError, ValueError):
        return default


def project_from_row(row) -> RegisteredProject:
    return RegisteredProject(
        id=row["id"],
        project_key=row["project_key"],
        name=row["name"] or row["project_key"],
        root_path=row["root_path"],
        repo_url=row["repo_url"],
        default_branch=row["default_branch"],
        status=row["status"] or "active",
        safety_profile_name=row["safety_profile_name"],
        allowed_write_paths=_safe_json_loads(row["allowed_write_paths_json"], []),
        protected_paths=_safe_json_loads(row["protected_paths_json"], []),
        labels=_safe_json_loads(row["labels_json"], []),
        notes=row["notes"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def profile_from_row(row) -> ProjectSafetyProfile:
    return ProjectSafetyProfile(
        profile_name=row["profile_name"],
        description=row["description"] or "",
        default_allowed_write_paths=_safe_json_loads(
            row["default_allowed_write_paths_json"], []),
        default_protected_paths=_safe_json_loads(
            row["default_protected_paths_json"], []),
        requires_explicit_approval=bool(row["requires_explicit_approval"]),
    )


def resolve_root(root_path) -> str:
    """Resolve a root to an absolute realpath. Does not read its contents."""
    if not root_path or not str(root_path).strip():
        raise ValueError("project root path is required")
    resolved = os.path.realpath(os.path.abspath(str(root_path).strip()))
    return resolved


def _is_inside_system_root(resolved) -> bool:
    for protected in PROTECTED_SYSTEM_ROOTS:
        base = os.path.realpath(protected)
        if resolved == base and base == os.path.realpath("/"):
            return True
        if resolved == base:
            return True
    return False


class ProjectRegistry:
    def __init__(self, conn):
        self.conn = conn

    # -- profiles -------------------------------------------------------- #
    def upsert_safety_profile(self, profile: ProjectSafetyProfile) -> ProjectSafetyProfile:
        if not profile.profile_name or not _KEY_RE.match(profile.profile_name):
            raise ValueError(f"invalid safety profile name: {profile.profile_name!r}")
        database.save_project_safety_profile(
            self.conn, profile.profile_name, profile.description,
            json.dumps(profile.default_allowed_write_paths),
            json.dumps(profile.default_protected_paths),
            1 if profile.requires_explicit_approval else 0)
        return profile

    def get_safety_profile(self, profile_name) -> Optional[ProjectSafetyProfile]:
        row = database.get_project_safety_profile(self.conn, profile_name)
        return profile_from_row(row) if row else None

    def list_safety_profiles(self) -> List[ProjectSafetyProfile]:
        return [profile_from_row(r)
                for r in database.list_project_safety_profiles(self.conn)]

    # -- projects -------------------------------------------------------- #
    def register_project(self, project_key, root_path, name=None, repo_url=None,
                         default_branch="main", status="active",
                         safety_profile_name=None, allowed_write_paths=None,
                         protected_paths=None, labels=None, notes=None) -> RegisteredProject:
        if not project_key or not _KEY_RE.match(str(project_key)):
            raise ValueError(
                f"invalid project key {project_key!r}; use letters, digits, '-', '_', '.'")
        if status not in VALID_STATUSES:
            raise ValueError(f"invalid status {status!r}; one of {VALID_STATUSES}")
        if self.get_project(project_key) is not None:
            raise ValueError(f"project key already registered: {project_key}")

        resolved = resolve_root(root_path)
        if not os.path.isdir(resolved):
            raise ValueError(f"project root does not exist or is not a directory: {resolved}")
        if _is_inside_system_root(resolved):
            raise ValueError(f"refusing to register project inside protected system path: {resolved}")

        allowed = list(allowed_write_paths or [])
        protected = list(protected_paths or [])
        if safety_profile_name:
            profile = self.get_safety_profile(safety_profile_name)
            if profile is not None:
                if not allowed:
                    allowed = list(profile.default_allowed_write_paths)
                if not protected:
                    protected = list(profile.default_protected_paths)

        project_id = database.register_project(
            self.conn, project_key, name or project_key, resolved, repo_url,
            default_branch, status, safety_profile_name,
            json.dumps(allowed), json.dumps(protected),
            json.dumps(list(labels or [])), notes)
        database.save_project_registry_event(
            self.conn, project_key, "registered",
            f"root={resolved} status={status}")
        return self.get_project_by_id(project_id)

    def get_project(self, project_key) -> Optional[RegisteredProject]:
        row = database.get_registered_project(self.conn, project_key)
        return project_from_row(row) if row else None

    def get_project_by_id(self, project_id) -> Optional[RegisteredProject]:
        row = database.get_registered_project_by_id(self.conn, project_id)
        return project_from_row(row) if row else None

    def list_projects(self, status=None) -> List[RegisteredProject]:
        if status is not None and status not in VALID_STATUSES:
            raise ValueError(f"invalid status filter {status!r}")
        return [project_from_row(r)
                for r in database.list_registered_projects(self.conn, status=status)]

    def set_status(self, project_key, status) -> RegisteredProject:
        if status not in VALID_STATUSES:
            raise ValueError(f"invalid status {status!r}; one of {VALID_STATUSES}")
        project = self.get_project(project_key)
        if project is None:
            raise ValueError(f"no project registered with key: {project_key}")
        database.update_registered_project_status(self.conn, project_key, status)
        database.save_project_registry_event(
            self.conn, project_key, "status_changed",
            f"{project.status}->{status}")
        return self.get_project(project_key)

    def events(self, project_key=None, limit=100):
        return database.list_project_registry_events(
            self.conn, project_key=project_key, limit=limit)

    def summary(self) -> ProjectRegistrySummary:
        projects = self.list_projects()
        by_status = {s: 0 for s in VALID_STATUSES}
        for project in projects:
            by_status[project.status] = by_status.get(project.status, 0) + 1
        return ProjectRegistrySummary(
            total=len(projects),
            active=by_status.get("active", 0),
            paused=by_status.get("paused", 0),
            archived=by_status.get("archived", 0),
            blocked=by_status.get("blocked", 0),
            by_status=by_status,
            projects=projects,
        )
