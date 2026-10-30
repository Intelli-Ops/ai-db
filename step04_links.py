"""
Step 4: links between tables (how to join them), checked against the data.

Finds possible links in four ways:
  1. foreign keys declared in the database (Step 1)
  2. a column named like another table's key (BILLCPTCODEID -> BILLCPTCODE.BILLCPTCODEID,
     PHYSICIANID -> PHYSICIAN.PHYSICIAN_ID, settle ProviderId -> settle.Providers.Id)
  3. hand-written hints in knowledge/links.yaml (CREATEDBY -> users, CASEINFO.PTP -> ?)
then CHECKS every one with counts: of the rows that have a value in the column,
how many find a matching row in the target table? When a column has several
possible targets, the best match wins. It also runs "two roads agree" checks
(e.g. a payment's BILLID equals the BILLID of its bill line), measures how many
rows per target a link has, and works out join paths between the core tables.

Only counts leave the database; no value is kept or printed. No AI.
Explained in docs/01_project_steps.md, Step 4.

Reads   catalog/catalog.json (Step 1), catalog/schema.json (Step 3), knowledge/links.yaml
Writes  (git-ignored, this machine only)
  catalog/links_parts.jsonl - one line per check as it finishes, so a re-run continues where it stopped
  catalog/links.json        - the links, checks and join paths, for the next steps
  catalog/links.md          - the same, readable

Run:  python step04_links.py            (check, then write the summary)
      python step04_links.py --plan     (only list what would be checked; no database)
      python step04_links.py --report   (only rebuild the summary from what is already checked)
"""
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict, deque
from datetime import datetime

import yaml
from sqlalchemy import text

from db import get_engine

OUT_DIR = "catalog"
PARTS_FILE = os.path.join(OUT_DIR, "links_parts.jsonl")
HINTS = os.path.join("knowledge", "links.yaml")
SAMPLE = 200_000          # bigger tables are checked on an even spread of about this many rows
TIMEOUT = 600             # seconds per query
TIER_RANK = {"core": 0, "support": 1, "archive": 2, "answer_key": 3}
CORE_TIERS = ("core", "support")

INTEGER_TYPES = {"int", "bigint", "smallint", "tinyint"}
NUMBER_TYPES = INTEGER_TYPES | {"numeric", "decimal"}
TEXT_TYPES = {"char", "varchar", "nchar", "nvarchar"}
LINKABLE = NUMBER_TYPES | TEXT_TYPES | {"uniqueidentifier"}
HOW_RANK = {"declared": 0, "hint": 1, "list": 1, "name": 2}
GENERIC_KEYS = {"id", "code", "name", "uid", "guid"}   # too common to link on by name alone
STATUS_BANDS = [(99, "confirmed"), (90, "mostly"), (50, "weak"), (0, "rejected")]


def q(name):
    return "[" + name.replace("]", "]]") + "]"


def norm(name):
    return re.sub(r"[_\s]", "", name).lower()


def base_type(t):
    return t.split("(")[0]


def table_sql(obj):
    return f"{q(obj['schema'])}.{q(obj['name'])}"


def key_of(obj):
    """The column that identifies a row: a one-column primary key, else an identity column."""
    if len(obj["primary_key"]) == 1:
        return obj["primary_key"][0]
    ident = [c["name"] for c in obj["columns"] if c.get("identity")]
    return ident[0] if len(ident) == 1 else None


def col_type(obj, name):
    return next(c["type"] for c in obj["columns"] if c["name"].lower() == name.lower())


def col_name(obj, name):
    """The column's exact spelling, or None."""
    return next((c["name"] for c in obj["columns"] if c["name"].lower() == name.lower()), None)


def split_target(target):
    schema, table, column = target.split(".", 2)
    return f"{schema}.{table}", column


# ---------------------------------------------------------------- 1. possible links

