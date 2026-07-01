"""Stage 8.0 — Governance Policy Registry.

Durable governance policy definitions for fleet-level rules (required
validation, stale project age, approval freshness, blocked-project handling,
handoff/schedule integrity, audit recency). Policies are metadata-only:
creating or inspecting one NEVER executes a command, calls a model, reads
project file contents, or writes to a registered project root.

Rules come from a fixed built-in ``RULE_REGISTRY``; each rule is a pure function
over Stage 7 metadata (no expression language, no dynamic code). Project-scoped
rules receive a ``ProjectView``; fleet-scoped rules receive a ``FleetView``.
"""

import datetime
import json
import re
from dataclasses import dataclass, field
from typing import Callable, List, Optional

import database


VALID_STATUSES = ("active", "inactive", "archived")
_KEY_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}$")

DEFAULT_POLICY_KEY = "fleet_baseline"


@dataclass
class GovernanceRule:
    key: str
    description: str
    default_severity: str  # "fail" | "warn"
    scope: str             # "project" | "fleet"
    evaluate: Callable


@dataclass
class GovernancePolicy:
    id: int
    policy_key: str
    name: str
    description: str
    rule_keys: List[str] = field(default_factory=list)
    severity_overrides: dict = field(default_factory=dict)
    status: str = "active"
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


@dataclass
class ProjectView:
    project_key: str
    status: str
    root_exists: bool
    repo_url: Optional[str]
    default_branch: Optional[str]
    safety_profile_name: Optional[str]
    protected_paths: List[str]
    latest_validation_status: str
    has_validation: bool


@dataclass
class FleetView:
    total_projects: int
    pending_approvals: int
    handoffs_without_approved_approval: int
    schedules_without_approved_approval: int
    multi_project_audit_count: int


def _now_iso() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def _safe_json_loads(blob, default):
    try:
        return json.loads(blob or "")
    except (TypeError, ValueError):
        return default


# --------------------------------------------------------------------------- #
# Built-in deterministic rules.
# --------------------------------------------------------------------------- #
def _r_require_validation(view: ProjectView):
    return view.has_validation, f"has_validation={view.has_validation}"


def _r_validation_not_failing(view: ProjectView):
    ok = view.latest_validation_status not in ("FAIL", "BLOCKED")
    return ok, f"latest_validation={view.latest_validation_status}"


def _r_not_stale(view: ProjectView):
    return view.root_exists, f"root_exists={view.root_exists}"


def _r_blocked_project_handling(view: ProjectView):
    ok = view.status != "blocked"
    return ok, f"status={view.status}"


def _r_require_safety_profile(view: ProjectView):
    ok = bool(view.safety_profile_name)
    return ok, f"safety_profile={view.safety_profile_name or '(none)'}"


def _r_approval_freshness(view: FleetView):
    ok = view.pending_approvals == 0
    return ok, f"pending_approvals={view.pending_approvals}"


def _r_handoff_schedule_integrity(view: FleetView):
    bad = (view.handoffs_without_approved_approval
           + view.schedules_without_approved_approval)
    return bad == 0, (
        f"handoffs_without_approval={view.handoffs_without_approved_approval} "
        f"schedules_without_approval={view.schedules_without_approved_approval}")


def _r_audit_recency(view: FleetView):
    ok = view.multi_project_audit_count >= 1
    return ok, f"multi_project_audits={view.multi_project_audit_count}"


RULE_REGISTRY = {
    "require_validation": GovernanceRule(
        "require_validation", "Each active project has a validation report.",
        "warn", "project", _r_require_validation),
    "validation_not_failing": GovernanceRule(
        "validation_not_failing",
        "No active project has a failing/blocked latest validation.",
        "fail", "project", _r_validation_not_failing),
    "not_stale": GovernanceRule(
        "not_stale", "Each active project root exists (not stale/missing).",
        "fail", "project", _r_not_stale),
    "blocked_project_handling": GovernanceRule(
        "blocked_project_handling",
        "No active project is left in blocked status unhandled.",
        "warn", "project", _r_blocked_project_handling),
    "require_safety_profile": GovernanceRule(
        "require_safety_profile", "Each active project declares a safety profile.",
        "warn", "project", _r_require_safety_profile),
    "approval_freshness": GovernanceRule(
        "approval_freshness", "No cross-project approval is left pending.",
        "warn", "fleet", _r_approval_freshness),
    "handoff_schedule_integrity": GovernanceRule(
        "handoff_schedule_integrity",
        "Every handoff/schedule references an approved approval.",
        "fail", "fleet", _r_handoff_schedule_integrity),
    "audit_recency": GovernanceRule(
        "audit_recency", "At least one multi-project audit has been recorded.",
        "warn", "fleet", _r_audit_recency),
}

