"""SQLite persistence layer (Stage 1.4).

Stores every loop run, agent step, file operation, command result, review, and
metric. Uses only the standard-library `sqlite3`. The database is created (and
tables added) on demand; existing data is never deleted.
"""

import hashlib
import json
import os
import sqlite3
from typing import List, Optional

import config

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))


def db_path() -> str:
    return os.path.join(PROJECT_ROOT, config.DB_FILE)


SCHEMA = """
CREATE TABLE IF NOT EXISTS loops (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    task TEXT,
    status TEXT,
    stop_reason TEXT,
    retry_count INTEGER,
    total_duration_seconds REAL,
    supervisor_model TEXT,
    coder_model TEXT,
    reviewer_model TEXT,
    loop_type TEXT,
    loop_version TEXT,
    workspace_name TEXT,
    workspace_root TEXT,
    template_name TEXT,
    template_version TEXT,
    template_variables_json TEXT,
    rendered_task TEXT,
    project_intelligence_report_id INTEGER,
    context_pack_id INTEGER,
    raw_task TEXT,
    clarified_task TEXT,
    intake_used INTEGER,
    intake_status TEXT
);

CREATE TABLE IF NOT EXISTS resume_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    loop_id INTEGER,
    resume_type TEXT,
    completion_imported INTEGER,
    status_before TEXT,
    status_after TEXT,
    stop_reason TEXT,
    report_path TEXT,
    commit_requested INTEGER,
    commit_created INTEGER,
    details_json TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS external_agent_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    loop_id INTEGER,
    attempt_number INTEGER,
    external_agent_name TEXT,
    status TEXT,
    workspace_name TEXT,
    workspace_root TEXT,
    handoff_path TEXT,
    packet_path TEXT,
    completion_path TEXT,
    priority TEXT,
    labels_json TEXT,
    notes TEXT,
    archived INTEGER,
    retry_count INTEGER,
    last_error TEXT,
    completed_at TEXT,
    cancelled_at TEXT,
    archived_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS external_job_health_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER,
    loop_id INTEGER,
    severity TEXT,
    issue_type TEXT,
    message TEXT,
    recommended_action TEXT,
    details_json TEXT,
    fixed INTEGER,
    fix_action TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS external_batch_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id TEXT,
    action TEXT,
    report_path TEXT,
    report_format TEXT,
    content_hash TEXT,
    bytes_written INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS external_job_batch_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id TEXT,
    action TEXT,
    job_id INTEGER,
    loop_id INTEGER,
    status_before TEXT,
    status_after TEXT,
    success INTEGER,
    skipped INTEGER,
    error TEXT,
    details_json TEXT,
    dry_run INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS external_completion_inbox_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER,
    loop_id INTEGER,
    completion_path TEXT,
    completion_type TEXT,
    action TEXT,
    status TEXT,
    error TEXT,
    dry_run INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS external_agent_job_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER,
    loop_id INTEGER,
    event_type TEXT,
    status_before TEXT,
    status_after TEXT,
    details_json TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS external_agent_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    loop_id INTEGER,
    attempt_number INTEGER,
    external_agent_name TEXT,
    mode TEXT,
    handoff_path TEXT,
    handoff_prompt_hash TEXT,
    started INTEGER,
    completed INTEGER,
    success INTEGER,
    exit_code INTEGER,
    stdout TEXT,
    stderr TEXT,
    duration_seconds REAL,
    files_changed_json TEXT,
    commands_run_json TEXT,
    summary TEXT,
    error TEXT,
    completion_json TEXT,
    completion_raw_text TEXT,
    completion_parsed INTEGER,
    completion_status TEXT,
    completion_tests_passed INTEGER,
    completion_imported_at TEXT,
    workspace_snapshot_json TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS task_intake_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    loop_id INTEGER,
    raw_task TEXT,
    clarified_task TEXT,
    intent_summary TEXT,
    detected_loop_type TEXT,
    confidence_score REAL,
    ambiguity_score REAL,
    risk_level TEXT,
    missing_details_json TEXT,
    assumptions_json TEXT,
    clarification_required INTEGER,
    clarification_questions_json TEXT,
    clarification_answers_json TEXT,
    recommended_workspace TEXT,
    recommended_profile TEXT,
    recommended_template TEXT,
    recommended_next_action TEXT,
    status TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS context_packs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    loop_id INTEGER,
    workspace_name TEXT,
    task TEXT,
    total_files_considered INTEGER,
    total_files_included INTEGER,
    total_chars INTEGER,
    truncated INTEGER,
    warnings_json TEXT,
    recommendations_json TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS context_pack_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    context_pack_id INTEGER NOT NULL,
    path TEXT,
    file_type TEXT,
    detected_language TEXT,
    size_bytes INTEGER,
    line_count INTEGER,
    content_hash TEXT,
    included_chars INTEGER,
    truncated INTEGER,
    relevance_score REAL,
    reason TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (context_pack_id) REFERENCES context_packs(id)
);

CREATE TABLE IF NOT EXISTS project_intelligence_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_name TEXT,
    workspace_root TEXT,
    generated_at TEXT,
    total_files_scanned INTEGER,
    total_dirs_scanned INTEGER,
    ignored_files_count INTEGER,
    languages_json TEXT,
    important_files_json TEXT,
    recommendations_json TEXT,
    warnings_json TEXT,
    report_json TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS project_file_summaries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    report_id INTEGER NOT NULL,
    workspace_name TEXT,
    path TEXT,
    file_type TEXT,
    size_bytes INTEGER,
    line_count INTEGER,
    detected_language TEXT,
    importance_score REAL,
    reason TEXT,
    content_preview TEXT,
    content_hash TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (report_id) REFERENCES project_intelligence_reports(id)
);

CREATE TABLE IF NOT EXISTS loop_template_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    loop_id INTEGER NOT NULL,
    template_name TEXT,
    template_version TEXT,
    variables_json TEXT,
    rendered_task TEXT,
    status TEXT,
    message TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (loop_id) REFERENCES loops(id)
);

CREATE TABLE IF NOT EXISTS memory_search_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    loop_id INTEGER,
    query TEXT,
    workspace_name TEXT,
    source_types_json TEXT,
    result_count INTEGER,
    top_results_json TEXT,
    used_for_context INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS replay_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_loop_id INTEGER,
    new_loop_id INTEGER,
    replay_mode TEXT,
    dry_run INTEGER,
    status TEXT,
    stop_reason TEXT,
    settings_json TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS run_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    loop_id INTEGER NOT NULL,
    report_path TEXT,
    report_format TEXT,
    content_hash TEXT,
    bytes_written INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (loop_id) REFERENCES loops(id)
);

CREATE TABLE IF NOT EXISTS approval_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    loop_id INTEGER NOT NULL,
    attempt_number INTEGER,
    gate_name TEXT,
    action_type TEXT,
    risk_level TEXT,
    summary TEXT,
    details_json TEXT,
    approved INTEGER,
    decision TEXT,
    reason TEXT,
    created_at TEXT,
    decided_at TEXT,
    FOREIGN KEY (loop_id) REFERENCES loops(id)
);

CREATE TABLE IF NOT EXISTS observatory_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    generated_at TEXT,
    time_window TEXT,
    filters_json TEXT,
    summary_json TEXT,
    alert_count INTEGER,
    critical_alert_count INTEGER,
    warning_alert_count INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS observatory_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id INTEGER NOT NULL,
    report_path TEXT,
    report_format TEXT,
    content_hash TEXT,
    bytes_written INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (snapshot_id) REFERENCES observatory_snapshots(id)
);

CREATE TABLE IF NOT EXISTS observatory_trend_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    generated_at TEXT,
    snapshot_count INTEGER,
    start_snapshot_id INTEGER,
    end_snapshot_id INTEGER,
    filters_json TEXT,
    trends_json TEXT,
    alerts_json TEXT,
    recommendations_json TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS observatory_trend_markdown_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trend_report_id INTEGER NOT NULL,
    report_path TEXT,
    report_format TEXT,
    content_hash TEXT,
    bytes_written INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (trend_report_id) REFERENCES observatory_trend_reports(id)
);

CREATE TABLE IF NOT EXISTS observatory_failure_drilldowns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    generated_at TEXT,
    filters_json TEXT,
    cluster_by TEXT,
    total_failures INTEGER,
    items_json TEXT,
    clusters_json TEXT,
    recommendations_json TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS observatory_failure_markdown_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    drilldown_id INTEGER NOT NULL,
    report_path TEXT,
    report_format TEXT,
    content_hash TEXT,
    bytes_written INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (drilldown_id) REFERENCES observatory_failure_drilldowns(id)
);

CREATE TABLE IF NOT EXISTS observatory_remediation_plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    generated_at TEXT,
    source_type TEXT,
    source_id INTEGER,
    filters_json TEXT,
    summary_json TEXT,
    items_json TEXT,
    total_items INTEGER,
    urgent_count INTEGER,
    high_priority_count INTEGER,
    medium_priority_count INTEGER,
    low_priority_count INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS observatory_remediation_markdown_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    remediation_plan_id INTEGER NOT NULL,
    report_path TEXT,
    report_format TEXT,
    content_hash TEXT,
    bytes_written INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (remediation_plan_id) REFERENCES observatory_remediation_plans(id)
);

CREATE TABLE IF NOT EXISTS observatory_action_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_plan_id INTEGER,
    source_item_id INTEGER,
    title TEXT,
    category TEXT,
    priority TEXT,
    status TEXT,
    suggested_command TEXT,
    problem_summary TEXT,
    recommended_action TEXT,
    affected_loop_ids_json TEXT,
    affected_job_ids_json TEXT,
    risk_level TEXT,
    effort_level TEXT,
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT,
    completed_at TEXT,
    dismissed_at TEXT
);

CREATE TABLE IF NOT EXISTS observatory_action_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action_id INTEGER,
    event_type TEXT,
    status_before TEXT,
    status_after TEXT,
    details_json TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (action_id) REFERENCES observatory_action_items(id)
);

CREATE TABLE IF NOT EXISTS observatory_action_markdown_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    report_path TEXT,
    report_format TEXT,
    content_hash TEXT,
    bytes_written INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS observatory_action_reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    generated_at TEXT,
    filters_json TEXT,
    group_by TEXT,
    total_actions_reviewed INTEGER,
    top_actions_json TEXT,
    groups_json TEXT,
    recommendations_json TEXT,
    next_steps_json TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS observatory_action_review_markdown_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action_review_id INTEGER NOT NULL,
    report_path TEXT,
    report_format TEXT,
    content_hash TEXT,
    bytes_written INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (action_review_id) REFERENCES observatory_action_reviews(id)
);

CREATE TABLE IF NOT EXISTS observatory_action_handoffs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action_id INTEGER,
    handoff_type TEXT,
    generated_task TEXT,
    target_loop_type TEXT,
    target_workspace TEXT,
    external_coder TEXT,
    suggested_command TEXT,
    safety_notes_json TEXT,
    status TEXT,
    created_loop_id INTEGER,
    created_external_job_id INTEGER,
    dry_run INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (action_id) REFERENCES observatory_action_items(id)
);

CREATE TABLE IF NOT EXISTS observatory_action_handoff_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    handoff_id INTEGER,
    action_id INTEGER,
    event_type TEXT,
    details_json TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (handoff_id) REFERENCES observatory_action_handoffs(id)
);

CREATE TABLE IF NOT EXISTS observatory_action_handoff_reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    generated_at TEXT,
    filters_json TEXT,
    group_by TEXT,
    total_handoffs_reviewed INTEGER,
    groups_json TEXT,
    items_json TEXT,
    recommendations_json TEXT,
    next_steps_json TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS observatory_action_handoff_review_markdown_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    handoff_review_id INTEGER NOT NULL,
    report_path TEXT,
    report_format TEXT,
    content_hash TEXT,
    bytes_written INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (handoff_review_id) REFERENCES observatory_action_handoff_reviews(id)
);

CREATE TABLE IF NOT EXISTS observatory_stage4_audits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    generated_at TEXT,
    overall_status TEXT,
    total_checks INTEGER,
    passed_checks INTEGER,
    warning_checks INTEGER,
    failed_checks INTEGER,
    sections_json TEXT,
    recommendations_json TEXT,
    stage5_readiness_json TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS observatory_stage4_audit_markdown_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    stage4_audit_id INTEGER NOT NULL,
    report_path TEXT,
    report_format TEXT,
    content_hash TEXT,
    bytes_written INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (stage4_audit_id) REFERENCES observatory_stage4_audits(id)
);

CREATE TABLE IF NOT EXISTS loop_improvement_plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    generated_at TEXT,
    source_type TEXT,
    source_id INTEGER,
    filters_json TEXT,
    summary_json TEXT,
    proposals_json TEXT,
    total_proposals INTEGER,
    urgent_count INTEGER,
    high_count INTEGER,
    medium_count INTEGER,
    low_count INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS loop_improvement_proposals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id INTEGER NOT NULL,
    target_type TEXT,
    target_name TEXT,
    title TEXT,
    problem_summary TEXT,
    evidence_json TEXT,
    proposed_change TEXT,
    expected_benefit TEXT,
    risk_level TEXT,
    effort_level TEXT,
    priority TEXT,
    affected_loop_ids_json TEXT,
    affected_action_ids_json TEXT,
    affected_remediation_plan_ids_json TEXT,
    status TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT,
    FOREIGN KEY (plan_id) REFERENCES loop_improvement_plans(id)
);

CREATE TABLE IF NOT EXISTS loop_improvement_markdown_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    improvement_plan_id INTEGER NOT NULL,
    report_path TEXT,
    report_format TEXT,
    content_hash TEXT,
    bytes_written INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (improvement_plan_id) REFERENCES loop_improvement_plans(id)
);

CREATE TABLE IF NOT EXISTS loop_improvement_reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    generated_at TEXT,
    filters_json TEXT,
    group_by TEXT,
    total_proposals_reviewed INTEGER,
    top_proposals_json TEXT,
    groups_json TEXT,
    recommendations_json TEXT,
    next_steps_json TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS loop_improvement_review_markdown_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    improvement_review_id INTEGER NOT NULL,
    report_path TEXT,
    report_format TEXT,
    content_hash TEXT,
    bytes_written INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (improvement_review_id) REFERENCES loop_improvement_reviews(id)
);

CREATE TABLE IF NOT EXISTS loop_improvement_action_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_review_id INTEGER NOT NULL,
    source_proposal_id INTEGER NOT NULL,
    source_plan_id INTEGER NOT NULL,
    target_type TEXT,
    target_name TEXT,
    title TEXT,
    priority TEXT,
    status TEXT,
    risk_level TEXT,
    effort_level TEXT,
    problem_summary TEXT,
    proposed_change TEXT,
    expected_benefit TEXT,
    recommended_decision TEXT,
    suggested_next_command TEXT,
    affected_loop_ids_json TEXT,
    affected_action_ids_json TEXT,
    affected_remediation_plan_ids_json TEXT,
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT,
    completed_at TEXT,
    dismissed_at TEXT,
    FOREIGN KEY (source_review_id) REFERENCES loop_improvement_reviews(id),
    FOREIGN KEY (source_proposal_id) REFERENCES loop_improvement_proposals(id),
    FOREIGN KEY (source_plan_id) REFERENCES loop_improvement_plans(id)
);

CREATE TABLE IF NOT EXISTS loop_improvement_action_batches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_review_id INTEGER NOT NULL,
    generated_at TEXT,
    filters_json TEXT,
    total_actions INTEGER,
    created_count INTEGER,
    skipped_duplicates INTEGER,
    action_ids_json TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (source_review_id) REFERENCES loop_improvement_reviews(id)
);

CREATE TABLE IF NOT EXISTS loop_improvement_action_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action_id INTEGER,
    event_type TEXT,
    status_before TEXT,
    status_after TEXT,
    details_json TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (action_id) REFERENCES loop_improvement_action_items(id)
);

CREATE TABLE IF NOT EXISTS loop_improvement_action_markdown_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    report_path TEXT,
    report_format TEXT,
    content_hash TEXT,
    bytes_written INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS loop_improvement_handoffs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action_id INTEGER NOT NULL,
    source_review_id INTEGER,
    source_proposal_id INTEGER,
    source_plan_id INTEGER,
    handoff_type TEXT,
    generated_task TEXT,
    implementation_scope TEXT,
    target_type TEXT,
    target_name TEXT,
    target_loop_type TEXT,
    target_workspace TEXT,
    external_coder TEXT,
    suggested_command TEXT,
    safety_notes_json TEXT,
    status TEXT,
    created_loop_id INTEGER,
    created_external_job_id INTEGER,
    dry_run INTEGER,
    packet_path TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (action_id) REFERENCES loop_improvement_action_items(id)
);

CREATE TABLE IF NOT EXISTS loop_improvement_handoff_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    handoff_id INTEGER,
    action_id INTEGER,
    event_type TEXT,
    details_json TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (handoff_id) REFERENCES loop_improvement_handoffs(id)
);

CREATE TABLE IF NOT EXISTS loop_improvement_handoff_packets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    handoff_id INTEGER NOT NULL,
    action_id INTEGER NOT NULL,
    packet_path TEXT,
    packet_format TEXT,
    content_hash TEXT,
    bytes_written INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (handoff_id) REFERENCES loop_improvement_handoffs(id),
    FOREIGN KEY (action_id) REFERENCES loop_improvement_action_items(id)
);

CREATE TABLE IF NOT EXISTS project_workspaces (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE,
    root_path TEXT,
    allowed_write_paths_json TEXT,
    allowed_read_paths_json TEXT,
    allowed_command_paths_json TEXT,
    allow_git INTEGER,
    profile_name TEXT,
    profile_version TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS steps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    loop_id INTEGER NOT NULL,
    step_name TEXT,
    agent_role TEXT,
    model TEXT,
    attempt_number INTEGER,
    prompt TEXT,
    response TEXT,
    latency_seconds REAL,
    prompt_eval_count INTEGER,
    eval_count INTEGER,
    eval_tokens_per_second REAL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (loop_id) REFERENCES loops(id)
);

CREATE TABLE IF NOT EXISTS reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    loop_id INTEGER NOT NULL,
    attempt_number INTEGER,
    approved INTEGER,
    summary TEXT,
    issues_json TEXT,
    required_changes_json TEXT,
    confidence_score REAL,
    stop_reason TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (loop_id) REFERENCES loops(id)
);

CREATE TABLE IF NOT EXISTS file_operations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    loop_id INTEGER NOT NULL,
    attempt_number INTEGER,
    path TEXT,
    operation TEXT,
    allowed INTEGER,
    reason_if_blocked TEXT,
    content_hash TEXT,
    bytes_written INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (loop_id) REFERENCES loops(id)
);

CREATE TABLE IF NOT EXISTS command_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    loop_id INTEGER NOT NULL,
    attempt_number INTEGER,
    command TEXT,
    allowed INTEGER,
    exit_code INTEGER,
    stdout TEXT,
    stderr TEXT,
    duration_seconds REAL,
    timed_out INTEGER,
    reason_if_blocked TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (loop_id) REFERENCES loops(id)
);

CREATE TABLE IF NOT EXISTS metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    loop_id INTEGER NOT NULL,
    metric_name TEXT,
    metric_value REAL,
    metric_unit TEXT,
    metric_text TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (loop_id) REFERENCES loops(id)
);

CREATE TABLE IF NOT EXISTS git_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    loop_id INTEGER NOT NULL,
    event_type TEXT,
    command TEXT,
    exit_code INTEGER,
    stdout TEXT,
    stderr TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (loop_id) REFERENCES loops(id)
);

CREATE TABLE IF NOT EXISTS agent_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    loop_id INTEGER NOT NULL,
    agent_name TEXT,
    agent_role TEXT,
    model TEXT,
    event_type TEXT,
    details_json TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (loop_id) REFERENCES loops(id)
);

CREATE TABLE IF NOT EXISTS quality_gate_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    loop_id INTEGER NOT NULL,
    attempt_number INTEGER,
    gate_name TEXT,
    passed INTEGER,
    required INTEGER,
    severity TEXT,
    message TEXT,
    details_json TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (loop_id) REFERENCES loops(id)
);

CREATE TABLE IF NOT EXISTS stop_condition_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    loop_id INTEGER NOT NULL,
    attempt_number INTEGER,
    condition_name TEXT,
    triggered INTEGER,
    severity TEXT,
    message TEXT,
    details_json TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (loop_id) REFERENCES loops(id)
);
"""