def candidates(catalog, tables, hints):
    """{(source, column): [(target table, target column, how)]} for every kept table and view."""
    targets = {n: key_of(catalog[n]) for n, t in tables.items()
               if catalog[n]["kind"] == "table" and t["tier"] != "answer_key" and key_of(catalog[n])}
    by_key = defaultdict(list)
    for n, k in targets.items():
        if norm(k) not in GENERIC_KEYS:
            by_key[norm(k)].append(n)
    by_schema = defaultdict(dict)                       # schema -> {normalised table name: table}
    for n in targets:
        by_schema[catalog[n]["schema"]][norm(catalog[n]["name"])] = n
    patterns = [(re.compile(p["pattern"], re.I), p["targets"]) for p in hints.get("by_pattern") or []]
    tries = {k.lower(): v for k, v in (hints.get("try") or {}).items()}
    lists = {k.lower(): v for k, v in (hints.get("lists") or {}).items()}

    found = defaultdict(list)
    for src, t in tables.items():
        obj = catalog[src]
        own_key = key_of(obj)
        for link in obj["links_out"]:
            if len(link["columns"]) == 1 and link["references"] in catalog:
                found[(src, link["columns"][0])].append((link["references"], link["ref_columns"][0], "declared"))
        for col in obj["columns"]:
            name = col["name"]
            if f"{src}.{name}".lower() in lists:
                found[(src, name)] = [(*split_target(lists[f"{src}.{name}".lower()]), "list")]
                continue
            if base_type(col["type"]) not in LINKABLE:
                continue
            for target in tries.get(f"{src}.{name}".lower(), []):
                found[(src, name)].append((*split_target(target), "hint"))
            for pattern, ts in patterns:
                if pattern.search(name):
                    found[(src, name)] += [(*split_target(target), "hint") for target in ts]
            for tgt in by_key.get(norm(name), []):
                if tgt == src:
                    continue
                if name == own_key and not extends(catalog, src, tgt):
                    continue                            # a row ID only links to a "main" table it extends
                found[(src, name)].append((tgt, targets[tgt], "name"))
            n = norm(name)
            if n.endswith("id") and len(n) > 2 and name != own_key:
                stem, same = n[:-2], by_schema[obj["schema"]]
                for tname in (stem, stem + "s", stem + "es"):
                    tgt = same.get(tname)
                    if tgt and tgt != src and norm(targets[tgt]) == "id":
                        found[(src, name)].append((tgt, targets[tgt], "name"))
    result = {}
    for key, cands in found.items():
        seen, unique = set(), []
        for tgt, tcol, how in sorted(cands, key=lambda c: HOW_RANK[c[2]]):
            if tgt in catalog and col_name(catalog[tgt], tcol) and (tgt, tcol.lower()) not in seen:
                seen.add((tgt, tcol.lower()))
                unique.append((tgt, col_name(catalog[tgt], tcol), how))
        if unique:
            result[key] = unique[:6]
    return result


def extends(catalog, src, tgt):
    """Is src an extension of tgt, sharing its row ID? (its name starts with tgt's: PATIENT_EXTRA -> PATIENT)"""
    a, b = norm(catalog[src]["name"]), norm(catalog[tgt]["name"])
    return a != b and a.startswith(b)


# ---------------------------------------------------------------- 2. checks against the data

def filled(alias, column, ctype):
    c = f"{alias}.{q(column)}"
    t = base_type(ctype)
    if t in TEXT_TYPES:
        return f"{c} IS NOT NULL AND LTRIM(RTRIM({c})) NOT IN ('', '0')"
    if t in NUMBER_TYPES:
        return f"{c} IS NOT NULL AND {c} <> 0"
    return f"{c} IS NOT NULL"


def sample_rows(obj, where, columns):
    """SELECT of the given columns from a spread of about SAMPLE rows (or all rows of a smaller table)."""
    rows, key = obj["rows"] or 0, key_of(obj)
    cols = ", ".join(f"s.{q(c)} AS {q('c' + str(i))}" for i, c in enumerate(columns))
    src = f"{table_sql(obj)} s WITH (NOLOCK)"
    if rows <= SAMPLE:
        return f"SELECT {cols} FROM {src} WHERE {where}", False
    if key and base_type(col_type(obj, key)) in INTEGER_TYPES:
        return f"SELECT {cols} FROM {src} WHERE {where} AND s.{q(key)} % {rows // SAMPLE + 1} = 0", True
    return f"SELECT TOP {SAMPLE} {cols} FROM {src} WHERE {where}", True


