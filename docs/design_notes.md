# Design and trade-off note

## Scope
A complete, tested vertical slice for one data domain (bank transactions), run locally.
I chose depth (rules, orchestration, tests, evidence) over breadth (more tables, a UI).

## Key decisions

| decision | why | trade-off |
|---|---|---|
| Small custom orchestrator instead of Airflow or Prefect | the brief asks for dependencies, retries, timeouts, status and alerts; a custom one is easy to run from a clean machine and easy to explain line by line | no scheduler, no web UI, no distributed workers |
| SQLite | zero setup, transactional, free and local | single writer, `REAL` for money, not for large scale |
| Reject bad rows instead of failing the whole run | one bad row should not block 99,999 good ones; rejects are stored with reason, file and row number | needs a quality gate so a mostly bad file is still stopped |
| Quality gate on the reject rate | a file that is mostly bad usually means an upstream problem, so it should not be published | the threshold (10%) is a judgement call and is configurable |
| Two critical tasks and a gated publish | the brief says prevent publication when critical upstream tasks fail | publish is blocked even for failures that might be harmless; the operator reruns |
| No retry for schema, quality-gate and reconciliation failures | they fail identically every time | a flaky check would not be retried |
| No retry after a timeout | a thread cannot be killed, so a retry could race the abandoned attempt | a slow-but-working task fails instead of recovering |
| Idempotent publish (conflict-ignore, upserts, atomic transaction) | reruns and restarts must not create duplicates | late corrections to an existing transaction are rejected as conflicts, not applied |
| First version wins on conflicting duplicates | simple and deterministic; the conflict is recorded in rejects | the first version might be the wrong one |
| Accounts upsert, with status history in its own table | the brief says keep history instead of overwriting silently | history is only recorded when a status change is seen in a loaded file |
| Incremental daily summary | cost grows with the new batch, not with history | extra code path, so it is tested against the full rebuild |
| Answer key separate from the input | the brief asks for it; the pipeline never sees the labels | none |

## Reject policy
Every reject keeps the raw row as JSON, the source file, the row number (counted from 1, header excluded),
the reason and the run ID, so any rejected row can be traced to its exact line.
Row-level problems are rejected. File-level problems (columns changed) stop the run.

## How I know it works
Unit and integration tests (see `docs/test_results.txt`), an end-to-end test that compares the pipeline with a generator answer key,
reconciliation checks on every run, and the committed evidence in `sample_output/`.

## Performance
[FILL IN: two or three sentences in your own words, using the numbers in `docs/performance_results.md`.]
