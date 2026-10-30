"""
Step 1: inventory of the database (what is in it, not what it says).

Reads only SQL Server's own catalog (the sys views), never a business
table: which schemas, tables and views exist, their columns and types,
row counts, primary keys, declared links (foreign keys), and the names of
stored procedures and functions. No AI. Explained in docs/01_project_steps.md, Step 1.

Writes (git-ignored, this machine only):
  catalog/catalog.json   - everything, for the later steps to read
  catalog/inventory.md   - the same, readable

Run:  python step01_inventory.py
"""
import json
import os
from collections import Counter, defaultdict
from datetime import datetime

import pandas as pd
from sqlalchemy import text

from db import DB_NAME, get_engine

OUT_DIR = "catalog"

WHO_SQL = """
SELECT @@SERVERNAME AS server_name, DB_NAME() AS database_name, SUSER_SNAME() AS login_name,
       CAST(SERVERPROPERTY('ProductVersion') AS nvarchar(50)) AS version,
       CAST(SERVERPROPERTY('Edition') AS nvarchar(100)) AS edition
"""

# Tables and views. Row counts come from the catalog (sys.partitions), not COUNT(*).
OBJECTS_SQL = """
SELECT s.name AS schema_name, o.name AS object_name,
       CASE o.type WHEN 'U' THEN 'table' ELSE 'view' END AS kind,
       o.create_date, o.modify_date,
       (SELECT SUM(p.rows) FROM sys.partitions p
         WHERE p.object_id = o.object_id AND p.index_id IN (0, 1)) AS row_count
FROM sys.objects o
JOIN sys.schemas s ON s.schema_id = o.schema_id
WHERE o.type IN ('U', 'V') AND o.is_ms_shipped = 0
"""

COLUMNS_SQL = """
SELECT s.name AS schema_name, o.name AS object_name, c.column_id, c.name AS column_name,
       t.name AS type_name, c.max_length, c.precision, c.scale, c.is_nullable, c.is_identity
FROM sys.columns c
JOIN sys.objects o ON o.object_id = c.object_id
JOIN sys.schemas s ON s.schema_id = o.schema_id
JOIN sys.types t ON t.user_type_id = c.user_type_id
WHERE o.type IN ('U', 'V') AND o.is_ms_shipped = 0
"""

PRIMARY_KEYS_SQL = """
SELECT s.name AS schema_name, o.name AS object_name, c.name AS column_name, ic.key_ordinal
FROM sys.indexes i
JOIN sys.index_columns ic ON ic.object_id = i.object_id AND ic.index_id = i.index_id
JOIN sys.columns c ON c.object_id = ic.object_id AND c.column_id = ic.column_id
JOIN sys.objects o ON o.object_id = i.object_id
JOIN sys.schemas s ON s.schema_id = o.schema_id
WHERE i.is_primary_key = 1
"""

FOREIGN_KEYS_SQL = """
SELECT fk.name AS fk_name,
       ps.name AS schema_name, po.name AS object_name, pc.name AS column_name,
       rs.name AS ref_schema, ro.name AS ref_object, rc.name AS ref_column, fkc.constraint_column_id
FROM sys.foreign_keys fk
JOIN sys.foreign_key_columns fkc ON fkc.constraint_object_id = fk.object_id
JOIN sys.objects po ON po.object_id = fkc.parent_object_id
JOIN sys.schemas ps ON ps.schema_id = po.schema_id
JOIN sys.columns pc ON pc.object_id = fkc.parent_object_id AND pc.column_id = fkc.parent_column_id
JOIN sys.objects ro ON ro.object_id = fkc.referenced_object_id
JOIN sys.schemas rs ON rs.schema_id = ro.schema_id
JOIN sys.columns rc ON rc.object_id = fkc.referenced_object_id AND rc.column_id = fkc.referenced_column_id
"""

