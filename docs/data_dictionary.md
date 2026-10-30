# Data Dictionary

## Scenario
A bank has accounts. Customers make transactions (money in or out). A batch file of
transactions arrives and the pipeline validates it, rejects bad rows with a reason,
and publishes clean data. All data is synthetic.

## Naming conventions
- Tables and columns use snake_case.
- Timestamps use ISO-8601, for example 2026-10-01T10:30:00.
- Pipeline outputs carry run_id and source_file so every row is traceable.
- Deterministic IDs: account_id like ACC00001, transaction_id like TXN0000001.

## Source files

### accounts.csv (one row per account)
| column | type | required | rule |
|---|---|---|---|
| account_id | string | yes | primary key, unique, format ACC + 5 digits |
| customer_name | string | yes | synthetic name |
| account_type | string | yes | savings or current |
| status | string | yes | active, frozen or closed |
| opened_date | date | yes | ISO format YYYY-MM-DD |

### transactions.csv (one row per transaction)
| column | type | required | rule |
|---|---|---|---|
| transaction_id | string | yes | primary key, unique, format TXN + 7 digits |
| account_id | string | yes | foreign key to accounts.account_id |
| amount | decimal | yes | greater than 0 |
| txn_type | string | yes | credit (money in) or debit (money out) |
| currency | string | yes | must be INR |
| transaction_time | timestamp | yes | ISO-8601, not in the future |

## Target tables

| table | grain (one row per) | purpose |
|---|---|---|
| clean_transactions | transaction | valid transactions only, with run_id and source_file |
| rejected_records | rejected source row | bad rows with reject_reason, source_file, row_number, run_id |
| daily_account_summary | account per day | total_credits, total_debits, net_amount, txn_count |
| account_status_history | account status change | keeps history of status changes, never overwritten |
| pipeline_runs | pipeline run | run_id, start/end time, status, rows_in, rows_out, rows_rejected, failure_reason |
| task_runs | task per run | task_name, status, attempts, error_message, start/end time |

## Derived fields
- net_amount = total_credits - total_debits (per account per day)
- txn_date = date part of transaction_time

## Business rules
1. Required fields must not be empty.
2. amount must be a number greater than 0.
3. txn_type must be credit or debit.
4. account_id must exist in accounts (otherwise: invalid reference).
5. Transactions on a closed account are rejected.
6. Transactions dated in the future are rejected.
7. Same transaction_id with identical content is a duplicate: keep one, log the other.
8. Same transaction_id with different content is a conflict: reject the later row.
9. Late-arriving data is accepted and assigned to its true transaction date.
10. A missing or renamed column is a schema failure and stops the run (critical).

## Critical vs non-critical tasks
- Critical: validate_schema, quality_gate. If these fail, publish must not run.
- Non-critical: individual bad rows are quarantined and the run continues.

## Assumptions
- One currency (INR) to keep the scope small.
- Files are small enough to process on a single machine.
- Reruns of the same file must not create duplicates (idempotent load).
