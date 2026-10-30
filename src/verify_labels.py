"""Compare the pipeline's rejected rows with the generator's answer key."""
import argparse
import csv
import sqlite3
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--labels", required=True)
    parser.add_argument("--source-file", default="transactions.csv")
    args = parser.parse_args()

    with open(args.labels, newline="", encoding="utf-8") as f:
        expected = {int(r["row_number"]): r["expected_reject_reason"]
                    for r in csv.DictReader(f)}

    conn = sqlite3.connect(args.db)
    actual = dict(conn.execute(
        "SELECT row_number, reject_reason FROM rejected_records "
        "WHERE record_type = 'transaction' AND source_file = ?", (args.source_file,)))

    missed = sorted(set(expected) - set(actual))
    unexpected = sorted(set(actual) - set(expected))
    wrong = sorted(r for r in set(expected) & set(actual) if expected[r] != actual[r])

    print(f"expected rejects : {len(expected)}")
    print(f"actual rejects   : {len(actual)}")
    print(f"missed           : {len(missed)} {missed[:5]}")
    print(f"unexpected       : {len(unexpected)} {unexpected[:5]}")
    print(f"wrong reason     : {len(wrong)} {wrong[:5]}")
    ok = not (missed or unexpected or wrong)
    print("RESULT:", "PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
