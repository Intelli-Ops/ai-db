"""
Run report: produce an approved report for any period. No AI involved.

This is the part that runs every month. It needs no AI key, costs
nothing, and gives the same answer every time it is run on the same data.

What it does, in order:
  1. Refuses to run unless a person has approved the SQL
     (and the approved file has not been edited since).
  2. Checks the inputs: the tables and columns still exist, the period
     has data, and the amount of data looks normal.
  3. Runs the approved SQL for the period.
  4. Checks the output: right columns, no repeated rows, and the same
     kinds of rows as before.
  5. Saves the report in output/ and adds a line to output/run_history.csv.

Run:  python run_report.py sales_by_category 2025-05-01 2025-05-31
"""
import csv
import getpass
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

from compare import tidy
from pick_tables import load_schema
from review_report import read_approval
from sql_checks import SqlReader
from sql_runner import check_sql, run_sql

REPORTS_DIR = Path("reports")
OUTPUT_DIR = Path("output")

# Warn when a period has less than half, or more than double, the rows
# of the periods the report was tested on.
LOW, HIGH = 0.5, 2.0


class Stop(Exception):
    """A check failed badly enough that no report should be produced."""


def period_name(params):
    """'2025-05' for a whole month, otherwise '2025-05-01_to_2025-05-15'."""
    values = list(params.values())
    try:
        start, end = date.fromisoformat(values[0]), date.fromisoformat(values[1])
    except (ValueError, IndexError):
        return "_".join(str(v) for v in values)
    whole_month = start.day == 1 and (end + timedelta(days=1)).day == 1 \
        and (start.year, start.month) == (end.year, end.month)
    return f"{start:%Y-%m}" if whole_month else f"{start}_to_{end}"


def check_structure(reader):
    """Every table and column the SQL reads must still exist in the database."""
    live = run_sql("SELECT TABLE_SCHEMA + '.' + TABLE_NAME AS t, COLUMN_NAME AS c "
                   "FROM INFORMATION_SCHEMA.COLUMNS")
    existing = {(t.lower(), c.lower()) for t, c in live.itertuples(index=False)}
    missing = sorted(f"{t}.{c}" for t, c in reader.columns_used()
                     if (t.lower(), c.lower()) not in existing)
    if missing:
        raise Stop("The database has changed. These columns no longer exist: "
                   + ", ".join(missing))


def rows_in_period(table, column, params):
    start, end = list(params)[:2]
    counted = run_sql(
        f"SELECT COUNT(*) AS n FROM {table} "
        f"WHERE {column} >= @{start} AND {column} < DATEADD(day, 1, @{end})",
        params,
    )
    return int(counted.iloc[0, 0])


def check_period(reader, params, case):
    """The period must have data, and a normal amount of it. Returns warnings."""
    warnings = []
    for table, column in sorted(reader.period_columns()):
        now = rows_in_period(table, column, params)
        if now == 0:
            raise Stop(f"{table} has no rows with {column} in this period. "
                       f"The data may not be loaded yet.")
        tested = [rows_in_period(table, column, case[p]) for p in ("params", "holdout_params")]
        usual = sum(tested) / len(tested)
        if not LOW * usual <= now <= HIGH * usual:
            warnings.append(
                f"{table} has {now:,} rows in this period. The tested periods had "
                f"about {usual:,.0f}. Check the data is complete."
            )
    return warnings


def check_output(result, folder, case):
    """The report must look like the ones it was tested against. Returns warnings."""
    expected = pd.concat([pd.read_csv(folder / "expected.csv"),
                          pd.read_csv(folder / "expected_holdout.csv")])
    if list(result.columns) != list(expected.columns):
        raise Stop(f"The report has columns {list(result.columns)} but should have "
                   f"{list(expected.columns)}.")
    if result.empty:
        raise Stop("The report came out empty.")
    key = case["key"]
    if result.duplicated(subset=key).any():
        raise Stop(f"The report has more than one row for the same {key}.")

    warnings = []
    seen_before = set(tidy(expected[key]).itertuples(index=False, name=None))
    now = set(tidy(result[key]).itertuples(index=False, name=None))
    gone = sorted(" / ".join(map(str, k)) for k in seen_before - now)
    new = sorted(" / ".join(map(str, k)) for k in now - seen_before)
    if gone:
        warnings.append(f"In earlier reports but missing now ({', '.join(key)}): {', '.join(gone)}")
    if new:
        warnings.append(f"New, not in earlier reports ({', '.join(key)}): {', '.join(new)}")
    if result.drop(columns=key).isna().any().any():
        warnings.append("Some cells are empty.")
    return warnings


def run_report(name, values):
    folder = REPORTS_DIR / name
    if not (folder / "case.json").exists():
        raise Stop(f"There is no report called {name}.")
    case = json.loads((folder / "case.json").read_text(encoding="utf-8"))

    # 1. Only approved SQL may run.
    approval = read_approval(folder)
    if not approval:
        raise Stop("This report has not been approved yet. "
                   f"Review it first: python review_report.py {name}")
    if not approval["intact"]:
        raise Stop(f"{approval['file']} was changed after it was approved. Refusing to run it.")
    sql = approval["sql"]

    names = list(case["params"])
    if len(values) != len(names):
        raise Stop(f"This report needs {len(names)} value(s): {', '.join(names)}")
    params = dict(zip(names, values))

    schema = load_schema()
    reader = SqlReader(sql, schema)
    problems = check_sql(sql, reader.tables)
    if problems:
        raise Stop("; ".join(problems))

    # 2. Inputs
    check_structure(reader)
    warnings = check_period(reader, params, case)

    # 3. Run
    result = run_sql(sql, params)

    # 4. Output
    warnings += check_output(result, folder, case)

    # 5. Save
    OUTPUT_DIR.mkdir(exist_ok=True)
    out_file = OUTPUT_DIR / f"{name}_{period_name(params)}.csv"
    result.to_csv(out_file, index=False)
    record(name, approval["version"], params, len(result), "OK", warnings, out_file)
    return result, warnings, out_file, approval


def record(name, version, params, rows, outcome, notes, out_file=""):
    """One line per run, so there is always a trail of who ran what and when."""
    OUTPUT_DIR.mkdir(exist_ok=True)
    history = OUTPUT_DIR / "run_history.csv"
    is_new = not history.exists()
    with open(history, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if is_new:
            writer.writerow(["run_at", "run_by", "report", "version", "period",
                             "outcome", "rows", "notes", "file"])
        writer.writerow([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), getpass.getuser(),
                         name, version, period_name(params) if params else "",
                         outcome, rows, " | ".join(notes), str(out_file)])


def main():
    if len(sys.argv) < 2:
        sys.exit("Usage: python run_report.py <report_name> <start_date> <end_date>")
    name, values = sys.argv[1], sys.argv[2:]
    try:
        result, warnings, out_file, approval = run_report(name, values)
    except Stop as e:
        record(name, "", {}, 0, "STOPPED", [f"{' '.join(values)}: {e}"])
        sys.exit(f"STOPPED, no report produced: {e}")

    print(f"{name}, version {approval['version']} "
          f"(approved by {approval['approved_by']} on {approval['approved_at']})")
    print(result.to_string(index=False))
    for w in warnings:
        print(f"[!] {w}")
    print(f"\nSaved {len(result)} rows to {out_file}")


if __name__ == "__main__":
    main()
