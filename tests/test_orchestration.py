"""Tests for the orchestrator: dependencies, retries, timeouts, status, alerts, publish gate."""
import sqlite3

import pytest

from src import schemas as S
from src.db import connect
from src.tasks import ReconciliationError, RunContext, publish, reconcile
from tests.helpers import txn, write_raw

TASK_ORDER = ["ingest", "validate_schema", "validate_rules", "quarantine",
              "transform", "quality_gate", "publish", "reconcile"]
HEADER = ",".join(S.TRANSACTION_COLUMNS)
GOOD_ROW = "TXN0000001,ACC00001,100.00,credit,INR,2026-10-01T10:00:00"


# ----------------------------------------------------------- run status
def test_successful_run_records_status_for_every_task(pipeline):
    run = pipeline(transactions=[txn("TXN0000001"), txn("TXN0000002")])
    assert run.result["status"] == "success"
    assert [r[0] for r in run.rows("SELECT task_name FROM task_runs ORDER BY id")] == TASK_ORDER
    assert all(r[0] == "success" for r in run.rows("SELECT status FROM task_runs"))
    assert run.value("SELECT ended_at FROM pipeline_runs") is not None
    assert run.alerts() == []


# ----------------------------------------------------------------- retries
def test_transient_failure_is_retried_until_it_works(pipeline):
    run = pipeline(transactions=[txn("TXN0000001")],
                   inject_failures={"transform": 2}, retries=2)
    assert run.result["status"] == "success"
    assert run.task("transform")["attempts"] == 3
    assert run.count("clean_transactions") == 1


def test_retries_exhausted_fails_task_and_blocks_publish(pipeline):
    run = pipeline(transactions=[txn("TXN0000001")],
                   inject_failures={"transform": 5}, retries=1)
    assert run.result["status"] == "failed"
    assert run.task("transform")["status"] == "failed"
    assert run.task("transform")["attempts"] == 2
    assert run.task("publish")["status"] == "skipped"
    assert run.task("reconcile")["status"] == "skipped"
    assert run.count("clean_transactions") == 0
    assert any(a["level"] == "ERROR" and "transform" in a["message"] for a in run.alerts())


def test_failure_during_publish_is_retried_without_creating_duplicates(pipeline):
    run = pipeline(transactions=[txn("TXN0000001"), txn("TXN0000002")],
                   inject_failures={"publish": 1}, retries=2)
    assert run.result["status"] == "success"
    assert run.task("publish")["attempts"] == 2
    assert run.count("clean_transactions") == 2


def test_publish_is_all_or_nothing(tmp_path):
    conn = connect(tmp_path / "atomic.db")
    ctx = RunContext(conn=conn, run_id="r1", accounts_path=tmp_path / "accounts.csv",
                     transactions_path=tmp_path / "transactions.csv")
    ctx.publish_accounts = [("ACC00001", "Asha Reddy", "savings", "active",
                             "2024-01-15", "r1", "accounts.csv")]
    ctx.publish_txns = [
        ("TXN0000001", "ACC00001", 100.0, "credit", "INR",
         "2026-10-01T10:00:00", "2026-10-01", "r1", "transactions.csv", 1),
        ("TXN0000002", "ACC00001", -5.0, "credit", "INR",     # violates the amount > 0 rule
         "2026-10-01T11:00:00", "2026-10-01", "r1", "transactions.csv", 2),
    ]
    with pytest.raises(sqlite3.IntegrityError):
        publish(ctx)
    assert conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM clean_transactions").fetchone()[0] == 0
    conn.close()


# ----------------------------------------------------------------- timeouts
def test_slow_task_times_out_and_blocks_everything_after_it(pipeline):
    run = pipeline(transactions=[txn("TXN0000001")],
                   inject_delays={"ingest": 2.0}, timeout=0.5)
    assert run.result["status"] == "failed"
    assert run.task("ingest")["status"] == "failed"
    assert "TaskTimeout" in run.task("ingest")["error"]
    assert run.task("ingest")["attempts"] == 1  # timeouts are not retried
    assert all(run.task(n)["status"] == "skipped" for n in TASK_ORDER[1:])
    assert run.count("clean_transactions") == 0


# ---------------------------------------------- critical failures block publish
@pytest.mark.parametrize("header, row, expected_word", [
    (HEADER.replace("amount", "amt"), GOOD_ROW, "amount"),   # a column was renamed
    (HEADER + ",notes", GOOD_ROW + ",x", "notes"),           # an unexpected column appeared
])
def test_schema_change_stops_the_run_and_blocks_publish(pipeline, tmp_path, header, row, expected_word):
    path = write_raw(tmp_path / "transactions.csv", f"{header}\n{row}\n")
    run = pipeline(txn_path=path)
    assert run.result["status"] == "failed"
    assert run.task("validate_schema")["status"] == "failed"
    assert run.task("validate_schema")["attempts"] == 1  # deterministic failure: no retry
    for name in ["validate_rules", "quarantine", "transform", "quality_gate", "publish", "reconcile"]:
        assert run.task(name)["status"] == "skipped"
    assert run.count("clean_transactions") == 0
    assert any(a["level"] == "CRITICAL" and expected_word in a["message"] for a in run.alerts())


def test_quality_gate_failure_blocks_publish_but_keeps_rejects(pipeline):
    rows = [txn("TXN0000001"), txn("TXN0000002"),
            txn("TXN0000003", currency="USD"), txn("TXN0000004", currency="USD")]
    run = pipeline(transactions=rows, max_reject_rate=0.10)
    assert run.result["status"] == "failed"
    assert run.task("quality_gate")["status"] == "failed"
    assert run.task("publish")["status"] == "skipped"
    assert run.count("clean_transactions") == 0
    assert run.count("rejected_records") == 2  # the operator can still inspect them
    assert run.value("SELECT status FROM pipeline_runs") == "failed"
    assert run.value("SELECT failure_reason FROM pipeline_runs") is not None
    assert any(a["level"] == "CRITICAL" and "BLOCKED" in a["message"] for a in run.alerts())


def test_reject_rate_exactly_at_the_limit_is_allowed(pipeline):
    rows = [txn(f"TXN{i:07d}") for i in range(1, 10)] + [txn("TXN0000010", currency="USD")]
    run = pipeline(transactions=rows, max_reject_rate=0.10)  # 1 of 10 rejected = 10%
    assert run.result["status"] == "success"
    assert run.count("clean_transactions") == 9


# ---------------------------------------------------------- reconciliation
def test_reconciliation_report_is_written_and_passes(pipeline):
    import json
    run = pipeline(transactions=[txn("TXN0000001"), txn("TXN0000002", currency="USD")])
    reports = list(run.out_dir.glob("reconciliation_*.json"))
    assert len(reports) == 1
    report = json.loads(reports[0].read_text(encoding="utf-8"))
    assert report["all_passed"] is True
    assert len(report["checks"]) == 4


def test_reconciliation_detects_missing_target_rows(pipeline):
    run = pipeline(transactions=[txn("TXN0000001"), txn("TXN0000002")])
    run.conn.execute("DELETE FROM clean_transactions WHERE transaction_id = 'TXN0000001'")
    run.conn.commit()
    with pytest.raises(ReconciliationError):
        reconcile(run.ctx)
