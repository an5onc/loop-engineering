"""Stage 7.3 — Cross-Project Work Planner (deterministic, plan-only).

Produces a structured plan for work that may span multiple registered projects.
The planner is fully deterministic and metadata-only: it executes no commands,
modifies no repositories, creates no loops or external jobs, and calls no model.
It only writes plan / item / event rows. Suggested commands are emitted as text
for a human to run manually — they are never executed.
"""

import datetime
import json
import os
from dataclasses import dataclass, field
from typing import List, Optional

import database
import multi_project_registry as registry_mod


VALID_STATUSES = ("proposed", "blocked", "approved_for_handoff", "cancelled")


@dataclass
class CrossProjectDependency:
    from_project: str
    to_project: str
    note: str


@dataclass
class CrossProjectWorkItem:
    id: int
    plan_id: int
    project_key: str
    description: str
    depends_on: List[str] = field(default_factory=list)
    safety_notes: List[str] = field(default_factory=list)


@dataclass
class CrossProjectWorkPlan:
    id: int
    generated_at: str
    source_request: str
    included_project_keys: List[str] = field(default_factory=list)
    excluded_project_keys: List[str] = field(default_factory=list)
    dependency_notes: List[str] = field(default_factory=list)
    required_approvals: List[str] = field(default_factory=list)
    safety_blockers: List[str] = field(default_factory=list)
    suggested_commands: List[str] = field(default_factory=list)
    status: str = "proposed"
    items: List[CrossProjectWorkItem] = field(default_factory=list)


def _now_iso() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def _safe_json_loads(blob, default):
    try:
        return json.loads(blob or "")
    except (TypeError, ValueError):
        return default


def _within(child, parent) -> bool:
    if not child or not parent:
        return False
    child = os.path.realpath(child)
    parent = os.path.realpath(parent)
    return child == parent or child.startswith(parent + os.sep)


def detect_dependencies(projects) -> List[CrossProjectDependency]:
    """Detect deterministic structural dependencies (overlapping roots)."""
    deps = []
    for i, a in enumerate(projects):
        for b in projects[i + 1:]:
            if not a.root_path or not b.root_path:
                continue
            if _within(a.root_path, b.root_path) or _within(b.root_path, a.root_path):
                deps.append(CrossProjectDependency(
                    from_project=a.project_key, to_project=b.project_key,
                    note="overlapping roots: changes may affect both projects"))
    return deps


