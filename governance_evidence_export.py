"""Stage 8.7 — Governance Evidence Export.

Exports a portable Markdown evidence packet summarizing the governance posture:
policy summaries, the latest evaluation results, waiver metadata, review queue
state, and the latest fleet governance report summary.

The packet is metadata-only. It NEVER includes protected file contents, secrets,
or local runtime database snapshots — it reads only governance/registry metadata
rows. Written under ``governance_evidence_exports/``.
"""

import datetime
import hashlib
import json
import os
from dataclasses import dataclass
from typing import Optional

import database


PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
EXPORTS_DIR = os.path.join(PROJECT_ROOT, "governance_evidence_exports")


@dataclass
class GovernanceEvidenceExport:
    id: int
    generated_at: str
    report_path: str
    report_format: str
    content_hash: str
    bytes_written: int
    summary: dict


def _now_iso() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def _now_stamp() -> str:
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


def is_export_path(path) -> bool:
    if not path:
        return False
    target = os.path.realpath(path)
    base = os.path.realpath(EXPORTS_DIR)
    return target != base and target.startswith(base + os.sep)


class GovernanceEvidenceExporter:
    def __init__(self, conn):
        self.conn = conn

    def export(self) -> GovernanceEvidenceExport:
        policies = database.list_governance_policies(self.conn)
        evaluations = database.list_governance_policy_evaluations(self.conn, limit=1)
        waivers = database.list_governance_waivers(self.conn, limit=1000)
        review_items = database.list_governance_review_items(self.conn, limit=1000)
        fleet = database.list_fleet_governance_reports(self.conn, limit=1)

        review_status_counts = {}
        for item in review_items:
            review_status_counts[item["status"]] = (
                review_status_counts.get(item["status"], 0) + 1)
        waiver_status_counts = {}
        for w in waivers:
            waiver_status_counts[w["status"]] = (
                waiver_status_counts.get(w["status"], 0) + 1)

        summary = {
            "generated_at": _now_iso(),
            "policies": len(policies),
            "active_policies": sum(1 for p in policies
                                   if (p["status"] or "") == "active"),
            "latest_evaluation_id": evaluations[0]["id"] if evaluations else None,
            "latest_evaluation_status": (
                evaluations[0]["overall_status"] if evaluations else "(none)"),
            "waivers": len(waivers),
            "review_items": len(review_items),
        }

        content = self._render(policies, evaluations, waivers, review_items,
                               fleet, review_status_counts, waiver_status_counts,
                               summary)
        path = self._new_export_path()
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        encoded = content.encode("utf-8")
        chash = hashlib.sha256(encoded).hexdigest()
        nbytes = len(encoded)
        export_id = database.save_governance_evidence_export(
            self.conn, summary["generated_at"], path, "markdown", chash, nbytes,
            json.dumps(summary, sort_keys=True))
        return GovernanceEvidenceExport(
            id=export_id, generated_at=summary["generated_at"], report_path=path,
            report_format="markdown", content_hash=chash, bytes_written=nbytes,
            summary=summary)

    def get_export(self, export_id) -> Optional[GovernanceEvidenceExport]:
        row = database.get_governance_evidence_export(self.conn, export_id)
        if row is None:
            return None
        try:
            summary = json.loads(row["summary_json"] or "{}")
        except (TypeError, ValueError):
            summary = {}
        return GovernanceEvidenceExport(
            id=row["id"], generated_at=row["generated_at"] or "",
            report_path=row["report_path"] or "",
            report_format=row["report_format"] or "markdown",
            content_hash=row["content_hash"] or "",
            bytes_written=row["bytes_written"] or 0, summary=summary)

    def list_exports(self, limit=50):
        return database.list_governance_evidence_exports(self.conn, limit=limit)

    def _new_export_path(self) -> str:
        os.makedirs(EXPORTS_DIR, exist_ok=True)
        filename = f"governance_evidence_{_now_stamp()}.md"
        target = os.path.realpath(os.path.join(EXPORTS_DIR, filename))
        base = os.path.realpath(EXPORTS_DIR)
        if target != base and not target.startswith(base + os.sep):
            raise ValueError("evidence export path escaped exports directory")
        return target

    def _render(self, policies, evaluations, waivers, review_items, fleet,
                review_counts, waiver_counts, summary) -> str:
        lines = []
        a = lines.append
        a("# Governance Evidence Packet")
        a("")
        a(f"- Generated at: {summary['generated_at']}")
        a("- Scope: governance/registry metadata only (no file contents/secrets).")
        a("")
        a("## Policies")
        if not policies:
            a("- (none)")
        for p in policies:
            rule_keys = p["rule_keys_json"] or "[]"
            try:
                n_rules = len(json.loads(rule_keys))
            except (TypeError, ValueError):
                n_rules = 0
            a(f"- {p['policy_key']} [{p['status']}] rules={n_rules}")
        a("")
        a("## Evaluation (latest)")
        if evaluations:
            e = evaluations[0]
            a(f"- Evaluation #{e['id']} @ {e['generated_at']}")
            a(f"- Overall: {e['overall_status']}")
            a(f"- pass/warn/fail/waived: {e['passed_findings']}/"
              f"{e['warning_findings']}/{e['failed_findings']}/{e['waived_findings']}")
        else:
            a("- (no evaluations)")
        a("")
        a("## Waivers")
        a(f"- Total: {len(waivers)}")
        for status, count in sorted(waiver_counts.items()):
            a(f"  - {status}: {count}")
        for w in waivers:
            a(f"  - #{w['id']} {w['signature']} owner={w['owner'] or '(none)'} "
              f"status={w['status']} expiry={w['expiry'] or '(none)'}")
        a("")
        a("## Review Queue")
        a(f"- Total items: {len(review_items)}")
        for status, count in sorted(review_counts.items()):
            a(f"  - {status}: {count}")
        a("")
        a("## Fleet Governance (latest)")
        if fleet:
            try:
                fs = json.loads(fleet[0]["summary_json"] or "{}")
            except (TypeError, ValueError):
                fs = {}
            a(f"- Report #{fleet[0]['id']} @ {fleet[0]['generated_at']}")
            a(f"- Total projects: {fs.get('total_projects', 0)}")
            a(f"- Stale: {fs.get('stale_projects', 0)}  "
              f"Blocked: {fs.get('blocked_projects', 0)}  "
              f"Missing validations: {fs.get('missing_validations', 0)}")
        else:
            a("- (no fleet governance report yet)")
        a("")
        a("## Safety")
        for note in (
            "This packet excludes protected file contents and secrets.",
            "This packet excludes local runtime database snapshots.",
            "Only governance/registry metadata rows are summarized.",
            "No commands were executed and no model was called.",
        ):
            a(f"- {note}")
        a("")
        return "\n".join(lines)
