"""Loop Replay (Stage 2.4).

Reconstructs the settings of a previous loop run so it can be inspected
(`--dry-run`) or re-executed. Replay NEVER bypasses current safety systems: the
reconstructed run goes through the same workspace/profile checks, quality gates,
stop conditions, approval gates, and filesystem/terminal/git safety as any run.
"""

import datetime
from dataclasses import dataclass
from typing import Optional

import database

REPLAY_MODES = ("exact", "task_only", "fixed")


def _now() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


@dataclass
class ReplayRequest:
    source_loop_id: int
    replay_mode: str
    task: str
    loop_type: str
    workspace_name: str
    supervisor_model: Optional[str]
    coder_model: Optional[str]
    reviewer_model: Optional[str]
    test_analyst_model: Optional[str]
    approval_mode: str
    require_approval: bool
    auto_approve_low_risk: bool
    min_reviewer_confidence: Optional[float]
    commit: bool
    commit_message: Optional[str]
    dry_run: bool
    created_at: str = ""
    # Template metadata carried from the source loop (exact replay only).
    template_name: Optional[str] = None
    template_version: Optional[str] = None
    template_variables_json: Optional[str] = None
    rendered_task: Optional[str] = None
    context_pack_used: bool = False
    source_raw_task: Optional[str] = None
    source_clarified_task: Optional[str] = None

    def model_overrides(self) -> dict:
        """Non-None model overrides keyed by role (for role resolution)."""
        out = {}
        if self.supervisor_model:
            out["supervisor"] = self.supervisor_model
        if self.coder_model:
            out["coder"] = self.coder_model
        if self.reviewer_model:
            out["reviewer"] = self.reviewer_model
        if self.test_analyst_model:
            out["test_analyst"] = self.test_analyst_model
        return out


@dataclass
class ReplayResult:
    source_loop_id: int
    new_loop_id: Optional[int]
    replay_mode: str
    status: str
    stop_reason: str
    report_path: Optional[str]
    created_at: str = ""


def _metric_map(conn, loop_id):
    out = {}
    for m in database.get_metrics(conn, loop_id):
        out[m["metric_name"]] = (m["metric_text"] if m["metric_text"] is not None
                                 else m["metric_value"])
    return out


class ReplayEngine:
    def __init__(self, conn):
        self.conn = conn

    def reconstruct(self, source_loop_id, mode="exact", cli=None) -> ReplayRequest:
        """Build a ReplayRequest from a source loop + CLI overrides.

        cli keys (all optional): workspace, supervisor_model, coder_model,
        reviewer_model, test_analyst_model, require_approval, approval_mode,
        auto_approve_low_risk, min_conf, commit, commit_message, dry_run.
        """
        if mode not in REPLAY_MODES:
            raise ValueError(f"unknown replay mode '{mode}' (use {REPLAY_MODES})")
        cli = cli or {}
        loop = database.get_loop(self.conn, source_loop_id)
        if loop is None:
            raise ValueError(f"no loop with id {source_loop_id}")
        mv = _metric_map(self.conn, source_loop_id)

        src = {
            "task": loop["task"],
            "loop_type": loop["loop_type"] or "code_build",
            "workspace": loop["workspace_name"] or "default",
            "sup": loop["supervisor_model"],
            "cod": loop["coder_model"],
            "rev": loop["reviewer_model"],
            "ta": mv.get("test_analyst_model"),
            "require": int(mv.get("approval_required", 0) or 0) == 1,
            "mode": mv.get("approval_mode"),
            "auto": int(mv.get("auto_approve_low_risk", 0) or 0) == 1,
            "minconf": mv.get("reviewer_confidence_minimum"),
        }

        def pick(cli_key, src_val, default=None):
            v = cli.get(cli_key)
            return v if v is not None else (src_val if src_val is not None else default)

        if mode == "exact":
            task, loop_type = src["task"], src["loop_type"]
            workspace = cli.get("workspace") or src["workspace"]
            sup = pick("supervisor_model", src["sup"])
            cod = pick("coder_model", src["cod"])
            rev = pick("reviewer_model", src["rev"])
            ta = pick("test_analyst_model", src["ta"])
            require = bool(cli.get("require_approval")) or src["require"]
            appr_mode = cli.get("approval_mode") or src["mode"]
            auto = bool(cli.get("auto_approve_low_risk")) or src["auto"]
            minconf = cli.get("min_conf") if cli.get("min_conf") is not None else src["minconf"]
        elif mode == "task_only":
            task = src["task"]
            loop_type = "code_build"
            workspace = cli.get("workspace") or "default"
            sup, cod, rev, ta = (cli.get("supervisor_model"), cli.get("coder_model"),
                                 cli.get("reviewer_model"), cli.get("test_analyst_model"))
            require = bool(cli.get("require_approval"))
            appr_mode = cli.get("approval_mode")
            auto = bool(cli.get("auto_approve_low_risk"))
            minconf = cli.get("min_conf")
        else:  # fixed
            task = src["task"]
            loop_type = src["loop_type"]
            workspace = cli.get("workspace") or "default"
            sup, cod, rev, ta = (cli.get("supervisor_model"), cli.get("coder_model"),
                                 cli.get("reviewer_model"), cli.get("test_analyst_model"))
            require = bool(cli.get("require_approval"))
            appr_mode = cli.get("approval_mode")
            auto = bool(cli.get("auto_approve_low_risk"))
            minconf = cli.get("min_conf")

        if not appr_mode:
            appr_mode = "interactive" if require else "none"
        try:
            minconf = float(minconf) if minconf is not None else None
        except (TypeError, ValueError):
            minconf = None

        # Carry template metadata only for exact replay (preserve the rendered run).
        tmpl_name = tmpl_ver = tmpl_vars = rendered = None
        if mode == "exact" and ("template_name" in loop.keys()) and loop["template_name"]:
            tmpl_name = loop["template_name"]
            tmpl_ver = loop["template_version"]
            tmpl_vars = loop["template_variables_json"]
            rendered = loop["rendered_task"]
            # exact replay defaults to the rendered task.
            task = rendered or task

        return ReplayRequest(
            source_loop_id=source_loop_id, replay_mode=mode, task=task,
            loop_type=loop_type, workspace_name=workspace,
            supervisor_model=sup, coder_model=cod, reviewer_model=rev,
            test_analyst_model=ta, approval_mode=appr_mode, require_approval=require,
            auto_approve_low_risk=auto, min_reviewer_confidence=minconf,
            commit=bool(cli.get("commit")), commit_message=cli.get("commit_message"),
            dry_run=bool(cli.get("dry_run")), created_at=_now(),
            template_name=tmpl_name, template_version=tmpl_ver,
            template_variables_json=tmpl_vars, rendered_task=rendered,
            context_pack_used=(mode == "exact"
                               and ("context_pack_id" in loop.keys())
                               and bool(loop["context_pack_id"])),
            source_raw_task=(loop["raw_task"] if "raw_task" in loop.keys() else None),
            source_clarified_task=(loop["clarified_task"]
                                   if "clarified_task" in loop.keys() else None),
        )