def _migrate(conn: sqlite3.Connection) -> None:
    """Add columns introduced after the original schema, if missing."""
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(loops)")}
    for col in ("loop_type", "loop_version", "workspace_name", "workspace_root",
                "template_name", "template_version", "template_variables_json",
                "rendered_task", "project_intelligence_report_id",
                "context_pack_id", "raw_task", "clarified_task", "intake_used",
                "intake_status"):
        if col not in existing:
            conn.execute(f"ALTER TABLE loops ADD COLUMN {col} TEXT")
    metric_cols = {row["name"] for row in conn.execute("PRAGMA table_info(metrics)")}
    if "metric_text" not in metric_cols:
        conn.execute("ALTER TABLE metrics ADD COLUMN metric_text TEXT")
    # project_workspaces may predate profile columns.
    pw_cols = {row["name"] for row in conn.execute("PRAGMA table_info(project_workspaces)")}
    if pw_cols:  # table exists
        for col in ("profile_name", "profile_version"):
            if col not in pw_cols:
                conn.execute(f"ALTER TABLE project_workspaces ADD COLUMN {col} TEXT")
    # external_agent_events may predate completion columns (Stage 3.1).
    ext_cols = {row["name"] for row in conn.execute("PRAGMA table_info(external_agent_events)")}
    if ext_cols:
        for col in ("completion_json", "completion_raw_text", "completion_parsed",
                    "completion_status", "completion_tests_passed",
                    "completion_imported_at", "workspace_snapshot_json"):
            if col not in ext_cols:
                conn.execute(f"ALTER TABLE external_agent_events ADD COLUMN {col} TEXT")
    # external_agent_jobs may predate queue/lifecycle columns (Stage 3.4).
    job_cols = {row["name"] for row in conn.execute("PRAGMA table_info(external_agent_jobs)")}
    if job_cols:
        for col in ("priority", "labels_json", "notes", "archived", "retry_count",
                    "last_error", "completed_at", "cancelled_at", "archived_at"):
            if col not in job_cols:
                conn.execute(f"ALTER TABLE external_agent_jobs ADD COLUMN {col} TEXT")
    conn.commit()


