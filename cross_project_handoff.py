"""Stage 7.5 — Cross-Project Handoff Packets.

Builds a safe, human-readable implementation handoff packet for an approved
cross-project plan. Fails closed: a packet is produced only when a valid
``approved`` approval that references the same plan exists.

This module:
  * executes no commands and creates no loops or external jobs;
  * never reads protected file CONTENTS — it lists protected path NAMES only;
  * writes only Markdown packets under ``cross_project_handoff_packets/`` and
    its own DB rows; it edits nothing outside the packet directory.
"""

import datetime
import hashlib
import json
import os
from dataclasses import dataclass, field
from typing import List, Optional

import database
import cross_project_approvals as approvals_mod
import cross_project_planner as planner_mod
import multi_project_registry as registry_mod


PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
PACKETS_DIR = os.path.join(PROJECT_ROOT, "cross_project_handoff_packets")


@dataclass
class CrossProjectHandoff:
    id: int
    plan_id: int
    approval_id: int
    generated_at: str
    report_path: str
    report_format: str
    content_hash: str
    bytes_written: int
    projects: List[str] = field(default_factory=list)
    status: str = "created"


def _now_iso() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def _now_stamp() -> str:
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


def is_packet_path(path) -> bool:
    if not path:
        return False
    target = os.path.realpath(path)
    base = os.path.realpath(PACKETS_DIR)
    return target != base and target.startswith(base + os.sep)


def handoff_from_row(row) -> CrossProjectHandoff:
    try:
        projects = json.loads(row["projects_json"] or "[]")
    except (TypeError, ValueError):
        projects = []
    return CrossProjectHandoff(
        id=row["id"], plan_id=row["plan_id"], approval_id=row["approval_id"],
        generated_at=row["generated_at"] or "", report_path=row["report_path"] or "",
        report_format=row["report_format"] or "markdown",
        content_hash=row["content_hash"] or "",
        bytes_written=row["bytes_written"] or 0, projects=projects,
        status=row["status"] or "created")


