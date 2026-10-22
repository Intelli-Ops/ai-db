"""
Step 0 on a new database: find out what is in it before building anything.

Read-only. It only asks the database's own catalog ("what tables exist,
what columns do they have") and never reads the business data itself,
except for row counts, which also come from the catalog.

It answers, in order:
  1. Who am I connected as, and to what?
  2. Which schemas can I see, and how many tables/views are in each?
  3. For our schema (DB_SCHEMA, e.g. EPM): every table and view, with
     row count, columns, primary key, links (foreign keys), descriptions.
  4. Stored procedures and functions in that schema (names only).

Writes:
  <database>/<schema>/overview.md   - readable summary, one section per table
  <database>/<schema>/catalog.json  - the same information for later scripts

Usage:  python explore_db.py            (uses DB_SCHEMA from .env)
        python explore_db.py EAMS
        python explore_db.py all        (every schema with tables or views)
"""
import json
import os
import sys

import pandas as pd

from db import DB_NAME, DB_SCHEMA, DB_SERVER, get_engine

engine = get_engine()

WHO_SQL = """
SELECT @@SERVERNAME AS server_name, DB_NAME() AS database_name,
       SUSER_SNAME() AS login_name, USER_NAME() AS user_name,
       CAST(SERVERPROPERTY('ProductVersion') AS NVARCHAR(50)) AS version,
       CAST(SERVERPROPERTY('Edition') AS NVARCHAR(100)) AS edition
"""

# Every schema I can see, with a count of each kind of object in it
SCHEMAS_SQL = """
SELECT s.name AS schema_name,
       SUM(CASE WHEN o.type = 'U'  THEN 1 ELSE 0 END) AS tables,
       SUM(CASE WHEN o.type = 'V'  THEN 1 ELSE 0 END) AS views,
       SUM(CASE WHEN o.type = 'P'  THEN 1 ELSE 0 END) AS procedures,
       SUM(CASE WHEN o.type IN ('FN','IF','TF') THEN 1 ELSE 0 END) AS functions
FROM sys.schemas s
LEFT JOIN sys.objects o ON o.schema_id = s.schema_id
GROUP BY s.name
HAVING COUNT(o.object_id) > 0
ORDER BY s.name
"""

# Tables and views in one schema. Row counts come from the catalog, not COUNT(*).
OBJECTS_SQL = """
SELECT o.name AS object_name,
       CASE o.type WHEN 'U' THEN 'table' ELSE 'view' END AS kind,
       o.create_date, o.modify_date,
       (SELECT SUM(p.rows) FROM sys.partitions p
         WHERE p.object_id = o.object_id AND p.index_id IN (0, 1)) AS row_count,
       CAST(ep.value AS NVARCHAR(4000)) AS description
FROM sys.objects o
LEFT JOIN sys.extended_properties ep
  ON ep.major_id = o.object_id AND ep.minor_id = 0
 AND ep.class = 1 AND ep.name = 'MS_Description'
WHERE o.type IN ('U', 'V') AND SCHEMA_NAME(o.schema_id) = :schema
ORDER BY o.type, o.name
"""

COLUMNS_SQL = """
SELECT o.name AS object_name, c.column_id, c.name AS column_name,
       TYPE_NAME(c.user_type_id) AS data_type, c.max_length, c.precision, c.scale,
       c.is_nullable, c.is_identity, c.is_computed,
       CAST(ep.value AS NVARCHAR(4000)) AS description
FROM sys.columns c
JOIN sys.objects o ON o.object_id = c.object_id
LEFT JOIN sys.extended_properties ep
  ON ep.major_id = c.object_id AND ep.minor_id = c.column_id
 AND ep.class = 1 AND ep.name = 'MS_Description'
WHERE o.type IN ('U', 'V') AND SCHEMA_NAME(o.schema_id) = :schema
ORDER BY o.name, c.column_id
"""

PRIMARY_KEYS_SQL = """
SELECT t.name AS object_name, c.name AS column_name, ic.key_ordinal
FROM sys.indexes i
JOIN sys.index_columns ic ON ic.object_id = i.object_id AND ic.index_id = i.index_id
JOIN sys.columns c ON c.object_id = ic.object_id AND c.column_id = ic.column_id
JOIN sys.tables t ON t.object_id = i.object_id
WHERE i.is_primary_key = 1 AND SCHEMA_NAME(t.schema_id) = :schema
ORDER BY t.name, ic.key_ordinal
"""

