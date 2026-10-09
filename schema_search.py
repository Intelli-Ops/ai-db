"""
Schema search: find the tables a plain-English question needs.

The database stores a short description for every table and column
(saved in schema.json). This script turns each description into a list
of numbers (an "embedding") so that texts with a similar meaning get
similar numbers. A question is turned into numbers the same way, and
the tables whose descriptions are closest in meaning are returned.

That is how "revenue by region" can find Sales.SalesOrderHeader and
Sales.SalesTerritory even though neither word appears in their names.

The model runs on this machine. Nothing is sent to an outside service.

Run:  python schema_search.py
"""
import json
import os
import re
from pathlib import Path

import numpy as np

# Windows cannot make the shortcut files the downloader prefers. It works
# fine without them, so hide the warning it prints about that.
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

from fastembed import TextEmbedding  # noqa: E402

MODEL_NAME = "BAAI/bge-base-en-v1.5"  # free, about 210 MB
MODEL_DIR = Path.home() / ".cache" / "fastembed"  # downloaded once, reused after

SCHEMA_FILE = "schema.json"
INDEX_VECTORS = "schema_index.npy"   # the numbers for every description
INDEX_DOCS = "schema_index.json"     # which table/column each row of numbers is for

# Housekeeping columns that exist on almost every table and say nothing
# about what the table is for. Leaving them in only adds noise.
SKIP_COLUMNS = {"rowguid", "ModifiedDate"}

_model = None


def get_model():
    global _model
    if _model is None:
        _model = TextEmbedding(MODEL_NAME, cache_dir=str(MODEL_DIR))
    return _model


def split_words(name):
    """SalesOrderHeader -> Sales Order Header, so the model sees real words."""
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", name)


def build_docs(schema):
    """One piece of text per table, plus one per column."""
    docs = []
    for t in schema:
        schema_name, table_name = t["name"].split(".")
        table_words = split_words(table_name)
        columns = [c for c in t["columns"] if c["name"] not in SKIP_COLUMNS]

        column_list = ", ".join(split_words(c["name"]) for c in columns)
        docs.append({
            "table": t["name"],
            "column": None,
            "text": f"{table_words} ({split_words(schema_name)}): "
                    f"{t['description']} Columns: {column_list}",
        })
        for c in columns:
            docs.append({
                "table": t["name"],
                "column": c["name"],
                "text": f"{table_words} - {split_words(c['name'])}: {c['description']}",
            })
    return docs


def build_index():
    """Turn every description into numbers and save them."""
    with open(SCHEMA_FILE, encoding="utf-8") as f:
        schema = json.load(f)
    docs = build_docs(schema)
    vectors = np.array(list(get_model().embed([d["text"] for d in docs])))

    np.save(INDEX_VECTORS, vectors)
    with open(INDEX_DOCS, "w", encoding="utf-8") as f:
        json.dump(docs, f, indent=2, ensure_ascii=False)
    return docs, vectors


def load_index():
    """Load the saved index, rebuilding it if schema.json has changed since."""
    files = (INDEX_VECTORS, INDEX_DOCS)
    fresh = all(os.path.exists(p) for p in files) and all(
        os.path.getmtime(p) >= os.path.getmtime(SCHEMA_FILE) for p in files
    )
    if not fresh:
        return build_index()
    with open(INDEX_DOCS, encoding="utf-8") as f:
        docs = json.load(f)
    return docs, np.load(INDEX_VECTORS)


def search(question, top=10, index=None):
    """Return the tables that best match the question, best first."""
    docs, vectors = index or load_index()
    query = next(iter(get_model().query_embed(question)))
    # Vectors are length 1, so this dot product is the cosine similarity:
    # close to 1 means same meaning, close to 0 means unrelated.
    scores = vectors @ query

    tables = {}
    for doc, score in zip(docs, scores):
        entry = tables.setdefault(doc["table"], {"table_score": 0.0, "columns": []})
        if doc["column"] is None:
            entry["table_score"] = float(score)
        else:
            entry["columns"].append((doc["column"], float(score)))

    results = []
    for name, entry in tables.items():
        columns = sorted(entry["columns"], key=lambda c: c[1], reverse=True)
        best_column = columns[0][1] if columns else 0.0
        results.append({
            "table": name,
            # A table matches if its overall description matches, or if any
            # one of its columns does, whichever is stronger.
            "score": max(entry["table_score"], best_column),
            "columns": [c[0] for c in columns[:3]],
        })
    results.sort(key=lambda r: r["score"], reverse=True)
    return results[:top]


def search_each(texts, per_text=3, index=None):
    """
    Search several pieces of text and combine the best few from each.

    A written procedure talks about different things in different steps
    (orders in one step, product categories in another). Searching each
    step on its own finds the right table for each, where one search over
    the whole text blurs them together.
    """
    index = index or load_index()
    best = {}
    for text in texts:
        for r in search(text, top=per_text, index=index):
            if r["table"] not in best or r["score"] > best[r["table"]]["score"]:
                best[r["table"]] = r
    return sorted(best.values(), key=lambda r: r["score"], reverse=True)


