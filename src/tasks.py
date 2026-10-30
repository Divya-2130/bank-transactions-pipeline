"""Pipeline tasks.

Each task receives a RunContext, does ONE job, and raises an exception on failure.
Tasks run in the order listed in PIPELINE at the bottom of this file.
"""
import csv
import json
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from src.schemas import (
    ACCOUNT_COLUMNS,
    ACCOUNT_ID_PATTERN,
    REJECT_BAD_AMOUNT,
    REJECT_BAD_CURRENCY,
    REJECT_BAD_TIMESTAMP,
    REJECT_BAD_TXN_TYPE,
    REJECT_CLOSED_ACCOUNT,
    REJECT_CONFLICT,
    REJECT_DUPLICATE,
    REJECT_FUTURE_TIMESTAMP,
    REJECT_INVALID_ACCOUNT,
    REJECT_MISSING_FIELD,
    TRANSACTION_COLUMNS,
    VALID_ACCOUNT_STATUSES,
    VALID_ACCOUNT_TYPES,
    VALID_CURRENCIES,
    VALID_TXN_TYPES,
)

# Extra reject reasons used only for rows that cannot even be read properly
REJECT_MALFORMED = "malformed_row"
REJECT_INVALID_ACCOUNT_RECORD = "invalid_account_record"
REJECT_DUPLICATE_ACCOUNT = "duplicate_account"


class SchemaValidationError(Exception):
    """Input file columns do not match the expected schema (critical)."""


class QualityGateError(Exception):
    """Too many bad rows, or counts do not add up (critical)."""


class ReconciliationError(Exception):
    """Source and target do not reconcile."""


@dataclass
class RunContext:
    """Everything the tasks share during one pipeline run."""

    conn: sqlite3.Connection
    run_id: str
    accounts_path: Path
    transactions_path: Path
    output_dir: Path = Path("output")
    max_reject_rate: float = 0.10
    as_of: datetime = field(default_factory=datetime.now)
    started_at: str = field(
        default_factory=lambda: datetime.now().isoformat(timespec="seconds")
    )

    account_header: list = field(default_factory=list)
    txn_header: list = field(default_factory=list)
    account_rows: list = field(default_factory=list)
    txn_rows: list = field(default_factory=list)
    clean_accounts: list = field(default_factory=list)
    clean_txns: list = field(default_factory=list)
    account_rejects: list = field(default_factory=list)
    txn_rejects: list = field(default_factory=list)
    publish_accounts: list = field(default_factory=list)
    publish_txns: list = field(default_factory=list)
    metrics: dict = field(default_factory=dict)

    def __post_init__(self):
        self.accounts_path = Path(self.accounts_path)
        self.transactions_path = Path(self.transactions_path)
        self.output_dir = Path(self.output_dir)


# ----------------------------------------------------------------- helpers
def _read_csv(path):
    """Return (header, [(row_number, row_dict), ...]). row_number starts at 1, header excluded."""
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        header = list(reader.fieldnames or [])
        rows = [(i, row) for i, row in enumerate(reader, start=1)]
    return header, rows


def _check_header(name, header, expected):
    missing = [c for c in expected if c not in header]
    extra = [c for c in header if c not in expected]
    if missing or extra:
        raise SchemaValidationError(
            f"{name}: missing columns {missing}, unexpected columns {extra}"
        )


def _is_malformed(row, columns):
    """True if the row has too many fields (None key) or too few (None value)."""
    return None in row or any(row.get(c) is None for c in columns)


def _strip(row):
    return {k: v.strip() for k, v in row.items()}


def _parse_amount(text):
    try:
        value = Decimal(text)
        if not value.is_finite() or value <= 0:
            return None
        return value.quantize(Decimal("0.01"))
    except InvalidOperation:
        return None


def _parse_timestamp(text):
    try:
        value = datetime.fromisoformat(text)
    except ValueError:
        return None
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _parse_date(text):
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _reject(record_type, source_file, row_number, key, reason, raw):
    return {
        "record_type": record_type,
        "source_file": source_file,
        "row_number": row_number,
        "record_key": key,
        "reject_reason": reason,
        "raw_record": json.dumps(raw, default=str),
    }


