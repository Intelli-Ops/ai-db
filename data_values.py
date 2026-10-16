"""
Data values: the real values the database stores, so the AI can use them.

People do not type values the way the database stores them. Someone asks
for "European countries" and the database says 'Europe'; someone asks for
"completed orders" and the database stores the number 5. A query written
with the user's words runs without error and returns nothing.

This file does the first two steps. Only the database is read; no AI.

Step 1: decide which columns are worth collecting values from.
A column is kept when it is one of these:
  - a text column with a small number of different values, such as
    SalesTerritory.[Group] (3 values) or ProductSubcategory.Name (37)
  - a number column whose description lists what each code means,
    such as SalesOrderHeader.Status ("1 = In process; ... 5 = Shipped")

Step 2: collect the values and save them to data_values.json.
  - text columns: every different value stored, e.g. 'Europe'
  - code columns: each code with its meaning, read from the
    description, e.g. 5 = 'Shipped'

Run:  python data_values.py            (collect and save)
      python data_values.py --columns  (also list every column and why)
"""
import json
import re
import sys

from schema_search import SCHEMA_FILE, SKIP_COLUMNS
from sql_runner import BLOCKED_TABLES, run_sql

VALUES_FILE = "data_values.json"

TEXT_TYPES = {"nvarchar", "nchar", "varchar", "char"}
CODE_TYPES = {"bit", "tinyint", "smallint", "int"}

# More different values than this and the column is a list of one-off
# entries (order numbers, street addresses), not a set of categories.
MAX_VALUES = 1000
# Longer than this on average and the column is free text (comments,
# descriptions), which people do not filter on word for word.
MAX_AVERAGE_LENGTH = 40

# "1 = In process; 2 = Approved" in a column description
CODE_LIST = re.compile(r"\b\d+\s*=\s*[A-Za-z]")
CODE_START = re.compile(r"\b(\d+)\s*=\s*")

# Details about individual people. Keep them out of the AI's reach until
# someone decides otherwise.
PRIVATE_TABLES = {
    "Person.Person", "Person.EmailAddress", "Person.PersonPhone",
    "Person.Password", "Sales.PersonCreditCard",
}
PRIVATE_COLUMNS = {
    ("HumanResources.Employee", "NationalIDNumber"),
    ("HumanResources.Employee", "LoginID"),
    ("Production.ProductReview", "ReviewerName"),
    ("Production.ProductReview", "EmailAddress"),
    ("Sales.CreditCard", "CardNumber"),  # the card type (Vista, ...) is fine
}

# Columns nobody filters a report by, whatever their number of values.
NOT_CATEGORIES = ("FileName", "URL", "AddressLine")


def quoted(table):
    """Sales.SalesTerritory -> [Sales].[SalesTerritory]"""
    return ".".join(f"[{part}]" for part in table.split("."))


def first_look(table, column):
    """How many different values a text column has, and how long they are."""
    found = run_sql(
        f"SELECT COUNT(DISTINCT [{column}]) AS n, AVG(CAST(LEN([{column}]) AS float)) AS avg_len "
        f"FROM {quoted(table)}"
    )
    return int(found.iloc[0]["n"]), float(found.iloc[0]["avg_len"] or 0)


