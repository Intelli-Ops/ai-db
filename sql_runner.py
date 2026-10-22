"""
SQL runner: check AI-written SQL is safe, then run it.

The AI writes SQL, but it never gets to run anything it likes.
check_sql() reads the SQL with a parser (no AI) and refuses it unless:
  - it is exactly one statement
  - that statement only reads data (a SELECT)
  - it only touches the tables we approved

run_sql() then runs it and always rolls back, so nothing can be saved
to the database even if something slipped through.

For a real company database, also connect with a login that only has
read permission. That is the strongest protection of all.
"""
import re

import pandas as pd
import sqlglot
from sqlglot import exp

from db import get_engine

engine = get_engine()

QUERY_TIMEOUT_SECONDS = 60

# Tables no report may read, even if the AI asks for them.
BLOCKED_TABLES = set()

# Anything that changes data or the database itself.
FORBIDDEN = (
    exp.Insert, exp.Update, exp.Delete, exp.Merge, exp.Into,
    exp.Create, exp.Drop, exp.Alter, exp.TruncateTable, exp.Command,
)


def check_sql(sql, allowed_tables):
    """Return a list of problems. An empty list means the SQL is safe to run."""
    try:
        statements = [s for s in sqlglot.parse(sql, read="tsql") if s is not None]
    except sqlglot.errors.SqlglotError as e:
        return [f"The SQL could not be understood: {e}"]

    if len(statements) != 1:
        return [f"Expected exactly one SQL statement, found {len(statements)}."]
    statement = statements[0]
    if not isinstance(statement, exp.Query):
        return ["Only a SELECT statement is allowed."]

    problems = []
    for node in statement.walk():
        if isinstance(node, FORBIDDEN):
            problems.append(f"Not allowed in a report query: {type(node).__name__.upper()}.")

    allowed = {t.lower() for t in allowed_tables} - {t.lower() for t in BLOCKED_TABLES}
    # Names defined inside the query itself (WITH name AS ...) are fine.
    local_names = {cte.alias.lower() for cte in statement.find_all(exp.CTE)}
    for table in statement.find_all(exp.Table):
        if not table.db and table.name.lower() in local_names:
            continue
        # Include every part of the name, so OtherDatabase.Sales.X does not
        # pass just because Sales.X is approved.
        full_name = ".".join(p for p in (table.catalog, table.db, table.name) if p)
        if full_name.lower() not in allowed:
            problems.append(
                f"Table {full_name} is not in the approved list. "
                f"Use only: {', '.join(sorted(allowed_tables))}. "
                f"Always include the schema, e.g. dbo.BILL."
            )
    return sorted(set(problems))


def sql_type(value):
    """The SQL type to declare a report parameter with."""
    if isinstance(value, int):
        return "int"
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(value)):
        return "date"
    return "nvarchar(200)"


def describe_params(params):
    """e.g. '@start_date date, @end_date date' - shown to the AI and saved with the SQL."""
    return ", ".join(f"@{name} {sql_type(value)}" for name, value in params.items())


def run_sql(sql, params=None):
    """
    Run a SELECT and return the rows as a table (DataFrame).

    params are the report's inputs, e.g. {"start_date": "2025-03-01"}.
    The SQL refers to them as @start_date. Passing them separately means
    the same SQL can be re-run for any period without being edited.
    """
    params = params or {}
    declares = "".join(
        f"DECLARE @{name} {sql_type(value)} = ?; " for name, value in params.items()
    )
    with engine.connect() as conn:
        # A badly written query could run for hours. Stop it after a while;
        # the error goes back to the AI like any other.
        conn.connection.dbapi_connection.timeout = QUERY_TIMEOUT_SECONDS
        try:
            result = conn.exec_driver_sql(
                "SET NOCOUNT ON; " + declares + "\n" + sql, tuple(params.values())
            )
            return pd.DataFrame(result.fetchall(), columns=list(result.keys()))
        finally:
            conn.rollback()
