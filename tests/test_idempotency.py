"""Tests for idempotent loads, restarts, late data and history."""
from src import schemas as S
from tests.helpers import ACCOUNTS, txn, write_raw

HEADER = ",".join(S.TRANSACTION_COLUMNS)


def test_rerunning_the_same_file_adds_nothing(pipeline):
    rows = [txn("TXN0000001"), txn("TXN0000002", amount="50.00"),
            txn("TXN0000003", currency="USD")]
    first = pipeline(transactions=rows)
    second = pipeline(transactions=rows)
    assert first.result["status"] == "success" and second.result["status"] == "success"
    assert first.ctx.metrics["rows_inserted_new"] == 2
    assert second.ctx.metrics["rows_inserted_new"] == 0
    assert second.count("clean_transactions") == 2
    assert second.count("rejected_records") == 1       # not doubled
    assert second.count("daily_account_summary") == 1
    assert second.count("pipeline_runs") == 2           # both runs are on record


def test_same_transaction_in_a_later_file_is_a_duplicate(pipeline):
    pipeline(transactions=[txn("TXN0000001")], txn_name="day1.csv")
    second = pipeline(transactions=[txn("TXN0000001"), txn("TXN0000002", amount="5.00")],
                      txn_name="day2.csv")
    assert second.count("clean_transactions") == 2
    assert second.rows("SELECT row_number, reject_reason FROM rejected_records "
                       "WHERE source_file = 'day2.csv'") == [(1, S.REJECT_DUPLICATE)]


def test_same_id_with_changed_content_in_a_later_file_is_a_conflict(pipeline):
    pipeline(transactions=[txn("TXN0000001", amount="100.00")], txn_name="day1.csv")
    second = pipeline(transactions=[txn("TXN0000001", amount="999.00")], txn_name="day2.csv")
    assert second.value("SELECT amount FROM clean_transactions "
                        "WHERE transaction_id = 'TXN0000001'") == 100.0
    assert second.rows("SELECT row_number, reject_reason FROM rejected_records "
                       "WHERE source_file = 'day2.csv'") == [(1, S.REJECT_CONFLICT)]


def test_late_arriving_data_lands_on_its_true_date(pipeline):
    pipeline(transactions=[
        txn("TXN0000001", amount="500.00", transaction_time="2026-10-02T09:00:00"),
    ], txn_name="day1.csv")
    second = pipeline(transactions=[
        txn("TXN0000002", amount="300.00", transaction_time="2026-10-01T08:00:00"),  # late
        txn("TXN0000003", amount="100.00", txn_type="debit",
            transaction_time="2026-10-02T18:00:00"),
    ], txn_name="day2.csv")
    assert second.rows(
        "SELECT account_id, txn_date, total_credits, total_debits, net_amount, txn_count "
        "FROM daily_account_summary ORDER BY txn_date"
    ) == [
        ("ACC00001", "2026-10-01", 300.0, 0.0, 300.0, 1),
        ("ACC00001", "2026-10-02", 500.0, 100.0, 400.0, 2),
    ]


def test_out_of_order_rows_in_one_file_are_all_accepted(pipeline):
    run = pipeline(transactions=[
        txn("TXN0000001", transaction_time="2026-10-03T10:00:00"),
        txn("TXN0000002", transaction_time="2026-10-01T10:00:00"),
        txn("TXN0000003", transaction_time="2026-10-02T10:00:00"),
    ])
    assert run.count("clean_transactions") == 3
    assert run.count("daily_account_summary") == 3


def test_status_changes_are_kept_as_history(pipeline):
    pipeline(started_at="2026-10-01T00:00:00")
    frozen = [dict(a) for a in ACCOUNTS]
    frozen[0]["status"] = "frozen"
    second = pipeline(accounts=frozen, started_at="2026-10-02T00:00:00")
    history = "SELECT status, effective_at FROM account_status_history " \
              "WHERE account_id = 'ACC00001' ORDER BY effective_at"
    assert second.rows(history) == [("active", "2026-10-01T00:00:00"),
                                    ("frozen", "2026-10-02T00:00:00")]
    assert second.value("SELECT status FROM accounts WHERE account_id = 'ACC00001'") == "frozen"
    third = pipeline(accounts=frozen, started_at="2026-10-03T00:00:00")  # nothing changed
    assert len(third.rows(history)) == 2


def test_failed_run_leaves_earlier_data_untouched(pipeline, tmp_path):
    first = pipeline(transactions=[txn("TXN0000001"), txn("TXN0000002")])
    broken = write_raw(tmp_path / "broken.csv",
                       f"{HEADER.replace('amount', 'amt')}\nTXN0000009,ACC00001,5.00,credit,INR,2026-10-01T10:00:00\n")
    second = pipeline(txn_path=broken)
    assert first.result["status"] == "success"
    assert second.result["status"] == "failed"
    assert second.count("clean_transactions") == 2


def test_restart_after_a_failed_run_publishes_once(pipeline):
    rows = [txn("TXN0000001"), txn("TXN0000002", currency="USD")]  # 50% bad
    first = pipeline(transactions=rows, max_reject_rate=0.10)
    assert first.result["status"] == "failed"
    assert first.count("clean_transactions") == 0
    second = pipeline(transactions=rows, max_reject_rate=0.60)       # operator raises the limit
    assert second.result["status"] == "success"
    assert second.count("clean_transactions") == 1
    assert second.count("rejected_records") == 1                     # not 2
