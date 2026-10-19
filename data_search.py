"""
Data search: find the stored values that a question's words refer to.

data_values.py collected the real values (Europe, Road Bikes,
XRQ - TRUCK GROUND, status 5 = Shipped). This file turns each one into
a list of numbers (an "embedding"), using the same model as
schema_search.py, so that words with a similar meaning get similar
numbers. "European countries" will then land close to 'Europe'.

Each value is embedded together with where it lives, so 'Red' the colour
and 'Red' in some other column do not look the same:
    Sales Territory - Group: Europe
    Sales Order Header - Status: Shipped     (the meaning, not the number 5)

The model runs on this machine. Nothing is sent to an outside service.

To search, the question is cut into short phrases ("red", "road bikes",
"shipped by truck") as well as kept whole, because one question can
mention several values. Each phrase keeps its own best matches.

All values are searched, not only those in tables schema search picked.
A value can point to a table nobody named: "Clothing" is a product
category, so finding it says the ProductCategory table is needed.

Run:  python data_search.py
"""
import json
import os
import re
import time

import numpy as np

from data_values import VALUES_FILE
from schema_search import get_model, split_words

INDEX_VECTORS = "data_index.npy"   # the numbers for every value
INDEX_DOCS = "data_index.json"     # which value each row of numbers is for

# Small words that never name a value on their own. A phrase may contain
# them ("on the website") but may not start or end with one.
STOP_WORDS = {
    "a", "an", "the", "of", "in", "on", "by", "for", "to", "from", "with",
    "and", "or", "we", "our", "us", "that", "were", "was", "are", "is",
    "be", "been", "being", "how", "many", "much", "what", "which", "who",
    "show", "me", "each", "per", "all", "any", "still", "have", "has",
    "had", "because", "did", "do", "does",
}


def value_text(v):
    """The text that gets embedded for one value."""
    table = split_words(v["table"].split(".")[1])
    # A code is embedded by its meaning: "Shipped" means something, "5" does not.
    shown = v.get("meaning", v["value"])
    return f"{table} - {split_words(v['column'])}: {shown}"


def build_index():
    """Turn every collected value into numbers and save them."""
    with open(VALUES_FILE, encoding="utf-8") as f:
        docs = json.load(f)
    for d in docs:
        d["text"] = value_text(d)
    vectors = np.array(list(get_model().embed([d["text"] for d in docs])))

    np.save(INDEX_VECTORS, vectors)
    with open(INDEX_DOCS, "w", encoding="utf-8") as f:
        json.dump(docs, f, indent=2, ensure_ascii=False)
    return docs, vectors


def load_index():
    """Load the saved index, rebuilding it if data_values.json has changed since."""
    files = (INDEX_VECTORS, INDEX_DOCS)
    fresh = all(os.path.exists(p) for p in files) and all(
        os.path.getmtime(p) >= os.path.getmtime(VALUES_FILE) for p in files
    )
    if not fresh:
        return build_index()
    with open(INDEX_DOCS, encoding="utf-8") as f:
        docs = json.load(f)
    return docs, np.load(INDEX_VECTORS)


def phrases(question, longest=3):
    """'Revenue from red road bikes' -> Revenue, red, road, bikes, red road, road bikes, ..."""
    words = re.findall(r"[A-Za-z0-9&'-]+", question)
    found = []
    for size in range(1, longest + 1):
        for i in range(len(words) - size + 1):
            part = words[i:i + size]
            if part[0].lower() in STOP_WORDS or part[-1].lower() in STOP_WORDS:
                continue
            found.append(" ".join(part))
    return list(dict.fromkeys(found))


def search(question, tables=None, per_phrase=2, top=20, index=None):
    """
    The stored values the question most likely refers to, best first.

    Each part of the question keeps its own best few matches. Otherwise
    a common word like "orders", which half-matches dozens of values,
    would push out the one value "truck" points to.
    """
    docs, vectors = index or load_index()
    rows = [i for i, d in enumerate(docs) if tables is None or d["table"] in tables]
    texts = [question] + phrases(question)
    queries = np.array(list(get_model().query_embed(texts)))
    # One score per value per text. Rows have length 1, so this is cosine similarity.
    scores = vectors[rows] @ queries.T

    best = {}  # row -> (score, text) of its best match
    for j, text in enumerate(texts):
        for r in np.argsort(-scores[:, j])[:per_phrase]:
            if r not in best or scores[r, j] > best[r][0]:
                best[r] = (float(scores[r, j]), text)

    results = []
    for r, (score, text) in best.items():
        d = docs[rows[r]]
        results.append({
            "table": d["table"], "column": d["column"], "value": d["value"],
            "meaning": d.get("meaning"), "score": score,
            "matched": text,  # which part of the question it matched
        })
    results.sort(key=lambda r: r["score"], reverse=True)
    return results[:top]


def search_each(texts, first_top=20, other_top=5, index=None):
    """
    Search the question (texts[0]) and each step of a procedure (the rest),
    and combine them. The question gets more room; each step adds its best few.
    """
    index = index or load_index()
    best = {}
    for n, text in enumerate(texts):
        for r in search(text, top=first_top if n == 0 else other_top, index=index):
            key = (r["table"], r["column"], r["value"])
            if key not in best or r["score"] > best[key]["score"]:
                best[key] = r
    return sorted(best.values(), key=lambda r: r["score"], reverse=True)