def init_db(path: Optional[str] = None) -> sqlite3.Connection:
    """Open (creating if needed) the database and ensure all tables exist."""
    conn = sqlite3.connect(path or db_path())
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    conn.commit()
    _migrate(conn)
    return conn


# --------------------------------------------------------------------------- #
# Writing
# --------------------------------------------------------------------------- #
def insert_loop(conn, task, supervisor_model, coder_model, reviewer_model,
                loop_type=None, loop_version=None,
                workspace_name=None, workspace_root=None,
                template_name=None, template_version=None,
                template_variables_json=None, rendered_task=None,
                project_intelligence_report_id=None,
                context_pack_id=None, raw_task=None, clarified_task=None,
                intake_used=None, intake_status=None) -> int:
    cur = conn.execute(
        "INSERT INTO loops (task, status, supervisor_model, coder_model, "
        "reviewer_model, loop_type, loop_version, workspace_name, workspace_root, "
        "template_name, template_version, template_variables_json, rendered_task, "
        "project_intelligence_report_id, context_pack_id, raw_task, clarified_task, "
        "intake_used, intake_status) "
        "VALUES (?, 'running', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (task, supervisor_model, coder_model, reviewer_model, loop_type,
         loop_version, workspace_name, workspace_root, template_name,
         template_version, template_variables_json, rendered_task,
         project_intelligence_report_id, context_pack_id, raw_task, clarified_task,
         (1 if intake_used else 0) if intake_used is not None else None, intake_status),
    )
    conn.commit()
    return cur.lastrowid


def save_external_agent_event(conn, loop_id, attempt_number, agent_name, mode,
                              handoff_path, handoff_prompt_hash, result) -> int:
    import json
    cur = conn.execute(
        "INSERT INTO external_agent_events (loop_id, attempt_number, "
        "external_agent_name, mode, handoff_path, handoff_prompt_hash, started, "
        "completed, success, exit_code, stdout, stderr, duration_seconds, "
        "files_changed_json, commands_run_json, summary, error) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (loop_id, attempt_number, agent_name, mode, handoff_path, handoff_prompt_hash,
         1 if result.started else 0, 1 if result.completed else 0,
         1 if result.success else 0, result.exit_code, result.stdout, result.stderr,
         result.duration_seconds, json.dumps(result.files_changed),
         json.dumps(result.commands_run), result.summary, result.error),
    )
    conn.commit()
    return cur.lastrowid


def get_external_agent_events(conn, loop_id):
    return conn.execute(
        "SELECT * FROM external_agent_events WHERE loop_id=? ORDER BY id",
        (loop_id,)).fetchall()


def save_external_agent_completion(conn, loop_id, completion):
    """Attach a completion to the latest external_agent_event for the loop."""
    import datetime as _dt
    import json as _json
    row = conn.execute(
        "SELECT id FROM external_agent_events WHERE loop_id=? ORDER BY id DESC LIMIT 1",
        (loop_id,)).fetchone()
    cj = _json.dumps({
        "agent_name": completion.agent_name, "status": completion.status,
        "summary": completion.summary, "files_changed": completion.files_changed,
        "commands_run": completion.commands_run, "tests_run": completion.tests_run,
        "tests_passed": completion.tests_passed, "issues": completion.issues,
        "notes": completion.notes, "next_steps": completion.next_steps,
        "parsed": completion.parsed})
    tp = (1 if completion.tests_passed else 0) if completion.tests_passed is not None else None
    now = _dt.datetime.now().isoformat(timespec="seconds")
    if row is not None:
        conn.execute(
            "UPDATE external_agent_events SET completion_json=?, completion_raw_text=?, "
            "completion_parsed=?, completion_status=?, completion_tests_passed=?, "
            "completion_imported_at=? WHERE id=?",
            (cj, completion.raw_text, 1 if completion.parsed else 0,
             completion.status, tp, now, row["id"]))
    else:
        cur = conn.execute(
            "INSERT INTO external_agent_events (loop_id, attempt_number, "
            "external_agent_name, mode, completion_json, completion_raw_text, "
            "completion_parsed, completion_status, completion_tests_passed, "
            "completion_imported_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (loop_id, completion.attempt_number, completion.agent_name, "import",
             cj, completion.raw_text, 1 if completion.parsed else 0,
             completion.status, tp, now))
    conn.commit()


def _now_iso():
    import datetime as _dt
    return _dt.datetime.now().isoformat(timespec="seconds")


def save_external_agent_job(conn, loop_id, attempt_number, external_agent_name,
                            status, workspace_name, workspace_root,
                            handoff_path=None, packet_path=None,
                            completion_path=None, priority="normal",
                            labels_json="[]", notes="") -> int:
    now = _now_iso()
    cur = conn.execute(
        "INSERT INTO external_agent_jobs (loop_id, attempt_number, "
        "external_agent_name, status, workspace_name, workspace_root, handoff_path, "
        "packet_path, completion_path, priority, labels_json, notes, archived, "
        "retry_count, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (loop_id, attempt_number, external_agent_name, status, workspace_name,
         workspace_root, handoff_path, packet_path, completion_path, priority,
         labels_json, notes, 0, 0, now, now))
    conn.commit()
    return cur.lastrowid


def update_external_agent_job(conn, job_id, **fields):
    if not fields:
        return
    fields["updated_at"] = _now_iso()
    cols = ", ".join(f"{k}=?" for k in fields)
    conn.execute(f"UPDATE external_agent_jobs SET {cols} WHERE id=?",
                 (*fields.values(), job_id))
    conn.commit()


def update_external_agent_job_status(conn, job_id, status):
    update_external_agent_job(conn, job_id, status=status)


def get_external_agent_job(conn, job_id):
    return conn.execute("SELECT * FROM external_agent_jobs WHERE id=?",
                        (job_id,)).fetchone()


def get_external_agent_job_for_loop(conn, loop_id):
    return conn.execute(
        "SELECT * FROM external_agent_jobs WHERE loop_id=? ORDER BY id DESC LIMIT 1",
        (loop_id,)).fetchone()


def list_external_agent_jobs(conn, status=None, limit=20):
    if status:
        return conn.execute(
            "SELECT * FROM external_agent_jobs WHERE status=? ORDER BY id DESC LIMIT ?",
            (status, limit)).fetchall()
    return conn.execute(
        "SELECT * FROM external_agent_jobs ORDER BY id DESC LIMIT ?",
        (limit,)).fetchall()


def list_external_agent_jobs_filtered(conn, archived=None, agent_name=None,
                                      workspace_name=None, status=None, limit=20):
    """Filtered job listing. archived: None=all, True/False to filter."""
    where, params = [], []
    if archived is not None:
        # archived may be stored as TEXT on migrated DBs; CAST normalizes it.
        where.append("CAST(COALESCE(archived,0) AS INTEGER)=?")
        params.append(1 if archived else 0)
    if agent_name:
        where.append("external_agent_name=?")
        params.append(agent_name)
    if workspace_name:
        where.append("workspace_name=?")
        params.append(workspace_name)
    if status:
        where.append("status=?")
        params.append(status)
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    params.append(limit)
    return conn.execute(
        f"SELECT * FROM external_agent_jobs{clause} ORDER BY id DESC LIMIT ?",
        params).fetchall()


def save_external_agent_job_event(conn, job_id, loop_id, event_type,
                                  status_before, status_after, details_json="{}") -> int:
    cur = conn.execute(
        "INSERT INTO external_agent_job_events (job_id, loop_id, event_type, "
        "status_before, status_after, details_json) VALUES (?,?,?,?,?,?)",
        (job_id, loop_id, event_type, status_before, status_after, details_json))
    conn.commit()
    return cur.lastrowid


def save_external_completion_inbox_event(conn, job_id, loop_id, completion_path,
                                         completion_type, action, status,
                                         error=None, dry_run=False) -> int:
    cur = conn.execute(
        "INSERT INTO external_completion_inbox_events (job_id, loop_id, "
        "completion_path, completion_type, action, status, error, dry_run) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (job_id, loop_id, completion_path, completion_type, action, status,
         error, 1 if dry_run else 0))
    conn.commit()
    return cur.lastrowid


def save_external_job_batch_event(conn, batch_id, action, job_id, loop_id,
                                  status_before, status_after, success, skipped,
                                  error=None, details_json="{}", dry_run=False) -> int:
    cur = conn.execute(
        "INSERT INTO external_job_batch_events (batch_id, action, job_id, loop_id, "
        "status_before, status_after, success, skipped, error, details_json, dry_run) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (batch_id, action, job_id, loop_id, status_before, status_after,
         1 if success else 0, 1 if skipped else 0, error, details_json,
         1 if dry_run else 0))
    conn.commit()
    return cur.lastrowid


def get_external_job_batch_events(conn, job_id=None, batch_id=None, limit=50):
    if job_id is not None:
        return conn.execute(
            "SELECT * FROM external_job_batch_events WHERE job_id=? ORDER BY id DESC "
            "LIMIT ?", (job_id, limit)).fetchall()
    if batch_id is not None:
        return conn.execute(
            "SELECT * FROM external_job_batch_events WHERE batch_id=? ORDER BY id "
            "LIMIT ?", (batch_id, limit)).fetchall()
    return conn.execute(
        "SELECT * FROM external_job_batch_events ORDER BY id DESC LIMIT ?",
        (limit,)).fetchall()


def save_external_job_health_event(conn, job_id, loop_id, severity, issue_type,
                                   message, recommended_action, details_json="{}",
                                   fixed=False, fix_action=None) -> int:
    cur = conn.execute(
        "INSERT INTO external_job_health_events (job_id, loop_id, severity, "
        "issue_type, message, recommended_action, details_json, fixed, fix_action) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (job_id, loop_id, severity, issue_type, message, recommended_action,
         details_json, 1 if fixed else 0, fix_action))
    conn.commit()
    return cur.lastrowid


def get_external_job_health_events(conn, job_id=None, loop_id=None, limit=50):
    if job_id is not None:
        return conn.execute(
            "SELECT * FROM external_job_health_events WHERE job_id=? ORDER BY id DESC "
            "LIMIT ?", (job_id, limit)).fetchall()
    if loop_id is not None:
        return conn.execute(
            "SELECT * FROM external_job_health_events WHERE loop_id=? ORDER BY id DESC "
            "LIMIT ?", (loop_id, limit)).fetchall()
    return conn.execute(
        "SELECT * FROM external_job_health_events ORDER BY id DESC LIMIT ?",
        (limit,)).fetchall()


def list_external_job_health_events(conn, limit=50):
    return conn.execute(
        "SELECT * FROM external_job_health_events ORDER BY id DESC LIMIT ?",
        (limit,)).fetchall()