def choose_columns(schema):
    """Return (kept, skipped). Each skipped column says why."""
    kept, skipped = [], []
    for t in schema:
        keys = set(t["primary_key"]) | {fk["column"] for fk in t["foreign_keys"]}
        for c in t["columns"]:
            where = (t["name"], c["name"])
            if c["type"] not in TEXT_TYPES | CODE_TYPES:
                continue  # dates, amounts, ids stored as GUIDs and so on
            if t["name"].startswith("dbo.") or c["name"] in SKIP_COLUMNS:
                reason = "housekeeping"
            elif t["name"] in PRIVATE_TABLES | BLOCKED_TABLES or where in PRIVATE_COLUMNS:
                reason = "about individual people"
            elif c["name"] in keys or c["name"].endswith(("ID", "Number")):
                reason = "identifier"
            elif any(part in c["name"] for part in NOT_CATEGORIES):
                reason = "file name, web link or street address"
            elif c["type"] in CODE_TYPES:
                if not CODE_LIST.search(c["description"] or ""):
                    continue  # an ordinary number, such as a quantity
                kept.append({"table": t["name"], "column": c["name"], "kind": "code",
                             "description": c["description"]})
                continue
            else:
                n, avg_len = first_look(*where)
                if n > MAX_VALUES:
                    reason = f"too many different values ({n:,})"
                elif avg_len > MAX_AVERAGE_LENGTH:
                    reason = f"free text (about {avg_len:.0f} characters)"
                elif n < 2:
                    reason = "fewer than 2 values"
                else:
                    kept.append({"table": t["name"], "column": c["name"], "kind": "text",
                                 "values": n, "description": c["description"]})
                    continue
            skipped.append({"table": t["name"], "column": c["name"], "reason": reason})
    return kept, skipped


def read_codes(description):
    """
    "1 = In process; 2 = Approved; 5 = Shipped" -> [(1, "In process"), ...]
    Each meaning runs until the next "number =", minus the separator.
    """
    starts = list(CODE_START.finditer(description))
    codes = []
    for this, after in zip(starts, starts[1:] + [None]):
        meaning = description[this.end():after.start() if after else None]
        codes.append((int(this.group(1)), meaning.strip(" ;,.")))
    return codes


def collect_values(kept):
    """Every value worth knowing, one entry each."""
    values = []
    for k in kept:
        where = {"table": k["table"], "column": k["column"]}
        if k["kind"] == "code":
            for code, meaning in read_codes(k["description"]):
                values.append({**where, "value": code, "meaning": meaning})
        else:
            found = run_sql(
                f"SELECT DISTINCT [{k['column']}] AS v FROM {quoted(k['table'])} "
                f"WHERE [{k['column']}] IS NOT NULL"
            )
            for v in sorted(str(v).strip() for v in found["v"]):
                values.append({**where, "value": v})
    return values


def print_choice(kept, skipped):
    print(f"===== Kept: {len(kept)} columns =====")
    print("\nText columns (values to collect):")
    for k in sorted((k for k in kept if k["kind"] == "text"), key=lambda k: k["values"]):
        print(f"  {k['values']:>5}  {k['table']}.{k['column']}")
    print("\nNumber columns with codes (meanings come from the description):")
    for k in (k for k in kept if k["kind"] == "code"):
        print(f"         {k['table']}.{k['column']}: {k['description'][:70]}")

    print(f"\n===== Skipped: {len(skipped)} columns =====")
    for s in sorted(skipped, key=lambda s: (s["reason"], s["table"])):
        print(f"  {s['table']}.{s['column']}: {s['reason']}")


def main():
    with open(SCHEMA_FILE, encoding="utf-8") as f:
        schema = json.load(f)
    kept, skipped = choose_columns(schema)
    if "--columns" in sys.argv:
        print_choice(kept, skipped)

    values = collect_values(kept)
    with open(VALUES_FILE, "w", encoding="utf-8") as f:
        json.dump(values, f, indent=2, ensure_ascii=False)

    codes = [v for v in values if "meaning" in v]
    print(f"Kept {len(kept)} columns, skipped {len(skipped)}.")
    print(f"Saved {len(values)} values to {VALUES_FILE}: "
          f"{len(values) - len(codes)} stored text values, {len(codes)} codes.")

    # A few to check by eye.
    for table, column in [("Sales.SalesTerritory", "Group"),
                          ("Purchasing.ShipMethod", "Name"),
                          ("Sales.SalesOrderHeader", "Status")]:
        found = [v for v in values if (v["table"], v["column"]) == (table, column)]
        shown = ", ".join(f"{v['value']} = {v['meaning']}" if "meaning" in v else v["value"]
                          for v in found)
        print(f"  {table}.{column}: {shown}")


if __name__ == "__main__":
    main()
