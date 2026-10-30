"""Tests for validation rules: what gets published and what gets rejected."""
import json

import pytest

from src import schemas as S
from tests.helpers import ACCOUNTS, txn, write_raw

REJECTS_SQL = "SELECT row_number, reject_reason FROM rejected_records ORDER BY row_number"


# ---------------------------------------------------------------- happy path
def test_happy_path_publishes_all_valid_rows(pipeline):
    run = pipeline(run_id="run_happy", transactions=[
        txn("TXN0000001", amount="1000.00", txn_type="credit"),
        txn("TXN0000002", amount="250.50", txn_type="debit",
            transaction_time="2026-10-01T15:30:00"),
        txn("TXN0000003", account_id="ACC00002", amount="75.25",
            transaction_time="2026-10-02T09:00:00"),  # frozen accounts may still receive money
    ])
    assert run.result["status"] == "success"
    assert run.count("clean_transactions") == 3
    assert run.count("rejected_records") == 0
    assert run.rows(
        "SELECT total_credits, total_debits, net_amount, txn_count "
        "FROM daily_account_summary WHERE account_id = 'ACC00001' AND txn_date = '2026-10-01'"
    ) == [(1000.0, 250.5, 749.5, 2)]
    assert run.rows(
        "SELECT total_credits, total_debits, net_amount, txn_count "
        "FROM daily_account_summary WHERE account_id = 'ACC00002'"
    ) == [(75.25, 0.0, 75.25, 1)]
    assert run.rows(
        "SELECT status, rows_in, rows_clean, rows_rejected FROM pipeline_runs "
        "WHERE run_id = 'run_happy'") == [("success", 3, 3, 0)]


# --------------------------------------------------------------- empty input
def test_empty_batch_succeeds_and_publishes_nothing(pipeline):
    run = pipeline(transactions=[])
    assert run.result["status"] == "success"
    assert run.count("clean_transactions") == 0
    assert run.count("accounts") == 3


def test_zero_byte_file_is_a_schema_failure(pipeline, tmp_path):
    empty = write_raw(tmp_path / "transactions.csv", "")
    run = pipeline(txn_path=empty)
    assert run.result["status"] == "failed"
    assert run.task("validate_schema")["status"] == "failed"
    assert run.task("publish")["status"] == "skipped"


# ------------------------------------------------------------ malformed rows
def test_malformed_rows_are_rejected(pipeline, tmp_path):
    header = ",".join(S.TRANSACTION_COLUMNS)
    text = (
        f"{header}\n"
        "TXN0000001,ACC00001,100.00,credit,INR,2026-10-01T10:00:00\n"
        "TXN0000002,ACC00001,100.00\n"                                          # too few fields
        "TXN0000003,ACC00001,100.00,credit,INR,2026-10-01T10:00:00,EXTRA\n"     # too many fields
    )
    run = pipeline(txn_path=write_raw(tmp_path / "transactions.csv", text))
    assert run.count("clean_transactions") == 1
    assert run.rows(REJECTS_SQL) == [(2, "malformed_row"), (3, "malformed_row")]


# --------------------------------------------------------------------- nulls
@pytest.mark.parametrize("column", S.TRANSACTION_COLUMNS)
def test_empty_required_field_is_rejected(pipeline, column):
    bad = txn("TXN0000002")
    bad[column] = ""
    run = pipeline(transactions=[txn("TXN0000001"), bad])
    assert run.count("clean_transactions") == 1
    assert run.rows(REJECTS_SQL) == [(2, S.REJECT_MISSING_FIELD)]


def test_whitespace_only_value_counts_as_missing(pipeline):
    run = pipeline(transactions=[txn("TXN0000001", amount="   ")])
    assert run.rows(REJECTS_SQL) == [(1, S.REJECT_MISSING_FIELD)]


