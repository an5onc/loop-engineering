"""Human Approval Gates (Stage 2.2).

Higher-risk actions (file writes, command execution, git commits) can require
explicit human approval before proceeding. The engine decides whether a given
action needs approval (per policy + risk), then obtains a decision either from an
injected responder (tests / automation) or an interactive `[y/N]` prompt. With
`--approval-mode none`, a required-but-unprompted action is DECLINED (fail
closed) — automatic approval of risky actions is never the default.
"""

import datetime
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

ACTION_TYPES = {
    "file_write", "command_execute", "git_commit", "workspace_profile_change",
    "unsafe_operation_review", "loop_continue_after_failure",
}
RISK_LEVELS = ["low", "medium", "high", "critical"]
_RISK_ORDER = {r: i for i, r in enumerate(RISK_LEVELS)}

DEFAULT_RISK = {
    "file_write": "medium",
    "command_execute": "medium",
    "git_commit": "high",
    "workspace_profile_change": "high",
    "unsafe_operation_review": "critical",
    "loop_continue_after_failure": "medium",
}

_PROMPT = {
    "file_write": "Approve file writes? [y/N] ",
    "command_execute": "Approve command execution? [y/N] ",
    "git_commit": "Approve git commit? [y/N] ",
}


def _now() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


@dataclass
class ApprovalRequest:
    loop_id: Optional[int]
    attempt_number: int
    gate_name: str
    action_type: str
    risk_level: str
    summary: str
    details_json: str = ""
    created_at: str = field(default_factory=_now)


@dataclass
class ApprovalDecision:
    approved: bool
    decision: str          # not_required | approved | declined | auto_approved_low_risk
    reason: str
    decided_at: str = field(default_factory=_now)


@dataclass
class ApprovalPolicy:
    name: str = "default"
    description: str = ""
    enabled: bool = False
    require_approval_for_writes: bool = True
    require_approval_for_commands: bool = True
    require_approval_for_git_commit: bool = True
    require_approval_for_profile_levels: List[str] = field(default_factory=list)
    auto_approve_low_risk: bool = False
    risk_threshold: str = "medium"


def validate_policy(policy: ApprovalPolicy) -> List[str]:
    errors = []
    if policy.risk_threshold not in _RISK_ORDER:
        errors.append(f"risk_threshold must be one of {RISK_LEVELS}")
    if not isinstance(policy.require_approval_for_profile_levels, list):
        errors.append("require_approval_for_profile_levels must be a list")
    return errors


class ApprovalGateEngine:
    def __init__(self, policy: ApprovalPolicy, mode: str = "none", responder=None):
        self.policy = policy
        self.mode = mode  # "none" | "interactive"
        self.responder = responder
        self.history: List[Tuple[ApprovalRequest, ApprovalDecision]] = []

    def default_risk(self, action_type: str) -> str:
        return DEFAULT_RISK.get(action_type, "medium")

    def is_required(self, action_type: str, risk_level: str) -> bool:
        p = self.policy
        if not p.enabled:
            return False
        flag = {
            "file_write": p.require_approval_for_writes,
            "command_execute": p.require_approval_for_commands,
            "git_commit": p.require_approval_for_git_commit,
        }.get(action_type, True)
        if not flag:
            return False
        if p.auto_approve_low_risk and risk_level == "low":
            return False
        return _RISK_ORDER.get(risk_level, 1) >= _RISK_ORDER.get(p.risk_threshold, 1)

    def evaluate(self, request: ApprovalRequest) -> ApprovalDecision:
        if not self.is_required(request.action_type, request.risk_level):
            if self.policy.auto_approve_low_risk and request.risk_level == "low":
                dec = ApprovalDecision(True, "auto_approved_low_risk",
                                       "low risk auto-approved by policy")
            else:
                dec = ApprovalDecision(True, "not_required",
                                       "policy does not require approval")
            self.history.append((request, dec))
            return dec

        if self.responder is not None:
            ok = bool(self.responder(request))
            dec = ApprovalDecision(ok, "approved" if ok else "declined",
                                   "responder decision")
        elif self.mode == "interactive":
            prompt = _PROMPT.get(request.action_type,
                                 f"Approve {request.action_type}? [y/N] ")
            try:
                ans = input(prompt).strip().lower()
            except EOFError:
                ans = ""
            ok = ans in ("y", "yes")
            dec = ApprovalDecision(ok, "approved" if ok else "declined",
                                   "interactive prompt")
        else:  # mode == "none" but approval is required -> fail closed
            dec = ApprovalDecision(False, "declined",
                                   "approval required but approval-mode is none")
        self.history.append((request, dec))
        return dec

    # --- summary accessors for metrics / output ------------------------- #
    @property
    def requests_count(self) -> int:
        return sum(1 for _r, d in self.history if d.decision != "not_required")

    @property
    def approved_count(self) -> int:
        return sum(1 for _r, d in self.history
                   if d.approved and d.decision not in ("not_required",))

    @property
    def declined_count(self) -> int:
        return sum(1 for _r, d in self.history if not d.approved)