ROUTINES_SQL = """
SELECT s.name AS schema_name, o.name AS routine_name,
       CASE WHEN o.type = 'P' THEN 'procedure' ELSE 'function' END AS kind
FROM sys.objects o
JOIN sys.schemas s ON s.schema_id = o.schema_id
WHERE o.type IN ('P', 'FN', 'IF', 'TF') AND o.is_ms_shipped = 0
"""

SIZE_BANDS = [(0, "empty (0 rows)"), (1_000, "1 - 1,000"), (100_000, "1,001 - 100,000"),
              (1_000_000, "100,001 - 1 million"), (float("inf"), "over 1 million")]


def type_label(c):
    """e.g. varchar(50), nvarchar(max), decimal(18,2), int."""
    t = c["type_name"]
    if t in ("varchar", "char", "varbinary", "binary"):
        return f"{t}({'max' if c['max_length'] == -1 else c['max_length']})"
    if t in ("nvarchar", "nchar"):
        return f"{t}({'max' if c['max_length'] == -1 else c['max_length'] // 2})"
    if t in ("decimal", "numeric"):
        return f"{t}({c['precision']},{c['scale']})"
    return t


def size_band(rows):
    for limit, label in SIZE_BANDS:
        if rows <= limit:
            return label


def read_catalog():
    with get_engine().connect() as conn:
        q = lambda sql: pd.read_sql(text(sql), conn)
        return (q(WHO_SQL).iloc[0].to_dict(), q(OBJECTS_SQL), q(COLUMNS_SQL),
                q(PRIMARY_KEYS_SQL), q(FOREIGN_KEYS_SQL), q(ROUTINES_SQL))


def build(objects, columns, primary_keys, foreign_keys):
    """One entry per table/view: rows, columns, primary key, links out and in."""
    full = lambda r, s="schema_name", o="object_name": f"{r[s]}.{r[o]}"
    cols, pks = defaultdict(list), defaultdict(list)
    for r in columns.sort_values("column_id").to_dict("records"):
        cols[full(r)].append({"name": r["column_name"], "type": type_label(r),
                              "nullable": bool(r["is_nullable"]), "identity": bool(r["is_identity"])})
    for r in primary_keys.sort_values("key_ordinal").to_dict("records"):
        pks[full(r)].append(r["column_name"])
    links = defaultdict(lambda: {"columns": [], "ref_columns": []})
    for r in foreign_keys.sort_values("constraint_column_id").to_dict("records"):
        link = links[(r["fk_name"], full(r))]
        link["table"], link["references"] = full(r), full(r, "ref_schema", "ref_object")
        link["columns"].append(r["column_name"])
        link["ref_columns"].append(r["ref_column"])
    out, referenced_by = {}, defaultdict(list)
    for link in links.values():
        referenced_by[link["references"]].append(link["table"])
    for r in objects.sort_values(["schema_name", "object_name"]).to_dict("records"):
        name = full(r)
        out[name] = {
            "schema": r["schema_name"], "name": r["object_name"], "kind": r["kind"],
            "rows": int(r["row_count"]) if pd.notna(r["row_count"]) else None,
            "created": str(r["create_date"])[:10], "modified": str(r["modify_date"])[:10],
            "primary_key": pks.get(name, []),
            "columns": cols.get(name, []),
            "links_out": [{"columns": l["columns"], "references": l["references"], "ref_columns": l["ref_columns"]}
                          for l in links.values() if l["table"] == name],
            "referenced_by": sorted(set(referenced_by.get(name, []))),
        }
    return out


