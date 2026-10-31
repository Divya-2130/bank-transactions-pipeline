# Performance results

- Machine: Windows-11-10.0.26200-SP0, 12 CPU threads
- Python 3.12.4, SQLite 3.45.3
- Generated 2026-10-31T11:43:19, seed 42

## 1. Full first load, by input size

Seconds per task. Each size is one run on a fresh database.

| rows | total (s) | rows/sec | ingest | validate_schema | validate_rules | quarantine | transform | quality_gate | publish | reconcile |
|---|---|---|---|---|---|---|---|---|---|---|
| 10,000 | 0.23 | 43,009 | 0.06 | 0.00 | 0.07 | 0.01 | 0.00 | 0.00 | 0.09 | 0.01 |
| 50,000 | 1.03 | 48,699 | 0.15 | 0.00 | 0.32 | 0.03 | 0.02 | 0.00 | 0.48 | 0.03 |
| 100,000 | 2.16 | 46,270 | 0.25 | 0.00 | 0.63 | 0.02 | 0.03 | 0.00 | 1.16 | 0.07 |
| 200,000 | 4.95 | 40,368 | 0.56 | 0.00 | 1.15 | 0.04 | 0.07 | 0.00 | 2.98 | 0.16 |

Slowest task at 200,000 rows: **publish** (2.98s of 4.95s).

## 2. Daily load on top of a large history

History already loaded: 190,000 rows. New file: 1,000 rows. Median of 3 runs, each on a fresh copy of the same database.

| summary mode | publish (s) | validate_rules (s) | reconcile (s) | total (s) |
|---|---|---|---|---|
| full rebuild (before) | 0.717 | 0.524 | 0.128 | 1.387 |
| incremental (after) | 0.193 | 0.511 | 0.148 | 0.867 |

Publish speed-up: **3.7x** (0.717s to 0.193s).
New rows inserted in the daily load: {'full': 1000, 'incremental': 1000}.
Summary table identical in both modes: **YES**.
