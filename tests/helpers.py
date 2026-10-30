"""Shared helpers for the tests."""
import csv
import json
from datetime import datetime
from pathlib import Path

from src.db import connect
from src.orchestrator import Notifier, Orchestrator, default_specs, new_run_id
from src.schemas import ACCOUNT_COLUMNS, TRANSACTION_COLUMNS
from src.tasks import RunContext

ROOT = Path(__file__).resolve().parents[1]
AS_OF = datetime(2026, 10, 30, 12, 0, 0)  # fixed "now" so tests never depend on today's date

ACCOUNTS = [
    {"account_id": "ACC00001", "customer_name": "Asha Reddy", "account_type": "savings",
     "status": "active", "opened_date": "2024-01-15"},
    {"account_id": "ACC00002", "customer_name": "Ravi Sharma", "account_type": "current",
     "status": "frozen", "opened_date": "2023-06-01"},
    {"account_id": "ACC00003", "customer_name": "Meena Rao", "account_type": "savings",
     "status": "closed", "opened_date": "2022-03-20"},
]


def txn(transaction_id="TXN0000001", **overrides):
    """A valid transaction row; override any field to make it bad."""
    row = {
        "transaction_id": transaction_id,
        "account_id": "ACC00001",
        "amount": "100.00",
        "txn_type": "credit",
        "currency": "INR",
        "transaction_time": "2026-10-01T10:00:00",
    }
    row.update(overrides)
    return row


def write_csv(path, columns, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    return Path(path)


def write_raw(path, text):
    Path(path).write_text(text, encoding="utf-8")
    return Path(path)


class Run:
    """The outcome of one pipeline run, with small query helpers."""

    def __init__(self, result, conn, ctx, out_dir):
        self.result = result
        self.conn = conn
        self.ctx = ctx
        self.out_dir = Path(out_dir)

    def rows(self, sql, params=()):
        return self.conn.execute(sql, params).fetchall()

    def value(self, sql, params=()):
        return self.conn.execute(sql, params).fetchone()[0]

    def count(self, table):
        return self.value(f"SELECT COUNT(*) FROM {table}")

    def task(self, name):
        return self.result["tasks"][name]

    def alerts(self):
        path = self.out_dir / "alerts.log"
        if not path.exists():
            return []
        lines = path.read_text(encoding="utf-8").splitlines()
        return [json.loads(line) for line in lines if line.strip()]


def run_pipeline(tmp_path, transactions=None, accounts=None, txn_path=None, acct_path=None,
                 txn_name="transactions.csv", acct_name="accounts.csv", db_name="bank.db",
                 run_id=None, started_at=None, as_of=AS_OF, max_reject_rate=1.0, summary_mode="incremental",
                 retries=2, timeout=30.0, retry_delay=0.0,
                 inject_failures=None, inject_delays=None):
    tmp_path = Path(tmp_path)
    if acct_path is None:
        acct_path = write_csv(tmp_path / acct_name, ACCOUNT_COLUMNS,
                              ACCOUNTS if accounts is None else accounts)
    if txn_path is None:
        txn_path = write_csv(tmp_path / txn_name, TRANSACTION_COLUMNS, transactions or [])

    out_dir = tmp_path / "out"
    conn = connect(tmp_path / db_name)
    extra = {"started_at": started_at} if started_at else {}
    ctx = RunContext(conn=conn, run_id=run_id or new_run_id(),
                     accounts_path=acct_path, transactions_path=txn_path,
                     output_dir=out_dir, max_reject_rate=max_reject_rate,
                     as_of=as_of, summary_mode=summary_mode, **extra)
    orchestrator = Orchestrator(
        specs=default_specs(retries=retries, timeout=timeout),
        notifier=Notifier(out_dir / "alerts.log"),
        retry_delay=retry_delay,
        inject_failures=inject_failures,
        inject_delays=inject_delays)
    result = orchestrator.run(ctx)
    return Run(result, conn, ctx, out_dir)
