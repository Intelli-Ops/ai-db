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

Run:  python data_search.py
"""
import json
import os
import time

import numpy as np

from data_values import VALUES_FILE
from schema_search import get_model, split_words

INDEX_VECTORS = "data_index.npy"   # the numbers for every value
INDEX_DOCS = "data_index.json"     # which value each row of numbers is for


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


def main():
    started = time.time()
    docs, vectors = build_index()
    print(f"Built: {len(docs)} values -> {vectors.shape[0]} rows of "
          f"{vectors.shape[1]} numbers, in {time.time() - started:.0f} seconds")

    # Check it reloads from the saved files, unchanged.
    docs_again, vectors_again = load_index()
    same = len(docs_again) == len(docs) and np.allclose(vectors_again, vectors)
    print(f"Reloaded from {INDEX_VECTORS} and {INDEX_DOCS}: "
          f"{'identical' if same else 'DIFFERENT'}")

    # Every row should have length 1, so a plain dot product is the
    # cosine similarity later on.
    lengths = np.linalg.norm(vectors, axis=1)
    print(f"Row lengths: {lengths.min():.3f} to {lengths.max():.3f}")

    print("\nExamples of what was embedded:")
    for text in ["Sales Territory - Group: Europe",
                 "Ship Method - Name: XRQ - TRUCK GROUND",
                 "Sales Order Header - Status: Shipped"]:
        row = next(i for i, d in enumerate(docs) if d["text"] == text)
        print(f"  {text}")
        print(f"      -> [{', '.join(f'{x:.3f}' for x in vectors[row][:5])}, ... 763 more]")


if __name__ == "__main__":
    main()
