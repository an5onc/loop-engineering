import json
import os
import sqlite3
import tempfile
import unittest


class Stage3CleanupTests(unittest.TestCase):
    def test_finds_and_quarantines_only_stage39_health_fixtures(self):
        import stage3_cleanup

        with tempfile.TemporaryDirectory() as td:
            db = os.path.join(td, "t.db")
            conn = sqlite3.connect(db)
            conn.row_factory = sqlite3.Row
            _create_min_schema(conn)
            _job(conn, 1, 101, "WAITING_FOR_EXTERNAL_AGENT", ["stage39-health"],
                 "stage39 health scenario: missing_packet")
            _job(conn, 2, 102, "WAITING_FOR_EXTERNAL_AGENT", [],
                 "real user job")

            report = stage3_cleanup.quarantine_health_fixtures(conn, dry_run=True)
            self.assertEqual([i.job_id for i in report.items], [1])
            self.assertEqual(
                conn.execute("select archived from external_agent_jobs where id=1").fetchone()[0],
                "0",
            )

            report = stage3_cleanup.quarantine_health_fixtures(conn, dry_run=False)
            self.assertEqual(report.changed_count, 1)
            self.assertEqual(
                conn.execute("select archived from external_agent_jobs where id=1").fetchone()[0],
                "1",
            )
            self.assertEqual(
                conn.execute("select archived from external_agent_jobs where id=2").fetchone()[0],
                "0",
            )
            events = conn.execute(
                "select event_type from external_agent_job_events where job_id=1"
            ).fetchall()
            self.assertEqual([e[0] for e in events], ["health_fixture_quarantined"])

    def test_repair_portable_paths_rebases_safe_known_paths(self):
        import stage3_cleanup

        with tempfile.TemporaryDirectory() as td:
            old = os.path.join(td, "old")
            new = os.path.join(td, "new")
            os.makedirs(os.path.join(new, "external_agent_jobs", "job_7"))
            os.makedirs(os.path.join(new, "reports"))
            os.makedirs(os.path.join(new, "external_batch_reports"))
            open(os.path.join(new, "external_agent_jobs", "job_7", "handoff.md"), "w").close()
            open(os.path.join(new, "reports", "loop_7.md"), "w").close()
            hashed_report = os.path.join(new, "reports", "loop_88_20260627_120000.md")
            with open(hashed_report, "w") as fh:
                fh.write("hashed report")
            open(os.path.join(new, "external_batch_reports", "batch_7.md"), "w").close()
            conn = sqlite3.connect(os.path.join(td, "t.db"))
            conn.row_factory = sqlite3.Row
            _create_min_schema(conn)
            conn.execute(
                "insert into external_agent_jobs(id, loop_id, handoff_path, packet_path, completion_path) "
                "values (7, 77, ?, ?, ?)",
                (
                    os.path.join(old, "external_agent_jobs", "job_7", "handoff.md"),
                    os.path.join(old, "external_agent_jobs", "job_7", "missing_packet.json"),
                    None,
                ),
            )
            conn.execute(
                "insert into run_reports(id, loop_id, report_path) values (1, 77, ?)",
                (os.path.join(old, "reports", "loop_7.md"),),
            )
            conn.execute(
                "insert into run_reports(id, loop_id, report_path, content_hash, bytes_written) "
                "values (2, 88, ?, ?, ?)",
                (
                    os.path.join(old, "reports", "loop_88.md"),
                    "e0a999dc7593c78ab4d82fd0d185fc2ae40263383e213d8207ba45cf78a48c09",
                    13,
                ),
            )
            conn.execute(
                "insert into external_batch_reports(id, batch_id, action, report_path) "
                "values (1, 'b7', 'archive', ?)",
                (os.path.join(old, "external_batch_reports", "batch_7.md"),),
            )
            conn.commit()

            dry = stage3_cleanup.repair_portable_paths(conn, new, dry_run=True)
            self.assertEqual(dry.repairable_count, 4)
            self.assertEqual(dry.warning_count, 1)
            self.assertTrue(
                conn.execute("select handoff_path from external_agent_jobs where id=7").fetchone()[0]
                .startswith(old)
            )

            report = stage3_cleanup.repair_portable_paths(conn, new, dry_run=False)
            self.assertEqual(report.repaired_count, 4)
            row = conn.execute("select handoff_path, packet_path from external_agent_jobs where id=7").fetchone()
            self.assertEqual(
                row["handoff_path"],
                os.path.realpath(os.path.join(new, "external_agent_jobs", "job_7", "handoff.md")),
            )
            self.assertTrue(row["packet_path"].startswith(old))
            self.assertEqual(
                conn.execute("select report_path from run_reports where id=1").fetchone()[0],
                os.path.realpath(os.path.join(new, "reports", "loop_7.md")),
            )
            self.assertEqual(
                conn.execute("select report_path from run_reports where id=2").fetchone()[0],
                os.path.realpath(hashed_report),
            )
            self.assertEqual(
                conn.execute("select report_path from external_batch_reports where id=1").fetchone()[0],
                os.path.realpath(os.path.join(new, "external_batch_reports", "batch_7.md")),
            )

    def test_selects_active_linked_job_for_import_compatibility(self):
        import stage3_cleanup

        with tempfile.TemporaryDirectory() as td:
            conn = sqlite3.connect(os.path.join(td, "t.db"))
            conn.row_factory = sqlite3.Row
            _create_min_schema(conn)
            _job(conn, 10, 55, "CANCELLED", [], "old")
            _job(conn, 11, 55, "WAITING_FOR_EXTERNAL_AGENT", [], "active")

            selected, reason = stage3_cleanup.select_job_for_loop_import(conn, 55)
            self.assertIsNone(reason)
            self.assertEqual(selected["id"], 11)

            stage3_cleanup.update_linked_job_after_loop_import(
                conn, selected, "completion.json", "REJECTED", "reviewed"
            )
            row = conn.execute("select status, completion_path from external_agent_jobs where id=11").fetchone()
            self.assertEqual(row["status"], "REVIEWED")
            self.assertEqual(row["completion_path"], "completion.json")


def _create_min_schema(conn):
    conn.executescript(
        """
        create table loops(id integer primary key, task text);
        create table external_agent_jobs(
            id integer primary key,
            loop_id integer,
            status text,
            labels_json text,
            notes text,
            archived text default '0',
            archived_at text,
            completion_path text,
            last_error text,
            handoff_path text,
            packet_path text,
            updated_at text
        );
        create table external_agent_job_events(
            id integer primary key autoincrement,
            job_id integer,
            loop_id integer,
            event_type text,
            status_before text,
            status_after text,
            details_json text,
            created_at text default current_timestamp
        );
        create table run_reports(
            id integer primary key,
            loop_id integer,
            report_path text,
            content_hash text,
            bytes_written integer
        );
        create table external_batch_reports(id integer primary key, batch_id text, action text, report_path text);
        """
    )
    conn.commit()


def _job(conn, job_id, loop_id, status, labels, task):
    conn.execute("insert or ignore into loops(id, task) values (?, ?)", (loop_id, task))
    conn.execute(
        "insert into external_agent_jobs(id, loop_id, status, labels_json, notes, archived) "
        "values (?, ?, ?, ?, '', '0')",
        (job_id, loop_id, status, json.dumps(labels)),
    )
    conn.commit()


if __name__ == "__main__":
    unittest.main()
