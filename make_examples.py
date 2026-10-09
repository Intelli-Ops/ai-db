"""
Make example reports for the POC to learn from.

In real life a person already produces each report by hand, so we would
be given three things: the written procedure (SOP), the report for one
month, and the report for another month to test with.

AdventureWorks has no such reports, so this script plays the part of
that person. For each report it writes, into reports/<name>/ :
  sop.txt               the written procedure, in plain English
  case.json             the question, the periods, and the key column(s)
  expected.csv          the report for the first month  (shown to the AI)
  expected_holdout.csv  the report for the second month (never shown to the AI)

IMPORTANT: the SQL in this file is the "answer key". It is used only to
produce the expected CSV files. The AI never sees it.

Run:  python make_examples.py
"""
import json
from pathlib import Path

from sql_runner import run_sql

REPORTS_DIR = Path("reports")

FIRST_MONTH = {"start_date": "2025-03-01", "end_date": "2025-03-31"}
HOLDOUT_MONTH = {"start_date": "2025-04-01", "end_date": "2025-04-30"}

EXAMPLES = [
    {
        "name": "sales_by_territory",
        "question": "Monthly sales by territory",
        "key": ["Territory"],
        "sop": """Monthly sales by territory

1. Take every sales order whose order date is within the report period
   (from the start date to the end date, both included).
2. For each sales territory, count the orders and add up the order
   subtotal (the amount before tax and freight).
3. Show three columns: Territory (the territory name), Orders, Sales.
   Round Sales to 2 decimal places.
4. Sort by Sales, largest first.
""",
        "answer_key": """
            SELECT t.Name AS Territory,
                   COUNT(*) AS Orders,
                   CAST(ROUND(SUM(h.SubTotal), 2) AS decimal(18, 2)) AS Sales
            FROM Sales.SalesOrderHeader h
            JOIN Sales.SalesTerritory t ON t.TerritoryID = h.TerritoryID
            WHERE h.OrderDate >= @start_date AND h.OrderDate < DATEADD(day, 1, @end_date)
            GROUP BY t.Name
            ORDER BY Sales DESC
        """,
    },
    {
        "name": "sales_by_category",
        "question": "Monthly sales by product category",
        "key": ["Category"],
        "sop": """Monthly sales by product category

1. Take every sales order whose order date is within the report period
   (from the start date to the end date, both included).
2. Look at each line of those orders and find the category of the
   product on that line.
3. For each product category, add up the quantity ordered and the
   line total.
4. Show three columns: Category (the category name), Units, Sales.
   Round Sales to 2 decimal places.
5. Sort by Category name, A to Z.
""",
        "answer_key": """
            SELECT c.Name AS Category,
                   SUM(d.OrderQty) AS Units,
                   CAST(ROUND(SUM(d.LineTotal), 2) AS decimal(18, 2)) AS Sales
            FROM Sales.SalesOrderHeader h
            JOIN Sales.SalesOrderDetail d ON d.SalesOrderID = h.SalesOrderID
            JOIN Production.Product p ON p.ProductID = d.ProductID
            JOIN Production.ProductSubcategory s ON s.ProductSubcategoryID = p.ProductSubcategoryID
            JOIN Production.ProductCategory c ON c.ProductCategoryID = s.ProductCategoryID
            WHERE h.OrderDate >= @start_date AND h.OrderDate < DATEADD(day, 1, @end_date)
            GROUP BY c.Name
            ORDER BY c.Name
        """,
    },
    {
        # This one is wrong ON PURPOSE. The SOP says "subtotal", but the
        # person who made the spreadsheet actually used TotalDue (which
        # includes tax and freight). The system should notice the SOP and
        # the expected output disagree and flag it for a person. It should
        # NOT quietly switch to TotalDue just to make the numbers match.
        "name": "sales_by_salesperson",
        "question": "Monthly sales by salesperson",
        "key": ["Salesperson"],
        "sop": """Monthly sales by salesperson

1. Take every sales order whose order date is within the report period
   (from the start date to the end date, both included).
2. Keep only orders that were made by a salesperson. Ignore online
   orders, which have no salesperson.
3. For each salesperson, count the orders and add up the order
   subtotal (the amount before tax and freight).
4. Show three columns: Salesperson (first name, a space, last name),
   Orders, Sales. Round Sales to 2 decimal places.
5. Sort by Sales, largest first.
""",
        "answer_key": """
            SELECT p.FirstName + ' ' + p.LastName AS Salesperson,
                   COUNT(*) AS Orders,
                   CAST(ROUND(SUM(h.TotalDue), 2) AS decimal(18, 2)) AS Sales
            FROM Sales.SalesOrderHeader h
            JOIN Person.Person p ON p.BusinessEntityID = h.SalesPersonID
            WHERE h.OrderDate >= @start_date AND h.OrderDate < DATEADD(day, 1, @end_date)
            GROUP BY p.FirstName, p.LastName
            ORDER BY Sales DESC
        """,
    },
]


def main():
    for example in EXAMPLES:
        folder = REPORTS_DIR / example["name"]
        folder.mkdir(parents=True, exist_ok=True)

        (folder / "sop.txt").write_text(example["sop"], encoding="utf-8")
        case = {
            "question": example["question"],
            "key": example["key"],
            "params": FIRST_MONTH,
            "holdout_params": HOLDOUT_MONTH,
        }
        (folder / "case.json").write_text(json.dumps(case, indent=2), encoding="utf-8")

        first = run_sql(example["answer_key"], FIRST_MONTH)
        holdout = run_sql(example["answer_key"], HOLDOUT_MONTH)
        first.to_csv(folder / "expected.csv", index=False)
        holdout.to_csv(folder / "expected_holdout.csv", index=False)
        print(f"{example['name']}: {len(first)} rows for the first month, "
              f"{len(holdout)} rows for the held-out month")


if __name__ == "__main__":
    main()
