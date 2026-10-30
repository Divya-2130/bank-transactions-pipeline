"""Schema definitions and constants shared across the pipeline."""

ACCOUNT_COLUMNS = [
    "account_id",
    "customer_name",
    "account_type",
    "status",
    "opened_date",
]

TRANSACTION_COLUMNS = [
    "transaction_id",
    "account_id",
    "amount",
    "txn_type",
    "currency",
    "transaction_time",
]

VALID_ACCOUNT_TYPES = {"savings", "current"}
VALID_ACCOUNT_STATUSES = {"active", "frozen", "closed"}
VALID_TXN_TYPES = {"credit", "debit"}
VALID_CURRENCIES = {"INR"}

ACCOUNT_ID_PATTERN = r"^ACC\d{5}$"
TRANSACTION_ID_PATTERN = r"^TXN\d{7}$"

# Tasks that must succeed before publishing is allowed
CRITICAL_TASKS = ["validate_schema", "quality_gate"]

# Reject reasons (kept as constants so tests and code use identical text)
REJECT_MISSING_FIELD = "missing_required_field"
REJECT_BAD_AMOUNT = "invalid_amount"
REJECT_BAD_TXN_TYPE = "invalid_txn_type"
REJECT_BAD_CURRENCY = "invalid_currency"
REJECT_BAD_TIMESTAMP = "invalid_timestamp"
REJECT_FUTURE_TIMESTAMP = "future_timestamp"
REJECT_INVALID_ACCOUNT = "invalid_account_reference"
REJECT_CLOSED_ACCOUNT = "closed_account"
REJECT_DUPLICATE = "duplicate_transaction"
REJECT_CONFLICT = "conflicting_duplicate"
