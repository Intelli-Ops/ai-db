"""
Phase 1: Extract the database schema into schema.json.

For every table, this reads:
  - its columns and data types
  - its primary key (the column that uniquely identifies each row)
  - its foreign keys (links to other tables)
  - any built-in descriptions stored in the database (MS_Description)

schema.json is the raw material for:
  - Phase 2: schema RAG (we embed table and column descriptions)
  - Phase 3: schema graph (tables become nodes, foreign keys become edges)
"""
import json

import pandas as pd

from db import get_engine

engine = get_engine()

# Every column of every real table (views are excluded)
COLUMNS_SQL = """
SELECT c.TABLE_SCHEMA, c.TABLE_NAME, c.COLUMN_NAME, c.DATA_TYPE, c.IS_NULLABLE
FROM INFORMATION_SCHEMA.COLUMNS c
JOIN INFORMATION_SCHEMA.TABLES t
  ON t.TABLE_SCHEMA = c.TABLE_SCHEMA AND t.TABLE_NAME = c.TABLE_NAME
WHERE t.TABLE_TYPE = 'BASE TABLE'
ORDER BY c.TABLE_SCHEMA, c.TABLE_NAME, c.ORDINAL_POSITION
"""

# Which columns form each table's primary key
PRIMARY_KEYS_SQL = """
SELECT k.TABLE_SCHEMA, k.TABLE_NAME, k.COLUMN_NAME
FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc
JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE k
  ON k.CONSTRAINT_NAME = tc.CONSTRAINT_NAME
 AND k.TABLE_SCHEMA = tc.TABLE_SCHEMA
WHERE tc.CONSTRAINT_TYPE = 'PRIMARY KEY'
"""

# Every foreign key: "column X in table A points to column Y in table B"
FOREIGN_KEYS_SQL = """
SELECT
    fk.name                    AS fk_name,
    SCHEMA_NAME(tp.schema_id)  AS from_schema,
    tp.name                    AS from_table,
    cp.name                    AS from_column,
    SCHEMA_NAME(tr.schema_id)  AS to_schema,
    tr.name                    AS to_table,
    cr.name                    AS to_column
FROM sys.foreign_keys fk
JOIN sys.foreign_key_columns fkc ON fkc.constraint_object_id = fk.object_id
JOIN sys.tables  tp ON tp.object_id = fkc.parent_object_id
JOIN sys.columns cp ON cp.object_id = fkc.parent_object_id
                   AND cp.column_id = fkc.parent_column_id
JOIN sys.tables  tr ON tr.object_id = fkc.referenced_object_id
JOIN sys.columns cr ON cr.object_id = fkc.referenced_object_id
                   AND cr.column_id = fkc.referenced_column_id
"""

# Built-in descriptions. column_name is NULL for table-level descriptions.
DESCRIPTIONS_SQL = """
SELECT
    SCHEMA_NAME(t.schema_id)          AS table_schema,
    t.name                            AS table_name,
    c.name                            AS column_name,
    CAST(ep.value AS NVARCHAR(4000))  AS description
FROM sys.extended_properties ep
JOIN sys.tables t ON t.object_id = ep.major_id
LEFT JOIN sys.columns c ON c.object_id = ep.major_id
                       AND c.column_id = ep.minor_id
WHERE ep.name = 'MS_Description' AND ep.class = 1
"""


def full_name(schema, table):
    return f"{schema}.{table}"


def main():
    print("Reading schema from the database...")
    cols = pd.read_sql(COLUMNS_SQL, engine)
    pks = pd.read_sql(PRIMARY_KEYS_SQL, engine)
    fks = pd.read_sql(FOREIGN_KEYS_SQL, engine)
    descs = pd.read_sql(DESCRIPTIONS_SQL, engine)

    # Split descriptions into table-level and column-level lookups
    table_desc, col_desc = {}, {}
    for r in descs.itertuples(index=False):
        name = full_name(r.table_schema, r.table_name)
        if pd.isna(r.column_name):
            table_desc[name] = r.description
        else:
            col_desc[(name, r.column_name)] = r.description

    # Build one entry per table
    tables = {}
    for r in cols.itertuples(index=False):
        name = full_name(r.TABLE_SCHEMA, r.TABLE_NAME)
        table = tables.setdefault(name, {
            "name": name,
            "description": table_desc.get(name, ""),
            "columns": [],
            "primary_key": [],
            "foreign_keys": [],
        })
        table["columns"].append({
            "name": r.COLUMN_NAME,
            "type": r.DATA_TYPE,
            "nullable": r.IS_NULLABLE == "YES",
            "description": col_desc.get((name, r.COLUMN_NAME), ""),
        })

    for r in pks.itertuples(index=False):
        name = full_name(r.TABLE_SCHEMA, r.TABLE_NAME)
        if name in tables:
            tables[name]["primary_key"].append(r.COLUMN_NAME)

    for r in fks.itertuples(index=False):
        src = full_name(r.from_schema, r.from_table)
        if src in tables:
            tables[src]["foreign_keys"].append({
                "fk_name": r.fk_name,
                "column": r.from_column,
                "references_table": full_name(r.to_schema, r.to_table),
                "references_column": r.to_column,
            })

    with open("schema.json", "w", encoding="utf-8") as f:
        json.dump(list(tables.values()), f, indent=2, ensure_ascii=False)

    # Summary so you can see what was extracted
    n_cols = sum(len(t["columns"]) for t in tables.values())
    n_fks = sum(len(t["foreign_keys"]) for t in tables.values())
    n_desc = sum(1 for t in tables.values() if t["description"])
    print(f"Tables:            {len(tables)}")
    print(f"Columns:           {n_cols}")
    print(f"Foreign key links: {n_fks}")
    print(f"Tables with a description: {n_desc}")
    print("Saved to schema.json")

    # Show one table as an example
    example = tables.get("Sales.SalesOrderHeader")
    if example:
        print("\nExample - Sales.SalesOrderHeader")
        print("  Description:", example["description"])
        print("  Primary key:", example["primary_key"])
        print("  Links to:")
        for fk in example["foreign_keys"]:
            print(f"    {fk['column']} -> {fk['references_table']}.{fk['references_column']}")


if __name__ == "__main__":
    main()
