"""Execution handoff bridge for Observatory action items (Stage 4.7).

Dry-run handoffs convert action metadata into reviewable loop/external-job task
instructions without executing suggested commands, calling models, or creating
loops/jobs. Confirmed creation must be routed through existing safe systems by
the CLI layer; this module records handoff metadata and safety notes.
"""

import datetime
import json
from dataclasses import dataclass, field
from typing import List, Optional

import database
import observatory_actions


HANDOFF_TYPES = {"loop_task", "external_agent_job", "dry_run_plan"}


@dataclass
class ObservatoryActionHandoffRequest:
    action_id: int
    handoff_type: str = "dry_run_plan"
    target_loop_type: str = "code_build"
    target_workspace: str = "default"
    external_coder: str = "codex"
    require_approval: bool = True
    dry_run: bool = True
    created_at: str = ""


@dataclass
class ObservatoryActionHandoff:
    id: int
    action_id: int
    handoff_type: str
    generated_task: str
    target_loop_type: str
    target_workspace: str
    external_coder: str
    suggested_command: str
    safety_notes: List[str] = field(default_factory=list)
    status: str = "DRY_RUN"
    created_at: str = ""
    created_loop_id: Optional[int] = None
    created_external_job_id: Optional[int] = None


def _now_iso():
    return datetime.datetime.now().isoformat(timespec="seconds")


def _safe_json_loads(blob, default):
    try:
        return json.loads(blob or "")
    except (TypeError, ValueError):
        return default


def handoff_from_row(row):
    return ObservatoryActionHandoff(
        id=row["id"],
        action_id=row["action_id"],
        handoff_type=row["handoff_type"],
        generated_task=row["generated_task"] or "",
        target_loop_type=row["target_loop_type"] or "",
        target_workspace=row["target_workspace"] or "",
        external_coder=row["external_coder"] or "",
        suggested_command=row["suggested_command"] or "",
        safety_notes=_safe_json_loads(row["safety_notes_json"], []),
        status=row["status"] or "",
        created_at=row["created_at"] or "",
        created_loop_id=row["created_loop_id"],
        created_external_job_id=row["created_external_job_id"],
    )


class ObservatoryActionHandoffEngine:
    def __init__(self, conn):
        self.conn = conn

    def create_handoff(self, action_id, handoff_type="dry_run_plan",
                       target_loop_type="code_build", target_workspace="default",
                       external_coder="codex", require_approval=True,
                       confirm_create_loop=False,
                       confirm_create_external_job=False,
                       created_loop_id=None, created_external_job_id=None):
        if handoff_type not in HANDOFF_TYPES:
            raise ValueError(f"unknown observatory action handoff type '{handoff_type}'")
        action = observatory_actions.ObservatoryActionEngine(
            self.conn).get_action(action_id, record_view=False)
        generated_task = self.generate_task(action)
        safety_notes = self.safety_notes(handoff_type)
        dry_run = True
        status = "DRY_RUN"
        if handoff_type == "loop_task" and confirm_create_loop:
            dry_run = False
            status = "LOOP_CREATED" if created_loop_id else "CONFIRMED_PENDING_LOOP_CREATION"
        elif handoff_type == "external_agent_job" and confirm_create_external_job:
            dry_run = False
            status = ("EXTERNAL_JOB_CREATED" if created_external_job_id
                      else "CONFIRMED_PENDING_EXTERNAL_JOB_CREATION")
        suggested_command = self.suggested_command(
            action.id, handoff_type, target_loop_type, target_workspace,
            external_coder)
        handoff_id = database.save_observatory_action_handoff(
            self.conn,
            action.id,
            handoff_type,
            generated_task,
            target_loop_type,
            target_workspace,
            external_coder,
            suggested_command,
            json.dumps(safety_notes, sort_keys=True),
            status,
            created_loop_id=created_loop_id,
            created_external_job_id=created_external_job_id,
            dry_run=dry_run,
        )
        database.save_observatory_action_handoff_event(
            self.conn,
            handoff_id,
            action.id,
            "created",
            json.dumps({
                "handoff_type": handoff_type,
                "dry_run": dry_run,
                "confirm_create_loop": bool(confirm_create_loop),
                "confirm_create_external_job": bool(confirm_create_external_job),
            }, sort_keys=True),
        )
        row = database.get_observatory_action_handoff(self.conn, handoff_id)
        return handoff_from_row(row)

    def generate_task(self, action):
        return (
            "Investigate and remediate the following Loop Engineering issue: "
            f"{action.title}. Problem: {action.problem_summary}. "
            f"Recommended action: {action.recommended_action}. "
            f"Relevant loops: {action.affected_loop_ids}. "
            f"Relevant jobs: {action.affected_job_ids}. "
            f"Suggested manual command for context only: {action.suggested_command}. "
            f"Category: {action.category}. Priority: {action.priority}. "
            f"Risk: {action.risk_level}. Effort: {action.effort_level}. "
            "Do not execute unsafe commands. Preserve all safety gates."
        )

    def suggested_command(self, action_id, handoff_type, target_loop_type,
                          target_workspace, external_coder):
        base = [
            "python3 main.py",
            "--handoff-observatory-action",
            str(action_id),
            "--type",
            handoff_type,
        ]
        if target_loop_type:
            base.extend(["--loop-type", target_loop_type])
        if target_workspace:
            base.extend(["--workspace", target_workspace])
        if handoff_type == "external_agent_job" and external_coder:
            base.extend(["--external-coder", external_coder])
        return " ".join(base)

    def safety_notes(self, handoff_type):
        notes = [
            "Dry-run handoff does not execute suggested commands.",
            "Dry-run handoff does not call Ollama.",
            "Dry-run handoff does not create loops or external jobs.",
            "Confirmed creation must use existing Loop Engineering safety gates.",
            "No auto-commit is performed by handoff generation.",
        ]
        if handoff_type == "external_agent_job":
            notes.append("External agent handoff never starts Claude or Codex automatically.")
        return notes
