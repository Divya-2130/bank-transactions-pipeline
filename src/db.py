"""SQLite connection and schema creation."""
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    account_id TEXT PRIMARY KEY,
    customer_name TEXT NOT NULL,
    account_type TEXT NOT NULL,
    status TEXT NOT NULL,
    opened_date TEXT NOT NULL,
    run_id TEXT NOT NULL,
    source_file TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS account_status_history (
    account_id TEXT NOT NULL,
    status TEXT NOT NULL,
    effective_at TEXT NOT NULL,
    run_id TEXT NOT NULL,
    PRIMARY KEY (account_id, effective_at)
);

CREATE TABLE IF NOT EXISTS clean_transactions (
    transaction_id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    amount REAL NOT NULL CHECK (amount > 0),
    txn_type TEXT NOT NULL CHECK (txn_type IN ('credit', 'debit')),
    currency TEXT NOT NULL,
    transaction_time TEXT NOT NULL,
    txn_date TEXT NOT NULL,
    run_id TEXT NOT NULL,
    source_file TEXT NOT NULL,
    row_number INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_clean_txn_account_date
    ON clean_transactions (account_id, txn_date);

CREATE TABLE IF NOT EXISTS rejected_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    record_type TEXT NOT NULL,
    source_file TEXT NOT NULL,
    row_number INTEGER NOT NULL,
    record_key TEXT,
    reject_reason TEXT NOT NULL,
    raw_record TEXT NOT NULL,
    run_id TEXT NOT NULL,
    rejected_at TEXT NOT NULL,
    UNIQUE (record_type, source_file, row_number)
);

CREATE TABLE IF NOT EXISTS daily_account_summary (
    account_id TEXT NOT NULL,
    txn_date TEXT NOT NULL,
    total_credits REAL NOT NULL,
    total_debits REAL NOT NULL,
    net_amount REAL NOT NULL,
    txn_count INTEGER NOT NULL,
    PRIMARY KEY (account_id, txn_date)
);

CREATE TABLE IF NOT EXISTS pipeline_runs (
    run_id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    status TEXT NOT NULL,
    accounts_file TEXT,
    transactions_file TEXT,
    rows_in INTEGER,
    rows_clean INTEGER,
    rows_rejected INTEGER,
    failure_reason TEXT
);

CREATE TABLE IF NOT EXISTS task_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    task_name TEXT NOT NULL,
    status TEXT NOT NULL,
    attempts INTEGER NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    error_message TEXT
);
"""


def connect(db_path):
    """Open (and create if needed) the SQLite database with all tables."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.executescript(SCHEMA)
    conn.commit()
    return conn