def same_value(left, ltype, right, rtype):
    """left = right, converting the left side when the two types differ."""
    a, b = base_type(ltype), base_type(rtype)
    if a == b or (a in NUMBER_TYPES and b in NUMBER_TYPES) or (a in TEXT_TYPES and b in TEXT_TYPES):
        return f"{right} = {left}"
    return f"{right} = TRY_CONVERT({rtype}, {left})"


def check_link(conn, catalog, src, column, tgt, tcol):
    s, t = catalog[src], catalog[tgt]
    inner, sampled = sample_rows(s, filled("s", column, col_type(s, column)), [column])
    match = same_value("x.c0", col_type(s, column), f"t.{q(tcol)}", col_type(t, tcol))
    sql = (f"SELECT COUNT_BIG(*) AS checked, COUNT_BIG(m.hit) AS matched FROM ({inner}) x "
           f"OUTER APPLY (SELECT TOP 1 1 AS hit FROM {table_sql(t)} t WITH (NOLOCK) WHERE {match}) m")
    r = conn.execute(text(sql)).mappings().one()
    return {"checked": int(r["checked"]), "matched": int(r["matched"] or 0), "sampled": sampled}


def check_list(conn, catalog, src, column, tgt, tcol):
    """Like check_link, for a column holding a comma-separated list of keys: checks the first key of each list."""
    s, t = catalog[src], catalog[tgt]
    c = f"s.{q(column)}"
    head = f"CONVERT(varchar(8000), LEFT({c}, 4000))"
    first = f"LTRIM(RTRIM(CASE WHEN CHARINDEX(',', {head}) > 0 THEN LEFT({head}, CHARINDEX(',', {head}) - 1) ELSE {head} END))"
    inner, sampled = sample_rows(s, f"{c} IS NOT NULL AND LEN({c}) > 0", [column])
    inner = inner.replace(f"s.{q(column)} AS [c0]", f"TRY_CONVERT({col_type(t, tcol)}, {first}) AS [c0]", 1)
    sql = (f"SELECT COUNT_BIG(*) AS checked, COUNT_BIG(m.hit) AS matched FROM ({inner}) x "
           f"OUTER APPLY (SELECT TOP 1 1 AS hit FROM {table_sql(t)} t WITH (NOLOCK) WHERE t.{q(tcol)} = x.c0) m")
    r = conn.execute(text(sql)).mappings().one()
    return {"checked": int(r["checked"]), "matched": int(r["matched"] or 0), "sampled": sampled}


def composite_match(catalog, comp, alias):
    """OUTER APPLY that counts the target rows matching all the columns of a composite link (n) and returns one key (k)."""
    t = catalog[comp["target"]]
    cond = " AND ".join(f"t.{q(tc)} = {alias}.{q(sc)}" for sc, tc in comp["join_on"].items())
    return (f"OUTER APPLY (SELECT COUNT(*) AS n, MAX(t.{q(comp['target_key'])}) AS k "
            f"FROM {table_sql(t)} t WITH (NOLOCK) WHERE {cond}) m")


