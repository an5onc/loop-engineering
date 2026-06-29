"""Loop Improvement Implementation Handoff (Stage 5.3).

This module converts loop-improvement action metadata into reviewable handoffs.
Default and packet modes do not execute commands, call models, create loops or
external jobs, apply proposals, or mutate framework definitions. Confirmed
creation is coordinated by the CLI through existing safe pathways.
"""

import datetime
import hashlib
import json
import os
from dataclasses import dataclass, field
from typing import List

import database
import loop_improvement_actions


PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
PACKETS_DIR = os.path.join(PROJECT_ROOT, "loop_improvement_handoff_packets")
HANDOFF_TYPES = {
    "dry_run_plan",
    "loop_task",
    "external_agent_job",
    "implementation_packet",
}


@dataclass
class LoopImprovementHandoffRequest:
    action_id: int
    handoff_type: str = "dry_run_plan"
    target_loop_type: str = "code_build"
    target_workspace: str = "default"
    external_coder: str = "codex"
    require_approval: bool = True
    dry_run: bool = True
    created_at: str = ""


@dataclass
class LoopImprovementHandoff:
    id: int
    action_id: int
    source_review_id: int
    source_proposal_id: int
    source_plan_id: int
    handoff_type: str
    generated_task: str
    implementation_scope: str
    target_type: str
    target_name: str
    target_loop_type: str
    target_workspace: str
    external_coder: str
    suggested_command: str
    safety_notes: List[str] = field(default_factory=list)
    status: str = "DRY_RUN"
    created_loop_id: int = None
    created_external_job_id: int = None
    dry_run: bool = True
    packet_path: str = ""
    created_at: str = ""


def _now_iso():
    return datetime.datetime.now().isoformat(timespec="seconds")


def _now_stamp():
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


def _safe_json_loads(blob, default):
    try:
        return json.loads(blob or "")
    except (TypeError, ValueError):
        return default


def infer_implementation_scope(target_type):
    return {
        "safety_policy": "safety_policy_update",
        "quality_gate": "quality_gate_update",
        "stop_condition": "stop_condition_update",
        "prompt": "prompt_contract_update",
        "agent_definition": "agent_definition_update",
        "loop_definition": "loop_definition_update",
        "external_agent_flow": "external_agent_flow_update",
        "documentation": "documentation_update",
        "testing": "testing_update",
        "observatory_flow": "observability_update",
    }.get(target_type, "unknown")


def is_packet_path(path):
    if not path:
        return False
    target = os.path.realpath(path)
    base = os.path.realpath(PACKETS_DIR)
    return target != base and target.startswith(base + os.sep)


def handoff_from_row(row):
    return LoopImprovementHandoff(
        id=row["id"],
        action_id=row["action_id"],
        source_review_id=row["source_review_id"],
        source_proposal_id=row["source_proposal_id"],
        source_plan_id=row["source_plan_id"],
        handoff_type=row["handoff_type"] or "",
        generated_task=row["generated_task"] or "",
        implementation_scope=row["implementation_scope"] or "",
        target_type=row["target_type"] or "",
        target_name=row["target_name"] or "",
        target_loop_type=row["target_loop_type"] or "",
        target_workspace=row["target_workspace"] or "",
        external_coder=row["external_coder"] or "",
        suggested_command=row["suggested_command"] or "",
        safety_notes=_safe_json_loads(row["safety_notes_json"], []),
        status=row["status"] or "",
        created_loop_id=row["created_loop_id"],
        created_external_job_id=row["created_external_job_id"],
        dry_run=bool(row["dry_run"]),
        packet_path=row["packet_path"] or "",
        created_at=row["created_at"] or "",
    )


