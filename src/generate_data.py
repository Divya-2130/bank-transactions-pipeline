"""Synthetic bank data generator (reproducible with --seed).

Writes accounts.csv and transactions.csv (the inputs) to --out-dir, and the
expected-answer labels to --labels-dir. Labels are kept separate from inputs.

row_number = position of the row in transactions.csv, counting from 1
(the header line is not counted).
"""
import argparse
import csv
import json
import random
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path

from src.schemas import (
    ACCOUNT_COLUMNS,
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
    VALID_ACCOUNT_TYPES,
)

FIRST_NAMES = ["Asha", "Ravi", "Meena", "Kiran", "Sneha", "Arjun", "Lakshmi",
               "Vikram", "Priya", "Rahul", "Anita", "Suresh", "Divya", "Manoj"]
LAST_NAMES = ["Reddy", "Sharma", "Rao", "Naidu", "Verma", "Iyer", "Gupta",
              "Das", "Patel", "Singh", "Kumar", "Nair", "Mehta", "Joshi"]

# Kinds of deliberately bad rows (each one is labelled in the answer key)
BAD_KINDS = [
    REJECT_MISSING_FIELD,
    REJECT_BAD_AMOUNT,
    REJECT_BAD_TXN_TYPE,
    REJECT_BAD_CURRENCY,
    REJECT_BAD_TIMESTAMP,
    REJECT_FUTURE_TIMESTAMP,
    REJECT_INVALID_ACCOUNT,
    REJECT_CLOSED_ACCOUNT,
    REJECT_DUPLICATE,
    REJECT_CONFLICT,
]


def make_accounts(rng, n):
    accounts = []
    for i in range(1, n + 1):
        accounts.append({
            "account_id": f"ACC{i:05d}",
            "customer_name": f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}",
            "account_type": rng.choice(sorted(VALID_ACCOUNT_TYPES)),
            "status": rng.choices(["active", "frozen", "closed"], weights=[80, 10, 10])[0],
            "opened_date": (date(2020, 1, 1) + timedelta(days=rng.randint(0, 1800))).isoformat(),
        })
    # Guarantee at least one closed and one non-closed account
    if not any(a["status"] == "closed" for a in accounts):
        accounts[-1]["status"] = "closed"
    if not any(a["status"] != "closed" for a in accounts):
        accounts[0]["status"] = "active"
    return accounts


def random_time(rng):
    start = datetime(2026, 1, 1)
    seconds = rng.randint(0, 302 * 86400)  # up to about 29 Oct 2026
    return (start + timedelta(seconds=seconds)).isoformat()


def make_transactions(rng, accounts, total, bad_rate):
    open_ids = [a["account_id"] for a in accounts if a["status"] != "closed"]
    closed_ids = [a["account_id"] for a in accounts if a["status"] == "closed"]

    per_kind = max(1, int(total * bad_rate) // len(BAD_KINDS))
    n_bad = per_kind * len(BAD_KINDS)
    n_valid = total - n_bad
    if n_valid < 1:
        raise ValueError("--transactions is too small for this --bad-rate")

    counter = 0
    seq = 0
    rows = []

    def next_id():
        nonlocal counter
        counter += 1
        return f"TXN{counter:07d}"

    def valid_data():
        return {
            "transaction_id": next_id(),
            "account_id": rng.choice(open_ids),
            "amount": f"{rng.uniform(10, 50000):.2f}",
            "txn_type": rng.choice(["credit", "debit"]),
            "currency": "INR",
            "transaction_time": random_time(rng),
        }

    def add(data, label, key):
        nonlocal seq
        seq += 1
        row = {"data": data, "label": label, "key": key, "seq": seq}
        rows.append(row)
        return row

    valid_rows = [add(valid_data(), None, rng.random()) for _ in range(n_valid)]

    for kind in BAD_KINDS:
        for _ in range(per_kind):
            if kind in (REJECT_DUPLICATE, REJECT_CONFLICT):
                orig = rng.choice(valid_rows)
                data = dict(orig["data"])
                if kind == REJECT_CONFLICT:
                    data["amount"] = f"{float(data['amount']) + 1.00:.2f}"
                # the copy always arrives AFTER the original
                key = orig["key"] + rng.random() * (1 - orig["key"])
                add(data, kind, key)
                continue

            data = valid_data()
            if kind == REJECT_MISSING_FIELD:
                data["amount"] = ""
            elif kind == REJECT_BAD_AMOUNT:
                data["amount"] = rng.choice(["-250.00", "0.00", "abc"])
            elif kind == REJECT_BAD_TXN_TYPE:
                data["txn_type"] = "transfer"
            elif kind == REJECT_BAD_CURRENCY:
                data["currency"] = "USD"
            elif kind == REJECT_BAD_TIMESTAMP:
                data["transaction_time"] = "31/13/2026 25:61"
            elif kind == REJECT_FUTURE_TIMESTAMP:
                data["transaction_time"] = "2031-05-01T09:00:00"
            elif kind == REJECT_INVALID_ACCOUNT:
                data["account_id"] = "ACC99999"
            elif kind == REJECT_CLOSED_ACCOUNT:
                data["account_id"] = rng.choice(closed_ids)
            add(data, kind, rng.random())

    # Shuffle into an "out-of-order" arrival order (duplicates stay after originals)
    rows.sort(key=lambda r: (r["key"], r["seq"]))
    return rows, n_valid


def write_csv(path, columns, records):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows(records)


def main():
    parser = argparse.ArgumentParser(description="Generate synthetic bank data")
    parser.add_argument("--out-dir", default="data/generated")
    parser.add_argument("--labels-dir", default="data/generated_labels")
    parser.add_argument("--accounts", type=int, default=1000)
    parser.add_argument("--transactions", type=int, default=100000)
    parser.add_argument("--bad-rate", type=float, default=0.05)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    if args.accounts < 2 or args.accounts > 99998:
        raise SystemExit("--accounts must be between 2 and 99998")

    rng = random.Random(args.seed)
    out_dir, labels_dir = Path(args.out_dir), Path(args.labels_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    labels_dir.mkdir(parents=True, exist_ok=True)

    accounts = make_accounts(rng, args.accounts)
    rows, n_valid = make_transactions(rng, accounts, args.transactions, args.bad_rate)

    write_csv(out_dir / "accounts.csv", ACCOUNT_COLUMNS, accounts)
    write_csv(out_dir / "transactions.csv", TRANSACTION_COLUMNS, [r["data"] for r in rows])

    # Answer key: kept OUTSIDE the input folder
    labels = [
        {
            "row_number": i,
            "transaction_id": r["data"]["transaction_id"],
            "expected_reject_reason": r["label"],
        }
        for i, r in enumerate(rows, start=1)
        if r["label"] is not None
    ]
    write_csv(labels_dir / "expected_rejects.csv",
              ["row_number", "transaction_id", "expected_reject_reason"], labels)

    summary = {
        "seed": args.seed,
        "accounts": len(accounts),
        "total_rows": len(rows),
        "expected_clean_rows": n_valid,
        "expected_rejected_rows": len(labels),
        "expected_rejects_by_reason": dict(Counter(l["expected_reject_reason"] for l in labels)),
    }
    with open(labels_dir / "expected_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
