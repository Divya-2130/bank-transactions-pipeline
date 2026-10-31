# Bank Transactions Pipeline

An orchestrated data pipeline for synthetic bank transactions. It reads two CSV files,
validates them, quarantines bad rows with a reason, publishes clean data to SQLite, and
reconciles source against target. If a critical task fails, nothing is published.

All data is synthetic. No real bank data is used.

## What it does

1. **ingest**: read `accounts.csv` and `transactions.csv`
2. **validate_schema** (critical): columns must match exactly
3. **validate_rules**: business rules; bad rows go to a reject list with a reason
4. **quarantine**: save rejects to `rejected_records` (with source file and row number)
5. **transform**: add `txn_date`, `run_id`, `source_file`
6. **quality_gate** (critical): fail if the reject rate is above the limit or counts do not add up
7. **publish**: one all-or-nothing database transaction, safe to run twice
8. **reconcile**: compare source and target, write a JSON report

## Setup and run

Requires Python 3.9+. No external services, no credentials.

Larger run (100,000+ rows):

Other commands: `python -m src.benchmark` (performance), `python -m src.make_sample_output` (regenerates `sample_output/`).

## Repository layout

| path | purpose |
|---|---|
| `src/schemas.py` | columns, allowed values, reject reasons, critical task list |
| `src/db.py` | SQLite schema |
| `src/tasks.py` | the pipeline tasks |
| `src/orchestrator.py` | dependencies, retries, timeouts, run status, alerts, publish gate |
| `src/run_pipeline.py` | command-line entry point |
| `src/generate_data.py` | reproducible synthetic data generator (fixed seed) |
| `src/verify_labels.py` | compares rejects with the generator's answer key |
| `src/benchmark.py`, `src/show_runs.py`, `src/make_sample_output.py` | performance, status viewer, evidence generator |
| `tests/` | pytest suite |
| `data/sample/`, `data/sample_labels/` | small sample input and its separate answer key |
| `sample_output/` | committed example results: reconciliation, rejects, queries, run status |
| `docs/` | data dictionary, design notes, performance results, test results |
| `ai-usage/` | prompt history and AI-use reflection |

## Data model, rules and naming

See `docs/data_dictionary.md` for tables, keys, types, nullability, grain and all business rules.
Naming: snake_case, ISO-8601 timestamps, deterministic IDs (`ACC00001`, `TXN0000001`),
`run_id` and `source_file` on pipeline outputs.

## Orchestration behaviour

- **Dependencies:** a task runs only if everything it depends on succeeded; otherwise it is `skipped`.
- **Publish gate:** `publish` also requires every critical task (`validate_schema`, `quality_gate`) to have succeeded.
- **Retries:** transient errors are retried (default 2 extra attempts, growing delay). Schema, quality-gate and reconciliation failures are not retried because they would fail the same way.
- **Timeouts:** each task attempt has a time limit (default 300 s). A timeout fails the task and is not retried. Limitation: a Python thread cannot be force-killed.
- **Run status:** `pipeline_runs` (one row per run) and `task_runs` (one row per task: status, attempts, error).
- **Alerts:** a console line and a JSON line in `output/alerts.log`. A real deployment would call email or Slack at the same place.

## Idempotency, restart and backfill

- Transactions load with `ON CONFLICT DO NOTHING`, accounts with an upsert, so loading the same file twice adds nothing.
- Rejects for a file are replaced on every run, so they are never doubled.
- Publish is one database transaction: all of it succeeds or none of it does.
- **Restart:** after a failed run, fix the cause and run the same file again.
- **Backfill:** run an older file. Late rows are accepted and land on their true `txn_date`, and only the affected days of the daily summary are recomputed.
- Same ID and same content in a later file is a `duplicate_transaction`. Same ID and different content is a `conflicting_duplicate`; the first version wins.

## Testing

`python -m pytest` runs 53 tests; results are saved in `docs/test_results.txt`. They cover:
happy path, empty input, zero-byte file, malformed rows, every required field empty, invalid values,
duplicates and conflicts, schema change, invalid account reference, closed accounts, late and
out-of-order data, retries, timeouts, the quality gate, all-or-nothing publish, reruns, restarts,
and end-to-end runs compared with the generator's answer key.

## Evidence of correctness

`sample_output/sample_queries.md` shows these checks on the sample data: source rows = clean + rejected, no duplicate IDs,
no orphan account references, no transactions on closed accounts, the daily summary equals the transaction totals,
a rerun adds nothing, and the rejects match the answer key exactly. Each run also writes a reconciliation report.

## Performance

Measured on my laptop (Windows 11, 12 CPU threads, Python 3.12, SQLite 3.45), full details in `docs/performance_results.md`.

- A first load of 100,000 rows took 3.00 s (about 33,000 rows per second). 200,000 rows took 7.69 s.
- The slowest task is `publish` (1.96 s of 3.00 s at 100,000 rows). Throughput drops as the input grows (about 48,000 rows per second at 10,000 rows and 26,000 at 200,000), and I did not investigate why.
- Daily load: a 1,000-row file on top of a 190,000-row history. `publish` went from 1.649 s to 0.176 s (9.3x faster) and the whole run from 2.381 s to 0.862 s. The daily summary table was identical in both modes.
- Each size was measured once, so small differences are noise. The daily-load comparison uses the median of 3 runs.

Optimization: the daily summary is now refreshed only for the (account, date) pairs in the new batch instead of being rebuilt from all history. A test and the benchmark both check that the result is identical to a full rebuild.

## AI use

See `ai-usage/prompts.md` (all prompts) and `ai-usage/reflection.md` (where AI helped and what I reviewed, changed and validated).

## Assumptions

- One currency (INR). Files are small enough to hold in memory. Timestamps with an offset are converted to UTC.
- "Now" for the future-date rule is the time of the run.
- The reject-rate limit of 10% is a default and can be changed with `--max-reject-rate`.
- The committed sample is 50% bad on purpose, so the sample run uses a 60% limit.
- The first version of a transaction wins when the same ID arrives again with different content.

## Known limitations

- The whole input is read into memory, and `validate_rules` loads all existing transaction IDs on every run.
- Amounts are stored as SQLite `REAL`; a real system would use integer paise.
- Timed-out tasks are not killed, only abandoned (threads cannot be force-killed).
- `account_status_history` is keyed by the run start second, so two status changes for one account in the same second would collapse.
- Alerts go to a console and a file, not to a real channel.
- No scheduler (cron or similar); the pipeline is started manually.

## Possible next steps

Stream the file in chunks, look up only the incoming IDs, store money as integer paise, run tasks in separate processes for hard timeouts, add a scheduler, and send real alerts.