def check_composite(conn, catalog, comp):
    """For a composite link: how many rows find no, exactly one, or several targets; does it agree with the
    one-column link where that is filled; and does it agree with the answer key?"""
    s = catalog[comp["table"]]
    where = " AND ".join(filled("s", sc, col_type(s, sc)) for sc in comp["join_on"])
    cols = list(comp["join_on"]) + ([comp["direct"]] if comp.get("direct") else [])
    inner, sampled = sample_rows(s, where, cols)
    for i, sc in enumerate(comp["join_on"]):
        inner = inner.replace(f" AS [c{i}]", f" AS {q(sc)}")
    d = f"x.[c{len(comp['join_on'])}]" if comp.get("direct") else "NULL"
    known = f"{d} IS NOT NULL AND {d} <> 0"
    sql = (f"SELECT COUNT_BIG(*) AS checked, SUM(CASE WHEN m.n = 0 THEN 1 ELSE 0 END) AS none, "
           f"SUM(CASE WHEN m.n = 1 THEN 1 ELSE 0 END) AS one, SUM(CASE WHEN m.n > 1 THEN 1 ELSE 0 END) AS many, "
           f"SUM(CASE WHEN {known} THEN 1 ELSE 0 END) AS direct_known, "
           f"SUM(CASE WHEN {known} AND m.n = 1 AND m.k = {d} THEN 1 ELSE 0 END) AS direct_same "
           f"FROM ({inner}) x {composite_match(catalog, comp, 'x')}")
    r = {k: int(v or 0) for k, v in conn.execute(text(sql)).mappings().one().items()}
    r["sampled"] = sampled
    if comp.get("answer_key"):
        ak = comp["answer_key"]
        a = catalog[ak["table"]]
        inner, _ = sample_rows(a, f"s.{q(ak['row'])} IS NOT NULL AND s.{q(ak['expect'])} IS NOT NULL",
                               [ak["row"], ak["expect"]])
        sql = (f"SELECT COUNT_BIG(*) AS n, SUM(CASE WHEN m.n = 1 AND m.k = x.c1 THEN 1 ELSE 0 END) AS same "
               f"FROM ({inner}) x JOIN {table_sql(s)} b WITH (NOLOCK) ON b.{q(key_of(s))} = x.c0 "
               f"{composite_match(catalog, comp, 'b')}")
        ra = conn.execute(text(sql)).mappings().one()
        r["answer_key_rows"], r["answer_key_same"] = int(ra["n"]), int(ra["same"] or 0)
    return r


def check_shape(conn, catalog, src, column, tgt, tcol):
    """How many source rows per target row, and how many target rows are used at all (full counts)."""
    s, t = catalog[src], catalog[tgt]
    where = filled("s", column, col_type(s, column))
    r = conn.execute(text(f"SELECT COUNT_BIG(s.{q(column)}) AS n, COUNT_BIG(DISTINCT s.{q(column)}) AS d "
                          f"FROM {table_sql(s)} s WITH (NOLOCK) WHERE {where}")).mappings().one()
    match = same_value(f"t.{q(tcol)}", col_type(t, tcol), f"s.{q(column)}", col_type(s, column))
    used = conn.execute(text(f"SELECT COUNT_BIG(*) FROM {table_sql(t)} t WITH (NOLOCK) WHERE EXISTS "
                             f"(SELECT 1 FROM {table_sql(s)} s WITH (NOLOCK) WHERE {match})")).scalar()
    return {"rows": int(r["n"]), "distinct": int(r["d"]), "target_rows": t["rows"], "target_used": int(used)}


def parse_agree(a):
    via_col, target = [x.strip() for x in a["via"].split("->")]
    tgt, tcol = split_target(target)
    left, right = [x.strip() for x in a["compare"].split("=")]
    return a["table"], via_col, tgt, tcol, left, right


def check_agree(conn, catalog, a):
    src, via, tgt, tcol, left, right = parse_agree(a)
    s, t = catalog[src], catalog[tgt]
    where = filled("s", via, col_type(s, via)) + f" AND s.{q(left)} IS NOT NULL"
    inner, sampled = sample_rows(s, where, [via, left])
    join = same_value("x.c0", col_type(s, via), f"t.{q(tcol)}", col_type(t, tcol))
    equal = same_value("x.c1", col_type(s, left), f"t.{q(right)}", col_type(t, right))
    sql = (f"SELECT COUNT_BIG(*) AS both_known, SUM(CASE WHEN {equal} THEN 1 ELSE 0 END) AS same "
           f"FROM ({inner}) x JOIN {table_sql(t)} t WITH (NOLOCK) ON {join} WHERE t.{q(right)} IS NOT NULL")
    r = conn.execute(text(sql)).mappings().one()
    return {"both_known": int(r["both_known"]), "same": int(r["same"] or 0), "sampled": sampled}


