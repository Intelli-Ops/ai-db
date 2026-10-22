"""
Pick tables: the AI chooses which tables and columns a question needs.

Steps for one question:
  1. schema_search gives a shortlist of 10 likely tables       (no AI)
  2. the AI reads their descriptions and picks the ones needed (AI)
  3. we check the AI only picked things that really exist      (no AI)
  4. schema_graph works out how to join them, with warnings    (no AI)

The AI writes no SQL here and never sees any data. It only chooses
from a list, and anything unclear becomes a question for a person.

Run:  python pick_tables.py "your question in plain English"
"""
import json
import re
import sys

from pydantic import BaseModel

from llm import ask
from schema_graph import build_graph, find_join_path
from schema_search import SCHEMA_FILE, SKIP_COLUMNS, search, search_each

class TableChoice(BaseModel):
    table: str          # full name, e.g. dbo.BILL
    columns: list[str]  # the columns needed from it
    reason: str         # one sentence: why this table


class Plan(BaseModel):
    tables: list[TableChoice]
    questions: list[str]  # anything a person must clarify before going on


PROMPT = """You are helping build a report from a SQL Server database.

Question from the business user:
"{question}"
{sop}
Below are candidate tables found by a search. Most are NOT needed.

Your job:
- Choose the smallest set of tables that holds the data the question asks for.
- For each chosen table, list the columns needed (values to add up or count,
  columns to group by, columns to filter on).
- Use only tables and columns listed below, spelled exactly as shown.
- Do NOT add tables whose only purpose is to connect two other tables.
  Separate code works out the joins.
- Do NOT write SQL.
- If the question can be read in more than one way, or the candidate tables
  cannot answer it, do not guess. Put a short clarifying question in
  "questions" instead.

Candidate tables:
{tables}
"""


def load_schema():
    with open(SCHEMA_FILE, encoding="utf-8") as f:
        return {t["name"]: t for t in json.load(f)}


def describe_table(t):
    """The text the AI sees for one candidate table."""
    lines = [f"TABLE {t['name']}: {t['description']}"]
    for c in t["columns"]:
        if c["name"] not in SKIP_COLUMNS:
            lines.append(f"  - {c['name']} ({c['type']}): {c['description']}")
    return "\n".join(lines)


def build_prompt(question, shortlist, schema, sop=None):
    tables = "\n\n".join(describe_table(schema[name]) for name in shortlist)
    # If a written procedure exists, it settles what the question means.
    sop_text = f"\nWritten procedure (SOP) for this report:\n{sop}\n" if sop else ""
    return PROMPT.format(question=question, sop=sop_text, tables=tables)


def sop_steps(sop):
    """Split a numbered procedure into its steps: '1. ...', '2. ...'."""
    steps = re.split(r"(?m)^\s*\d+\.\s", sop)[1:]
    return [" ".join(step.split()) for step in steps]


def check_plan(plan, shortlist, schema):
    """
    Never trust the AI's answer blindly. Keep only tables from the
    shortlist and columns that really exist; report everything else.
    """
    accepted, rejected = [], []
    for choice in plan.tables:
        if choice.table not in shortlist:
            rejected.append(f"{choice.table}: not one of the candidate tables")
            continue
        real_columns = {c["name"] for c in schema[choice.table]["columns"]}
        columns = []
        for column in choice.columns:
            if column in real_columns:
                columns.append(column)
            else:
                rejected.append(f"{choice.table}.{column}: no such column")
        accepted.append({"table": choice.table, "columns": columns, "reason": choice.reason})
    return accepted, rejected


def most_detailed_first(G, names):
    """
    Put the most detailed table first, so the joins start from it.

    Starting from orders and looking up each order's territory is safe.
    Starting from territories and fanning out to orders multiplies rows.
    Same tables, same join, but the first way is how a report should be
    built. We try each table as the start and keep the one with the
    fewest row-multiplying joins. The AI's order is only a tie-breaker.
    """
    def multiplying_joins(start):
        ordered = [start] + [n for n in names if n != start]
        return sum(
            w["type"] == "MULTIPLIES ROWS"
            for j in find_join_path(G, ordered)
            for w in j["options"][0]["warnings"]
        )

    start = min(names, key=multiplying_joins)
    return [start] + [n for n in names if n != start]


def pick_tables(question, G, schema, ask=ask, sop=None):
    # Search the question and each step of the procedure separately.
    texts = [question] + (sop_steps(sop) if sop else [])
    if sop:
        shortlist = [r["table"] for r in search_each(texts)]
    else:
        shortlist = [r["table"] for r in search(question)]

    plan = ask(build_prompt(question, shortlist, schema, sop), Plan)
    tables, rejected = check_plan(plan, shortlist, schema)

    result = {
        "question": question,
        "shortlist": shortlist,
        "tables": tables,
        "rejected": rejected,
        "questions": list(plan.questions),
        "joins": [],
        "join_error": None,
    }
    if tables:
        try:
            order = most_detailed_first(G, [t["table"] for t in tables])
            tables.sort(key=lambda t: order.index(t["table"]))
            result["joins"] = find_join_path(G, order)
        except ValueError as e:
            result["join_error"] = str(e)

    # Two tables linked in more than one way is also a question for a person.
    for j in result["joins"]:
        if j["ambiguous"]:
            options = "; or ".join(o["condition"] for o in j["options"])
            result["questions"].append(
                f"{j['from']} and {j['to']} can be linked in "
                f"{len(j['options'])} ways. Which is meant? {options}"
            )
    return result


def print_result(result):
    print(f"\n===== {result['question']} =====")
    print(f"Shortlist from search: {len(result['shortlist'])} tables")

    print("\nAI chose:")
    for t in result["tables"]:
        print(f"  {t['table']}  ({', '.join(t['columns'])})")
        print(f"      why: {t['reason']}")
    if not result["tables"]:
        print("  nothing")
    for r in result["rejected"]:
        print(f"  [!] REJECTED AI answer - {r}")

    if result["join_error"]:
        print(f"\n[!] Cannot join these tables: {result['join_error']}")
    elif result["tables"]:
        print("\nJoin path (from our own code, not the AI):")
        print(f"FROM {result['tables'][0]['table']}")
        for j in result["joins"]:
            chosen = j["options"][0]
            print(f"JOIN {j['to']}")
            print(f"  ON {chosen['condition']}")
            for w in chosen["warnings"]:
                print(f"  [!] {w['type']}: {w['message']}")

    if result["questions"]:
        print("\nQuestions for a person before going further:")
        for n, q in enumerate(result["questions"], start=1):
            print(f"  {n}. {q}")


def main():
    questions = sys.argv[1:]
    if not questions:
        sys.exit('Give a question:  python pick_tables.py "your question"')
    G = build_graph()
    schema = load_schema()
    for question in questions:
        print_result(pick_tables(question, G, schema))


if __name__ == "__main__":
    main()
