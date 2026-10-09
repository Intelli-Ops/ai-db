"""
Build report: the AI writes the SQL for a report, and we prove it is right.

For each report folder in reports/ (made by make_examples.py):
  1. Pick the tables and work out the joins            (pick_tables.py)
  2. The AI writes one SQL query from the SOP             (AI)
  3. We check the SQL is safe, then run it                (no AI)
  4. We compare the result with expected.csv, cell by cell (no AI)
  5. If anything differs, the differences go back to the AI
     and it tries again (up to MAX_ATTEMPTS)
     If the AI finds it is missing a table, it can ask for it. We check
     the table really exists, work out the join ourselves, and let it retry.
  6. Once it matches, we run the SAME SQL on a second month the AI
     has never seen. Only if that also matches is the SQL saved.

The numbers always come from the database running the SQL. The AI only
writes the query, once. After that the report runs without any AI.

If the SOP and the expected output disagree, the AI is told to say so
instead of bending the SQL to fit. That is flagged for a person.

Run:  python build_report.py                      (all reports)
      python build_report.py sales_by_territory   (just one)
"""
import json
import sys
from datetime import date
from pathlib import Path

import pandas as pd
from pydantic import BaseModel

import llm
from compare import compare
from pick_tables import describe_table, load_schema, most_detailed_first, pick_tables
from schema_graph import build_graph, find_join_path
from schema_search import search
from sql_checks import same_sql
from sql_runner import BLOCKED_TABLES, check_sql, describe_params, run_sql

REPORTS_DIR = Path("reports")
MAX_ATTEMPTS = 5


class SqlAnswer(BaseModel):
    sql: str
    explanation: str        # one or two sentences on what the query does
    need_tables: list[str]  # tables it needs that are not in the approved list
    conflict: str           # empty, unless the SOP and the expected output disagree


PROMPT = """You are an automation engineer. Write ONE SQL Server (T-SQL) SELECT
statement that produces the report described below.

Report: {question}

Written procedure (SOP). This is the intended logic. Follow it.
{sop}

Parameters. They are already declared for you: just use them, do not DECLARE them.
  {params}

Tables you may use (no others):
{tables}

How these tables join (worked out from the database's foreign keys):
{joins}

Expected output when run with {param_values}: {row_count} rows.
Columns, exactly and in this order: {columns}
First rows:
{sample}

Rules:
- One SELECT statement only (WITH ... SELECT is fine). Nothing that changes data.
- Always write table names with their schema, e.g. Sales.SalesOrderHeader.
- Output column names and their order must match the expected output exactly.
- Mind the join warnings: after a join marked MULTIPLIES ROWS, do not add up
  columns from the tables that came before it.
- The same SQL will be re-run for other periods, so never hard-code dates or
  any values copied from the expected output.
- If the SOP needs data that none of the listed tables hold, do not work around
  it. Put the full name of each missing table (schema.table) in "need_tables".
  It will be checked and added, with its join, and you will be asked again.
  Otherwise leave "need_tables" empty.
- The expected output is a TEST of your SQL, not a source of logic. If the only
  way to match it is to do something the SOP does not say, or that goes against
  the SOP, do NOT do it. Keep the SQL faithful to the SOP and describe the
  disagreement in "conflict". Otherwise leave "conflict" as an empty string.
  "conflict" is ONLY for the SOP and the expected output disagreeing about the
  logic or the numbers. A missing table is not a conflict: use "need_tables".
{history}"""


def describe_joins(joins):
    """The join path and its warnings, as text for the AI."""
    if not joins:
        return "(only one table is needed, so there is nothing to join)"
    lines = []
    for j in joins:
        if j["ambiguous"]:
            lines.append(f"{j['from']} JOIN {j['to']} - there are {len(j['options'])} "
                         f"possible links. Choose the one the SOP calls for:")
        else:
            lines.append(f"{j['from']} JOIN {j['to']}")
        for option in j["options"]:
            lines.append(f"  ON {option['condition']}   ({option['relationship']})")
            for w in option["warnings"]:
                lines.append(f"    WARNING - {w['type']}: {w['message']}")
    return "\n".join(lines)