def plan(catalog, tables, hints):
    """Every check to run, as (id, kind, args), core tables first."""
    cands = candidates(catalog, tables, hints)
    jobs = []
    for (src, column), cs in sorted(cands.items(), key=lambda kv: (TIER_RANK[tables[kv[0][0]]["tier"]], kv[0])):
        if catalog[src]["kind"] != "table" or not catalog[src]["rows"]:
            continue                                    # views and tables empty here can't be checked
        for tgt, tcol, how in cs:
            jobs.append((f"link|{src}|{column}|{tgt}|{tcol}", "list" if how == "list" else "link",
                         (src, column, tgt, tcol)))
    for a in hints.get("agree") or []:
        jobs.append(("agree|" + "|".join(parse_agree(a)), "agree", a))
    for c in hints.get("composite") or []:
        jobs.append((f"composite|{c['name']}", "composite", c))
    return cands, jobs


def done_checks():
    if not os.path.exists(PARTS_FILE):
        return {}
    with open(PARTS_FILE, encoding="utf-8") as f:
        return {p["id"]: p for p in map(json.loads, f) if "error" not in p}


def run_checks(catalog, jobs):
    done = done_checks()
    todo = [j for j in jobs if j[0] not in done]
    print(f"{len(jobs)} checks: {len(jobs) - len(todo)} already done, {len(todo)} to go", flush=True)
    engine, start = get_engine(), time.time()
    for k, (jid, kind, args) in enumerate(todo, 1):
        t0, part = time.time(), {"id": jid}
        try:
            with engine.connect() as conn:
                conn.connection.dbapi_connection.timeout = TIMEOUT
                check = {"link": lambda: check_link(conn, catalog, *args), "list": lambda: check_list(conn, catalog, *args),
                         "agree": lambda: check_agree(conn, catalog, args),
                         "composite": lambda: check_composite(conn, catalog, args)}[kind]
                part.update(check())
        except Exception as e:  # keep going; the error is recorded and the check is retried next run
            part["error"] = str(e).splitlines()[0][:300]
        with open(PARTS_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(part) + "\n")
        if "error" in part:
            status = "ERROR " + part["error"][:90]
        elif kind in ("link", "list"):
            status = f"{part['matched']:,}/{part['checked']:,}"
        elif kind == "agree":
            status = f"same {part['same']:,}/{part['both_known']:,}"
        else:
            status = f"one target {part['one']:,}/{part['checked']:,}"
        print(f"[{k}/{len(todo)}] {jid[:110]}: {status} ({time.time() - t0:.1f}s, "
              f"{(time.time() - start) / 60:.1f} min)", flush=True)


def run_shapes(catalog, links):
    """Shape (rows per target, targets used) for the links between core tables and from the answer key."""
    done = done_checks()
    todo = [l for l in links if l["status"] in ("confirmed", "mostly") and l["how"] != "list" and l["tier"] in ("core", "answer_key")
            and l["target_tier"] == "core" and f"shape|{l['id']}" not in done]
    if not todo:
        return
    print(f"{len(todo)} link shapes to measure", flush=True)
    engine = get_engine()
    for k, l in enumerate(todo, 1):
        t0, part = time.time(), {"id": f"shape|{l['id']}"}
        try:
            with engine.connect() as conn:
                conn.connection.dbapi_connection.timeout = TIMEOUT
                part.update(check_shape(conn, catalog, l["table"], l["column"], l["target"], l["target_column"]))
        except Exception as e:
            part["error"] = str(e).splitlines()[0][:300]
        with open(PARTS_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(part) + "\n")
        print(f"[shape {k}/{len(todo)}] {l['id'][:100]} ({time.time() - t0:.1f}s)", flush=True)


# ---------------------------------------------------------------- 3. results

def status_of(pct):
    return next(s for limit, s in STATUS_BANDS if pct >= limit)


def shared_words(column, table):
    a = set(re.findall(r"[a-z]{3,}", re.sub(r"([a-z])([A-Z])", r"\1 \2", column).lower().replace("_", " ")))
    b = set(re.findall(r"[a-z]{3,}", re.sub(r"([a-z])([A-Z])", r"\1 \2", table).lower().replace("_", " ")))
    return len(a & b)


