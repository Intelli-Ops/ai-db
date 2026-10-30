"""
Step 2: data profile (what is actually used).

For every non-empty table found in Step 1, counts how full each column is,
finds the first and last date in each date column, and counts rows per month
on the table's "when added" date. Only counts and dates are kept; no row is
copied out. No AI. Explained in docs/01_project_steps.md, Step 2.

Reads   catalog/catalog.json (from Step 1)
Writes  (git-ignored, this machine only)
  catalog/profile_parts.jsonl - one line per table as it finishes, so a re-run continues where it stopped
  catalog/profile.json        - everything, for the later steps to read
  catalog/profile.md          - the same, readable

Run:  python step02_profile.py            (profile, then write the summary)
      python step02_profile.py --report   (only rebuild the summary from what is already profiled)
"""
import json
import os
import re
import statistics
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime

from sqlalchemy import text

from db import get_engine

OUT_DIR = "catalog"
PARTS_FILE = os.path.join(OUT_DIR, "profile_parts.jsonl")

DATE_TYPES = {"date", "datetime", "datetime2", "smalldatetime", "datetimeoffset"}
TEXT_TYPES = {"char", "varchar", "nchar", "nvarchar", "sysname"}
NO_COUNT_TYPES = {"text", "ntext", "image", "xml"}  # COUNT(column) does not accept these

# Column names that usually mean "when this row was added".
ADDED_NAME = re.compile(r"creat|entry|entered|insert|added|adddate", re.I)
# Table names that look like backups, copies, temporary or test tables.
COPY_NAME = re.compile(r"bkp|backup(?=\d|_|$)|_bak$|copy|_old$|(^|_)te?mp(?!lat)|test|\d{6,8}", re.I)

FILL_BANDS = ["always empty", "almost empty (under 1%)", "partly filled", "always filled"]
LAST_USE_BANDS = ["2023 or later", "2020 - 2022", "2015 - 2019", "before 2015", "no date column", "no usable dates"]


def q(name):
    return "[" + name.replace("]", "]]") + "]"


def base_type(col):
    return col["type"].split("(")[0]


def filled_expr(col):
    """SQL that counts the rows where this column holds something (blank text counts as empty)."""
    c, t = q(col["name"]), base_type(col)
    if t in TEXT_TYPES:
        return f"SUM(CASE WHEN {c} IS NULL OR LTRIM(RTRIM({c})) = '' THEN 0 ELSE 1 END)"
    if t in NO_COUNT_TYPES:
        return f"SUM(CASE WHEN {c} IS NULL THEN 0 ELSE 1 END)"
    return f"COUNT_BIG({c})"


def profile_table(conn, name, obj):
    """Pass 1: fill count of every column, first/last date of every date column."""
    source = f"{q(obj['schema'])}.{q(obj['name'])} WITH (NOLOCK)"
    cols = obj["columns"]
    parts = ["COUNT_BIG(*) AS n"]
    for i, col in enumerate(cols):
        parts.append(f"{filled_expr(col)} AS f{i}")
        if base_type(col) in DATE_TYPES:
            c = q(col["name"])
            parts += [f"MIN({c}) AS mn{i}", f"MAX({c}) AS mx{i}",
                      f"MAX(CASE WHEN {c} <= GETDATE() THEN {c} END) AS mxp{i}",
                      f"SUM(CASE WHEN {c} > GETDATE() THEN 1 ELSE 0 END) AS fut{i}"]
    row = conn.execute(text(f"SELECT {', '.join(parts)} FROM {source}")).mappings().one()
    n = int(row["n"])
    out_cols = []
    for i, col in enumerate(cols):
        filled = int(row[f"f{i}"] or 0)
        c = {"name": col["name"], "type": col["type"], "filled": filled,
             "fill_pct": round(100 * filled / n, 2) if n else 0.0}
        if base_type(col) in DATE_TYPES:
            day = lambda v: str(v)[:10] if v is not None else None
            c.update(first=day(row[f"mn{i}"]), last=day(row[f"mx{i}"]),
                     last_not_future=day(row[f"mxp{i}"]), future_rows=int(row[f"fut{i}"] or 0))
        out_cols.append(c)
    return n, out_cols