# ------------------------------------------------------------------ tasks
def ingest(ctx):
    """Read both CSV files into memory (rows keep their original row_number)."""
    ctx.account_header, ctx.account_rows = _read_csv(ctx.accounts_path)
    ctx.txn_header, ctx.txn_rows = _read_csv(ctx.transactions_path)


def validate_schema(ctx):
    """CRITICAL: file columns must match the expected schema exactly."""
    _check_header("accounts.csv", ctx.account_header, ACCOUNT_COLUMNS)
    _check_header("transactions.csv", ctx.txn_header, TRANSACTION_COLUMNS)


def _validate_accounts(ctx):
    source = ctx.accounts_path.name
    seen = set()
    for rn, row in ctx.account_rows:
        if _is_malformed(row, ACCOUNT_COLUMNS):
            ctx.account_rejects.append(
                _reject("account", source, rn, None, REJECT_MALFORMED, row))
            continue
        r = _strip(row)
        key = r["account_id"]
        if key in seen:
            ctx.account_rejects.append(
                _reject("account", source, rn, key, REJECT_DUPLICATE_ACCOUNT, row))
            continue
        valid = bool(
            re.match(ACCOUNT_ID_PATTERN, key)
            and r["customer_name"]
            and r["account_type"] in VALID_ACCOUNT_TYPES
            and r["status"] in VALID_ACCOUNT_STATUSES
            and _parse_date(r["opened_date"])
        )
        if not valid:
            ctx.account_rejects.append(
                _reject("account", source, rn, key or None,
                        REJECT_INVALID_ACCOUNT_RECORD, row))
            continue
        seen.add(key)
        ctx.clean_accounts.append(r)


def _validate_transactions(ctx):
    source = ctx.transactions_path.name

    # Account statuses: what is already in the database, overridden by this batch
    acct_status = {r[0]: r[1] for r in ctx.conn.execute(
        "SELECT account_id, status FROM accounts")}
    acct_status.update({a["account_id"]: a["status"] for a in ctx.clean_accounts})

    # Transactions already published by earlier runs
    existing = {}
    for r in ctx.conn.execute(
            "SELECT transaction_id, account_id, amount, txn_type, currency, "
            "transaction_time, source_file FROM clean_transactions"):
        existing[r[0]] = ((r[1], f"{r[2]:.2f}", r[3], r[4], r[5]), r[6])

    seen = {}  # transaction_id -> content, for rows accepted in THIS file

    def reject(rn, tid, reason, row):
        ctx.txn_rejects.append(
            _reject("transaction", source, rn, tid or None, reason, row))

    for rn, row in ctx.txn_rows:
        if _is_malformed(row, TRANSACTION_COLUMNS):
            reject(rn, None, REJECT_MALFORMED, row)
            continue
        r = _strip(row)
        tid = r["transaction_id"]

        if any(r[c] == "" for c in TRANSACTION_COLUMNS):
            reject(rn, tid, REJECT_MISSING_FIELD, row)
            continue
        amount = _parse_amount(r["amount"])
        if amount is None:
            reject(rn, tid, REJECT_BAD_AMOUNT, row)
            continue
        if r["txn_type"] not in VALID_TXN_TYPES:
            reject(rn, tid, REJECT_BAD_TXN_TYPE, row)
            continue
        if r["currency"] not in VALID_CURRENCIES:
            reject(rn, tid, REJECT_BAD_CURRENCY, row)
            continue
        ts = _parse_timestamp(r["transaction_time"])
        if ts is None:
            reject(rn, tid, REJECT_BAD_TIMESTAMP, row)
            continue
        if ts > ctx.as_of:
            reject(rn, tid, REJECT_FUTURE_TIMESTAMP, row)
            continue
        status = acct_status.get(r["account_id"])
        if status is None:
            reject(rn, tid, REJECT_INVALID_ACCOUNT, row)
            continue
        if status == "closed":
            reject(rn, tid, REJECT_CLOSED_ACCOUNT, row)
            continue

        ts_text = ts.isoformat(timespec="seconds")
        content = (r["account_id"], f"{amount:.2f}", r["txn_type"],
                   r["currency"], ts_text)

        if tid in seen:
            reason = REJECT_DUPLICATE if seen[tid] == content else REJECT_CONFLICT
            reject(rn, tid, reason, row)
            continue
        if tid in existing:
            old_content, old_source = existing[tid]
            if old_content == content and old_source == source:
                pass  # same file loaded again: a safe rerun, accept it
            elif old_content == content:
                reject(rn, tid, REJECT_DUPLICATE, row)
                continue
            else:
                reject(rn, tid, REJECT_CONFLICT, row)
                continue

        seen[tid] = content
        ctx.clean_txns.append({
            "row_number": rn,
            "transaction_id": tid,
            "account_id": r["account_id"],
            "amount": f"{amount:.2f}",
            "txn_type": r["txn_type"],
            "currency": r["currency"],
            "transaction_time": ts_text,
        })


