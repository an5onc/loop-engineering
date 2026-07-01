"""Stage 7.1 — Multi-Project Workspace Validation.

Validates registered projects using metadata and safe filesystem checks only.
Validation NEVER reads project file contents, executes commands, calls a model,
or mutates an external repository. Branch metadata is read directly from
``<root>/.git/HEAD`` (a tiny ref pointer), never via a git subprocess.

Stale or missing roots produce warnings, not crashes.
"""

import datetime
import json
import os
from dataclasses import dataclass, field
from typing import List, Optional

import database
import multi_project_registry as registry_mod


@dataclass
class ValidationCheck:
    name: str
    status: str  # PASS | WARN | FAIL | BLOCKED
    message: str
    evidence: str = ""


@dataclass
class ProjectValidationReport:
    id: int
    project_key: str
    generated_at: str
    overall_status: str
    total_checks: int
    passed_checks: int
    warning_checks: int
    failed_checks: int
    blocked_checks: int
    root_exists: bool
    branch_metadata: Optional[str]
    checks: List[ValidationCheck] = field(default_factory=list)
    summary: str = ""


def _now_iso() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def _aggregate_status(checks) -> str:
    statuses = [c.status for c in checks]
    if "BLOCKED" in statuses:
        return "BLOCKED"
    if "FAIL" in statuses:
        return "FAIL"
    if "WARN" in statuses:
        return "PASS_WITH_WARNINGS"
    return "PASS"


def _within(child, parent) -> bool:
    child = os.path.realpath(child)
    parent = os.path.realpath(parent)
    return child == parent or child.startswith(parent + os.sep)


def read_branch_metadata(root) -> Optional[str]:
    """Read the current branch name from <root>/.git/HEAD without subprocesses."""
    head = os.path.join(root, ".git", "HEAD")
    try:
        with open(head, "r", encoding="utf-8") as fh:
            content = fh.read().strip()
    except OSError:
        return None
    if content.startswith("ref:"):
        ref = content.split(":", 1)[1].strip()
        return ref.rsplit("/", 1)[-1] if "/" in ref else ref
    return content[:12] if content else None  # detached HEAD (short sha)


def check_to_dict(check) -> dict:
    return {"name": check.name, "status": check.status,
            "message": check.message, "evidence": check.evidence}


def check_from_dict(data) -> ValidationCheck:
    return ValidationCheck(
        name=data.get("name", ""), status=data.get("status", ""),
        message=data.get("message", ""), evidence=data.get("evidence", ""))


def report_from_row(row) -> ProjectValidationReport:
    checks = []
    try:
        checks = [check_from_dict(c) for c in json.loads(row["checks_json"] or "[]")]
    except (TypeError, ValueError):
        checks = []
    return ProjectValidationReport(
        id=row["id"],
        project_key=row["project_key"],
        generated_at=row["generated_at"] or "",
        overall_status=row["overall_status"] or "",
        total_checks=row["total_checks"] or 0,
        passed_checks=row["passed_checks"] or 0,
        warning_checks=row["warning_checks"] or 0,
        failed_checks=row["failed_checks"] or 0,
        blocked_checks=row["blocked_checks"] or 0,
        root_exists=bool(row["root_exists"]),
        branch_metadata=row["branch_metadata"],
        checks=checks,
        summary=row["summary"] or "",
    )