def choose(catalog, tables, cands, parts):
    """One link per column: the candidate with the best match; the others are kept as alternatives."""
    links, rejected = [], []
    for (src, column), cs in cands.items():
        obj, options = catalog[src], []
        for tgt, tcol, how in cs:
            p = parts.get(f"link|{src}|{column}|{tgt}|{tcol}")
            opt = {"target": tgt, "target_column": tcol, "how": how,
                   "target_tier": tables[tgt]["tier"] if tgt in tables else "left out"}
            if obj["kind"] == "view":
                opt["status"] = "not checked (view)"
            elif not obj["rows"]:
                opt["status"] = "not checked (no rows here)"
            elif p is None:
                opt["status"] = "not checked yet"
            elif p["checked"] == 0:
                opt.update(status="not checked (column empty here)", checked=0)
            else:
                pct = round(100 * p["matched"] / p["checked"], 1)
                opt.update(status=status_of(pct), match_pct=pct, checked=p["checked"], sampled=p["sampled"])
            options.append(opt)
        rank = lambda o: (-(o.get("match_pct") if o.get("match_pct") is not None else -1),
                          HOW_RANK[o["how"]], TIER_RANK.get(o["target_tier"], 9),
                          catalog[o["target"]]["schema"] != obj["schema"], -shared_words(column, o["target"]))
        measured = [o for o in options if "match_pct" in o]
        if measured:
            top = max(o["match_pct"] for o in measured)
            close = [o for o in measured if o["match_pct"] >= top - 0.5]
            best = min(close, key=lambda o: rank(o)[1:])
        else:
            best = min(options, key=lambda o: rank(o)[1:])
        link = {"id": f"{src}|{column}|{best['target']}|{best['target_column']}", "table": src, "column": column,
                "tier": tables[src]["tier"], **best,
                "alternatives": [o for o in options if o is not best]}
        strong = [o for o in link["alternatives"] if o.get("status") == "confirmed"]
        if best.get("status") == "confirmed" and strong:
            link["also_matches"] = [o["target"] for o in strong]
        (rejected if best["status"] == "rejected" else links).append(link)
    for l in links + rejected:
        shape = parts.get(f"shape|{l['id']}")
        if shape:
            l["shape"] = shape
        col = next((c for c in tables[l["table"]]["columns"] if c["name"] == l["column"]), {})
        l["fill_pct"] = col.get("fill_pct")      # how often the link column is filled in this database
    return links, rejected


def unresolved(tables, links, rejected):
    """Columns the schema calls links (in core and support) that point nowhere we could find."""
    have = {(l["table"], l["column"].lower()) for l in links}
    return sorted({(n, c["name"]) for n, t in tables.items() if t["tier"] in CORE_TIERS
                   for c in t["columns"] if c["role"] == "link" and (n, c["name"].lower()) not in have})


def join_paths(tables, links):
    """Shortest join path between every pair of core tables, through core tables first, then support."""
    usable = [l for l in links if l["status"] in ("confirmed", "mostly") and l["how"] != "list"
              and l["tier"] in CORE_TIERS and l["target_tier"] in CORE_TIERS]
    core = sorted(n for n, t in tables.items() if t["tier"] == "core")

    def bfs(start, allowed):
        graph = defaultdict(list)
        for l in usable:
            if l["table"] in allowed and l["target"] in allowed:
                hop = f"{l['table']}.{l['column']} = {l['target']}.{l['target_column']}"
                graph[l["table"]].append((l["target"], hop))
                graph[l["target"]].append((l["table"], hop))
        prev, todo = {start: None}, deque([start])
        while todo:
            node = todo.popleft()
            for nxt, hop in sorted(graph[node]):
                if nxt not in prev:
                    prev[nxt] = (node, hop)
                    todo.append(nxt)
        return prev

    support = {n for n, t in tables.items() if t["tier"] in CORE_TIERS}
    paths = {}
    for a in core:
        for allowed in (set(core), support):
            prev = bfs(a, allowed)
            for b in core:
                if b > a and b in prev and f"{a} ~ {b}" not in paths:
                    hops, node = [], b
                    while prev[node]:
                        node, hop = prev[node]
                        hops.append(hop)
                    paths[f"{a} ~ {b}"] = hops[::-1]
    return paths