# Links that start in our schema (they may point into other schemas)
FOREIGN_KEYS_SQL = """
SELECT fk.name AS fk_name, tp.name AS from_table, cp.name AS from_column,
       SCHEMA_NAME(tr.schema_id) AS to_schema, tr.name AS to_table, cr.name AS to_column
FROM sys.foreign_keys fk
JOIN sys.foreign_key_columns fkc ON fkc.constraint_object_id = fk.object_id
JOIN sys.tables tp ON tp.object_id = fkc.parent_object_id
JOIN sys.columns cp ON cp.object_id = fkc.parent_object_id AND cp.column_id = fkc.parent_column_id
JOIN sys.tables tr ON tr.object_id = fkc.referenced_object_id
JOIN sys.columns cr ON cr.object_id = fkc.referenced_object_id AND cr.column_id = fkc.referenced_column_id
WHERE SCHEMA_NAME(tp.schema_id) = :schema
ORDER BY tp.name, fk.name
"""

ROUTINES_SQL = """
SELECT o.name, CASE o.type WHEN 'P' THEN 'procedure' ELSE 'function' END AS kind,
       o.modify_date
FROM sys.objects o
WHERE o.type IN ('P', 'FN', 'IF', 'TF') AND SCHEMA_NAME(o.schema_id) = :schema
ORDER BY o.type, o.name
"""


def q(sql, schema=None):
    from sqlalchemy import text
    with engine.connect() as conn:
        return pd.read_sql(text(sql), conn, params={"schema": schema} if schema else None)


def type_label(r):
    t = r.data_type
    if t in ("varchar", "char", "varbinary", "binary"):
        return f"{t}({'max' if r.max_length == -1 else r.max_length})"
    if t in ("nvarchar", "nchar"):
        return f"{t}({'max' if r.max_length == -1 else r.max_length // 2})"
    if t in ("decimal", "numeric"):
        return f"{t}({r.precision},{r.scale})"
    return t


def clean(v):
    return "" if v is None or (isinstance(v, float) and pd.isna(v)) else v


def main():
    wanted = sys.argv[1] if len(sys.argv) > 1 else DB_SCHEMA
    if not wanted:
        sys.exit("Say which schema to explore: set DB_SCHEMA in .env or run  python explore_db.py all")

    print(f"Connecting to {DB_SERVER} / {DB_NAME} ...")
    who = q(WHO_SQL).iloc[0]
    print(f"Connected as {who.login_name} (user {who.user_name}), SQL Server {who.version} {who.edition}")

    schemas = q(SCHEMAS_SQL)
    print("\nSchemas I can see:")
    print(schemas.to_string(index=False))

    if wanted.lower() == "all":
        names = schemas[(schemas.tables + schemas.views) > 0].schema_name.tolist()
    else:
        names = [wanted]
    for schema in names:
        explore_schema(schema, who, schemas)


