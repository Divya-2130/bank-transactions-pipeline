"""End-to-end tests: generator -> pipeline -> compare with the answer key."""
import csv
import hashlib
import json
import subprocess
import sys

from tests.helpers import ROOT


def read_expected(path):
    with open(path, newline="", encoding="utf-8") as f:
        return {int(r["row_number"]): r["expected_reject_reason"] for r in csv.DictReader(f)}


def actual_rejects(run):
    return dict(run.rows(
        "SELECT row_number, reject_reason FROM rejected_records "
        "WHERE record_type = 'transaction' AND source_file = 'transactions.csv'"))


def generate(out_dir, labels_dir, accounts, transactions, bad_rate, seed):
    subprocess.run(
        [sys.executable, "-m", "src.generate_data",
         "--out-dir", str(out_dir), "--labels-dir", str(labels_dir),
         "--accounts", str(accounts), "--transactions", str(transactions),
         "--bad-rate", str(bad_rate), "--seed", str(seed)],
        cwd=ROOT, check=True, capture_output=True)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_committed_sample_matches_its_answer_key(pipeline):
    run = pipeline(acct_path=ROOT / "data/sample/accounts.csv",
                   txn_path=ROOT / "data/sample/transactions.csv",
                   max_reject_rate=0.6)
    expected = read_expected(ROOT / "data/sample_labels/expected_rejects.csv")
    summary = json.loads((ROOT / "data/sample_labels/expected_summary.json").read_text())
    assert run.result["status"] == "success"
    assert actual_rejects(run) == expected
    assert run.count("clean_transactions") == summary["expected_clean_rows"]


def test_generated_dataset_matches_its_answer_key_and_reruns_safely(pipeline, tmp_path):
    data, labels = tmp_path / "gen", tmp_path / "gen_labels"
    generate(data, labels, accounts=200, transactions=5000, bad_rate=0.08, seed=7)
    kwargs = dict(acct_path=data / "accounts.csv", txn_path=data / "transactions.csv",
                  max_reject_rate=0.10)
    first = pipeline(**kwargs)
    summary = json.loads((labels / "expected_summary.json").read_text())
    assert first.result["status"] == "success"
    assert actual_rejects(first) == read_expected(labels / "expected_rejects.csv")
    assert first.count("clean_transactions") == summary["expected_clean_rows"]
    assert first.count("clean_transactions") + first.count("rejected_records") == 5000
    second = pipeline(**kwargs)
    assert second.ctx.metrics["rows_inserted_new"] == 0
    assert second.count("clean_transactions") == summary["expected_clean_rows"]


def test_generator_is_reproducible_for_a_fixed_seed(tmp_path):
    generate(tmp_path / "a", tmp_path / "a_l", 20, 100, 0.2, seed=5)
    generate(tmp_path / "b", tmp_path / "b_l", 20, 100, 0.2, seed=5)
    generate(tmp_path / "c", tmp_path / "c_l", 20, 100, 0.2, seed=6)
    assert sha(tmp_path / "a" / "transactions.csv") == sha(tmp_path / "b" / "transactions.csv")
    assert sha(tmp_path / "a" / "transactions.csv") != sha(tmp_path / "c" / "transactions.csv")
