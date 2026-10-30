"""Simple performance benchmark for the pipeline.

Run:  python -m src.benchmark
Writes the results table to docs/performance_results.md

Two measurements:
1. Scaling: a full first load at several input sizes, with per-task timings.
2. Daily load: a small file arriving on top of a large history, comparing the
   old full summary rebuild with the new incremental refresh.
"""
import argparse
import csv
import os
import platform
import random
import shutil
import sqlite3
import statistics
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path

from src.db import connect
from src.schemas import TRANSACTION_COLUMNS
from src.tasks import PIPELINE, RunContext

ROOT = Path(__file__).resolve().parents[1]
TASK_NAMES = [name for name, _ in PIPELINE]


def generate(out_dir, rows, accounts):
    out_dir = Path(out_dir)
    subprocess.run(
        [sys.executable, "-m", "src.generate_data",
         "--out-dir", str(out_dir), "--labels-dir", str(out_dir / "labels"),
         "--accounts", str(accounts), "--transactions", str(rows), "--seed", "42"],
        cwd=ROOT, check=True, capture_output=True)


def run_tasks(db_path, accounts_path, txn_path, out_dir, summary_mode="incremental"):
    """Run every task in order and time each one."""
    conn = connect(db_path)
    ctx = RunContext(conn=conn, run_id=f"bench_{time.time_ns()}",
                     accounts_path=accounts_path, transactions_path=txn_path,
                     output_dir=out_dir, summary_mode=summary_mode, max_reject_rate=0.10)
    timings = {}
    for name, task in PIPELINE:
        start = time.perf_counter()
        task(ctx)
        timings[name] = time.perf_counter() - start
    conn.close()
    return timings, ctx.metrics


def make_daily_file(accounts_path, out_path, n, seed=99):
    """A small file of brand-new, valid transactions (new IDs, open accounts)."""
    rng = random.Random(seed)
    with open(accounts_path, newline="", encoding="utf-8") as f:
        open_ids = [r["account_id"] for r in csv.DictReader(f) if r["status"] != "closed"]
    start = datetime(2026, 10, 1)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(TRANSACTION_COLUMNS)
        for i in range(n):
            ts = start + timedelta(seconds=rng.randint(0, 28 * 86400))
            writer.writerow([f"TXN{9000000 + i:07d}", rng.choice(open_ids),
                             f"{rng.uniform(10, 50000):.2f}",
                             rng.choice(["credit", "debit"]), "INR", ts.isoformat()])


def summary_rows(db_path):
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT * FROM daily_account_summary ORDER BY account_id, txn_date").fetchall()
    conn.close()
    return rows


def run_scaling(work, sizes):
    results, bases = [], {}
    for size in sizes:
        print(f"[scaling] {size:,} rows: generating...", flush=True)
        folder = work / f"n{size}"
        folder.mkdir()
        generate(folder, size, max(20, size // 50))
        db = folder / "bench.db"
        timings, metrics = run_tasks(db, folder / "accounts.csv",
                                     folder / "transactions.csv", folder / "out")
        total = sum(timings.values())
        print(f"[scaling] {size:,} rows: {total:.2f}s", flush=True)
        results.append({"timings": timings, "metrics": metrics, "total": total})
        bases[size] = (db, folder / "accounts.csv")
    return results, bases


def run_daily_scenario(work, base, daily_rows, repeats):
    base_db, accounts_path = base
    daily = work / "daily.csv"
    make_daily_file(accounts_path, daily, daily_rows)
    runs = {"full": [], "incremental": []}
    final = {}
    inserted = {}
    for rep in range(repeats):
        for mode in ("full", "incremental"):
            db = work / f"scenario_{mode}.db"
            shutil.copy2(base_db, db)  # every measurement starts from the same history
            timings, metrics = run_tasks(db, accounts_path, daily, work / "daily_out", mode)
            runs[mode].append(timings)
            inserted[mode] = metrics.get("rows_inserted_new")
            final[mode] = summary_rows(db)
            print(f"[daily load] repeat {rep + 1}/{repeats} {mode}: "
                  f"publish {timings['publish']:.3f}s", flush=True)
    return runs, final["full"] == final["incremental"], inserted


def median(runs, task):
    return statistics.median(r[task] for r in runs)


def build_report(sizes, scaling, daily_rows, history_rows, runs, same, inserted, repeats):
    out = ["# Performance results", "",
           f"- Machine: {platform.platform()}, {os.cpu_count()} CPU threads",
           f"- Python {platform.python_version()}, SQLite {sqlite3.sqlite_version}",
           f"- Generated {datetime.now().isoformat(timespec='seconds')}, seed 42", "",
           "## 1. Full first load, by input size", "",
           "Seconds per task. Each size is one run on a fresh database.", "",
           "| rows | total (s) | rows/sec | " + " | ".join(TASK_NAMES) + " |",
           "|---|---|---|" + "---|" * len(TASK_NAMES)]
    for r in scaling:
        rows_in = r["metrics"]["rows_in"]
        cells = " | ".join(f"{r['timings'][n]:.2f}" for n in TASK_NAMES)
        out.append(f"| {rows_in:,} | {r['total']:.2f} | {rows_in / r['total']:,.0f} | {cells} |")
    last = scaling[-1]
    slowest = max(last["timings"], key=last["timings"].get)
    out += ["", f"Slowest task at {last['metrics']['rows_in']:,} rows: **{slowest}** "
                f"({last['timings'][slowest]:.2f}s of {last['total']:.2f}s).", "",
            "## 2. Daily load on top of a large history", "",
            f"History already loaded: {history_rows:,} rows. New file: {daily_rows:,} rows. "
            f"Median of {repeats} runs, each on a fresh copy of the same database.", "",
            "| summary mode | publish (s) | validate_rules (s) | reconcile (s) | total (s) |",
            "|---|---|---|---|---|"]
    for mode, label in (("full", "full rebuild (before)"), ("incremental", "incremental (after)")):
        rs = runs[mode]
        total = statistics.median(sum(r.values()) for r in rs)
        out.append(f"| {label} | {median(rs, 'publish'):.3f} | {median(rs, 'validate_rules'):.3f} "
                   f"| {median(rs, 'reconcile'):.3f} | {total:.3f} |")
    before, after = median(runs["full"], "publish"), median(runs["incremental"], "publish")
    out += ["", f"Publish speed-up: **{before / after:.1f}x** ({before:.3f}s to {after:.3f}s).",
            f"New rows inserted in the daily load: {inserted}.",
            f"Summary table identical in both modes: **{'YES' if same else 'NO - INVESTIGATE'}**.", ""]
    return "\n".join(out)


def main():
    parser = argparse.ArgumentParser(description="Pipeline benchmark")
    parser.add_argument("--sizes", default="10000,50000,100000,200000")
    parser.add_argument("--daily-rows", type=int, default=1000)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--report", default="docs/performance_results.md")
    args = parser.parse_args()

    sizes = sorted(int(x) for x in args.sizes.split(","))
    work = Path(tempfile.mkdtemp(prefix="bank_bench_"))
    try:
        scaling, bases = run_scaling(work, sizes)
        history = sizes[-1]
        runs, same, inserted = run_daily_scenario(
            work, bases[history], args.daily_rows, args.repeats)
        report = build_report(sizes, scaling, args.daily_rows,
                              scaling[-1]["metrics"]["rows_clean"], runs, same,
                              inserted, args.repeats)
    finally:
        shutil.rmtree(work, ignore_errors=True)

    path = Path(args.report)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report, encoding="utf-8")
    print("\n" + report)
    print(f"Saved to {path}")


if __name__ == "__main__":
    main()