def explore_schema(schema, who, schemas):
    objects = q(OBJECTS_SQL, schema)
    columns = q(COLUMNS_SQL, schema)
    pks = q(PRIMARY_KEYS_SQL, schema)
    fks = q(FOREIGN_KEYS_SQL, schema)
    routines = q(ROUTINES_SQL, schema)

    # Who points at me (so each table shows both directions of its links)
    incoming = fks[fks.to_schema == schema]

    catalog = []
    for o in objects.itertuples(index=False):
        cols = columns[columns.object_name == o.object_name]
        catalog.append({
            "name": f"{schema}.{o.object_name}",
            "kind": o.kind,
            "row_count": None if pd.isna(o.row_count) else int(o.row_count),
            "created": str(o.create_date)[:10],
            "modified": str(o.modify_date)[:10],
            "description": clean(o.description),
            "primary_key": pks[pks.object_name == o.object_name].column_name.tolist(),
            "columns": [{
                "name": c.column_name,
                "type": type_label(c),
                "nullable": bool(c.is_nullable),
                "identity": bool(c.is_identity),
                "description": clean(c.description),
            } for c in cols.itertuples(index=False)],
            "foreign_keys": [{
                "column": f.from_column,
                "references": f"{f.to_schema}.{f.to_table}.{f.to_column}",
            } for f in fks[fks.from_table == o.object_name].itertuples(index=False)],
            "referenced_by": [
                f"{schema}.{f.from_table}.{f.from_column}"
                for f in incoming[incoming.to_table == o.object_name].itertuples(index=False)
            ],
        })

    out_dir = os.path.join(DB_NAME, schema)
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "catalog.json"), "w", encoding="utf-8") as f:
        json.dump({
            "server": DB_SERVER, "database": DB_NAME, "schema": schema,
            "connected_as": who.login_name,
            "schemas_visible": schemas.to_dict("records"),
            "objects": catalog,
            "routines": [{"name": r.name, "kind": r.kind, "modified": str(r.modify_date)[:10]}
                         for r in routines.itertuples(index=False)],
        }, f, indent=2, ensure_ascii=False, default=str)

    write_overview(out_dir, schema, who, schemas, catalog, routines)

    tables = [t for t in catalog if t["kind"] == "table"]
    print(f"\nSchema {schema}:")
    print(f"  Tables: {len(tables)}   Views: {len(catalog) - len(tables)}   "
          f"Procedures/functions: {len(routines)}")
    print(f"  Columns: {sum(len(t['columns']) for t in catalog)}")
    print(f"  Foreign key links: {len(fks)}")
    print(f"  Tables with a primary key: {sum(1 for t in tables if t['primary_key'])}")
    print(f"  Objects with a description: {sum(1 for t in catalog if t['description'])}")
    print(f"  Empty tables (0 rows): {sum(1 for t in tables if t['row_count'] == 0)}")
    print(f"  Saved {out_dir}/overview.md and catalog.json")


def write_overview(out_dir, schema, who, schemas, catalog, routines):
    L = [f"# {DB_NAME} - schema {schema}", "",
         f"Server `{DB_SERVER}`, connected as `{who.login_name}`, SQL Server {who.version} ({who.edition}).", "",
         "## Schemas visible to this login", "",
         "| Schema | Tables | Views | Procedures | Functions |", "|---|---|---|---|---|"]
    for s in schemas.itertuples(index=False):
        L.append(f"| {s.schema_name} | {s.tables} | {s.views} | {s.procedures} | {s.functions} |")

    L += ["", f"## Everything in {schema}, biggest first", "",
          "| Name | Kind | Rows | Columns | PK | Links out | Links in | Description |",
          "|---|---|---|---|---|---|---|---|"]
    for t in sorted(catalog, key=lambda t: -(t["row_count"] or 0)):
        rows = "" if t["row_count"] is None else f"{t['row_count']:,}"
        L.append(f"| {t['name']} | {t['kind']} | {rows} | {len(t['columns'])} | "
                 f"{'yes' if t['primary_key'] else '-'} | {len(t['foreign_keys'])} | "
                 f"{len(t['referenced_by'])} | {t['description'][:80]} |")

    for t in catalog:
        rows = "n/a" if t["row_count"] is None else f"{t['row_count']:,}"
        L += ["", f"## {t['name']} ({t['kind']}, {rows} rows)", ""]
        if t["description"]:
            L += [t["description"], ""]
        L.append(f"Primary key: {', '.join(t['primary_key']) or 'none'}  ")
        L.append(f"Created {t['created']}, last changed {t['modified']}")
        L += ["", "| Column | Type | Null? | Links to | Description |", "|---|---|---|---|---|"]
        links = {f["column"]: f["references"] for f in t["foreign_keys"]}
        for c in t["columns"]:
            name = f"**{c['name']}**" if c["name"] in t["primary_key"] else c["name"]
            L.append(f"| {name} | {c['type']} | {'yes' if c['nullable'] else 'no'} | "
                     f"{links.get(c['name'], '')} | {c['description']} |")
        if t["referenced_by"]:
            L += ["", "Referenced by: " + ", ".join(t["referenced_by"])]

    if len(routines):
        L += ["", f"## Procedures and functions in {schema}", ""]
        L += [f"- {r.name} ({r.kind}, changed {str(r.modify_date)[:10]})"
              for r in routines.itertuples(index=False)]

    with open(os.path.join(out_dir, "overview.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")


if __name__ == "__main__":
    main()