def pick_added_column(n, cols):
    """The date column that best says when a row was added: mostly filled, 'created'-like name first."""
    dates = [c for c in cols if "first" in c and c["last_not_future"] and n and c["filled"] >= 0.5 * n]
    if not dates:
        return None
    return max(dates, key=lambda c: (bool(ADDED_NAME.search(c["name"])), c["filled"], c["last_not_future"]))["name"]


def rows_per_month(conn, obj, column):
    """Pass 2: rows per month on one date column (future dates left out)."""
    c = q(column)
    sql = (f"SELECT YEAR({c}) AS y, MONTH({c}) AS m, COUNT_BIG(*) AS n "
           f"FROM {q(obj['schema'])}.{q(obj['name'])} WITH (NOLOCK) "
           f"WHERE {c} <= GETDATE() GROUP BY YEAR({c}), MONTH({c})")
    return {f"{r.y:04d}-{r.m:02d}": int(r.n) for r in conn.execute(text(sql))}


def next_month(month):
    y, m = int(month[:4]), int(month[5:])
    return f"{y + m // 12:04d}-{m % 12 + 1:02d}"


def last_busy_month(months):
    """The last month of normal use: the end of the latest run of 3 calendar months in a row that
    each have at least 10% of the table's typical (median) month. A one-off batch, such as a test
    import in a quiet year, does not count. Tables with no such run fall back to their last busy month."""
    if not months:
        return None
    typical = statistics.median(months.values())
    busy = {m for m, n in months.items() if n >= 0.1 * typical}
    runs = [m for m in busy if next_month(m) in busy and next_month(next_month(m)) in busy]
    if runs:
        return next_month(next_month(max(runs)))
    return max(busy) if busy else None


def done_tables():
    if not os.path.exists(PARTS_FILE):
        return {}
    with open(PARTS_FILE, encoding="utf-8") as f:
        return {p["table"]: p for p in map(json.loads, f) if "error" not in p}


def run_profile(catalog):
    tables = sorted(((n, o) for n, o in catalog.items() if o["kind"] == "table" and (o["rows"] or 0) > 0),
                    key=lambda x: x[1]["rows"])
    done = done_tables()
    todo = [(n, o) for n, o in tables if n not in done]
    print(f"{len(tables)} non-empty tables: {len(done)} already profiled, {len(todo)} to go "
          f"({sum(o['rows'] for _, o in todo):,} rows to scan)", flush=True)
    engine = get_engine()
    start = time.time()
    for k, (name, obj) in enumerate(todo, 1):
        t0 = time.time()
        part = {"table": name}
        try:
            with engine.connect() as conn:
                n, cols = profile_table(conn, name, obj)
                added = pick_added_column(n, cols)
                months = rows_per_month(conn, obj, added) if added else {}
            part.update(rows=n, columns=cols, added_column=added, rows_per_month=months)
        except Exception as e:  # keep going; the error is recorded and the table is retried next run
            part["error"] = str(e).splitlines()[0][:300]
        with open(PARTS_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(part) + "\n")
        status = "ERROR " + part["error"][:80] if "error" in part else f"{part['rows']:,} rows"
        print(f"[{k}/{len(todo)}] {name}: {status} ({time.time() - t0:.1f}s, "
              f"{(time.time() - start) / 60:.1f} min total)", flush=True)


def last_use_band(p):
    if not any("first" in c for c in p["columns"]):
        return "no date column"
    month = p.get("last_busy_month")
    if not month:
        return "no usable dates"
    year = int(month[:4])
    return ("2023 or later" if year >= 2023 else "2020 - 2022" if year >= 2020
            else "2015 - 2019" if year >= 2015 else "before 2015")


def fill_band(c):
    if c["filled"] == 0:
        return FILL_BANDS[0]
    if c["fill_pct"] < 1:
        return FILL_BANDS[1]
    return FILL_BANDS[3] if c["fill_pct"] == 100 else FILL_BANDS[2]


