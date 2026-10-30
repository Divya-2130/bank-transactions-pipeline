"""Show recent runs, their tasks, and table row counts."""
import argparse
import sqlite3


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--db", required=True)
    p.add_argument("--last", type=int, default=3)
    args = p.parse_args()

    conn = sqlite3.connect(args.db)
    runs = conn.execute(
        "SELECT run_id, status, rows_in, rows_clean, rows_rejected, failure_reason "
        "FROM pipeline_runs ORDER BY started_at DESC, rowid DESC LIMIT ?", (args.last,)).fetchall()
    for run_id, status, rin, rclean, rrej, reason in runs:
        print(f"\n{run_id}  status={status}  in={rin} clean={rclean} rejected={rrej}")
        if reason:
            print(f"  failure_reason: {reason}")
        for name, st, att, err in conn.execute(
                "SELECT task_name, status, attempts, error_message FROM task_runs "
                "WHERE run_id = ? ORDER BY id", (run_id,)):
            line = f"  {name:<16}{st:<9}attempts={att}"
            print(line + (f"  ({err[:70]})" if err else ""))

    print("\nrow counts:")
    for table in ["clean_transactions", "rejected_records", "daily_account_summary",
                  "account_status_history", "pipeline_runs", "task_runs"]:
        n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"  {table:<24}{n}")


if __name__ == "__main__":
    main()