# ------------------------------------------------------------ invalid values
@pytest.mark.parametrize("field, value, reason", [
    ("amount", "-250.00", S.REJECT_BAD_AMOUNT),
    ("amount", "0.00", S.REJECT_BAD_AMOUNT),
    ("amount", "abc", S.REJECT_BAD_AMOUNT),
    ("amount", "NaN", S.REJECT_BAD_AMOUNT),
    ("amount", "0.004", S.REJECT_BAD_AMOUNT),  # rounds to 0.00, so not a real amount
    ("txn_type", "transfer", S.REJECT_BAD_TXN_TYPE),
    ("currency", "USD", S.REJECT_BAD_CURRENCY),
    ("transaction_time", "31/13/2026 25:61", S.REJECT_BAD_TIMESTAMP),
    ("transaction_time", "2031-05-01T09:00:00", S.REJECT_FUTURE_TIMESTAMP),
    ("account_id", "ACC99999", S.REJECT_INVALID_ACCOUNT),  # reference does not exist
    ("account_id", "ACC00003", S.REJECT_CLOSED_ACCOUNT),   # account is closed
])
def test_invalid_value_is_rejected_with_the_right_reason(pipeline, field, value, reason):
    bad = txn("TXN0000002")
    bad[field] = value
    run = pipeline(transactions=[txn("TXN0000001"), bad])
    assert run.count("clean_transactions") == 1
    assert run.rows(REJECTS_SQL) == [(2, reason)]


# ---------------------------------------------------------------- duplicates
def test_exact_duplicate_in_same_file_is_rejected(pipeline):
    run = pipeline(transactions=[txn("TXN0000001"), txn("TXN0000001")])
    assert run.count("clean_transactions") == 1
    assert run.rows(REJECTS_SQL) == [(2, S.REJECT_DUPLICATE)]


def test_same_id_with_different_content_is_a_conflict(pipeline):
    run = pipeline(transactions=[
        txn("TXN0000001", amount="100.00"),
        txn("TXN0000001", amount="999.00"),
    ])
    assert run.value("SELECT amount FROM clean_transactions") == 100.0  # first one wins
    assert run.rows(REJECTS_SQL) == [(2, S.REJECT_CONFLICT)]


# ------------------------------------------------- bank-specific edge cases
def test_timestamps_with_offsets_are_normalised_to_utc(pipeline):
    run = pipeline(transactions=[txn("TXN0000001", transaction_time="2026-10-02T01:00:00+05:30")])
    # 01:00 IST on the 2nd is 19:30 UTC on the 1st, so it belongs to the 1st
    assert run.rows("SELECT transaction_time, txn_date FROM clean_transactions") == [
        ("2026-10-01T19:30:00", "2026-10-01")]


def test_smallest_valid_amount_accepted_and_sub_paisa_rejected(pipeline):
    run = pipeline(transactions=[
        txn("TXN0000001", amount="0.01"),
        txn("TXN0000002", amount="0.004"),
    ])
    assert run.value("SELECT amount FROM clean_transactions") == 0.01
    assert run.rows(REJECTS_SQL) == [(2, S.REJECT_BAD_AMOUNT)]


# --------------------------------------------------------- account records
def test_bad_account_rows_are_rejected_and_their_transactions_too(pipeline):
    good = dict(ACCOUNTS[0])
    duplicate = dict(ACCOUNTS[0])
    bad_status = dict(ACCOUNTS[1], account_id="ACC00004", status="suspended")
    run = pipeline(
        accounts=[good, duplicate, bad_status],
        transactions=[txn("TXN0000001"), txn("TXN0000002", account_id="ACC00004")])
    assert run.count("accounts") == 1
    assert run.rows(
        "SELECT row_number, reject_reason FROM rejected_records "
        "WHERE record_type = 'account' ORDER BY row_number"
    ) == [(2, "duplicate_account"), (3, "invalid_account_record")]
    assert run.rows(
        "SELECT row_number, reject_reason FROM rejected_records "
        "WHERE record_type = 'transaction'") == [(2, S.REJECT_INVALID_ACCOUNT)]


# ------------------------------------------------------------- traceability
def test_rejected_rows_can_be_traced_back_to_the_source(pipeline):
    run = pipeline(run_id="run_trace",
                   transactions=[txn("TXN0000001"), txn("TXN0000002", amount="abc")])
    row = run.rows(
        "SELECT source_file, row_number, record_key, reject_reason, run_id, raw_record "
        "FROM rejected_records")[0]
    assert row[:5] == ("transactions.csv", 2, "TXN0000002", S.REJECT_BAD_AMOUNT, "run_trace")
    assert json.loads(row[5])["amount"] == "abc"
