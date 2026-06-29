"""Controlled filesystem layer.

Writes are confined to a workspace's allowed write paths. Without a workspace,
the default internal `workspace/` sandbox is used (Stage 1.9 behavior). All
writes go through ProjectWorkspace permission checks; blocked operations are
returned with a reason and never written.
"""

import os
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import config
import project_workspace
from project_workspace import UnsafePathError  # re-exported for callers/tests

PROJECT_ROOT = project_workspace.PROJECT_ROOT
_MANAGER = project_workspace.WorkspaceManager()


def _ws(workspace):
    return workspace or _MANAGER.default_workspace()


def workspace_dir(workspace=None) -> str:
    """Absolute path to the (primary) write base, created if missing."""
    return _MANAGER.write_base(_ws(workspace))


def safe_join(base_dir: str, relative_path: str) -> str:
    """Join relative_path onto base_dir, guaranteeing it stays inside.

    Retained for direct/base-relative use (and tests). Raises UnsafePathError.
    """
    if relative_path is None or str(relative_path).strip() == "":
        raise UnsafePathError("Empty path is not allowed.")
    rel = str(relative_path).strip()
    if "\x00" in rel:
        raise UnsafePathError("Null byte in path is not allowed.")
    if os.path.isabs(rel):
        raise UnsafePathError(f"Absolute paths are not allowed: {rel!r}")
    if rel.startswith("~"):
        raise UnsafePathError(f"Home-relative paths are not allowed: {rel!r}")
    base = os.path.realpath(base_dir)
    target = os.path.realpath(os.path.join(base, rel))
    if target != base and not target.startswith(base + os.sep):
        raise UnsafePathError(f"Path escapes the workspace: {rel!r} -> {target!r}")
    return target


def write_file(relative_path: str, content: str, workspace=None) -> str:
    """Write content under the workspace's write base. Returns the absolute path."""
    ws = _ws(workspace)
    target = _MANAGER.resolve_safe_path(ws, relative_path)
    parent = os.path.dirname(target)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(target, "w", encoding="utf-8") as fh:
        fh.write(content if content is not None else "")
    return target


def read_file(relative_path: str, workspace=None) -> str:
    ws = _ws(workspace)
    target = _MANAGER.resolve_safe_path(ws, relative_path)
    with open(target, "r", encoding="utf-8") as fh:
        return fh.read()


def list_files(workspace=None) -> List[str]:
    """All files under the write base as sorted POSIX relative paths."""
    base = workspace_dir(workspace)
    if not base or not os.path.isdir(base):
        return []
    found: List[str] = []
    for root, _dirs, files in os.walk(base):
        for name in files:
            rel = os.path.relpath(os.path.join(root, name), base)
            found.append(rel.replace(os.sep, "/"))
    return sorted(found)


@dataclass
class ApplyResult:
    created: List[str] = field(default_factory=list)
    updated: List[str] = field(default_factory=list)
    blocked: List[Tuple[str, str]] = field(default_factory=list)  # (path, reason)

    @property
    def changed_count(self) -> int:
        return len(self.created) + len(self.updated)


def apply_file_operations(operations, workspace=None) -> ApplyResult:
    """Apply {"path","content"} ops under the workspace. Unsafe ops are blocked."""
    result = ApplyResult()
    ws = _ws(workspace)
    base = workspace_dir(ws)

    for op in operations or []:
        path = (op or {}).get("path")
        content = (op or {}).get("content", "")
        try:
            target = _MANAGER.resolve_safe_path(ws, path)
        except UnsafePathError as exc:
            result.blocked.append((str(path), str(exc)))
            continue

        rel_to_root = os.path.relpath(target, ws.root_path)
        if project_workspace.is_protected_path(rel_to_root):
            result.blocked.append((str(path), f"protected path blocked: {rel_to_root}"))
            continue
        if not _MANAGER.is_path_allowed_for_write(ws, target):
            result.blocked.append((str(path), f"outside allowed write path: {rel_to_root}"))
            continue

        existed = os.path.exists(target)
        try:
            write_file(path, content, workspace=ws)
        except OSError as exc:
            result.blocked.append((str(path), f"write failed: {exc}"))
            continue

        # Display name: single-write-path -> relative to that base (e.g. sandbox
        # shows "calc.py"); multi-path -> root-relative (e.g. "docs/g.md").
        if base and len(ws.allowed_write_paths) == 1:
            rel = os.path.relpath(target, base).replace(os.sep, "/")
        else:
            rel = os.path.relpath(target, ws.root_path).replace(os.sep, "/")
        (result.updated if existed else result.created).append(rel)

    return result