def build(catalog, parts):
    """One entry per table: Step 2 measurements plus a last-use band and a copy flag."""
    column_sets = defaultdict(list)
    for name, o in catalog.items():
        if o["kind"] == "table" and not COPY_NAME.search(o["name"]):
            column_sets[tuple(sorted(c["name"].lower() for c in o["columns"]))].append(name)
    out = {}
    for name, o in catalog.items():
        if o["kind"] != "table":
            continue
        p = dict(parts.get(name, {"table": name, "rows": o["rows"] or 0, "columns": [],
                                  "added_column": None, "rows_per_month": {}}))
        p["profiled"] = name in parts
        months = p["rows_per_month"]
        p["last_busy_month"] = last_busy_month(months)
        years = defaultdict(int)
        for month, n in months.items():
            years[month[:4]] += n
        p["rows_per_year"] = dict(sorted(years.items()))
        p["last_use"] = "empty" if not (o["rows"] or 0) else last_use_band(p) if p["profiled"] else "not profiled"
        p["looks_like_copy"] = bool(COPY_NAME.search(o["name"]))
        same = column_sets.get(tuple(sorted(c["name"].lower() for c in o["columns"])), [])
        p["same_columns_as"] = [s for s in same if s != name] if p["looks_like_copy"] else []
        out[name] = p
    return out


def write_markdown(profile):
    tables = profile.values()
    used = [p for p in tables if p["last_use"] != "empty"]
    cols = [c for p in used for c in p["columns"]]
    L = [f"# Data profile", "",
         f"Made on {datetime.now():%Y-%m-%d %H:%M}. Counts and dates only; no row was copied out.", "",
         "## Tables by last normal use", "",
         "Last normal use = the last month with at least 10% of the table's typical monthly rows, "
         "on its \"when added\" date column.", "", "| Last normal use | Tables | Rows |", "|---|---:|---:|"]
    for band in LAST_USE_BANDS + ["not profiled", "empty"]:
        group = [p for p in tables if p["last_use"] == band]
        if group:
            L.append(f"| {band} | {len(group)} | {sum(p['rows'] for p in group):,} |")
    L += ["", "## Columns of non-empty tables by how full they are", "", "| Fill | Columns |", "|---|---:|"]
    bands = Counter(fill_band(c) for c in cols)
    L += [f"| {b} | {bands.get(b, 0):,} |" for b in FILL_BANDS]
    copies = sorted((n, p) for n, p in profile.items() if p["looks_like_copy"])
    L += ["", f"## Tables that look like backups, copies, temporary or test tables ({len(copies)})", "",
          "| Table | Rows | Last normal use | Same columns as |", "|---|---:|---|---|"]
    L += [f"| {n} | {p['rows']:,} | {p['last_use']} | {', '.join(p['same_columns_as']) or '-'} |" for n, p in copies]
    L += ["", "## Every non-empty table", "",
          "| Table | Rows | \"When added\" column | First month | Last normal use | Latest date | Future-dated rows | Empty columns |",
          "|---|---:|---|---|---|---|---:|---:|"]
    for n, p in sorted((n, p) for n, p in profile.items() if p["last_use"] != "empty"):
        added = next((c for c in p["columns"] if c["name"] == p["added_column"]), {})
        months = p.get("rows_per_month", {})
        L.append(f"| {n} | {p['rows']:,} | {p['added_column'] or '-'} | {min(months) if months else '-'} | "
                 f"{p['last_busy_month'] or '-'} | {added.get('last_not_future') or '-'} | "
                 f"{added.get('future_rows', 0):,} | {sum(c['filled'] == 0 for c in p['columns'])} of {len(p['columns'])} |")
    with open(os.path.join(OUT_DIR, "profile.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")


def main():
    with open(os.path.join(OUT_DIR, "catalog.json"), encoding="utf-8") as f:
        catalog = json.load(f)["objects"]
    if "--report" not in sys.argv:
        run_profile(catalog)
    profile = build(catalog, done_tables())
    with open(os.path.join(OUT_DIR, "profile.json"), "w", encoding="utf-8") as f:
        json.dump({"made_at": f"{datetime.now():%Y-%m-%d %H:%M}", "tables": profile}, f, indent=1)
    write_markdown(profile)
    print("Last normal use:", dict(Counter(p["last_use"] for p in profile.values())))
    print(f"Saved {OUT_DIR}/profile.json and {OUT_DIR}/profile.md")


if __name__ == "__main__":
    main()