class CrossProjectHandoffBuilder:
    def __init__(self, conn):
        self.conn = conn
        self.registry = registry_mod.ProjectRegistry(conn)
        self.planner = planner_mod.CrossProjectPlanner(conn)
        self.gate = approvals_mod.CrossProjectApprovalGate(conn)

    def create_handoff(self, plan_id, approval_id) -> CrossProjectHandoff:
        plan = self.planner.get_plan(plan_id)
        if plan is None:
            raise ValueError(f"no cross-project plan {plan_id}")
        approval = self.gate.get_approval(approval_id)
        if approval is None:
            raise ValueError(f"no cross-project approval {approval_id}")
        if approval.plan_id != plan.id:
            raise ValueError(
                f"approval {approval_id} references plan {approval.plan_id}, "
                f"not plan {plan.id}")
        if not approvals_mod.is_usable(approval):
            raise ValueError(
                f"approval {approval_id} is not usable (status={approval.status}); "
                "an approved approval is required before handoff")

        content = self.render_packet(plan, approval)
        path = self._new_packet_path(plan.id, approval.id)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        encoded = content.encode("utf-8")
        chash = hashlib.sha256(encoded).hexdigest()
        nbytes = len(encoded)
        handoff_id = database.save_cross_project_handoff(
            self.conn, plan.id, approval.id, _now_iso(), path, "markdown",
            chash, nbytes, json.dumps(plan.included_project_keys), "created")
        database.save_cross_project_handoff_event(
            self.conn, handoff_id, "created",
            f"plan={plan.id} approval={approval.id} projects="
            f"{len(plan.included_project_keys)}")
        return CrossProjectHandoff(
            id=handoff_id, plan_id=plan.id, approval_id=approval.id,
            generated_at=_now_iso(), report_path=path, report_format="markdown",
            content_hash=chash, bytes_written=nbytes,
            projects=plan.included_project_keys, status="created")

    def get_handoff(self, handoff_id) -> Optional[CrossProjectHandoff]:
        row = database.get_cross_project_handoff(self.conn, handoff_id)
        return handoff_from_row(row) if row else None

    def list_handoffs(self, limit=50):
        return database.list_cross_project_handoffs(self.conn, limit=limit)

    def _new_packet_path(self, plan_id, approval_id) -> str:
        os.makedirs(PACKETS_DIR, exist_ok=True)
        filename = (f"cross_project_handoff_plan_{int(plan_id)}_"
                    f"approval_{int(approval_id)}_{_now_stamp()}.md")
        target = os.path.realpath(os.path.join(PACKETS_DIR, filename))
        base = os.path.realpath(PACKETS_DIR)
        if target != base and not target.startswith(base + os.sep):
            raise ValueError("handoff packet path escaped packet directory")
        return target

    def render_packet(self, plan, approval) -> str:
        lines = []
        a = lines.append
        a("# Cross-Project Implementation Handoff Packet")
        a("")
        a("## Plan Summary")
        a(f"- Plan ID: {plan.id}")
        a(f"- Approval ID: {approval.id} (status: {approval.status})")
        a(f"- Generated at: {_now_iso()}")
        a(f"- Plan status: {plan.status}")
        a(f"- Source request: {plan.source_request}")
        a("")
        a("## Projects Involved")
        if not plan.included_project_keys:
            a("- (none)")
        for key in plan.included_project_keys:
            project = self.registry.get_project(key)
            if project is None:
                a(f"- {key} (no longer registered)")
                continue
            a(f"- {key} — root: {project.root_path}")
            a(f"  - default branch: {project.default_branch or '(none)'}")
        a("")
        a("## Safety Profile Per Project")
        for key in plan.included_project_keys:
            project = self.registry.get_project(key)
            if project is None:
                continue
            a(f"- {key}")
            a(f"  - safety profile: {project.safety_profile_name or '(none)'}")
            a(f"  - allowed write paths: {project.allowed_write_paths or '(none)'}")
            # Protected path NAMES only — contents are never read or included.
            a(f"  - protected paths (names only): {project.protected_paths or '(none)'}")
        a("")
        a("## Explicit Non-Goals")
        for goal in (
            "Do NOT modify any protected path listed above.",
            "Do NOT execute commands automatically — run verification manually.",
            "Do NOT write outside each project's allowed write paths.",
            "Do NOT modify projects not listed in this packet.",
            "Do NOT create loops or external agent jobs from this packet.",
        ):
            a(f"- {goal}")
        a("")
        a("## Required Verification Commands")
        for cmd in (
            "python3 main.py --validate-projects",
            "python3 main.py --multi-project-observatory",
            f"python3 main.py --cross-project-plan {plan.id}",
            f"python3 main.py --cross-project-approval {approval.id}",
        ):
            a(f"- `{cmd}`")
        a("")
        a("## Completion Response JSON")
        a("Return this JSON when the cross-project work is complete:")
        a("```json")
        a(json.dumps({
            "plan_id": plan.id,
            "approval_id": approval.id,
            "status": "completed",
            "projects": plan.included_project_keys,
            "files_changed": [],
            "commands_run": [],
            "tests_passed": None,
            "notes": "",
        }, indent=2))
        a("```")
        a("")
        a("## Resume / Handoff Instructions")
        for step in (
            f"Review the plan: `python3 main.py --cross-project-plan {plan.id}`.",
            f"Confirm the approval is still approved: "
            f"`python3 main.py --cross-project-approval {approval.id}`.",
            "Make changes only within each project's allowed write paths.",
            "Run the verification commands above before reporting completion.",
            "Record completion using the JSON block above.",
        ):
            a(f"- {step}")
        a("")
        a("## Protected-Content Warning")
        a("- This packet lists protected path NAMES only.")
        a("- Protected file CONTENTS are intentionally excluded and were not read.")
        a("- Never copy secrets or protected file contents into any handoff artifact.")
        a("")
        return "\n".join(lines)
