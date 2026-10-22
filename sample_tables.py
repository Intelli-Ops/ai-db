"""
Sample tables: read the first rows of every table so we can understand
what each one holds, and write rough descriptions.

Reads TOP 10 rows per table (WITH (NOLOCK), so nobody else is blocked).
For each column it writes up to 3 different example values, plus how many
of the 10 rows were empty.

Personal details are masked before anything is written to samples.md:
names, birth dates, SSNs, addresses, phones, emails, passwords and free
text are replaced by their shape ("Aaaaa Aaaa", "999-999-9999"). Codes,
statuses, amounts, dates and IDs are kept, because they say what a table
is for. Nothing here is sent to the paid AI.

Writes:
  <database>/<schema>/samples.md   - masked examples, one section per table

Usage:  python sample_tables.py dbo
        python sample_tables.py dbo --only "offline|report"
            (only tables whose name matches; writes samples_only.md)
"""
import json
import os
import re
import sys
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import text

from db import DB_NAME, get_engine

engine = get_engine()

TOP = 10
EXAMPLES = 3     # different values shown per column
MAX_LEN = 40     # longer values are cut
SKIP_NAMES = re.compile(r"offline|report", re.I)

# Columns whose values identify a person, or are secrets, or free text.
PERSONAL = re.compile(
    r"name|first|last|middle|ssn|social|dob|birth|address|addr|street|"
    r"phone|fax|cell|mobile|email|e_mail|password|pwd|pass|token|secret|hash|"
    r"note|comment|remark|memo|narrative|body|message|text|"
    r"patient|applicant|claimant|adjuster|attorney|doctor|physician|employee|"
    r"manager|pseudo|contact|user|signer|signed|collector|assignee|owner",
    re.I,
)
EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.\w+")
PHONE = re.compile(r"\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}")
SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")


def shape(value):
    """'John Smith' -> 'Aaaa Aaaaa', '555-1234' -> '999-9999'."""
    s = re.sub(r"[A-Z]", "A", str(value))
    s = re.sub(r"[a-z]", "a", s)
    s = re.sub(r"\d", "9", s)
    return s[:20] + ("..." if len(s) > 20 else "")


def show(value, column):
    """One value as text, masked when it could identify a person."""
    if value is None:
        return None
    if isinstance(value, (bytes, bytearray, memoryview)):
        return "<binary>"
    if isinstance(value, (datetime, date)):
        if re.search(r"dob|birth", column, re.I):
            return "<birth date>"
        return str(value)[:19]
    if isinstance(value, (int, float, Decimal, bool)):
        return str(value)
    s = " ".join(str(value).split())
    if PERSONAL.search(column) or EMAIL.search(s) or PHONE.search(s) or SSN.search(s):
        return f"<{shape(s)}>"
    if len(s) > 60:  # long free text may describe a patient
        return f"<text, {len(s)} chars>"
    return s[:MAX_LEN] + ("..." if len(s) > MAX_LEN else "")


def sample_table(conn, schema, table):
    sql = f"SELECT TOP ({TOP}) * FROM [{schema}].[{table.replace(']', ']]')}] WITH (NOLOCK)"
    result = conn.execute(text(sql))
    columns = list(result.keys())
    rows = result.fetchall()
    out = []
    for i, column in enumerate(columns):
        values = [row[i] for row in rows]
        empty = sum(v is None or (isinstance(v, str) and not v.strip()) for v in values)
        examples = []
        for v in values:
            s = show(v, column)
            if s not in (None, "") and s not in examples:
                examples.append(s)
            if len(examples) == EXAMPLES:
                break
        out.append((column, empty, examples))
    return len(rows), out


def main():
    args = sys.argv[1:]
    only = None
    if "--only" in args:
        i = args.index("--only")
        only = re.compile(args[i + 1], re.I)
        del args[i:i + 2]
    schema = args[0] if args else "dbo"
    folder = os.path.join(DB_NAME, schema)
    with open(os.path.join(folder, "catalog.json"), encoding="utf-8") as f:
        catalog = json.load(f)
    tables = sorted(
        (o for o in catalog["objects"]
         if o["kind"] == "table"
         and (only.search(o["name"]) if only else not SKIP_NAMES.search(o["name"]))),
        key=lambda o: o["name"].lower(),
    )

    lines = [f"# {schema}: first {TOP} rows of each table (masked)", "",
             "Each column: type, empty values out of the rows read, up to "
             f"{EXAMPLES} different examples. <...> = masked.", ""]
    failed = 0
    with engine.connect() as conn:
        conn.execute(text("SET LOCK_TIMEOUT 10000"))
        for n, t in enumerate(tables, start=1):
            name = t["name"].split(".", 1)[1]
            types = {c["name"]: c["type"] for c in t["columns"]}
            lines.append(f"## {name}  ({t['row_count']:,} rows)")
            if t["row_count"] == 0:
                lines += ["(empty)", ""]
                continue
            try:
                read, cols = sample_table(conn, schema, name)
            except Exception as e:
                failed += 1
                lines += [f"(could not read: {str(e).split(']')[-1][:150]})", ""]
                continue
            for column, empty, examples in cols:
                ex = " | ".join(examples) if examples else "-"
                lines.append(f"- {column} ({types.get(column, '?')}, {empty}/{read} empty): {ex}")
            lines.append("")
            if n % 50 == 0:
                print(f"  {n} of {len(tables)} tables read")

    path = os.path.join(folder, "samples_only.md" if only else "samples.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"Read {len(tables)} tables ({failed} could not be read). Saved {path}")


if __name__ == "__main__":
    main()