def describe_history(attempts):
    """What was tried before and what was wrong with it."""
    if not attempts:
        return ""
    lines = ["\nYour previous attempts, and what was wrong with each:"]
    for n, a in enumerate(attempts, start=1):
        lines.append(f"\n--- Attempt {n} ---\n{a['sql']}\nProblems found:")
        lines.extend(f"- {p}" for p in a["problems"])
    lines.append("\nFix the problems and give the full corrected SQL.")
    return "\n".join(lines)


def plan_joins(G, tables):
    """Join path for these tables, and the full list the SQL may touch."""
    order = most_detailed_first(G, tables)
    joins = find_join_path(G, order)
    return joins, sorted(set(tables) | {j["to"] for j in joins})


def add_tables(requested, tables, G, schema):
    """
    The AI asked for more tables. Decide, without AI, which to grant.
    Returns the new table list and a note on each request for the AI.
    """
    notes = []
    for name in requested:
        if name in BLOCKED_TABLES:
            notes.append(f"{name} may not be used in any report.")
        elif name not in schema:
            close = ", ".join(r["table"] for r in search(name, top=5))
            notes.append(f"There is no table called {name}. Closest real tables: {close}.")
        else:
            try:
                plan_joins(G, tables + [name])
            except ValueError:
                notes.append(f"{name} exists but has no link to the other tables.")
                continue
            tables = tables + [name]
            notes.append(f"{name} has been added. See the updated table list and join path.")
    return tables, notes


def try_sql(sql, allowed_tables, params, expected, key):
    """Safety check, run, compare. Returns the list of problems (empty = perfect)."""
    problems = check_sql(sql, allowed_tables)
    if problems:
        return problems
    try:
        result = run_sql(sql, params)
    except Exception as e:  # the database rejected the query
        return [f"The database returned an error: {str(e)[:500]}"]
    return compare(result, expected, key)