def describe_value(v):
    """One value as the AI sees it, ready to paste into SQL."""
    column = f"{v['table']}.[{v['column']}]"
    value = f"'{v['value']}'" if isinstance(v["value"], str) else str(v["value"])
    meaning = f"   ({v['meaning']})" if v["meaning"] else ""
    return f"  {column} = {value}{meaning}"


def describe_values(values):
    if not values:
        return "  (none found)"
    return "\n".join(describe_value(v) for v in values)


def wanted(table, column, *values):
    """One thing a correct answer must contain: any one of these values."""
    return [(table, column, v) for v in values]


TERRITORY = ("Sales.SalesTerritory", "Name")
SUBCATEGORY = ("Production.ProductSubcategory", "Name")
ORDER_STATUS = ("Sales.SalesOrderHeader", "Status")
ONLINE = ("Sales.SalesOrderHeader", "OnlineOrderFlag")

# Test phrases. For each, the values a correct search must find.
# These are used to choose the search settings.
TEST_QUESTIONS = [
    ("Sales in European countries", [wanted("Sales.SalesTerritory", "Group", "Europe")]),
    ("How many orders were completed", [wanted(*ORDER_STATUS, 5)]),
    ("Revenue from red road bikes",
     [wanted("Production.Product", "Color", "Red"), wanted(*SUBCATEGORY, "Road Bikes")]),
    ("Orders shipped by truck", [wanted("Purchasing.ShipMethod", "Name", "XRQ - TRUCK GROUND")]),
    ("Mountain bike sales in the south west",
     [wanted(*SUBCATEGORY, "Mountain Bikes"), wanted(*TERRITORY, "Southwest")]),
    ("Orders customers placed on the website", [wanted(*ONLINE, 1)]),
    ("Products we manufacture ourselves", [wanted("Production.Product", "MakeFlag", 1)]),
    ("Headcount on the night shift", [wanted("HumanResources.Shift", "Name", "Night")]),
    ("Employees in R&D",
     [wanted("HumanResources.Department", "Name", "Research and Development")]),
    ("Vendors with the best credit rating", [wanted("Purchasing.Vendor", "CreditRating", 1)]),
    ("Clothing sold in Canada",
     [wanted("Production.ProductCategory", "Name", "Clothing"), wanted(*TERRITORY, "Canada")]),
    ("Purchase orders that were turned down",
     [wanted("Purchasing.PurchaseOrderHeader", "Status", 3)]),
    ("Orders paid with a Vista card", [wanted("Sales.CreditCard", "CardType", "Vista")]),
    ("Scrap caused by paint problems",
     [wanted("Production.ScrapReason", "Name", "Paint process failed")]),
    ("Sales of women's products", [wanted("Production.Product", "Style", "W")]),
]

# Held-out phrases, written at the same time as the ones above but never
# used to choose settings, so they give the honest score. Do not change
# the search to fix these; add new phrases instead.
HELD_OUT_QUESTIONS = [
    ("Sales across Asia-Pacific", [wanted("Sales.SalesTerritory", "Group", "Pacific")]),
    ("Orders that are still being processed", [wanted(*ORDER_STATUS, 1)]),
    ("Black touring bikes",
     [wanted("Production.Product", "Color", "Black"), wanted(*SUBCATEGORY, "Touring Bikes")]),
    ("Hourly paid staff", [wanted("HumanResources.Employee", "SalariedFlag", 0)]),
    ("Employees who have left", [wanted("HumanResources.Employee", "CurrentFlag", 0)]),
    ("Sales to British customers", [wanted(*TERRITORY, "United Kingdom")]),
    ("Orders bought because of a discount promotion",
     [wanted("Sales.SalesReason", "Name", "On Promotion")]),
    ("Vendors we stopped using", [wanted("Purchasing.Vendor", "ActiveFlag", 0)]),
    ("High-end products in the mountain line",
     [wanted("Production.Product", "Class", "H"), wanted("Production.Product", "ProductLine", "M")]),
    ("Orders taken by our sales reps", [wanted(*ONLINE, 0)]),
]


def show(r):
    value = f"{r['value']} = {r['meaning']}" if r["meaning"] else r["value"]
    return f"{r['table']}.{r['column']}: {value}"


def run_questions(title, questions, index, top):
    """Search each phrase and count how often every needed value is found."""
    print(f"\n===== {title} =====")
    passed = 0
    for question, needed in questions:
        results = search(question, top=top, index=index)
        found = {(r["table"], r["column"], r["value"]) for r in results}
        missing = [group for group in needed if not found & set(group)]
        passed += not missing

        print(f"\nQ: {question}")
        for r in results:
            mark = "*" if any((r["table"], r["column"], r["value"]) in g for g in needed) else " "
            print(f"  {mark} {r['score']:.2f}  {show(r):<62} <- \"{r['matched']}\"")
        for group in missing:
            table, column, value = group[0]
            print(f"  MISSED: {table}.{column}: {value}")
    return passed


def main():
    started = time.time()
    index = load_index()
    docs, vectors = index
    print(f"Index ready: {len(docs)} values, {time.time() - started:.0f} seconds")

    top = 20
    tuned = run_questions("Test phrases (used to choose settings)", TEST_QUESTIONS, index, top)
    held_out = run_questions("Held-out phrases (the honest score)",
                             HELD_OUT_QUESTIONS, index, top)

    print(f"\nPhrases where every needed value was in the top {top}:")
    print(f"  Test phrases:     {tuned} of {len(TEST_QUESTIONS)}")
    print(f"  Held-out phrases: {held_out} of {len(HELD_OUT_QUESTIONS)}")


if __name__ == "__main__":
    main()