# Test questions. For each one we list what a correct answer must contain.
# Each inner list is "any one of these tables will do" (for example, sales
# figures can come from the order header or from the order lines).
TEST_QUESTIONS = [
    ("Total sales by territory",
     [["Sales.SalesOrderHeader", "Sales.SalesOrderDetail"], ["Sales.SalesTerritory"]]),
    ("Show me revenue by region",
     [["Sales.SalesOrderHeader", "Sales.SalesOrderDetail"], ["Sales.SalesTerritory"]]),
    ("Sales by product category",
     [["Sales.SalesOrderHeader", "Sales.SalesOrderDetail"], ["Production.ProductCategory"]]),
    ("Sales by customer city",
     [["Sales.SalesOrderHeader", "Sales.SalesOrderDetail"], ["Person.Address"]]),
    ("How many employees work in each department",
     [["HumanResources.Employee", "HumanResources.EmployeeDepartmentHistory"],
      ["HumanResources.Department"]]),
    ("Average pay rate by job title",
     [["HumanResources.EmployeePayHistory"], ["HumanResources.Employee"]]),
    ("Which vendors supply each product",
     [["Purchasing.Vendor"], ["Production.Product", "Purchasing.ProductVendor"]]),
    ("Purchase order spend by vendor",
     [["Purchasing.PurchaseOrderHeader", "Purchasing.PurchaseOrderDetail"],
      ["Purchasing.Vendor"]]),
    ("Current stock on hand per warehouse location",
     [["Production.ProductInventory"], ["Production.Location"]]),
    ("Top selling products last year",
     [["Sales.SalesOrderDetail"], ["Production.Product"]]),
    ("Number of orders paid with each credit card type",
     [["Sales.SalesOrderHeader"], ["Sales.CreditCard"]]),
    ("Scrapped quantity by scrap reason",
     [["Production.WorkOrder"], ["Production.ScrapReason"]]),
    ("Sales quota versus actual sales for each salesperson",
     [["Sales.SalesPerson", "Sales.SalesPersonQuotaHistory"],
      ["Sales.SalesOrderHeader", "Sales.SalesOrderDetail"]]),
    ("Average customer rating for each product",
     [["Production.ProductReview"], ["Production.Product"]]),
    ("Money owed to us by each store",
     [["Sales.SalesOrderHeader"], ["Sales.Store"]]),
]

# Held-out questions. The search settings above were chosen by looking at
# TEST_QUESTIONS, so the score on those flatters us. These were written
# afterwards and never used for tuning, so they give the honest score.
# Do not adjust the search to fix these; add new questions instead.
HELD_OUT_QUESTIONS = [
    ("Headcount by shift",
     [["HumanResources.EmployeeDepartmentHistory", "HumanResources.Employee"],
      ["HumanResources.Shift"]]),
    ("Which products are low on inventory and need reordering",
     [["Production.ProductInventory"], ["Production.Product"]]),
    ("Number of order lines sold under each special offer",
     [["Sales.SpecialOffer"], ["Sales.SalesOrderDetail", "Sales.SpecialOfferProduct"]]),
    ("Freight cost by shipping method",
     [["Purchasing.ShipMethod"],
      ["Sales.SalesOrderHeader", "Purchasing.PurchaseOrderHeader"]]),
    ("Why do customers buy from us: orders by sales reason",
     [["Sales.SalesReason"],
      ["Sales.SalesOrderHeaderSalesReason", "Sales.SalesOrderHeader"]]),
    ("Manufacturing cost by work centre",
     [["Production.WorkOrderRouting"], ["Production.Location"]]),
    ("Tax collected by state",
     [["Sales.SalesOrderHeader", "Sales.SalesTaxRate"], ["Person.StateProvince"]]),
    ("Email addresses of all our contacts",
     [["Person.EmailAddress"], ["Person.Person"]]),
    ("Parts needed to build each bicycle",
     [["Production.BillOfMaterials"], ["Production.Product"]]),
    ("Orders placed in a foreign currency",
     [["Sales.SalesOrderHeader"], ["Sales.CurrencyRate", "Sales.Currency"]]),
]


def run_questions(title, questions, index, top):
    """Search for each question and count how often nothing needed is missed."""
    print(f"\n===== {title} =====")
    passed = 0
    for question, needed in questions:
        results = search(question, top=top, index=index)
        found = {r["table"] for r in results}
        missing = [" or ".join(group) for group in needed if not found & set(group)]
        passed += not missing

        print(f"\nQ: {question}")
        for r in results:
            mark = "*" if any(r["table"] in group for group in needed) else " "
            print(f"  {mark} {r['score']:.2f}  {r['table']:<42} {', '.join(r['columns'])}")
        if missing:
            print(f"  MISSED: {'; '.join(missing)}")
    return passed


def main():
    index = load_index()
    docs, _ = index
    n_tables = sum(1 for d in docs if d["column"] is None)
    print(f"Index ready: {n_tables} tables, {len(docs) - n_tables} columns")

    top = 10
    tuned = run_questions("Test questions (used to choose settings)", TEST_QUESTIONS, index, top)
    held_out = run_questions("Held-out questions (the honest score)", HELD_OUT_QUESTIONS, index, top)

    print(f"\nQuestions where every needed table was in the top {top}:")
    print(f"  Test questions:     {tuned} of {len(TEST_QUESTIONS)}")
    print(f"  Held-out questions: {held_out} of {len(HELD_OUT_QUESTIONS)}")


if __name__ == "__main__":
    main()