def build_report(folder, G, schema):
    case = json.loads((folder / "case.json").read_text(encoding="utf-8"))
    sop = (folder / "sop.txt").read_text(encoding="utf-8")
    expected = pd.read_csv(folder / "expected.csv")
    print(f"\n===== {folder.name}: {case['question']} =====")

    # Step 1: which tables, and how do they join?
    plan = pick_tables(case["question"], G, schema, sop=sop)
    tables = [t["table"] for t in plan["tables"]]
    log = {
        "report": folder.name,
        "date": date.today().isoformat(),
        "tables_picked_by_ai": list(tables),
        "tables_added_on_request": [],
        "attempts": [],
        "status": None,
    }
    if not tables or plan["join_error"]:
        log["status"] = "NO PLAN"
        log["detail"] = plan["join_error"] or "; ".join(plan["questions"])
        return finish(folder, log)
    joins, allowed = plan_joins(G, tables)
    print(f"Tables: {', '.join(allowed)}")

    # Steps 2-5: write, check, run, compare, and feed the differences back.
    for n in range(1, MAX_ATTEMPTS + 1):
        answer = llm.ask(
            PROMPT.format(
                question=case["question"],
                sop=sop,
                params=describe_params(case["params"]),
                tables="\n\n".join(describe_table(schema[name]) for name in allowed),
                joins=describe_joins(joins),
                param_values=case["params"],
                row_count=len(expected),
                columns=list(expected.columns),
                sample=expected.head(5).to_csv(index=False),
                history=describe_history(log["attempts"]),
            ),
            SqlAnswer,
        )
        attempt = {
            "model": llm.last_model,
            "sql": answer.sql,
            "explanation": answer.explanation,
            "need_tables": answer.need_tables,
            "conflict": answer.conflict,
        }
        log["attempts"].append(attempt)

        requested = [t for t in answer.need_tables if t not in allowed]
        if requested:
            # The AI is missing a table. Grant what is valid and ask again.
            before = set(tables)
            tables, attempt["problems"] = add_tables(requested, tables, G, schema)
            log["tables_added_on_request"] += sorted(set(tables) - before)
            joins, allowed = plan_joins(G, tables)
            print(f"Attempt {n} ({llm.last_model}): asked for more tables")
            for p in attempt["problems"]:
                print(f"    - {p[:300]}")
            continue

        # Only attempts that were really tested count as "tried before".
        repeat_of = [i for i, a in enumerate(log["attempts"][:-1], start=1)
                     if a.get("tested") and same_sql(a["sql"], answer.sql)]
        if repeat_of:
            # Same SQL as before: testing it again would tell us nothing new.
            problems = [f"This is exactly the same SQL as attempt {repeat_of[-1]}, which "
                        f"had the problems listed there. Change the SQL to fix them."]
        else:
            problems = try_sql(answer.sql, allowed, case["params"], expected, case["key"])
            attempt["tested"] = True
        attempt["problems"] = problems
        print(f"Attempt {n} ({llm.last_model}): "
              f"{'matches the expected output' if not problems else 'does not match'}")
        for p in problems:
            print(f"    - {p[:300]}")

        if answer.conflict.strip():
            # The AI says the SOP and the expected output disagree.
            # A person has to decide which one is right, so stop here.
            log["status"] = "CONFLICT - needs a person"
            log["detail"] = answer.conflict
            return finish(folder, log)
        if not problems:
            break
    else:
        log["status"] = f"FAILED - no match after {MAX_ATTEMPTS} attempts"
        return finish(folder, log)

    # Step 6: the real test. Same SQL, a month the AI never saw.
    sql = log["attempts"][-1]["sql"]
    holdout_expected = pd.read_csv(folder / "expected_holdout.csv")
    holdout_problems = try_sql(
        sql, allowed, case["holdout_params"], holdout_expected, case["key"]
    )
    log["holdout_problems"] = holdout_problems
    if holdout_problems:
        log["status"] = "FAILED - matched the first month but not the held-out month"
        return finish(folder, log)

    log["status"] = "PASSED - awaiting human review"
    header = "\n".join([
        f"-- Report:     {case['question']}",
        f"-- Status:     {log['status']}",
        f"-- Tested on:  {case['params']} and held-out {case['holdout_params']}",
        f"-- Written by: {log['attempts'][-1]['model']} on {log['date']}, "
        f"attempt {len(log['attempts'])} of {MAX_ATTEMPTS}",
        f"-- Parameters: {describe_params(case['params'])}",
        f"-- Tables:     {', '.join(allowed)}",
        "",
    ])
    (folder / "automation.sql").write_text(header + sql.strip() + "\n", encoding="utf-8")
    return finish(folder, log)


def finish(folder, log):
    """Save the full record of what happened, for the person who reviews it."""
    (folder / "run_log.json").write_text(json.dumps(log, indent=2), encoding="utf-8")
    # A report that did not pass must not leave an old approved-looking SQL behind.
    if not log["status"].startswith("PASSED"):
        (folder / "automation.sql").unlink(missing_ok=True)
    print(f"Result: {log['status']}")
    if log.get("detail"):
        print(f"    {log['detail']}")
    for p in log.get("holdout_problems", []):
        print(f"    held-out month - {p[:300]}")
    return log


def main():
    names = sys.argv[1:] or sorted(p.parent.name for p in REPORTS_DIR.glob("*/case.json"))
    G = build_graph()
    schema = load_schema()
    logs = [build_report(REPORTS_DIR / name, G, schema) for name in names]

    print("\n===== Summary =====")
    for log in logs:
        print(f"  {log['report']:<24} attempts: {len(log['attempts'])}   {log['status']}")


if __name__ == "__main__":
    main()