def build(catalog, tables, hints, cands):
    parts = done_checks()
    links, rejected = choose(catalog, tables, cands, parts)
    agree = []
    for a in hints.get("agree") or []:
        src, via, tgt, tcol, left, right = parse_agree(a)
        p = parts.get("agree|" + "|".join(parse_agree(a)))
        row = {"table": src, "road_1": f"{src}.{left}", "road_2": f"{src}.{via} -> {tgt}.{right}",
               "tier": tables[src]["tier"]}
        if p:
            row.update(both_known=p["both_known"], same=p["same"], sampled=p["sampled"],
                       same_pct=round(100 * p["same"] / p["both_known"], 2) if p["both_known"] else None)
        agree.append(row)
    composite = []
    for c in hints.get("composite") or []:
        row = {"name": c["name"], "table": c["table"], "target": c["target"],
               "on": [f"{c['table']}.{s} = {c['target']}.{t}" for s, t in c["join_on"].items()]}
        p = parts.get(f"composite|{c['name']}")
        if p:
            row.update({k: v for k, v in p.items() if k != "id"})
            row["one_pct"] = round(100 * p["one"] / p["checked"], 2) if p["checked"] else None
            if p.get("direct_known"):
                row["direct_same_pct"] = round(100 * p["direct_same"] / p["direct_known"], 2)
            if p.get("answer_key_rows"):
                row["answer_key_same_pct"] = round(100 * p["answer_key_same"] / p["answer_key_rows"], 2)
        composite.append(row)
    paths = join_paths(tables, links)
    for c in hints.get("composite") or []:      # a composite link replaces its often-empty one-column link
        if c.get("direct"):
            direct = f"{c['table']}.{c['direct']} = {c['target']}.{c['target_key']}"
            both = " AND ".join(f"{c['table']}.{s} = {c['target']}.{t}" for s, t in c["join_on"].items())
            paths = {pair: [both if hop == direct else hop for hop in hops] for pair, hops in paths.items()}
    return {"made_at": f"{datetime.now():%Y-%m-%d %H:%M}", "links": links, "rejected": rejected,
            "composite": composite,
            "unresolved": [{"table": t, "column": c} for t, c in unresolved(tables, links, rejected)],
            "agree": agree, "paths": paths}


def shape_text(s):
    per = s["rows"] / s["distinct"] if s["distinct"] else 0
    kind = "one-to-one" if s["rows"] == s["distinct"] else f"many-to-one (avg {per:,.1f}, rows per target)"
    used = f"{100 * s['target_used'] / s['target_rows']:.1f}%" if s["target_rows"] else "?"
    return f"{kind}; {used} of target rows used"