DEFAULT_POLICY_RULES = [
    "not_stale",
    "validation_not_failing",
    "require_validation",
    "blocked_project_handling",
    "approval_freshness",
    "handoff_schedule_integrity",
    "audit_recency",
]


def policy_from_row(row) -> GovernancePolicy:
    return GovernancePolicy(
        id=row["id"], policy_key=row["policy_key"],
        name=row["name"] or row["policy_key"],
        description=row["description"] or "",
        rule_keys=_safe_json_loads(row["rule_keys_json"], []),
        severity_overrides=_safe_json_loads(row["severity_overrides_json"], {}),
        status=row["status"] or "active",
        created_at=row["created_at"], updated_at=row["updated_at"])


def effective_severity(policy: GovernancePolicy, rule_key: str) -> str:
    override = policy.severity_overrides.get(rule_key)
    if override in ("fail", "warn"):
        return override
    rule = RULE_REGISTRY.get(rule_key)
    return rule.default_severity if rule else "fail"


class GovernancePolicyRegistry:
    def __init__(self, conn):
        self.conn = conn

    def create_policy(self, policy_key, rule_keys, name=None, description="",
                      severity_overrides=None, status="active") -> GovernancePolicy:
        if not policy_key or not _KEY_RE.match(str(policy_key)):
            raise ValueError(
                f"invalid policy key {policy_key!r}; use letters, digits, '-', '_', '.'")
        if status not in VALID_STATUSES:
            raise ValueError(f"invalid status {status!r}; one of {VALID_STATUSES}")
        rule_keys = list(rule_keys or [])
        if not rule_keys:
            raise ValueError("a policy must include at least one rule")
        unknown = [k for k in rule_keys if k not in RULE_REGISTRY]
        if unknown:
            raise ValueError(f"unknown rule keys: {', '.join(unknown)}")
        overrides = dict(severity_overrides or {})
        for key, val in overrides.items():
            if val not in ("fail", "warn"):
                raise ValueError(f"invalid severity override for {key}: {val!r}")
        if self.get_policy_by_key(policy_key) is not None:
            raise ValueError(f"policy key already exists: {policy_key}")
        policy_id = database.create_governance_policy(
            self.conn, policy_key, name or policy_key, description,
            json.dumps(rule_keys), json.dumps(overrides), status)
        database.save_governance_policy_event(
            self.conn, policy_id, policy_key, "created",
            f"rules={len(rule_keys)} status={status}")
        return self.get_policy(policy_id)

    def get_policy(self, policy_id) -> Optional[GovernancePolicy]:
        row = database.get_governance_policy(self.conn, policy_id)
        return policy_from_row(row) if row else None

    def get_policy_by_key(self, policy_key) -> Optional[GovernancePolicy]:
        row = database.get_governance_policy_by_key(self.conn, policy_key)
        return policy_from_row(row) if row else None

    def list_policies(self) -> List[GovernancePolicy]:
        return [policy_from_row(r)
                for r in database.list_governance_policies(self.conn)]

    def set_status(self, policy_id, status) -> GovernancePolicy:
        if status not in VALID_STATUSES:
            raise ValueError(f"invalid status {status!r}; one of {VALID_STATUSES}")
        policy = self.get_policy(policy_id)
        if policy is None:
            raise ValueError(f"no governance policy {policy_id}")
        database.update_governance_policy_status(self.conn, policy_id, status)
        database.save_governance_policy_event(
            self.conn, policy_id, policy.policy_key, "status_changed",
            f"{policy.status}->{status}")
        return self.get_policy(policy_id)

    def ensure_default_policy(self) -> GovernancePolicy:
        existing = self.get_policy_by_key(DEFAULT_POLICY_KEY)
        if existing is not None:
            return existing
        return self.create_policy(
            DEFAULT_POLICY_KEY, DEFAULT_POLICY_RULES,
            name="Fleet Baseline Policy",
            description="Default fleet governance baseline.")