class LoopImprovementHandoffEngine:
    def __init__(self, conn):
        self.conn = conn

    def create_handoff(self, action_id, handoff_type="dry_run_plan",
                       target_loop_type="code_build", target_workspace="default",
                       external_coder="codex", require_approval=True,
                       confirm_create_loop=False,
                       confirm_create_external_job=False,
                       created_loop_id=None, created_external_job_id=None):
        if handoff_type not in HANDOFF_TYPES:
            raise ValueError(f"unknown loop improvement handoff type '{handoff_type}'")
        action = loop_improvement_actions.LoopImprovementActionEngine(
            self.conn).get_action(action_id, record_view=False)
        generated_task = self.generate_task(action)
        implementation_scope = infer_implementation_scope(action.target_type)
        safety_notes = self.safety_notes(handoff_type)
        dry_run = True
        status = "DRY_RUN"
        if handoff_type == "implementation_packet":
            status = "PACKET_PENDING"
        elif handoff_type == "loop_task" and confirm_create_loop:
            dry_run = False
            status = "LOOP_CREATED" if created_loop_id else "CONFIRMED_PENDING_LOOP_CREATION"
        elif handoff_type == "external_agent_job" and confirm_create_external_job:
            dry_run = False
            status = ("EXTERNAL_JOB_CREATED" if created_external_job_id
                      else "CONFIRMED_PENDING_EXTERNAL_JOB_CREATION")
        suggested_command = self.suggested_command(
            action.id, handoff_type, target_loop_type, target_workspace, external_coder)
        handoff_id = database.save_loop_improvement_handoff(
            self.conn,
            action.id,
            action.source_review_id,
            action.source_proposal_id,
            action.source_plan_id,
            handoff_type,
            generated_task,
            implementation_scope,
            action.target_type,
            action.target_name,
            target_loop_type,
            target_workspace,
            external_coder,
            suggested_command,
            json.dumps(safety_notes, sort_keys=True),
            status,
            created_loop_id=created_loop_id,
            created_external_job_id=created_external_job_id,
            dry_run=dry_run,
            packet_path=None,
        )
        database.save_loop_improvement_handoff_event(
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
        if handoff_type == "implementation_packet":
            packet_path = self.save_packet(handoff_id, action, generated_task,
                                           implementation_scope, safety_notes,
                                           suggested_command)
            database.update_loop_improvement_handoff_packet_path(
                self.conn, handoff_id, packet_path, "PACKET_CREATED")
            database.save_loop_improvement_handoff_event(
                self.conn,
                handoff_id,
                action.id,
                "packet_created",
                json.dumps({"packet_path": packet_path}, sort_keys=True),
            )
        row = database.get_loop_improvement_handoff(self.conn, handoff_id)
        return handoff_from_row(row)

    def generate_task(self, action):
        return (
            f"Implement a safe Loop Engineering improvement for {action.target_type}: "
            f"{action.target_name}. Problem: {action.problem_summary}. "
            f"Proposed change: {action.proposed_change}. "
            f"Expected benefit: {action.expected_benefit}. "
            f"Recommended decision: {action.recommended_decision}. "
            f"Priority: {action.priority}. Risk: {action.risk_level}. "
            f"Effort: {action.effort_level}. "
            f"Affected loops: {action.affected_loop_ids}. "
            f"Affected actions: {action.affected_action_ids}. "
            f"Affected remediation plans: {action.affected_remediation_plan_ids}. "
            f"Operator notes: {action.notes or '(none)'}. "
            f"Suggested manual command for context only: {action.suggested_next_command}. "
            "Constraints: do not bypass safety gates, do not execute unsafe commands, "
            "preserve approval/workspace/command protections, and produce a "
            "reviewable change summary."
        )

    def suggested_command(self, action_id, handoff_type, target_loop_type,
                          target_workspace, external_coder):
        base = [
            "python3 main.py",
            "--handoff-loop-improvement-action",
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
            "Default handoff mode is dry-run.",
            "Suggested commands are never executed by handoff generation.",
            "Dry-run and implementation packet modes do not call Ollama.",
            "Dry-run and implementation packet modes do not create loops or external jobs.",
            "Confirmed creation must use existing Loop Engineering safety gates.",
            "No auto-commit is performed by handoff generation.",
            "Loop, agent, prompt, quality gate, and stop-condition definitions are not mutated.",
        ]
        if handoff_type == "external_agent_job":
            notes.append("External agent handoff never starts Claude or Codex automatically.")
        if handoff_type == "implementation_packet":
            notes.append("Implementation packet writes only under loop_improvement_handoff_packets/.")
        return notes

    def save_packet(self, handoff_id, action, generated_task, implementation_scope,
                    safety_notes, suggested_command):
        os.makedirs(PACKETS_DIR, exist_ok=True)
        filename = f"loop_improvement_handoff_{int(action.id)}_{_now_stamp()}.md"
        target = os.path.realpath(os.path.join(PACKETS_DIR, filename))
        base = os.path.realpath(PACKETS_DIR)
        if target != base and not target.startswith(base + os.sep):
            raise ValueError("handoff packet path escaped loop_improvement_handoff_packets/")
        content = self.render_packet(
            handoff_id, action, generated_task, implementation_scope,
            safety_notes, suggested_command)
        with open(target, "w", encoding="utf-8") as fh:
            fh.write(content)
        encoded = content.encode("utf-8")
        database.save_loop_improvement_handoff_packet(
            self.conn,
            handoff_id,
            action.id,
            target,
            "markdown",
            hashlib.sha256(encoded).hexdigest(),
            len(encoded),
        )
        return target

    def render_packet(self, handoff_id, action, generated_task, implementation_scope,
                      safety_notes, suggested_command):
        lines = []
        a = lines.append
        a("# Loop Improvement Implementation Handoff")
        a("")
        a("## Summary")
        a(f"- Handoff ID: {handoff_id}")
        a(f"- Action ID: {action.id}")
        a(f"- Target: {action.target_type}/{action.target_name}")
        a(f"- Priority: {action.priority}")
        a("")
        a("## Source Action")
        a(f"- Title: {action.title}")
        a(f"- Status: {action.status}")
        a(f"- Risk: {action.risk_level}")
        a(f"- Effort: {action.effort_level}")
        a(f"- Notes: {action.notes or '(none)'}")
        a("")
        a("## Source Proposal")
        a(f"- Review ID: {action.source_review_id}")
        a(f"- Proposal ID: {action.source_proposal_id}")
        a(f"- Plan ID: {action.source_plan_id}")
        a(f"- Problem: {action.problem_summary}")
        a(f"- Proposed change: {action.proposed_change}")
        a(f"- Expected benefit: {action.expected_benefit}")
        a(f"- Recommended decision: {action.recommended_decision}")
        a("")
        a("## Implementation Scope")
        a(f"- {implementation_scope}")
        a("")
        a("## Generated Task")
        a(generated_task)
        a("")
        a("## Safety Constraints")
        for note in safety_notes:
            a(f"- {note}")
        a("")
        a("## Suggested Manual Commands")
        a(f"- {suggested_command}")
        a(f"- {action.suggested_next_command}")
        a("")
        a("## Review Checklist")
        a("- Verify no safety gate, workspace, approval, or command protections were bypassed.")
        a("- Verify generated changes are reviewable and scoped to the intended target.")
        a("- Run relevant tests before accepting implementation.")
        a("")
        a("## Next Steps")
        a("- Review this packet manually.")
        a("- Decide whether to run a loop task or external-agent handoff with confirmation.")
        a("")
        return "\n".join(lines)