def write_markdown(res, tables):
    links = res["links"]
    L = ["# Links between tables (Step 4)", "", f"Made on {res['made_at']}. Every link was checked against the data "
         "with counts only: of the rows that have a value in the column, how many find their row in the target?", "",
         "Status: **confirmed** 99%+ match, **mostly** 90-99%, **weak** 50-90%, **rejected** under 50%. Tables over "
         f"{SAMPLE:,} rows were checked on an even spread of about {SAMPLE:,} rows.", "", "## Totals", "",
         "| Status | " + " | ".join(TIER_RANK) + " |", "|---|" + "---:|" * len(TIER_RANK)]
    statuses = Counter((l["status"], l["tier"]) for l in links + res["rejected"])
    for st in sorted({s for s, _ in statuses}):
        L.append(f"| {st} | " + " | ".join(str(statuses[(st, t)]) for t in TIER_RANK) + " |")
    L += ["", "By source of the link: " + ", ".join(f"{v} {k}" for k, v in Counter(l["how"] for l in links).items()) + "."]
    L += ["", "## Two roads agree", "", "| Table | Road 1 | Road 2 | Both known | Same |", "|---|---|---|---:|---:|"]
    for a in res["agree"]:
        L.append(f"| {a['table']} | {a['road_1']} | {a['road_2']} | {a.get('both_known', 0):,} | "
                 f"{a.get('same_pct', '-')}% |")
    L += ["", "## Links on two or more columns", ""]
    for c in res["composite"]:
        L += [f"**{c['name']}**", "", "Join on: " + " AND ".join(f"`{x}`" for x in c["on"]) + ".", ""]
        if "checked" in c:
            L += [f"- Rows checked: {c['checked']:,}. Exactly one target: {c['one']:,} ({c['one_pct']}%); "
                  f"none: {c['none']:,}; several: {c['many']:,}."]
            if "direct_same_pct" in c:
                L.append(f"- Where the one-column link is filled ({c['direct_known']:,} rows), both give the same "
                         f"target in {c['direct_same_pct']}%.")
            if "answer_key_same_pct" in c:
                L.append(f"- Against the answer key ({c['answer_key_rows']:,} rows): same target in "
                         f"{c['answer_key_same_pct']}%.")
        L.append("")
    for tier in ("core", "answer_key", "support"):
        L += ["", f"## Links from {tier.replace('_', ' ')} tables", "",
              "| Table.column | Filled here | Points to | Status | Match | How found | Shape / note |", "|---|---:|---|---|---:|---|---|"]
        for l in sorted((l for l in links if l["tier"] == tier), key=lambda l: (l["table"], l["column"])):
            note = shape_text(l["shape"]) if "shape" in l else ""
            if l.get("also_matches"):
                note += (" " if note else "") + "also matches " + ", ".join(l["also_matches"])
            L.append(f"| {l['table']}.{l['column']} | {'' if l['fill_pct'] is None else str(l['fill_pct']) + '%'} | {l['target']}.{l['target_column']} ({l['target_tier']}) | "
                     f"{l['status']} | {'' if 'match_pct' not in l else str(l['match_pct']) + '%'} | {l['how']} | {note} |")
    L += ["", "## Rejected (the data says no)", "", "| Table.column | Tried | Match |", "|---|---|---:|"]
    for l in sorted(res["rejected"], key=lambda l: (TIER_RANK[l["tier"]], l["table"])):
        tried = [l] + l["alternatives"]
        L.append(f"| {l['table']}.{l['column']} | " + "; ".join(f"{o['target']}.{o['target_column']} "
                 f"{o.get('match_pct', '-')}%" for o in tried) + f" | {l.get('match_pct')}% |")
    L += ["", f"## Link columns in core and support with no target found ({len(res['unresolved'])})", ""]
    L += [f"- {u['table']}.{u['column']}" for u in res["unresolved"]]
    L += ["", "## Join paths between core tables", ""]
    L += [f"- **{pair}**: " + " → ".join(f"`{h}`" for h in hops) for pair, hops in res["paths"].items()]
    L += ["", "## Links from archive tables", "", f"{sum(l['tier'] == 'archive' for l in links):,} links; "
          "see catalog/links.json."]
    with open(os.path.join(OUT_DIR, "links.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")


def main():
    with open(os.path.join(OUT_DIR, "catalog.json"), encoding="utf-8") as f:
        catalog = json.load(f)["objects"]
    with open(os.path.join(OUT_DIR, "schema.json"), encoding="utf-8") as f:
        tables = json.load(f)["tables"]
    with open(HINTS, encoding="utf-8") as f:
        hints = yaml.safe_load(f)
    cands, jobs = plan(catalog, tables, hints)
    if "--plan" in sys.argv:
        print(f"{len(cands)} columns with possible links; {len(jobs)} checks to run")
        print("By tier:", dict(Counter(tables[s]["tier"] for s, _ in cands)))
        print("By how:", dict(Counter(h for cs in cands.values() for _, _, h in cs)))
        return
    if "--report" not in sys.argv:
        run_checks(catalog, jobs)
        run_shapes(catalog, build(catalog, tables, hints, cands)["links"])
    res = build(catalog, tables, hints, cands)
    with open(os.path.join(OUT_DIR, "links.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, indent=1)
    write_markdown(res, tables)
    print("Links:", dict(Counter(l["status"] for l in res["links"])), "| rejected:", len(res["rejected"]),
          "| unresolved in core/support:", len(res["unresolved"]))
    print(f"Saved {OUT_DIR}/links.json and {OUT_DIR}/links.md")


if __name__ == "__main__":
    main()
