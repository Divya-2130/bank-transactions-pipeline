# Performance results

- Machine: Windows-11-10.0.26200-SP0, 12 CPU threads
- Python 3.12.4, SQLite 3.45.3
- Generated 2026-10-30T13:00:08, seed 42

## 1. Full first load, by input size

Seconds per task. Each size is one run on a fresh database.

| rows | total (s) | rows/sec | ingest | validate_schema | validate_rules | quarantine | transform | quality_gate | publish | reconcile |
|---|---|---|---|---|---|---|---|---|---|---|
| 10,000 | 0.21 | 48,097 | 0.06 | 0.00 | 0.05 | 0.01 | 0.00 | 0.00 | 0.07 | 0.01 |
| 50,000 | 1.20 | 41,674 | 0.15 | 0.00 | 0.28 | 0.02 | 0.02 | 0.00 | 0.68 | 0.05 |
| 100,000 | 3.00 | 33,387 | 0.26 | 0.00 | 0.60 | 0.04 | 0.04 | 0.00 | 1.96 | 0.10 |
| 200,000 | 7.69 | 26,008 | 0.56 | 0.00 | 1.13 | 0.04 | 0.06 | 0.00 | 5.70 | 0.20 |

Slowest task at 200,000 rows: **publish** (5.70s of 7.69s).

## 2. Daily load on top of a large history

History already loaded: 190,000 rows. New file: 1,000 rows. Median of 3 runs, each on a fresh copy of the same database.

| summary mode | publish (s) | validate_rules (s) | reconcile (s) | total (s) |
|---|---|---|---|---|
| full rebuild (before) | 1.649 | 0.501 | 0.177 | 2.381 |
| incremental (after) | 0.176 | 0.496 | 0.166 | 0.862 |

Publish speed-up: **9.3x** (1.649s to 0.176s).
New rows inserted in the daily load: {'full': 1000, 'incremental': 1000}.
Summary table identical in both modes: **YES**.