class ProjectValidator:
    def __init__(self, conn):
        self.conn = conn
        self.registry = registry_mod.ProjectRegistry(conn)

    def validate_project(self, project_key, persist=True) -> ProjectValidationReport:
        project = self.registry.get_project(project_key)
        if project is None:
            raise ValueError(f"no project registered with key: {project_key}")
        others = [p for p in self.registry.list_projects()
                  if p.project_key != project.project_key]
        checks, root_exists, branch = self._run_checks(project, others)
        overall = _aggregate_status(checks)
        passed = sum(1 for c in checks if c.status == "PASS")
        warnings = sum(1 for c in checks if c.status == "WARN")
        failed = sum(1 for c in checks if c.status == "FAIL")
        blocked = sum(1 for c in checks if c.status == "BLOCKED")
        summary = (f"{passed} pass, {warnings} warning, {failed} fail, "
                   f"{blocked} blocked")
        generated_at = _now_iso()
        report = ProjectValidationReport(
            id=0, project_key=project.project_key, generated_at=generated_at,
            overall_status=overall, total_checks=len(checks), passed_checks=passed,
            warning_checks=warnings, failed_checks=failed, blocked_checks=blocked,
            root_exists=root_exists, branch_metadata=branch, checks=checks,
            summary=summary)
        if persist:
            report.id = database.save_project_validation_report(
                self.conn, project.project_key, generated_at, overall,
                len(checks), passed, warnings, failed, blocked, root_exists,
                branch, json.dumps([check_to_dict(c) for c in checks]), summary)
        return report

    def validate_all(self) -> List[ProjectValidationReport]:
        return [self.validate_project(p.project_key)
                for p in self.registry.list_projects()]

    def _run_checks(self, project, others):
        checks = []
        root = project.root_path
        root_exists = bool(root) and os.path.isdir(root)

        if root_exists:
            checks.append(ValidationCheck(
                "root exists", "PASS", f"root directory present: {root}", root))
        else:
            checks.append(ValidationCheck(
                "root exists", "WARN",
                f"root is missing or stale: {root}",
                "register the project again or restore the path"))

        # System-path containment.
        if root and registry_mod._is_inside_system_root(os.path.realpath(root)):
            checks.append(ValidationCheck(
                "root not in protected system path", "BLOCKED",
                f"root resolves inside a protected system path: {root}", root))
        else:
            checks.append(ValidationCheck(
                "root not in protected system path", "PASS",
                "root is not inside a protected system path", root or ""))

        # .git presence when a repo_url is declared.
        if project.repo_url:
            has_git = root_exists and os.path.isdir(os.path.join(root, ".git"))
            checks.append(ValidationCheck(
                "git repo present", "PASS" if has_git else "WARN",
                ".git directory present" if has_git else
                "repo_url is set but no .git directory was found (not cloned yet?)",
                os.path.join(root, ".git") if root else ""))
        else:
            checks.append(ValidationCheck(
                "git repo present", "PASS",
                "no repo_url declared; git presence check skipped", "n/a"))

        # Branch metadata (read-only).
        branch = read_branch_metadata(root) if root_exists else None
        checks.append(ValidationCheck(
            "branch metadata readable", "PASS" if branch else "WARN",
            f"current branch: {branch}" if branch else
            "no readable branch metadata (.git/HEAD missing)",
            branch or ""))

        # Root overlap with other registered projects.
        overlaps = []
        if root:
            for other in others:
                if not other.root_path:
                    continue
                if _within(root, other.root_path) or _within(other.root_path, root):
                    overlaps.append(other.project_key)
        if overlaps:
            checks.append(ValidationCheck(
                "root does not overlap other projects", "FAIL",
                "root overlaps registered project(s): " + ", ".join(overlaps),
                ", ".join(overlaps)))
        else:
            checks.append(ValidationCheck(
                "root does not overlap other projects", "PASS",
                "no overlapping registered roots", ""))

        # allowed_write_paths must stay within root.
        bad_writes = []
        for path in project.allowed_write_paths:
            candidate = path if os.path.isabs(path) else os.path.join(root or "", path)
            if not root or not _within(candidate, root):
                bad_writes.append(path)
        if bad_writes:
            checks.append(ValidationCheck(
                "allowed_write_paths stay within root", "FAIL",
                "allowed write paths escape root: " + ", ".join(bad_writes),
                ", ".join(bad_writes)))
        else:
            checks.append(ValidationCheck(
                "allowed_write_paths stay within root", "PASS",
                "all allowed write paths are within root", ""))

        # protected_paths must be within root OR explicit absolute paths.
        bad_protected = []
        for path in project.protected_paths:
            if os.path.isabs(path):
                continue  # explicit absolute protected path is allowed
            candidate = os.path.join(root or "", path)
            if not root or not _within(candidate, root):
                bad_protected.append(path)
        if bad_protected:
            checks.append(ValidationCheck(
                "protected_paths stay within root or are absolute", "FAIL",
                "relative protected paths escape root: " + ", ".join(bad_protected),
                ", ".join(bad_protected)))
        else:
            checks.append(ValidationCheck(
                "protected_paths stay within root or are absolute", "PASS",
                "protected paths are valid", ""))

        return checks, root_exists, branch