def save_external_batch_report(conn, batch_id, action, report_path, report_format,
                               content_hash, bytes_written) -> int:
    cur = conn.execute(
        "INSERT INTO external_batch_reports (batch_id, action, report_path, "
        "report_format, content_hash, bytes_written) VALUES (?,?,?,?,?,?)",
        (batch_id, action, report_path, report_format, content_hash, bytes_written))
    conn.commit()
    return cur.lastrowid


def get_external_batch_report(conn, batch_id):
    return conn.execute(
        "SELECT * FROM external_batch_reports WHERE batch_id=? ORDER BY id DESC LIMIT 1",
        (batch_id,)).fetchone()


def list_external_batch_reports(conn, limit=20):
    return conn.execute(
        "SELECT * FROM external_batch_reports ORDER BY id DESC LIMIT ?",
        (limit,)).fetchall()


def list_external_job_batch_events(conn, limit=50):
    return conn.execute(
        "SELECT * FROM external_job_batch_events ORDER BY id DESC LIMIT ?",
        (limit,)).fetchall()


def get_external_completion_inbox_events(conn, job_id):
    return conn.execute(
        "SELECT * FROM external_completion_inbox_events WHERE job_id=? ORDER BY id",
        (job_id,)).fetchall()


def list_external_completion_inbox_events(conn, limit=20):
    return conn.execute(
        "SELECT * FROM external_completion_inbox_events ORDER BY id DESC LIMIT ?",
        (limit,)).fetchall()


def get_external_agent_job_events(conn, job_id):
    return conn.execute(
        "SELECT * FROM external_agent_job_events WHERE job_id=? ORDER BY id",
        (job_id,)).fetchall()


def save_resume_event(conn, loop_id, resume_type, completion_imported, status_before,
                      status_after, stop_reason, report_path, commit_requested,
                      commit_created, details_json="{}") -> int:
    cur = conn.execute(
        "INSERT INTO resume_events (loop_id, resume_type, completion_imported, "
        "status_before, status_after, stop_reason, report_path, commit_requested, "
        "commit_created, details_json) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (loop_id, resume_type, 1 if completion_imported else 0, status_before,
         status_after, stop_reason, report_path, 1 if commit_requested else 0,
         1 if commit_created else 0, details_json),
    )
    conn.commit()
    return cur.lastrowid


def get_resume_events(conn, loop_id):
    return conn.execute(
        "SELECT * FROM resume_events WHERE loop_id=? ORDER BY id", (loop_id,)).fetchall()


def list_paused_external_loops(conn, limit=20):
    return conn.execute(
        "SELECT l.*, (SELECT external_agent_name FROM external_agent_events e "
        "WHERE e.loop_id=l.id ORDER BY e.id DESC LIMIT 1) AS ext_agent, "
        "(SELECT handoff_path FROM external_agent_events e WHERE e.loop_id=l.id "
        "ORDER BY e.id DESC LIMIT 1) AS handoff_path "
        "FROM loops l WHERE l.status IN ('PAUSED_EXTERNAL_AGENT','NEEDS_EXTERNAL_AGENT') "
        "ORDER BY l.id DESC LIMIT ?", (limit,)).fetchall()


def save_external_agent_snapshot(conn, loop_id, snapshot_json):
    """Attach a handoff-time workspace snapshot to the latest external event."""
    row = conn.execute(
        "SELECT id FROM external_agent_events WHERE loop_id=? ORDER BY id DESC LIMIT 1",
        (loop_id,)).fetchone()
    if row is not None:
        conn.execute(
            "UPDATE external_agent_events SET workspace_snapshot_json=? WHERE id=?",
            (snapshot_json, row["id"]))
        conn.commit()


def get_external_agent_snapshot(conn, loop_id):
    row = conn.execute(
        "SELECT workspace_snapshot_json FROM external_agent_events WHERE loop_id=? "
        "AND workspace_snapshot_json IS NOT NULL ORDER BY id DESC LIMIT 1",
        (loop_id,)).fetchone()
    return row["workspace_snapshot_json"] if row else None


def get_external_agent_completion(conn, loop_id):
    return conn.execute(
        "SELECT * FROM external_agent_events WHERE loop_id=? AND completion_imported_at "
        "IS NOT NULL ORDER BY id DESC LIMIT 1", (loop_id,)).fetchone()


def save_task_intake_event(conn, loop_id, result, status, answers_json=None) -> int:
    import json
    cur = conn.execute(
        "INSERT INTO task_intake_events (loop_id, raw_task, clarified_task, "
        "intent_summary, detected_loop_type, confidence_score, ambiguity_score, "
        "risk_level, missing_details_json, assumptions_json, clarification_required, "
        "clarification_questions_json, clarification_answers_json, "
        "recommended_workspace, recommended_profile, recommended_template, "
        "recommended_next_action, status) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (loop_id, result.raw_task, result.clarified_task, result.intent_summary,
         result.detected_loop_type, result.confidence_score, result.ambiguity_score,
         result.risk_level, json.dumps(result.missing_details),
         json.dumps(result.assumptions), 1 if result.clarification_required else 0,
         json.dumps([vars(q) for q in result.clarification_questions]),
         answers_json, result.recommended_workspace, result.recommended_profile,
         result.recommended_template, result.recommended_next_action, status),
    )
    conn.commit()
    return cur.lastrowid


def get_task_intake_events(conn, loop_id):
    return conn.execute(
        "SELECT * FROM task_intake_events WHERE loop_id=? ORDER BY id",
        (loop_id,)).fetchall()


def save_context_pack(conn, pack, loop_id=None) -> int:
    import json
    cur = conn.execute(
        "INSERT INTO context_packs (loop_id, workspace_name, task, "
        "total_files_considered, total_files_included, total_chars, truncated, "
        "warnings_json, recommendations_json) VALUES (?,?,?,?,?,?,?,?,?)",
        (loop_id, pack.workspace_name, pack.task, pack.total_files_considered,
         pack.total_files_included, pack.total_chars, 1 if pack.truncated else 0,
         json.dumps(pack.warnings), json.dumps(pack.recommendations)),
    )
    cp_id = cur.lastrowid
    for f in pack.files:  # metadata only — never store file contents
        conn.execute(
            "INSERT INTO context_pack_files (context_pack_id, path, file_type, "
            "detected_language, size_bytes, line_count, content_hash, included_chars, "
            "truncated, relevance_score, reason) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (cp_id, f.path, f.file_type, f.detected_language, f.size_bytes,
             f.line_count, f.content_hash, f.included_chars, 1 if f.truncated else 0,
             f.relevance_score, f.reason),
        )
    conn.commit()
    return cp_id


def set_loop_context_pack_id(conn, loop_id, context_pack_id):
    conn.execute("UPDATE loops SET context_pack_id=? WHERE id=?",
                 (context_pack_id, loop_id))
    conn.commit()


def get_context_pack(conn, loop_id):
    return conn.execute(
        "SELECT * FROM context_packs WHERE loop_id=? ORDER BY id DESC LIMIT 1",
        (loop_id,)).fetchone()


def get_context_pack_by_id(conn, cp_id):
    return conn.execute("SELECT * FROM context_packs WHERE id=?", (cp_id,)).fetchone()


def get_context_pack_files(conn, context_pack_id):
    return conn.execute(
        "SELECT * FROM context_pack_files WHERE context_pack_id=? ORDER BY id",
        (context_pack_id,)).fetchall()


def list_context_packs(conn, workspace_name=None, limit=20):
    if workspace_name:
        return conn.execute(
            "SELECT * FROM context_packs WHERE workspace_name=? ORDER BY id DESC LIMIT ?",
            (workspace_name, limit)).fetchall()
    return conn.execute(
        "SELECT * FROM context_packs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()


def save_project_intelligence_report(conn, report) -> int:
    import json
    s = report.structure_summary
    cur = conn.execute(
        "INSERT INTO project_intelligence_reports (workspace_name, workspace_root, "
        "generated_at, total_files_scanned, total_dirs_scanned, ignored_files_count, "
        "languages_json, important_files_json, recommendations_json, warnings_json, "
        "report_json) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (report.workspace_name, s.root_path, report.generated_at,
         s.total_files_scanned, s.total_dirs_scanned, s.ignored_files_count,
         json.dumps(s.languages_detected), json.dumps(s.important_files),
         json.dumps(report.recommendations), json.dumps(report.warnings),
         json.dumps(report.to_dict())),
    )
    report_id = cur.lastrowid
    for f in report.file_summaries:
        conn.execute(
            "INSERT INTO project_file_summaries (report_id, workspace_name, path, "
            "file_type, size_bytes, line_count, detected_language, importance_score, "
            "reason, content_preview, content_hash) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (report_id, report.workspace_name, f.path, f.file_type, f.size_bytes,
             f.line_count, f.detected_language, f.importance_score, f.reason,
             f.content_preview, f.hash),
        )
    conn.commit()
    return report_id


def get_latest_project_intelligence_report(conn, workspace_name):
    return conn.execute(
        "SELECT * FROM project_intelligence_reports WHERE workspace_name=? "
        "ORDER BY id DESC LIMIT 1", (workspace_name,)).fetchone()


def get_project_intelligence_report(conn, report_id):
    return conn.execute(
        "SELECT * FROM project_intelligence_reports WHERE id=?", (report_id,)).fetchone()


def list_project_intelligence_reports(conn, workspace_name=None, limit=20):
    if workspace_name:
        return conn.execute(
            "SELECT * FROM project_intelligence_reports WHERE workspace_name=? "
            "ORDER BY id DESC LIMIT ?", (workspace_name, limit)).fetchall()
    return conn.execute(
        "SELECT * FROM project_intelligence_reports ORDER BY id DESC LIMIT ?",
        (limit,)).fetchall()


def save_loop_template_event(conn, loop_id, template_name, template_version,
                             variables_json, rendered_task, status, message) -> int:
    cur = conn.execute(
        "INSERT INTO loop_template_events (loop_id, template_name, "
        "template_version, variables_json, rendered_task, status, message) "
        "VALUES (?,?,?,?,?,?,?)",
        (loop_id, template_name, template_version, variables_json, rendered_task,
         status, message),
    )
    conn.commit()
    return cur.lastrowid


def get_loop_template_events(conn, loop_id):
    return conn.execute(
        "SELECT * FROM loop_template_events WHERE loop_id=? ORDER BY id",
        (loop_id,)).fetchall()


def save_project_workspace(conn, ws) -> None:
    import json
    conn.execute(
        "INSERT INTO project_workspaces (name, root_path, allowed_write_paths_json, "
        "allowed_read_paths_json, allowed_command_paths_json, allow_git, "
        "profile_name, profile_version, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(name) DO UPDATE SET root_path=excluded.root_path, "
        "allowed_write_paths_json=excluded.allowed_write_paths_json, "
        "allowed_read_paths_json=excluded.allowed_read_paths_json, "
        "allowed_command_paths_json=excluded.allowed_command_paths_json, "
        "allow_git=excluded.allow_git, profile_name=excluded.profile_name, "
        "profile_version=excluded.profile_version, updated_at=excluded.updated_at",
        (ws.name, ws.root_path, json.dumps(ws.allowed_write_paths),
         json.dumps(ws.allowed_read_paths), json.dumps(ws.allowed_command_paths),
         1 if ws.allow_git else 0, ws.profile_name, ws.profile_version,
         ws.created_at, ws.updated_at),
    )
    conn.commit()


