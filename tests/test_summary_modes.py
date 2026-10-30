"""The fast incremental summary must give exactly the same answers as a full rebuild."""
from tests.helpers import txn

DAY1 = [
    txn("TXN0000001", amount="500.00", transaction_time="2026-10-02T09:00:00"),
    txn("TXN0000002", account_id="ACC00002", amount="40.00",
        transaction_time="2026-10-02T11:00:00"),
]
DAY2 = [
    txn("TXN0000003", amount="300.00", transaction_time="2026-10-01T08:00:00"),   # late data
    txn("TXN0000004", amount="100.00", txn_type="debit",
        transaction_time="2026-10-02T18:00:00"),
    txn("TXN0000005", account_id="ACC00002", amount="75.50",
        transaction_time="2026-10-05T10:00:00"),
    txn("TXN0000006", currency="USD"),                                              # rejected
]


def load_two_days(pipeline, mode):
    db_name = f"{mode}.db"
    pipeline(transactions=DAY1, txn_name="day1.csv", db_name=db_name, summary_mode=mode)
    run = pipeline(transactions=DAY2, txn_name="day2.csv", db_name=db_name, summary_mode=mode)
    return run.rows("SELECT * FROM daily_account_summary ORDER BY account_id, txn_date")


def test_incremental_summary_matches_full_rebuild(pipeline):
    incremental = load_two_days(pipeline, "incremental")
    full = load_two_days(pipeline, "full")
    assert len(incremental) == 4
    assert incremental == full


def test_incremental_summary_only_touches_affected_days(pipeline):
    pipeline(transactions=DAY1, txn_name="day1.csv")
    run = pipeline(transactions=DAY2, txn_name="day2.csv")
    assert run.rows(
        "SELECT total_credits, total_debits, net_amount, txn_count "
        "FROM daily_account_summary WHERE account_id = 'ACC00002' AND txn_date = '2026-10-02'"
    ) == [(40.0, 0.0, 40.0, 1)]   # day 1's row for this account/day is unchanged