class CrossProjectPlanner:
    def __init__(self, conn):
        self.conn = conn
        self.registry = registry_mod.ProjectRegistry(conn)

    def plan_work(self, source_request, persist=True) -> CrossProjectWorkPlan:
        if not source_request or not str(source_request).strip():
            raise ValueError("a cross-project task request is required")
        source_request = str(source_request).strip()
        projects = self.registry.list_projects()
        included = [p for p in projects if p.status == "active"]
        excluded = [p for p in projects if p.status != "active"]

        safety_blockers = []
        for p in projects:
            if p.status == "blocked":
                safety_blockers.append(f"{p.project_key}: project status is blocked")
            if p.root_path and not os.path.isdir(p.root_path):
                safety_blockers.append(
                    f"{p.project_key}: root is missing or stale ({p.root_path})")

        dependencies = detect_dependencies(included)
        dependency_notes = [
            f"{d.from_project} <-> {d.to_project}: {d.note}" for d in dependencies]
        if not dependency_notes:
            dependency_notes = ["No structural cross-project dependencies detected."]

        required_approvals = [
            "Explicit cross-project approval is required before any handoff.",
            "Each included project must be re-validated before changes are applied.",
        ]
        for p in included:
            required_approvals.append(
                f"{p.project_key}: changes confined to allowed write paths only.")

        suggested_commands = [
            "python3 main.py --validate-projects",
            "python3 main.py --multi-project-observatory --save-report",
        ]
        for p in included:
            suggested_commands.append(f"python3 main.py --validate-project {p.project_key}")
        suggested_commands.append(
            "python3 main.py --request-cross-project-approval PLAN_ID")

        status = "blocked" if safety_blockers else "proposed"

        plan = CrossProjectWorkPlan(
            id=0, generated_at=_now_iso(), source_request=source_request,
            included_project_keys=[p.project_key for p in included],
            excluded_project_keys=[p.project_key for p in excluded],
            dependency_notes=dependency_notes,
            required_approvals=required_approvals,
            safety_blockers=safety_blockers,
            suggested_commands=suggested_commands,
            status=status)

        for p in included:
            notes = ["Metadata-only plan; no commands run."]
            if p.protected_paths:
                notes.append("Protected paths must not be modified: "
                             + ", ".join(p.protected_paths))
            plan.items.append(CrossProjectWorkItem(
                id=0, plan_id=0, project_key=p.project_key,
                description=f"{source_request} (project: {p.project_key})",
                depends_on=[d.to_project for d in dependencies
                            if d.from_project == p.project_key],
                safety_notes=notes))

        if persist:
            self._persist(plan)
        return plan

    def _persist(self, plan) -> None:
        plan.id = database.save_cross_project_work_plan(
            self.conn, plan.generated_at, plan.source_request,
            json.dumps(plan.included_project_keys),
            json.dumps(plan.excluded_project_keys),
            json.dumps(plan.dependency_notes),
            json.dumps(plan.required_approvals),
            json.dumps(plan.safety_blockers),
            json.dumps(plan.suggested_commands),
            plan.status)
        for item in plan.items:
            item.plan_id = plan.id
            item.id = database.save_cross_project_work_item(
                self.conn, plan.id, item.project_key, item.description,
                json.dumps(item.depends_on), json.dumps(item.safety_notes))
        database.save_cross_project_plan_event(
            self.conn, plan.id, "created",
            f"status={plan.status} included={len(plan.included_project_keys)} "
            f"blockers={len(plan.safety_blockers)}")

    def get_plan(self, plan_id) -> Optional[CrossProjectWorkPlan]:
        row = database.get_cross_project_work_plan(self.conn, plan_id)
        if row is None:
            return None
        items = [
            CrossProjectWorkItem(
                id=r["id"], plan_id=r["plan_id"], project_key=r["project_key"],
                description=r["description"],
                depends_on=_safe_json_loads(r["depends_on_json"], []),
                safety_notes=_safe_json_loads(r["safety_notes_json"], []))
            for r in database.list_cross_project_work_items(self.conn, plan_id)
        ]
        return CrossProjectWorkPlan(
            id=row["id"], generated_at=row["generated_at"] or "",
            source_request=row["source_request"] or "",
            included_project_keys=_safe_json_loads(row["included_project_keys_json"], []),
            excluded_project_keys=_safe_json_loads(row["excluded_project_keys_json"], []),
            dependency_notes=_safe_json_loads(row["dependency_notes_json"], []),
            required_approvals=_safe_json_loads(row["required_approvals_json"], []),
            safety_blockers=_safe_json_loads(row["safety_blockers_json"], []),
            suggested_commands=_safe_json_loads(row["suggested_commands_json"], []),
            status=row["status"] or "proposed", items=items)

    def list_plans(self, limit=50):
        return database.list_cross_project_work_plans(self.conn, limit=limit)

    def set_status(self, plan_id, status) -> CrossProjectWorkPlan:
        if status not in VALID_STATUSES:
            raise ValueError(f"invalid plan status {status!r}; one of {VALID_STATUSES}")
        plan = self.get_plan(plan_id)
        if plan is None:
            raise ValueError(f"no cross-project plan {plan_id}")
        database.update_cross_project_work_plan_status(self.conn, plan_id, status)
        database.save_cross_project_plan_event(
            self.conn, plan_id, "status_changed", f"{plan.status}->{status}")
        return self.get_plan(plan_id)