def save_memory_search_event(conn, loop_id, query, workspace_name,
                             source_types_json, result_count, top_results_json,
                             used_for_context) -> int:
    cur = conn.execute(
        "INSERT INTO memory_search_events (loop_id, query, workspace_name, "
        "source_types_json, result_count, top_results_json, used_for_context) "
        "VALUES (?,?,?,?,?,?,?)",
        (loop_id, query, workspace_name, source_types_json, result_count,
         top_results_json, 1 if used_for_context else 0),
    )
    conn.commit()
    return cur.lastrowid


def get_memory_search_events(conn, loop_id):
    return conn.execute(
        "SELECT * FROM memory_search_events WHERE loop_id=? ORDER BY id",
        (loop_id,)).fetchall()


def save_replay_event(conn, source_loop_id, new_loop_id, replay_mode, dry_run,
                      status, stop_reason, settings_json) -> int:
    cur = conn.execute(
        "INSERT INTO replay_events (source_loop_id, new_loop_id, replay_mode, "
        "dry_run, status, stop_reason, settings_json) VALUES (?,?,?,?,?,?,?)",
        (source_loop_id, new_loop_id, replay_mode, 1 if dry_run else 0, status,
         stop_reason, settings_json),
    )
    conn.commit()
    return cur.lastrowid


def get_replay_events_for_source(conn, source_loop_id):
    return conn.execute(
        "SELECT * FROM replay_events WHERE source_loop_id=? ORDER BY id",
        (source_loop_id,)).fetchall()


def get_replay_events_for_new_loop(conn, new_loop_id):
    return conn.execute(
        "SELECT * FROM replay_events WHERE new_loop_id=? ORDER BY id",
        (new_loop_id,)).fetchall()


def save_run_report(conn, loop_id, report_path, report_format, content_hash,
                    bytes_written) -> int:
    cur = conn.execute(
        "INSERT INTO run_reports (loop_id, report_path, report_format, "
        "content_hash, bytes_written) VALUES (?,?,?,?,?)",
        (loop_id, report_path, report_format, content_hash, bytes_written),
    )
    conn.commit()
    return cur.lastrowid


def get_run_report(conn, loop_id):
    return conn.execute(
        "SELECT * FROM run_reports WHERE loop_id=? ORDER BY id DESC LIMIT 1",
        (loop_id,)).fetchone()


def list_run_reports(conn, limit=20):
    return conn.execute(
        "SELECT r.*, l.status AS status, l.task AS task FROM run_reports r "
        "JOIN loops l ON l.id = r.loop_id ORDER BY r.id DESC LIMIT ?",
        (limit,)).fetchall()


def save_observatory_snapshot(conn, generated_at, time_window, filters_json,
                              summary_json, alert_count,
                              critical_alert_count, warning_alert_count) -> int:
    cur = conn.execute(
        "INSERT INTO observatory_snapshots "
        "(generated_at, time_window, filters_json, summary_json, alert_count, "
        "critical_alert_count, warning_alert_count) VALUES (?,?,?,?,?,?,?)",
        (generated_at, time_window, filters_json, summary_json, alert_count,
         critical_alert_count, warning_alert_count),
    )
    conn.commit()
    return cur.lastrowid


def get_observatory_snapshot(conn, snapshot_id):
    return conn.execute(
        "SELECT * FROM observatory_snapshots WHERE id=?", (snapshot_id,)
    ).fetchone()


