"""Run the full pipeline once: python -m src.run_pipeline --accounts ... --transactions ..."""
import argparse
import logging
import sys
from pathlib import Path

from src.db import connect
from src.orchestrator import Notifier, Orchestrator, default_specs, new_run_id
from src.tasks import RunContext


def parse_pairs(items, cast):
    out = {}
    for item in items or []:
        name, _, value = item.partition(":")
        out[name] = cast(value)
    return out


def main():
    p = argparse.ArgumentParser(description="Bank transactions pipeline")
    p.add_argument("--accounts", required=True)
    p.add_argument("--transactions", required=True)
    p.add_argument("--db", default="output/bank.db")
    p.add_argument("--output-dir", default="output")
    p.add_argument("--max-reject-rate", type=float, default=0.10)
    p.add_argument("--retries", type=int, default=2, help="extra attempts per task")
    p.add_argument("--timeout", type=float, default=300.0, help="seconds per task attempt")
    p.add_argument("--retry-delay", type=float, default=1.0, help="seconds, multiplied by attempt number")
    p.add_argument("--inject-failure", action="append", metavar="TASK:COUNT",
                   help="testing: make TASK fail COUNT times before it works")
    p.add_argument("--inject-delay", action="append", metavar="TASK:SECONDS",
                   help="testing: make TASK slow")
    args = p.parse_args()

    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.StreamHandler(sys.stdout),
                  logging.FileHandler(out / "pipeline.log", encoding="utf-8")])

    conn = connect(args.db)
    ctx = RunContext(conn=conn, run_id=new_run_id(),
                     accounts_path=args.accounts, transactions_path=args.transactions,
                     output_dir=out, max_reject_rate=args.max_reject_rate)
    orchestrator = Orchestrator(
        specs=default_specs(retries=args.retries, timeout=args.timeout),
        notifier=Notifier(out / "alerts.log"),
        retry_delay=args.retry_delay,
        inject_failures=parse_pairs(args.inject_failure, int),
        inject_delays=parse_pairs(args.inject_delay, float))

    result = orchestrator.run(ctx)

    print()
    print(f"RUN {result['run_id']}: {result['status'].upper()}")
    print(f"{'task':<18}{'status':<10}{'attempts':<9}")
    for name, r in result["tasks"].items():
        print(f"{name:<18}{r['status']:<10}{r['attempts']:<9}")
    if result["failure_reason"]:
        print("failure:", result["failure_reason"])
    else:
        print("metrics:", result["metrics"])
    conn.close()
    sys.exit(0 if result["status"] == "success" else 1)


if __name__ == "__main__":
    main()
