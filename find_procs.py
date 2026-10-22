"""
Find procs: which stored procedures fill a set of tables, and save their code.

Many report tables (BDR report, billing dashboards, "offline" tables) are
filled by stored procedures that run on a schedule. Their SQL shows how
each report column is calculated from the source tables. This reads only
the procedure code from the catalog, never table data.

For every table whose name matches the pattern, it finds procedures that
INSERT INTO, UPDATE, MERGE INTO, SELECT ... INTO or TRUNCATE it.

Writes:
  <database>/<schema>/procs/<procedure>.sql   - the code of each procedure found
  <database>/<schema>/procs/index.md          - which procedure fills which table

Usage:  python find_procs.py dbo "offline|report"
"""
import json
import os
import re
import sys

from sqlalchemy import text

from db import DB_NAME, get_engine

PROCS_SQL = """
SELECT o.name, o.modify_date, m.definition
FROM sys.sql_modules m
JOIN sys.objects o ON o.object_id = m.object_id
WHERE o.type = 'P' AND SCHEMA_NAME(o.schema_id) = :schema
"""


def writes_to(definition, table):
    """True if the code changes this table (not just reads it)."""
    name = rf"(\[?dbo\]?\.)?\[?{re.escape(table)}\]?(?![\w$])"
    verbs = rf"(insert\s+(into\s+)?|update\s+|merge\s+(into\s+)?|into\s+|truncate\s+table\s+|delete\s+(from\s+)?){name}"
    return re.search(verbs, definition, re.I) is not None


def main():
    schema, pattern = sys.argv[1], re.compile(sys.argv[2], re.I)
    folder = os.path.join(DB_NAME, schema)
    with open(os.path.join(folder, "catalog.json"), encoding="utf-8") as f:
        catalog = json.load(f)
    tables = sorted(o["name"].split(".", 1)[1] for o in catalog["objects"]
                    if o["kind"] == "table" and pattern.search(o["name"]))

    with get_engine().connect() as conn:
        procs = conn.execute(text(PROCS_SQL), {"schema": schema}).fetchall()
    print(f"{len(procs)} procedures, {len(tables)} tables to look for")

    out_dir = os.path.join(folder, "procs")
    os.makedirs(out_dir, exist_ok=True)
    found, saved = {}, set()
    for table in tables:
        found[table] = [p for p in procs if p.definition and writes_to(p.definition, table)]
        for p in found[table]:
            if p.name not in saved:
                safe = re.sub(r'[\\/:*?"<>|]', "_", p.name)
                with open(os.path.join(out_dir, f"{safe}.sql"), "w", encoding="utf-8") as f:
                    f.write(p.definition)
                saved.add(p.name)

    lines = [f"# Procedures that fill {schema} tables matching '{sys.argv[2]}'", "",
             "| Table | Filled by | Procedure last changed |", "|---|---|---|"]
    for table in tables:
        if found[table]:
            for p in found[table]:
                lines.append(f"| {table} | {p.name} | {str(p.modify_date)[:10]} |")
        else:
            lines.append(f"| {table} | (none found) | |")
    with open(os.path.join(out_dir, "index.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"{sum(1 for t in tables if found[t])} of {len(tables)} tables have a procedure; "
          f"{len(saved)} procedures saved to {out_dir}")


if __name__ == "__main__":
    main()