def validate_rules(ctx):
    """Business-rule checks. Bad rows go to reject lists; good rows to clean lists."""
    _validate_accounts(ctx)
    _validate_transactions(ctx)
    ctx.metrics.update({
        "accounts_in": len(ctx.account_rows),
        "accounts_rejected": len(ctx.account_rejects),
        "rows_in": len(ctx.txn_rows),
        "rows_clean": len(ctx.clean_txns),
        "rows_rejected": len(ctx.txn_rejects),
    })


def quarantine(ctx):
    """Store rejected rows with reason, source file and row number (traceable)."""
    sources = [ctx.accounts_path.name, ctx.transactions_path.name]
    now = datetime.now().isoformat(timespec="seconds")
    rows = [
        (r["record_type"], r["source_file"], r["row_number"], r["record_key"],
         r["reject_reason"], r["raw_record"], ctx.run_id, now)
        for r in ctx.account_rejects + ctx.txn_rejects
    ]
    with ctx.conn:
        # Replace this file's old rejects so the table always matches the latest file
        ctx.conn.execute(
            "DELETE FROM rejected_records WHERE source_file IN (?, ?)", sources)
        ctx.conn.executemany(
            "INSERT INTO rejected_records (record_type, source_file, row_number, "
            "record_key, reject_reason, raw_record, run_id, rejected_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows)


def transform(ctx):
    """Add derived fields (txn_date) and lineage fields (run_id, source_file)."""
    src_a = ctx.accounts_path.name
    src_t = ctx.transactions_path.name
    ctx.publish_accounts = [
        (a["account_id"], a["customer_name"], a["account_type"], a["status"],
         a["opened_date"], ctx.run_id, src_a)
        for a in ctx.clean_accounts
    ]
    ctx.publish_txns = [
        (t["transaction_id"], t["account_id"], float(t["amount"]), t["txn_type"],
         t["currency"], t["transaction_time"], t["transaction_time"][:10],
         ctx.run_id, src_t, t["row_number"])
        for t in ctx.clean_txns
    ]


def quality_gate(ctx):
    """CRITICAL: stop the run if too many rows were rejected or counts do not add up."""
    rows_in = len(ctx.txn_rows)
    rejected = len(ctx.txn_rejects)
    if len(ctx.clean_txns) + rejected != rows_in:
        raise QualityGateError(
            f"counts do not add up: clean {len(ctx.clean_txns)} + "
            f"rejected {rejected} != input {rows_in}")
    if rows_in == 0:
        return  # empty batch: nothing to judge, nothing to publish
    rate = rejected / rows_in
    if rate > ctx.max_reject_rate:
        raise QualityGateError(
            f"reject rate {rate:.1%} is above the allowed {ctx.max_reject_rate:.1%}")


def publish(ctx):
    """Load clean data. Idempotent: running the same input twice adds nothing new."""
    conn = ctx.conn
    existing = {r[0]: r[1] for r in conn.execute(
        "SELECT account_id, status FROM accounts")}
    # History: record a row whenever an account is new or its status changed
    history = [(a[0], a[3], ctx.started_at, ctx.run_id)
               for a in ctx.publish_accounts if existing.get(a[0]) != a[3]]

    with conn:  # one transaction: all of this succeeds, or none of it does
        conn.executemany(
            "INSERT INTO accounts (account_id, customer_name, account_type, status, "
            "opened_date, run_id, source_file) VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(account_id) DO UPDATE SET "
            "customer_name = excluded.customer_name, "
            "account_type = excluded.account_type, status = excluded.status, "
            "opened_date = excluded.opened_date, run_id = excluded.run_id, "
            "source_file = excluded.source_file", ctx.publish_accounts)
        conn.executemany(
            "INSERT OR IGNORE INTO account_status_history "
            "(account_id, status, effective_at, run_id) VALUES (?, ?, ?, ?)", history)

        before = conn.total_changes
        conn.executemany(
            "INSERT INTO clean_transactions (transaction_id, account_id, amount, "
            "txn_type, currency, transaction_time, txn_date, run_id, source_file, "
            "row_number) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(transaction_id) DO NOTHING", ctx.publish_txns)
        inserted = conn.total_changes - before

        # Rebuild the summary from clean data (also handles late-arriving rows)
        conn.execute("DELETE FROM daily_account_summary")
        conn.execute(
            "INSERT INTO daily_account_summary (account_id, txn_date, total_credits, "
            "total_debits, net_amount, txn_count) "
            "SELECT account_id, txn_date, "
            "ROUND(SUM(CASE WHEN txn_type = 'credit' THEN amount ELSE 0 END), 2), "
            "ROUND(SUM(CASE WHEN txn_type = 'debit' THEN amount ELSE 0 END), 2), "
            "ROUND(SUM(CASE WHEN txn_type = 'credit' THEN amount ELSE -amount END), 2), "
            "COUNT(*) FROM clean_transactions GROUP BY account_id, txn_date")

    ctx.metrics["rows_inserted_new"] = inserted


def reconcile(ctx):
    """Compare source and target, write a JSON report, fail if anything differs."""
    conn = ctx.conn
    checks = []

    def check(name, ok, detail):
        checks.append({"check": name, "passed": bool(ok), "detail": detail})

    rows_in = len(ctx.txn_rows)
    check("source_equals_clean_plus_rejected",
          rows_in == len(ctx.clean_txns) + len(ctx.txn_rejects),
          f"input {rows_in} = clean {len(ctx.clean_txns)} + rejected {len(ctx.txn_rejects)}")

    db_ids = {r[0] for r in conn.execute("SELECT transaction_id FROM clean_transactions")}
    missing = [t["transaction_id"] for t in ctx.clean_txns
               if t["transaction_id"] not in db_ids]
    check("all_clean_rows_present_in_target", not missing,
          f"{len(missing)} clean rows missing from target")

    summary_net = conn.execute(
        "SELECT ROUND(COALESCE(SUM(net_amount), 0), 2) FROM daily_account_summary"
    ).fetchone()[0]
    txn_net = conn.execute(
        "SELECT ROUND(COALESCE(SUM(CASE WHEN txn_type = 'credit' THEN amount "
        "ELSE -amount END), 0), 2) FROM clean_transactions").fetchone()[0]
    check("summary_net_equals_transaction_net", abs(summary_net - txn_net) < 0.01,
          f"summary {summary_net} vs transactions {txn_net}")

    summary_count = conn.execute(
        "SELECT COALESCE(SUM(txn_count), 0) FROM daily_account_summary").fetchone()[0]
    table_count = conn.execute("SELECT COUNT(*) FROM clean_transactions").fetchone()[0]
    check("summary_count_equals_transaction_count", summary_count == table_count,
          f"summary {summary_count} vs table {table_count}")

    report = {
        "run_id": ctx.run_id,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "metrics": ctx.metrics,
        "checks": checks,
        "all_passed": all(c["passed"] for c in checks),
    }
    ctx.output_dir.mkdir(parents=True, exist_ok=True)
    path = ctx.output_dir / f"reconciliation_{ctx.run_id}.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    if not report["all_passed"]:
        failed = [c["check"] for c in checks if not c["passed"]]
        raise ReconciliationError(f"reconciliation failed: {failed}")


# Order of execution. Step 5 adds retries/timeouts/status around this list.
PIPELINE = [
    ("ingest", ingest),
    ("validate_schema", validate_schema),   # critical
    ("validate_rules", validate_rules),
    ("quarantine", quarantine),
    ("transform", transform),
    ("quality_gate", quality_gate),         # critical
    ("publish", publish),
    ("reconcile", reconcile),
]
