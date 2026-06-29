"""Workspace permission profiles (Stage 2.1).

A profile is a named, reusable bundle of permissions (read/write/command paths,
git, safety level) that can be applied to a registered ProjectWorkspace. Profiles
never loosen the global protected-path rules — those are always enforced.
"""

from dataclasses import dataclass, field
from typing import List, Optional

# Shown for reference; the global protected-path rules are always enforced
# regardless of profile (see project_workspace.is_protected_path).
STANDARD_PROTECTED = [
    ".git/", ".env", ".env.*", "node_modules/", "__pycache__/", ".venv/",
    "venv/", "env/", ".DS_Store", "secrets*", "*.pem", "*.key", "id_rsa",
    "id_ed25519",
]

_DATE = "2026-06-26T00:00:00Z"
DEFAULT_PROFILE = "sandbox"


@dataclass
class WorkspacePermissionProfile:
    name: str
    display_name: str
    description: str
    allowed_read_paths: List[str]
    allowed_write_paths: List[str]
    allowed_command_paths: List[str]
    allow_git: bool
    safety_level: str
    protected_path_patterns: List[str] = field(default_factory=lambda: list(STANDARD_PROTECTED))
    allowed_command_families_override: Optional[List[str]] = None
    tags: List[str] = field(default_factory=list)
    version: str = "1.0"
    created_at: str = _DATE
    updated_at: str = _DATE


def validate_profile(profile: WorkspacePermissionProfile) -> List[str]:
    """Return a list of validation errors (empty == valid)."""
    errors = []
    if not profile.name or not isinstance(profile.name, str):
        errors.append("name must be a non-empty string")
    if not profile.safety_level:
        errors.append("safety_level is required")
    if not isinstance(profile.allow_git, bool):
        errors.append("allow_git must be a bool")
    for label, lst in (("allowed_read_paths", profile.allowed_read_paths),
                       ("allowed_write_paths", profile.allowed_write_paths),
                       ("allowed_command_paths", profile.allowed_command_paths)):
        if not isinstance(lst, list):
            errors.append(f"{label} must be a list")
            continue
        for p in lst:
            ps = str(p)
            if ps.startswith("/") or ps.startswith("~") or ".." in ps.split("/"):
                errors.append(f"{label} entry is unsafe: {ps!r}")
    return errors


def load_builtin_profiles():
    profiles = [
        WorkspacePermissionProfile(
            name="sandbox", display_name="Sandbox",
            description="Safest default: writes and commands confined to workspace/.",
            allowed_read_paths=["."], allowed_write_paths=["workspace"],
            allowed_command_paths=["workspace"], allow_git=True,
            safety_level="strict", tags=["default", "safe"],
        ),
        WorkspacePermissionProfile(
            name="source_only", display_name="Source Only",
            description="Allow edits only in common source folders.",
            allowed_read_paths=["."],
            allowed_write_paths=["src", "app", "lib", "tests", "workspace"],
            allowed_command_paths=["."], allow_git=True,
            safety_level="standard", tags=["code"],
        ),
        WorkspacePermissionProfile(
            name="docs_only", display_name="Docs Only",
            description="Allow documentation edits only.",
            allowed_read_paths=["."],
            allowed_write_paths=["docs", "README.md", "workspace"],
            allowed_command_paths=["workspace"], allow_git=True,
            safety_level="standard", tags=["docs"],
        ),
        WorkspacePermissionProfile(
            name="tests_only", display_name="Tests Only",
            description="Allow test file edits only.",
            allowed_read_paths=["."],
            allowed_write_paths=["tests", "test", "workspace"],
            allowed_command_paths=["."], allow_git=True,
            safety_level="standard", tags=["test"],
        ),
        WorkspacePermissionProfile(
            name="read_only", display_name="Read Only",
            description="Review and analysis only; no writes, no git commit.",
            allowed_read_paths=["."], allowed_write_paths=[],
            allowed_command_paths=["."], allow_git=False,
            safety_level="strict", tags=["review"],
        ),
    ]
    return {p.name: p for p in profiles}


class WorkspaceProfileRegistry:
    def __init__(self, profiles=None):
        self._profiles = {}
        for p in (profiles or load_builtin_profiles()).values():
            self.register(p)

    def register(self, profile):
        errors = validate_profile(profile)
        if errors:
            raise ValueError(f"invalid profile '{profile.name}': {errors}")
        self._profiles[profile.name] = profile

    def list_profiles(self):
        return sorted(self._profiles.values(), key=lambda p: p.name)

    def get_profile(self, name):
        return self._profiles.get(name)

    def names(self):
        return sorted(self._profiles.keys())