def list_observatory_snapshots(conn, limit=20):
    return conn.execute(
        "SELECT * FROM observatory_snapshots ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()


def save_observatory_report(conn, snapshot_id, report_path, report_format,
                            content_hash, bytes_written) -> int:
    cur = conn.execute(
        "INSERT INTO observatory_reports "
        "(snapshot_id, report_path, report_format, content_hash, bytes_written) "
        "VALUES (?,?,?,?,?)",
        (snapshot_id, report_path, report_format, content_hash, bytes_written),
    )
    conn.commit()
    return cur.lastrowid


def get_observatory_report(conn, snapshot_id):
    return conn.execute(
        "SELECT * FROM observatory_reports WHERE snapshot_id=? "
        "ORDER BY id DESC LIMIT 1",
        (snapshot_id,),
    ).fetchone()


def list_observatory_reports(conn, limit=20):
    return conn.execute(
        "SELECT * FROM observatory_reports ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()


def save_observatory_trend_report(conn, generated_at, snapshot_count,
                                  start_snapshot_id, end_snapshot_id,
                                  filters_json, trends_json, alerts_json,
                                  recommendations_json) -> int:
    cur = conn.execute(
        "INSERT INTO observatory_trend_reports "
        "(generated_at, snapshot_count, start_snapshot_id, end_snapshot_id, "
        "filters_json, trends_json, alerts_json, recommendations_json) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (generated_at, snapshot_count, start_snapshot_id, end_snapshot_id,
         filters_json, trends_json, alerts_json, recommendations_json),
    )
    conn.commit()
    return cur.lastrowid


def get_observatory_trend_report(conn, report_id):
    return conn.execute(
        "SELECT * FROM observatory_trend_reports WHERE id=?", (report_id,)
    ).fetchone()


def list_observatory_trend_reports(conn, limit=20):
    return conn.execute(
        "SELECT * FROM observatory_trend_reports ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()


def save_observatory_trend_markdown_report(conn, trend_report_id, report_path,
                                           report_format, content_hash,
                                           bytes_written) -> int:
    cur = conn.execute(
        "INSERT INTO observatory_trend_markdown_reports "
        "(trend_report_id, report_path, report_format, content_hash, bytes_written) "
        "VALUES (?,?,?,?,?)",
        (trend_report_id, report_path, report_format, content_hash, bytes_written),
    )
    conn.commit()
    return cur.lastrowid


def get_observatory_trend_markdown_report(conn, trend_report_id):
    return conn.execute(
        "SELECT * FROM observatory_trend_markdown_reports WHERE trend_report_id=? "
        "ORDER BY id DESC LIMIT 1",
        (trend_report_id,),
    ).fetchone()


def list_observatory_trend_markdown_reports(conn, limit=20):
    return conn.execute(
        "SELECT * FROM observatory_trend_markdown_reports ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()


def save_observatory_failure_drilldown(conn, generated_at, filters_json,
                                       cluster_by, total_failures, items_json,
                                       clusters_json, recommendations_json) -> int:
    cur = conn.execute(
        "INSERT INTO observatory_failure_drilldowns "
        "(generated_at, filters_json, cluster_by, total_failures, items_json, "
        "clusters_json, recommendations_json) VALUES (?,?,?,?,?,?,?)",
        (generated_at, filters_json, cluster_by, total_failures, items_json,
         clusters_json, recommendations_json),
    )
    conn.commit()
    return cur.lastrowid


def get_observatory_failure_drilldown(conn, drilldown_id):
    return conn.execute(
        "SELECT * FROM observatory_failure_drilldowns WHERE id=?", (drilldown_id,)
    ).fetchone()


def list_observatory_failure_drilldowns(conn, limit=20):
    return conn.execute(
        "SELECT * FROM observatory_failure_drilldowns ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()


def save_observatory_failure_markdown_report(conn, drilldown_id, report_path,
                                             report_format, content_hash,
                                             bytes_written) -> int:
    cur = conn.execute(
        "INSERT INTO observatory_failure_markdown_reports "
        "(drilldown_id, report_path, report_format, content_hash, bytes_written) "
        "VALUES (?,?,?,?,?)",
        (drilldown_id, report_path, report_format, content_hash, bytes_written),
    )
    conn.commit()
    return cur.lastrowid


def get_observatory_failure_markdown_report(conn, drilldown_id):
    return conn.execute(
        "SELECT * FROM observatory_failure_markdown_reports WHERE drilldown_id=? "
        "ORDER BY id DESC LIMIT 1",
        (drilldown_id,),
    ).fetchone()


def list_observatory_failure_markdown_reports(conn, limit=20):
    return conn.execute(
        "SELECT * FROM observatory_failure_markdown_reports ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()


def save_observatory_remediation_plan(conn, generated_at, source_type, source_id,
                                      filters_json, summary_json, items_json,
                                      total_items, urgent_count,
                                      high_priority_count, medium_priority_count,
                                      low_priority_count) -> int:
    cur = conn.execute(
        "INSERT INTO observatory_remediation_plans "
        "(generated_at, source_type, source_id, filters_json, summary_json, "
        "items_json, total_items, urgent_count, high_priority_count, "
        "medium_priority_count, low_priority_count) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (generated_at, source_type, source_id, filters_json, summary_json,
         items_json, total_items, urgent_count, high_priority_count,
         medium_priority_count, low_priority_count),
    )
    conn.commit()
    return cur.lastrowid


def get_observatory_remediation_plan(conn, plan_id):
    return conn.execute(
        "SELECT * FROM observatory_remediation_plans WHERE id=?", (plan_id,)
    ).fetchone()


def list_observatory_remediation_plans(conn, limit=20):
    return conn.execute(
        "SELECT * FROM observatory_remediation_plans ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()


def save_observatory_remediation_markdown_report(conn, remediation_plan_id,
                                                 report_path, report_format,
                                                 content_hash,
                                                 bytes_written) -> int:
    cur = conn.execute(
        "INSERT INTO observatory_remediation_markdown_reports "
        "(remediation_plan_id, report_path, report_format, content_hash, bytes_written) "
        "VALUES (?,?,?,?,?)",
        (remediation_plan_id, report_path, report_format, content_hash, bytes_written),
    )
    conn.commit()
    return cur.lastrowid


def get_observatory_remediation_markdown_report(conn, plan_id):
    return conn.execute(
        "SELECT * FROM observatory_remediation_markdown_reports "
        "WHERE remediation_plan_id=? ORDER BY id DESC LIMIT 1",
        (plan_id,),
    ).fetchone()


def list_observatory_remediation_markdown_reports(conn, limit=20):
    return conn.execute(
        "SELECT * FROM observatory_remediation_markdown_reports ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()


def save_observatory_action_item(conn, source_plan_id, source_item_id, title,
                                 category, priority, status, suggested_command,
                                 problem_summary, recommended_action,
                                 affected_loop_ids_json, affected_job_ids_json,
                                 risk_level, effort_level, notes="") -> int:
    now = _now_iso()
    cur = conn.execute(
        "INSERT INTO observatory_action_items "
        "(source_plan_id, source_item_id, title, category, priority, status, "
        "suggested_command, problem_summary, recommended_action, "
        "affected_loop_ids_json, affected_job_ids_json, risk_level, effort_level, "
        "notes, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (source_plan_id, source_item_id, title, category, priority, status,
         suggested_command, problem_summary, recommended_action,
         affected_loop_ids_json, affected_job_ids_json, risk_level, effort_level,
         notes, now, now),
    )
    conn.commit()
    return cur.lastrowid


def get_observatory_action_item(conn, action_id):
    return conn.execute(
        "SELECT * FROM observatory_action_items WHERE id=?", (action_id,)
    ).fetchone()


def get_observatory_action_item_for_source(conn, source_plan_id, source_item_id):
    return conn.execute(
        "SELECT * FROM observatory_action_items "
        "WHERE source_plan_id=? AND source_item_id=? ORDER BY id DESC LIMIT 1",
        (source_plan_id, source_item_id),
    ).fetchone()


def list_observatory_action_items(conn, status=None, priority=None,
                                  category=None, limit=25):
    where, params = [], []
    if status is not None:
        where.append("status=?")
        params.append(status)
    if priority is not None:
        where.append("priority=?")
        params.append(priority)
    if category is not None:
        where.append("category=?")
        params.append(category)
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    params.append(limit)
    return conn.execute(
        f"SELECT * FROM observatory_action_items{clause} ORDER BY id DESC LIMIT ?",
        params,
    ).fetchall()


def update_observatory_action_status(conn, action_id, status):
    now = _now_iso()
    completed_at = now if status == "completed" else None
    dismissed_at = now if status == "dismissed" else None
    conn.execute(
        "UPDATE observatory_action_items SET status=?, updated_at=?, "
        "completed_at=COALESCE(?, completed_at), "
        "dismissed_at=COALESCE(?, dismissed_at) WHERE id=?",
        (status, now, completed_at, dismissed_at, action_id),
    )
    conn.commit()


def update_observatory_action_notes(conn, action_id, notes):
    conn.execute(
        "UPDATE observatory_action_items SET notes=?, updated_at=? WHERE id=?",
        (notes, _now_iso(), action_id),
    )
    conn.commit()


def save_observatory_action_event(conn, action_id, event_type,
                                  status_before=None, status_after=None,
                                  details_json="{}") -> int:
    cur = conn.execute(
        "INSERT INTO observatory_action_events "
        "(action_id, event_type, status_before, status_after, details_json) "
        "VALUES (?,?,?,?,?)",
        (action_id, event_type, status_before, status_after, details_json),
    )
    conn.commit()
    return cur.lastrowid


def get_observatory_action_events(conn, action_id):
    return conn.execute(
        "SELECT * FROM observatory_action_events WHERE action_id=? ORDER BY id",
        (action_id,),
    ).fetchall()


def save_observatory_action_markdown_report(conn, report_path, report_format,
                                            content_hash, bytes_written) -> int:
    cur = conn.execute(
        "INSERT INTO observatory_action_markdown_reports "
        "(report_path, report_format, content_hash, bytes_written) VALUES (?,?,?,?)",
        (report_path, report_format, content_hash, bytes_written),
    )
    conn.commit()
    return cur.lastrowid


def list_observatory_action_markdown_reports(conn, limit=20):
    return conn.execute(
        "SELECT * FROM observatory_action_markdown_reports ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()


def save_observatory_action_review(conn, generated_at, filters_json, group_by,
                                   total_actions_reviewed, top_actions_json,
                                   groups_json, recommendations_json,
                                   next_steps_json) -> int:
    cur = conn.execute(
        "INSERT INTO observatory_action_reviews "
        "(generated_at, filters_json, group_by, total_actions_reviewed, "
        "top_actions_json, groups_json, recommendations_json, next_steps_json) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (generated_at, filters_json, group_by, total_actions_reviewed,
         top_actions_json, groups_json, recommendations_json, next_steps_json),
    )
    conn.commit()
    return cur.lastrowid


def get_observatory_action_review(conn, review_id):
    return conn.execute(
        "SELECT * FROM observatory_action_reviews WHERE id=?", (review_id,)
    ).fetchone()


def list_observatory_action_reviews(conn, limit=20):
    return conn.execute(
        "SELECT * FROM observatory_action_reviews ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()


def save_observatory_action_review_markdown_report(conn, action_review_id,
                                                   report_path, report_format,
                                                   content_hash,
                                                   bytes_written) -> int:
    cur = conn.execute(
        "INSERT INTO observatory_action_review_markdown_reports "
        "(action_review_id, report_path, report_format, content_hash, bytes_written) "
        "VALUES (?,?,?,?,?)",
        (action_review_id, report_path, report_format, content_hash, bytes_written),
    )
    conn.commit()
    return cur.lastrowid


def get_observatory_action_review_markdown_report(conn, review_id):
    return conn.execute(
        "SELECT * FROM observatory_action_review_markdown_reports "
        "WHERE action_review_id=? ORDER BY id DESC LIMIT 1",
        (review_id,),
    ).fetchone()


def list_observatory_action_review_markdown_reports(conn, limit=20):
    return conn.execute(
        "SELECT * FROM observatory_action_review_markdown_reports "
        "ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()


def save_loop_improvement_plan(conn, generated_at, source_type, source_id,
                               filters_json, summary_json, proposals_json,
                               total_proposals, urgent_count, high_count,
                               medium_count, low_count) -> int:
    cur = conn.execute(
        "INSERT INTO loop_improvement_plans "
        "(generated_at, source_type, source_id, filters_json, summary_json, "
        "proposals_json, total_proposals, urgent_count, high_count, "
        "medium_count, low_count) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (generated_at, source_type, source_id, filters_json, summary_json,
         proposals_json, total_proposals, urgent_count, high_count, medium_count,
         low_count),
    )
    conn.commit()
    return cur.lastrowid


def get_loop_improvement_plan(conn, plan_id):
    return conn.execute(
        "SELECT * FROM loop_improvement_plans WHERE id=?", (plan_id,)
    ).fetchone()


def list_loop_improvement_plans(conn, limit=20):
    return conn.execute(
        "SELECT * FROM loop_improvement_plans ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()


def update_loop_improvement_plan_proposals(conn, plan_id, proposals_json):
    conn.execute(
        "UPDATE loop_improvement_plans SET proposals_json=? WHERE id=?",
        (proposals_json, plan_id),
    )
    conn.commit()


def save_loop_improvement_proposal(conn, plan_id, target_type, target_name,
                                   title, problem_summary, evidence_json,
                                   proposed_change, expected_benefit,
                                   risk_level, effort_level, priority,
                                   affected_loop_ids_json,
                                   affected_action_ids_json,
                                   affected_remediation_plan_ids_json,
                                   status="proposed") -> int:
    now = _now_iso()
    cur = conn.execute(
        "INSERT INTO loop_improvement_proposals "
        "(plan_id, target_type, target_name, title, problem_summary, "
        "evidence_json, proposed_change, expected_benefit, risk_level, "
        "effort_level, priority, affected_loop_ids_json, "
        "affected_action_ids_json, affected_remediation_plan_ids_json, "
        "status, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (plan_id, target_type, target_name, title, problem_summary, evidence_json,
         proposed_change, expected_benefit, risk_level, effort_level, priority,
         affected_loop_ids_json, affected_action_ids_json,
         affected_remediation_plan_ids_json, status, now, now),
    )
    conn.commit()
    return cur.lastrowid


def get_loop_improvement_proposal(conn, proposal_id):
    return conn.execute(
        "SELECT * FROM loop_improvement_proposals WHERE id=?", (proposal_id,)
    ).fetchone()


def list_loop_improvement_proposals(conn, status=None, priority=None,
                                    target_type=None, limit=25, plan_id=None):
    where, params = [], []
    if status is not None:
        where.append("status=?")
        params.append(status)
    if priority is not None:
        where.append("priority=?")
        params.append(priority)
    if target_type is not None:
        where.append("target_type=?")
        params.append(target_type)
    if plan_id is not None:
        where.append("plan_id=?")
        params.append(plan_id)
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    params.append(limit)
    return conn.execute(
        f"SELECT * FROM loop_improvement_proposals{clause} "
        "ORDER BY id DESC LIMIT ?",
        params,
    ).fetchall()


def update_loop_improvement_proposal_status(conn, proposal_id, status):
    conn.execute(
        "UPDATE loop_improvement_proposals SET status=?, updated_at=? WHERE id=?",
        (status, _now_iso(), proposal_id),
    )
    conn.commit()


def save_loop_improvement_markdown_report(conn, improvement_plan_id,
                                          report_path, report_format,
                                          content_hash,
                                          bytes_written) -> int:
    cur = conn.execute(
        "INSERT INTO loop_improvement_markdown_reports "
        "(improvement_plan_id, report_path, report_format, content_hash, "
        "bytes_written) VALUES (?,?,?,?,?)",
        (improvement_plan_id, report_path, report_format, content_hash,
         bytes_written),
    )
    conn.commit()
    return cur.lastrowid


def get_loop_improvement_markdown_report(conn, plan_id):
    return conn.execute(
        "SELECT * FROM loop_improvement_markdown_reports "
        "WHERE improvement_plan_id=? ORDER BY id DESC LIMIT 1",
        (plan_id,),
    ).fetchone()


def list_loop_improvement_markdown_reports(conn, limit=20):
    return conn.execute(
        "SELECT * FROM loop_improvement_markdown_reports ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()


def save_loop_improvement_review(conn, generated_at, filters_json, group_by,
                                 total_proposals_reviewed, top_proposals_json,
                                 groups_json, recommendations_json,
                                 next_steps_json) -> int:
    cur = conn.execute(
        "INSERT INTO loop_improvement_reviews "
        "(generated_at, filters_json, group_by, total_proposals_reviewed, "
        "top_proposals_json, groups_json, recommendations_json, next_steps_json) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (generated_at, filters_json, group_by, total_proposals_reviewed,
         top_proposals_json, groups_json, recommendations_json, next_steps_json),
    )
    conn.commit()
    return cur.lastrowid


def get_loop_improvement_review(conn, review_id):
    return conn.execute(
        "SELECT * FROM loop_improvement_reviews WHERE id=?", (review_id,)
    ).fetchone()


def list_loop_improvement_reviews(conn, limit=20):
    return conn.execute(
        "SELECT * FROM loop_improvement_reviews ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()


def save_loop_improvement_review_markdown_report(conn, improvement_review_id,
                                                 report_path, report_format,
                                                 content_hash,
                                                 bytes_written) -> int:
    cur = conn.execute(
        "INSERT INTO loop_improvement_review_markdown_reports "
        "(improvement_review_id, report_path, report_format, content_hash, "
        "bytes_written) VALUES (?,?,?,?,?)",
        (improvement_review_id, report_path, report_format, content_hash,
         bytes_written),
    )
    conn.commit()
    return cur.lastrowid


def get_loop_improvement_review_markdown_report(conn, review_id):
    return conn.execute(
        "SELECT * FROM loop_improvement_review_markdown_reports "
        "WHERE improvement_review_id=? ORDER BY id DESC LIMIT 1",
        (review_id,),
    ).fetchone()


def list_loop_improvement_review_markdown_reports(conn, limit=20):
    return conn.execute(
        "SELECT * FROM loop_improvement_review_markdown_reports "
        "ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()


def save_loop_improvement_action_item(
    conn,
    source_review_id,
    source_proposal_id,
    source_plan_id,
    target_type,
    target_name,
    title,
    priority,
    status,
    risk_level,
    effort_level,
    problem_summary,
    proposed_change,
    expected_benefit,
    recommended_decision,
    suggested_next_command,
    affected_loop_ids_json,
    affected_action_ids_json,
    affected_remediation_plan_ids_json,
    notes="",
) -> int:
    now = _now_iso()
    cur = conn.execute(
        "INSERT INTO loop_improvement_action_items "
        "(source_review_id, source_proposal_id, source_plan_id, target_type, "
        "target_name, title, priority, status, risk_level, effort_level, "
        "problem_summary, proposed_change, expected_benefit, recommended_decision, "
        "suggested_next_command, affected_loop_ids_json, affected_action_ids_json, "
        "affected_remediation_plan_ids_json, notes, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            source_review_id,
            source_proposal_id,
            source_plan_id,
            target_type,
            target_name,
            title,
            priority,
            status,
            risk_level,
            effort_level,
            problem_summary,
            proposed_change,
            expected_benefit,
            recommended_decision,
            suggested_next_command,
            affected_loop_ids_json,
            affected_action_ids_json,
            affected_remediation_plan_ids_json,
            notes,
            now,
            now,
        ),
    )
    conn.commit()
    return cur.lastrowid


def get_loop_improvement_action_item(conn, action_id):
    return conn.execute(
        "SELECT * FROM loop_improvement_action_items WHERE id=?", (action_id,)
    ).fetchone()


def get_loop_improvement_action_item_for_source(conn, source_review_id,
                                                source_proposal_id):
    return conn.execute(
        "SELECT * FROM loop_improvement_action_items "
        "WHERE source_review_id=? AND source_proposal_id=? ORDER BY id DESC LIMIT 1",
        (source_review_id, source_proposal_id),
    ).fetchone()


def list_loop_improvement_action_items(conn, status=None, priority=None,
                                       target_type=None, limit=25):
    where, params = [], []
    if status is not None:
        where.append("status=?")
        params.append(status)
    if priority is not None:
        where.append("priority=?")
        params.append(priority)
    if target_type is not None:
        where.append("target_type=?")
        params.append(target_type)
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    params.append(limit)
    return conn.execute(
        f"SELECT * FROM loop_improvement_action_items{clause} "
        "ORDER BY id DESC LIMIT ?",
        params,
    ).fetchall()


def update_loop_improvement_action_status(conn, action_id, status):
    now = _now_iso()
    completed_at = now if status == "completed" else None
    dismissed_at = now if status == "dismissed" else None
    conn.execute(
        "UPDATE loop_improvement_action_items SET status=?, updated_at=?, "
        "completed_at=COALESCE(?, completed_at), "
        "dismissed_at=COALESCE(?, dismissed_at) WHERE id=?",
        (status, now, completed_at, dismissed_at, action_id),
    )
    conn.commit()


def update_loop_improvement_action_notes(conn, action_id, notes):
    conn.execute(
        "UPDATE loop_improvement_action_items SET notes=?, updated_at=? WHERE id=?",
        (notes, _now_iso(), action_id),
    )
    conn.commit()


def save_loop_improvement_action_batch(
    conn,
    source_review_id,
    generated_at,
    filters_json,
    total_actions,
    created_count,
    skipped_duplicates,
    action_ids_json,
) -> int:
    cur = conn.execute(
        "INSERT INTO loop_improvement_action_batches "
        "(source_review_id, generated_at, filters_json, total_actions, "
        "created_count, skipped_duplicates, action_ids_json) "
        "VALUES (?,?,?,?,?,?,?)",
        (
            source_review_id,
            generated_at,
            filters_json,
            total_actions,
            created_count,
            skipped_duplicates,
            action_ids_json,
        ),
    )
    conn.commit()
    return cur.lastrowid


def get_loop_improvement_action_batch(conn, batch_id):
    return conn.execute(
        "SELECT * FROM loop_improvement_action_batches WHERE id=?", (batch_id,)
    ).fetchone()


def list_loop_improvement_action_batches(conn, limit=20):
    return conn.execute(
        "SELECT * FROM loop_improvement_action_batches ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()


def save_loop_improvement_action_event(conn, action_id, event_type,
                                       status_before=None, status_after=None,
                                       details_json="{}") -> int:
    cur = conn.execute(
        "INSERT INTO loop_improvement_action_events "
        "(action_id, event_type, status_before, status_after, details_json) "
        "VALUES (?,?,?,?,?)",
        (action_id, event_type, status_before, status_after, details_json),
    )
    conn.commit()
    return cur.lastrowid


def get_loop_improvement_action_events(conn, action_id):
    return conn.execute(
        "SELECT * FROM loop_improvement_action_events WHERE action_id=? ORDER BY id",
        (action_id,),
    ).fetchall()


def save_loop_improvement_action_markdown_report(conn, report_path, report_format,
                                                 content_hash,
                                                 bytes_written) -> int:
    cur = conn.execute(
        "INSERT INTO loop_improvement_action_markdown_reports "
        "(report_path, report_format, content_hash, bytes_written) VALUES (?,?,?,?)",
        (report_path, report_format, content_hash, bytes_written),
    )
    conn.commit()
    return cur.lastrowid


def list_loop_improvement_action_markdown_reports(conn, limit=20):
    return conn.execute(
        "SELECT * FROM loop_improvement_action_markdown_reports "
        "ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()


def save_loop_improvement_handoff(
    conn,
    action_id,
    source_review_id,
    source_proposal_id,
    source_plan_id,
    handoff_type,
    generated_task,
    implementation_scope,
    target_type,
    target_name,
    target_loop_type,
    target_workspace,
    external_coder,
    suggested_command,
    safety_notes_json,
    status,
    created_loop_id=None,
    created_external_job_id=None,
    dry_run=True,
    packet_path=None,
) -> int:
    cur = conn.execute(
        "INSERT INTO loop_improvement_handoffs "
        "(action_id, source_review_id, source_proposal_id, source_plan_id, "
        "handoff_type, generated_task, implementation_scope, target_type, target_name, "
        "target_loop_type, target_workspace, external_coder, suggested_command, "
        "safety_notes_json, status, created_loop_id, created_external_job_id, "
        "dry_run, packet_path) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            action_id,
            source_review_id,
            source_proposal_id,
            source_plan_id,
            handoff_type,
            generated_task,
            implementation_scope,
            target_type,
            target_name,
            target_loop_type,
            target_workspace,
            external_coder,
            suggested_command,
            safety_notes_json,
            status,
            created_loop_id,
            created_external_job_id,
            1 if dry_run else 0,
            packet_path,
        ),
    )
    conn.commit()
    return cur.lastrowid


def update_loop_improvement_handoff_packet_path(conn, handoff_id, packet_path,
                                                status=None):
    if status is None:
        conn.execute(
            "UPDATE loop_improvement_handoffs SET packet_path=? WHERE id=?",
            (packet_path, handoff_id),
        )
    else:
        conn.execute(
            "UPDATE loop_improvement_handoffs SET packet_path=?, status=? WHERE id=?",
            (packet_path, status, handoff_id),
        )
    conn.commit()


def get_loop_improvement_handoff(conn, handoff_id):
    return conn.execute(
        "SELECT * FROM loop_improvement_handoffs WHERE id=?", (handoff_id,)
    ).fetchone()


def list_loop_improvement_handoffs(conn, limit=20):
    return conn.execute(
        "SELECT * FROM loop_improvement_handoffs ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()


def list_loop_improvement_handoffs_for_action(conn, action_id, limit=20):
    return conn.execute(
        "SELECT * FROM loop_improvement_handoffs WHERE action_id=? "
        "ORDER BY id DESC LIMIT ?",
        (action_id, limit),
    ).fetchall()


def save_loop_improvement_handoff_event(conn, handoff_id, action_id, event_type,
                                        details_json="{}") -> int:
    cur = conn.execute(
        "INSERT INTO loop_improvement_handoff_events "
        "(handoff_id, action_id, event_type, details_json) VALUES (?,?,?,?)",
        (handoff_id, action_id, event_type, details_json),
    )
    conn.commit()
    return cur.lastrowid


def get_loop_improvement_handoff_events(conn, handoff_id):
    return conn.execute(
        "SELECT * FROM loop_improvement_handoff_events WHERE handoff_id=? ORDER BY id",
        (handoff_id,),
    ).fetchall()


def save_loop_improvement_handoff_packet(conn, handoff_id, action_id, packet_path,
                                         packet_format, content_hash,
                                         bytes_written) -> int:
    cur = conn.execute(
        "INSERT INTO loop_improvement_handoff_packets "
        "(handoff_id, action_id, packet_path, packet_format, content_hash, bytes_written) "
        "VALUES (?,?,?,?,?,?)",
        (handoff_id, action_id, packet_path, packet_format, content_hash, bytes_written),
    )
    conn.commit()
    return cur.lastrowid


def get_loop_improvement_handoff_packet(conn, handoff_id):
    return conn.execute(
        "SELECT * FROM loop_improvement_handoff_packets "
        "WHERE handoff_id=? ORDER BY id DESC LIMIT 1",
        (handoff_id,),
    ).fetchone()


def list_loop_improvement_handoff_packets(conn, limit=20):
    return conn.execute(
        "SELECT * FROM loop_improvement_handoff_packets ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()


def save_observatory_action_handoff(conn, action_id, handoff_type,
                                    generated_task, target_loop_type,
                                    target_workspace, external_coder,
                                    suggested_command, safety_notes_json,
                                    status, created_loop_id=None,
                                    created_external_job_id=None,
                                    dry_run=True) -> int:
    cur = conn.execute(
        "INSERT INTO observatory_action_handoffs "
        "(action_id, handoff_type, generated_task, target_loop_type, "
        "target_workspace, external_coder, suggested_command, safety_notes_json, "
        "status, created_loop_id, created_external_job_id, dry_run) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (action_id, handoff_type, generated_task, target_loop_type,
         target_workspace, external_coder, suggested_command, safety_notes_json,
         status, created_loop_id, created_external_job_id, 1 if dry_run else 0),
    )
    conn.commit()
    return cur.lastrowid


def get_observatory_action_handoff(conn, handoff_id):
    return conn.execute(
        "SELECT * FROM observatory_action_handoffs WHERE id=?", (handoff_id,)
    ).fetchone()


def list_observatory_action_handoffs(conn, limit=20):
    return conn.execute(
        "SELECT * FROM observatory_action_handoffs ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()


def list_observatory_action_handoffs_for_action(conn, action_id, limit=20):
    return conn.execute(
        "SELECT * FROM observatory_action_handoffs WHERE action_id=? "
        "ORDER BY id DESC LIMIT ?",
        (action_id, limit),
    ).fetchall()


def save_observatory_action_handoff_event(conn, handoff_id, action_id,
                                          event_type, details_json="{}") -> int:
    cur = conn.execute(
        "INSERT INTO observatory_action_handoff_events "
        "(handoff_id, action_id, event_type, details_json) VALUES (?,?,?,?)",
        (handoff_id, action_id, event_type, details_json),
    )
    conn.commit()
    return cur.lastrowid


def get_observatory_action_handoff_events(conn, handoff_id):
    return conn.execute(
        "SELECT * FROM observatory_action_handoff_events WHERE handoff_id=? ORDER BY id",
        (handoff_id,),
    ).fetchall()


def save_observatory_action_handoff_review(conn, generated_at, filters_json, group_by,
                                           total_handoffs_reviewed, groups_json,
                                           items_json, recommendations_json,
                                           next_steps_json) -> int:
    cur = conn.execute(
        "INSERT INTO observatory_action_handoff_reviews "
        "(generated_at, filters_json, group_by, total_handoffs_reviewed, "
        "groups_json, items_json, recommendations_json, next_steps_json) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (generated_at, filters_json, group_by, total_handoffs_reviewed,
         groups_json, items_json, recommendations_json, next_steps_json),
    )
    conn.commit()
    return cur.lastrowid


def get_observatory_action_handoff_review(conn, review_id):
    return conn.execute(
        "SELECT * FROM observatory_action_handoff_reviews WHERE id=?",
        (review_id,),
    ).fetchone()


def list_observatory_action_handoff_reviews(conn, limit=20):
    return conn.execute(
        "SELECT * FROM observatory_action_handoff_reviews ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()


def save_observatory_action_handoff_review_markdown_report(
        conn, handoff_review_id, report_path, report_format, content_hash,
        bytes_written) -> int:
    cur = conn.execute(
        "INSERT INTO observatory_action_handoff_review_markdown_reports "
        "(handoff_review_id, report_path, report_format, content_hash, bytes_written) "
        "VALUES (?,?,?,?,?)",
        (handoff_review_id, report_path, report_format, content_hash, bytes_written),
    )
    conn.commit()
    return cur.lastrowid


def get_observatory_action_handoff_review_markdown_report(conn, review_id):
    return conn.execute(
        "SELECT * FROM observatory_action_handoff_review_markdown_reports "
        "WHERE handoff_review_id=? ORDER BY id DESC LIMIT 1",
        (review_id,),
    ).fetchone()


def list_observatory_action_handoff_review_markdown_reports(conn, limit=20):
    return conn.execute(
        "SELECT * FROM observatory_action_handoff_review_markdown_reports "
        "ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()


def save_observatory_stage4_audit(conn, generated_at, overall_status, total_checks,
                                  passed_checks, warning_checks, failed_checks,
                                  sections_json, recommendations_json,
                                  stage5_readiness_json) -> int:
    cur = conn.execute(
        "INSERT INTO observatory_stage4_audits "
        "(generated_at, overall_status, total_checks, passed_checks, warning_checks, "
        "failed_checks, sections_json, recommendations_json, stage5_readiness_json) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (generated_at, overall_status, total_checks, passed_checks, warning_checks,
         failed_checks, sections_json, recommendations_json, stage5_readiness_json),
    )
    conn.commit()
    return cur.lastrowid


def get_observatory_stage4_audit(conn, audit_id):
    return conn.execute(
        "SELECT * FROM observatory_stage4_audits WHERE id=?", (audit_id,)
    ).fetchone()


def list_observatory_stage4_audits(conn, limit=20):
    return conn.execute(
        "SELECT * FROM observatory_stage4_audits ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()


def save_observatory_stage4_audit_markdown_report(conn, stage4_audit_id,
                                                  report_path, report_format,
                                                  content_hash,
                                                  bytes_written) -> int:
    cur = conn.execute(
        "INSERT INTO observatory_stage4_audit_markdown_reports "
        "(stage4_audit_id, report_path, report_format, content_hash, bytes_written) "
        "VALUES (?,?,?,?,?)",
        (stage4_audit_id, report_path, report_format, content_hash, bytes_written),
    )
    conn.commit()
    return cur.lastrowid


def get_observatory_stage4_audit_markdown_report(conn, audit_id):
    return conn.execute(
        "SELECT * FROM observatory_stage4_audit_markdown_reports "
        "WHERE stage4_audit_id=? ORDER BY id DESC LIMIT 1",
        (audit_id,),
    ).fetchone()


def list_observatory_stage4_audit_markdown_reports(conn, limit=20):
    return conn.execute(
        "SELECT * FROM observatory_stage4_audit_markdown_reports "
        "ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()


def get_project_workspace(conn, name):
    return conn.execute(
        "SELECT * FROM project_workspaces WHERE name=?", (name,)).fetchone()


def list_project_workspaces(conn):
    return conn.execute(
        "SELECT * FROM project_workspaces ORDER BY name").fetchall()


def finish_loop(conn, loop_id, status, stop_reason, retry_count, total_duration_seconds):
    conn.execute(
        "UPDATE loops SET status=?, stop_reason=?, retry_count=?, total_duration_seconds=? "
        "WHERE id=?",
        (status, stop_reason, retry_count, total_duration_seconds, loop_id),
    )
    conn.commit()


class LoopRecorder:
    """Per-loop writer. Holds the connection and the loop id."""

    def __init__(self, conn: sqlite3.Connection, loop_id: int):
        self.conn = conn
        self.loop_id = loop_id

    def save_step(self, step_name, agent_role, model, attempt_number,
                  prompt, response, latency_seconds,
                  prompt_eval_count, eval_count, eval_tokens_per_second):
        self.conn.execute(
            "INSERT INTO steps (loop_id, step_name, agent_role, model, attempt_number, "
            "prompt, response, latency_seconds, prompt_eval_count, eval_count, "
            "eval_tokens_per_second) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (self.loop_id, step_name, agent_role, model, attempt_number, prompt,
             response, latency_seconds, prompt_eval_count, eval_count,
             eval_tokens_per_second),
        )
        self.conn.commit()

    def save_review(self, attempt_number, review):
        self.conn.execute(
            "INSERT INTO reviews (loop_id, attempt_number, approved, summary, "
            "issues_json, required_changes_json, confidence_score, stop_reason) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (self.loop_id, attempt_number, 1 if review.approved else 0,
             review.summary, json.dumps(review.issues),
             json.dumps(review.required_changes), review.confidence_score,
             review.stop_reason),
        )
        self.conn.commit()

    def save_file_operation(self, attempt_number, path, operation, allowed,
                            reason_if_blocked, content):
        content = content or ""
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        bytes_written = len(content.encode("utf-8")) if allowed else 0
        self.conn.execute(
            "INSERT INTO file_operations (loop_id, attempt_number, path, operation, "
            "allowed, reason_if_blocked, content_hash, bytes_written) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (self.loop_id, attempt_number, path, operation, 1 if allowed else 0,
             reason_if_blocked, content_hash, bytes_written),
        )
        self.conn.commit()

    def save_command_result(self, attempt_number, r):
        self.conn.execute(
            "INSERT INTO command_results (loop_id, attempt_number, command, allowed, "
            "exit_code, stdout, stderr, duration_seconds, timed_out, reason_if_blocked) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (self.loop_id, attempt_number, r.command, 1 if r.allowed else 0,
             r.exit_code, r.stdout, r.stderr, r.duration_seconds,
             1 if r.timed_out else 0, r.reason_if_blocked),
        )
        self.conn.commit()

    def save_metric(self, metric_name, metric_value, metric_unit, metric_text=None):
        self.conn.execute(
            "INSERT INTO metrics (loop_id, metric_name, metric_value, metric_unit, "
            "metric_text) VALUES (?,?,?,?,?)",
            (self.loop_id, metric_name, metric_value, metric_unit, metric_text),
        )
        self.conn.commit()

    def save_agent_event(self, agent_name, agent_role, model, event_type, details_json=""):
        self.conn.execute(
            "INSERT INTO agent_events (loop_id, agent_name, agent_role, model, "
            "event_type, details_json) VALUES (?,?,?,?,?,?)",
            (self.loop_id, agent_name, agent_role, model, event_type, details_json),
        )
        self.conn.commit()

    def save_quality_gate_result(self, attempt_number, gate_name, passed, required,
                                 severity, message, details_json=""):
        self.conn.execute(
            "INSERT INTO quality_gate_results (loop_id, attempt_number, gate_name, "
            "passed, required, severity, message, details_json) VALUES (?,?,?,?,?,?,?,?)",
            (self.loop_id, attempt_number, gate_name, 1 if passed else 0,
             1 if required else 0, severity, message, details_json),
        )
        self.conn.commit()

    def save_stop_condition_result(self, attempt_number, condition_name, triggered,
                                   severity, message, details_json=""):
        self.conn.execute(
            "INSERT INTO stop_condition_results (loop_id, attempt_number, "
            "condition_name, triggered, severity, message, details_json) "
            "VALUES (?,?,?,?,?,?,?)",
            (self.loop_id, attempt_number, condition_name, 1 if triggered else 0,
             severity, message, details_json),
        )
        self.conn.commit()

    def save_approval_event(self, request, decision):
        self.conn.execute(
            "INSERT INTO approval_events (loop_id, attempt_number, gate_name, "
            "action_type, risk_level, summary, details_json, approved, decision, "
            "reason, created_at, decided_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (self.loop_id, request.attempt_number, request.gate_name,
             request.action_type, request.risk_level, request.summary,
             request.details_json, 1 if decision.approved else 0,
             decision.decision, decision.reason, request.created_at,
             decision.decided_at),
        )
        self.conn.commit()

    def save_external_agent_event(self, attempt_number, agent_name, mode,
                                  handoff_path, handoff_prompt_hash, result):
        save_external_agent_event(self.conn, self.loop_id, attempt_number,
                                  agent_name, mode, handoff_path,
                                  handoff_prompt_hash, result)

    def save_git_event(self, event_type, command, exit_code, stdout, stderr):
        self.conn.execute(
            "INSERT INTO git_events (loop_id, event_type, command, exit_code, "
            "stdout, stderr) VALUES (?,?,?,?,?,?)",
            (self.loop_id, event_type, command, exit_code, stdout, stderr),
        )
        self.conn.commit()


# --------------------------------------------------------------------------- #
# Reading
# --------------------------------------------------------------------------- #
def list_loops(conn, limit: int = 20) -> List[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM loops ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()


def get_loop(conn, loop_id) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM loops WHERE id=?", (loop_id,)).fetchone()


def get_steps(conn, loop_id) -> List[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM steps WHERE loop_id=? ORDER BY id", (loop_id,)
    ).fetchall()


def get_reviews(conn, loop_id) -> List[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM reviews WHERE loop_id=? ORDER BY id", (loop_id,)
    ).fetchall()


def get_file_operations(conn, loop_id) -> List[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM file_operations WHERE loop_id=? ORDER BY id", (loop_id,)
    ).fetchall()


def get_command_results(conn, loop_id) -> List[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM command_results WHERE loop_id=? ORDER BY id", (loop_id,)
    ).fetchall()


def get_metrics(conn, loop_id) -> List[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM metrics WHERE loop_id=? ORDER BY id", (loop_id,)
    ).fetchall()


def get_git_events(conn, loop_id) -> List[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM git_events WHERE loop_id=? ORDER BY id", (loop_id,)
    ).fetchall()


def get_agent_events(conn, loop_id) -> List[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM agent_events WHERE loop_id=? ORDER BY id", (loop_id,)
    ).fetchall()


def get_approval_events(conn, loop_id) -> List[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM approval_events WHERE loop_id=? ORDER BY id", (loop_id,)
    ).fetchall()


def get_quality_gate_results(conn, loop_id) -> List[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM quality_gate_results WHERE loop_id=? ORDER BY id", (loop_id,)
    ).fetchall()


def get_stop_condition_results(conn, loop_id) -> List[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM stop_condition_results WHERE loop_id=? ORDER BY id", (loop_id,)
    ).fetchall()