def write_markdown(who, catalog, routines):
    tables = {n: o for n, o in catalog.items() if o["kind"] == "table"}
    views = {n: o for n, o in catalog.items() if o["kind"] == "view"}
    schemas = sorted({o["schema"] for o in catalog.values()} | set(routines["schema_name"]), key=str.lower)
    L = [f"# Inventory of {who['database_name']}", "",
         f"Read on {datetime.now():%Y-%m-%d %H:%M} from {who['server_name']} as {who['login_name']} "
         f"(SQL Server {who['version']}, {who['edition']}). Catalog only: no business data was read.", "",
         "## Totals", "",
         f"- Tables: {len(tables)} ({sum(o['rows'] or 0 for o in tables.values()):,} rows in all)",
         f"- Views: {len(views)}",
         f"- Columns: {sum(len(o['columns']) for o in catalog.values()):,}",
         f"- Tables with a primary key: {sum(bool(o['primary_key']) for o in tables.values())} of {len(tables)}",
         f"- Declared links (foreign keys): {sum(len(o['links_out']) for o in catalog.values())}",
         f"- Stored procedures: {(routines['kind'] == 'procedure').sum()}, functions: {(routines['kind'] == 'function').sum()}",
         "", "## Per schema", "",
         "| Schema | Tables | Views | Rows in its tables | Empty tables | Procedures/functions |",
         "|---|---:|---:|---:|---:|---:|"]
    for s in schemas:
        t = [o for o in tables.values() if o["schema"] == s]
        L.append(f"| {s} | {len(t)} | {sum(o['schema'] == s for o in views.values())} | "
                 f"{sum(o['rows'] or 0 for o in t):,} | {sum((o['rows'] or 0) == 0 for o in t)} | "
                 f"{(routines['schema_name'] == s).sum()} |")
    bands = Counter(size_band(o["rows"] or 0) for o in tables.values())
    L += ["", "## Tables by size", "", "| Rows | Tables |", "|---|---:|"]
    L += [f"| {label} | {bands.get(label, 0)} |" for _, label in SIZE_BANDS]
    L += ["", "## The 30 biggest tables", "", "| Table | Rows | Columns | Primary key |", "|---|---:|---:|---|"]
    for name, o in sorted(tables.items(), key=lambda x: -(x[1]["rows"] or 0))[:30]:
        L.append(f"| {name} | {o['rows']:,} | {len(o['columns'])} | {', '.join(o['primary_key']) or '-'} |")
    for s in schemas:
        objs = {n: o for n, o in catalog.items() if o["schema"] == s}
        if not objs:
            continue
        L += ["", f"## Schema {s}: every table and view", "",
              "| Name | Kind | Rows | Columns | Primary key | Links out | Linked from |", "|---|---|---:|---:|---|---:|---:|"]
        for name, o in objs.items():
            rows = "-" if o["rows"] is None else f"{o['rows']:,}"
            L.append(f"| {o['name']} | {o['kind']} | {rows} | {len(o['columns'])} | "
                     f"{', '.join(o['primary_key']) or '-'} | {len(o['links_out'])} | {len(o['referenced_by'])} |")
    with open(os.path.join(OUT_DIR, "inventory.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")


def main():
    print(f"Reading the catalog of {DB_NAME} ...")
    who, objects, columns, primary_keys, foreign_keys, routines = read_catalog()
    catalog = build(objects, columns, primary_keys, foreign_keys)
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, "catalog.json"), "w", encoding="utf-8") as f:
        json.dump({"read_at": f"{datetime.now():%Y-%m-%d %H:%M}", "connection": who,
                   "objects": catalog,
                   "routines": routines.sort_values(["schema_name", "routine_name"]).to_dict("records")},
                  f, indent=1, default=str)
    write_markdown(who, catalog, routines)
    tables = [o for o in catalog.values() if o["kind"] == "table"]
    print(f"Connected as {who['login_name']} to {who['database_name']} on {who['server_name']}")
    print(f"{len(tables)} tables, {len(catalog) - len(tables)} views, "
          f"{sum(len(o['columns']) for o in catalog.values()):,} columns, {len(routines)} procedures/functions")
    print(f"Saved {OUT_DIR}/catalog.json and {OUT_DIR}/inventory.md")


if __name__ == "__main__":
    main()
