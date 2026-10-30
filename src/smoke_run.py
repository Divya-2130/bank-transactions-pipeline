"""Temporary runner: executes the tasks in order and prints the metrics."""
import argparse
import json
import time
from datetime import datetime

from src.db import connect
from src.tasks import PIPELINE, RunContext


def main():
    parser = argparse.ArgumentParser(description="Run the pipeline once (simple version)")
    parser.add_argument("--db", default="output/bank.db")
    parser.add_argument("--accounts", required=True)
    parser.add_argument("--transactions", required=True)
    parser.add_argument("--max-reject-rate", type=float, default=0.10)
    args = parser.parse_args()

    conn = connect(args.db)
    ctx = RunContext(
        conn=conn,
        run_id=f"smoke_{datetime.now():%Y%m%dT%H%M%S}",
        accounts_path=args.accounts,
        transactions_path=args.transactions,
        max_reject_rate=args.max_reject_rate,
    )
    for name, task in PIPELINE:
        start = time.perf_counter()
        task(ctx)
        print(f"{name:<16} ok  ({time.perf_counter() - start:.2f}s)")
    print(json.dumps(ctx.metrics, indent=2))


if __name__ == "__main__":
    main()
