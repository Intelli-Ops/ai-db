"""
Review report: one readable page for the person who approves the SQL.

A report that passed its tests is not live yet. A person has to look at
it first, because matching two months of numbers does not prove the
logic is right. This script gathers everything that person needs into
reports/<name>/review.html (open it in a browser):

  - the verdict, and which months it was tested on
  - the written procedure (SOP) next to the SQL
  - things to check, found by our own code (no AI)
  - the numbers the SQL produces, re-run right now, against the expected ones
  - every attempt the AI made, and what it changed between attempts

Approving saves the SQL as a numbered version. run_report.py will only
ever run an approved version.

Run:  python review_report.py sales_by_category
      python review_report.py sales_by_category --approve "Your Name"
"""
import hashlib
import html
import json
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

from compare import compare
from pick_tables import load_schema
from schema_graph import build_graph
from sql_checks import SqlReader, changes_between, check_joins, known_traps, layout
from sql_runner import check_sql, run_sql

REPORTS_DIR = Path("reports")


def fingerprint(text):
    """A short code that changes if even one character of the SQL changes."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_approval(folder):
    """The current approval, or None. Checks the approved file was not edited since."""
    path = folder / "approved.json"
    if not path.exists():
        return None
    approval = json.loads(path.read_text(encoding="utf-8"))
    sql = (folder / approval["file"]).read_text(encoding="utf-8")
    approval["intact"] = fingerprint(sql) == approval["fingerprint"]
    approval["sql"] = sql
    return approval


def test_month(sql, schema, params, expected, key):
    """Run the SQL for one period. Returns (result table or None, problems)."""
    problems = check_sql(sql, SqlReader(sql, schema).tables)
    if problems:
        return None, problems
    try:
        result = run_sql(sql, params)
    except Exception as e:
        return None, [f"The database returned an error: {str(e)[:300]}"]
    return result, compare(result, expected, key)


def gather(folder, G, schema):
    """Collect everything the review page shows."""
    case = json.loads((folder / "case.json").read_text(encoding="utf-8"))
    log = json.loads((folder / "run_log.json").read_text(encoding="utf-8"))
    saved = folder / "automation.sql"
    # A report that did not pass has no saved SQL; show its last attempt instead.
    sql = saved.read_text(encoding="utf-8") if saved.exists() else log["attempts"][-1]["sql"]

    months = []
    for label, params, file in [
        ("First month (shown to the AI)", case["params"], "expected.csv"),
        ("Held-out month (never shown to the AI)", case["holdout_params"], "expected_holdout.csv"),
    ]:
        expected = pd.read_csv(folder / file)
        result, problems = test_month(sql, schema, params, expected, case["key"])
        months.append({"label": label, "params": params, "expected": expected,
                       "result": result, "problems": problems})

    joins = check_joins(sql, G, schema)
    attempts = log["attempts"]
    changed_logic = []
    for i in range(1, len(attempts)):
        attempts[i]["changes"] = changes_between(attempts[i - 1]["sql"], attempts[i]["sql"], schema)
        # A change of columns after a failed comparison deserves a close look:
        # the AI may have bent the logic to fit the numbers. (Not when the
        # attempt before was only asking for a missing table.)
        swapped = any(c.startswith(("Started using", "Stopped using"))
                      for c in attempts[i]["changes"])
        if swapped and not attempts[i - 1].get("need_tables"):
            changed_logic.append(
                f"Between attempts {i} and {i + 1} the AI changed which columns it uses: "
                f"{'; '.join(attempts[i]['changes'])}. Make sure this follows the SOP "
                f"and was not done only to make the numbers match."
            )

    return {
        "name": folder.name,
        "case": case,
        "sop": (folder / "sop.txt").read_text(encoding="utf-8"),
        "log": log,
        "sql": sql,
        "saved": saved.exists(),
        "months": months,
        "must_check": known_traps(sql, schema, case["params"]) + joins["problems"] + changed_logic,
        "notes": joins["notes"],
        "approval": read_approval(folder),
    }


# ---------- the page ----------

STYLE = """
:root { --bg:#fff; --fg:#1b1f24; --soft:#f4f5f7; --line:#d5d9e0; --good:#16794a;
        --bad:#b42318; --warn:#9a6700; --warnbg:#fff8e1; }
@media (prefers-color-scheme: dark) {
  :root { --bg:#15181c; --fg:#e6e8eb; --soft:#1f242b; --line:#39414c; --good:#57c98e;
          --bad:#ff8a80; --warn:#f2c14e; --warnbg:#2a2413; } }
body { background:var(--bg); color:var(--fg); font:15px/1.5 Segoe UI, Arial, sans-serif;
       max-width:1100px; margin:0 auto; padding:24px 16px 60px; }
h1 { font-size:24px; margin:0 0 4px; } h2 { font-size:18px; margin:32px 0 8px;
       border-bottom:1px solid var(--line); padding-bottom:4px; }
.verdict { padding:12px 16px; border-radius:8px; background:var(--soft);
           border-left:6px solid var(--line); margin:12px 0; }
.verdict.good { border-color:var(--good); } .verdict.bad { border-color:var(--bad); }
.verdict.warn { border-color:var(--warn); }
.cols { display:grid; grid-template-columns:1fr 1fr; gap:16px; }
@media (max-width:800px) { .cols { grid-template-columns:1fr; } }
pre { background:var(--soft); border:1px solid var(--line); border-radius:6px; padding:12px;
      overflow-x:auto; white-space:pre-wrap; font:13px/1.45 Consolas, monospace; margin:0; }
ul.check li { background:var(--warnbg); border-left:4px solid var(--warn);
              padding:8px 12px; margin:6px 0; list-style:none; border-radius:4px; }
ul.check { padding:0; } ul.note { color:var(--fg); opacity:.85; }
table { border-collapse:collapse; margin:8px 0; } th, td { border:1px solid var(--line);
        padding:4px 10px; text-align:right; } th { background:var(--soft); }
td:first-child, th:first-child { text-align:left; }
.ok { color:var(--good); font-weight:600; } .no { color:var(--bad); font-weight:600; }
.small { opacity:.75; font-size:13px; } details { margin:8px 0; }
summary { cursor:pointer; font-weight:600; }
"""


def esc(value):
    return html.escape(str(value))


def bullet_list(items, css):
    return f"<ul class='{css}'>" + "".join(f"<li>{esc(i)}</li>" for i in items) + "</ul>"


def table_html(df):
    head = "".join(f"<th>{esc(c)}</th>" for c in df.columns)
    rows = "".join(
        "<tr>" + "".join(f"<td>{esc(v)}</td>" for v in row) + "</tr>"
        for row in df.itertuples(index=False)
    )
    return f"<table><tr>{head}</tr>{rows}</table>"


def render(d):
    status = d["log"]["status"]
    approval = d["approval"]
    passed = status.startswith("PASSED")
    still_matches = all(not m["problems"] for m in d["months"])

    if approval and approval["intact"] and approval["sql"] == d["sql"]:
        kind, verdict = "good", (f"APPROVED as version {approval['version']} by "
                                 f"{approval['approved_by']} on {approval['approved_at']}.")
    elif not passed:
        kind, verdict = "bad", f"NOT READY: {status}. This SQL cannot be approved."
    elif not still_matches:
        kind, verdict = "bad", "The SQL passed when it was built but no longer matches. See the numbers below."
    else:
        kind, verdict = "warn", "PASSED its tests. Waiting for a person to review and approve."
        if approval:
            verdict += (f" Version {approval['version']} stays the approved one "
                        f"until this newer SQL is approved.")

    last = d["log"]["attempts"][-1]
    parts = [
        f"<h1>{esc(d['case']['question'])}</h1>",
        f"<div class='small'>Report folder: reports/{esc(d['name'])} &middot; "
        f"page made {datetime.now():%Y-%m-%d %H:%M}</div>",
        f"<div class='verdict {kind}'><b>{esc(verdict)}</b><br>"
        f"SQL written by {esc(last['model'])} on {esc(d['log']['date'])}, "
        f"after {len(d['log']['attempts'])} attempt(s).</div>",
    ]
    if d["log"].get("detail"):
        parts.append(f"<div class='verdict bad'><b>Why it stopped:</b> {esc(d['log']['detail'])}</div>")

    parts.append("<h2>1. Things to check before approving</h2>")
    if d["must_check"]:
        parts.append("<p>Found by our own code, not by the AI. Each one is a way the report "
                     "could be wrong even though the test months match.</p>")
        parts.append(bullet_list(d["must_check"], "check"))
    else:
        parts.append("<p class='ok'>Our checks found nothing that needs attention.</p>")
    if d["notes"]:
        parts.append("<details><summary>Good to know about the joins "
                     f"({len(d['notes'])})</summary>{bullet_list(d['notes'], 'note')}</details>")

    parts.append("<h2>2. The written procedure and the SQL</h2>")
    title = "SQL" if d["saved"] else "SQL (last attempt, not saved)"
    parts.append(f"<div class='cols'><div><b>Written procedure (SOP)</b><pre>{esc(d['sop'])}</pre></div>"
                 f"<div><b>{title}</b><pre>{esc(layout(d['sql']))}</pre></div></div>")
    added = d["log"].get("tables_added_on_request")
    if added:
        parts.append(f"<p class='small'>Tables the AI asked to add: {esc(', '.join(added))}</p>")

    parts.append("<h2>3. The numbers (re-run just now)</h2>")
    for m in d["months"]:
        period = f"{m['params']['start_date']} to {m['params']['end_date']}"
        parts.append(f"<h3>{esc(m['label'])}: {esc(period)}</h3>")
        if not m["problems"]:
            parts.append(f"<p class='ok'>Every cell matches the expected report "
                         f"({len(m['expected'])} rows).</p>{table_html(m['result'])}")
        else:
            parts.append("<p class='no'>Does not match the expected report:</p>")
            parts.append(bullet_list(m["problems"], "note"))
            parts.append("<div class='cols'><div><b>Expected</b>" + table_html(m["expected"]) + "</div>")
            produced = table_html(m["result"]) if m["result"] is not None else "<p>(no result)</p>"
            parts.append(f"<div><b>Produced by the SQL</b>{produced}</div></div>")

    parts.append("<h2>4. What the AI tried</h2>")
    for n, a in enumerate(d["log"]["attempts"], start=1):
        outcome = "matched" if not a["problems"] else "did not match"
        if a.get("need_tables") and not a.get("tested"):
            outcome = "asked for more tables"
        body = ""
        if a.get("changes"):
            body += "<b>Changed since the attempt before:</b>" + bullet_list(a["changes"], "note")
        if a["problems"]:
            body += "<b>Result:</b>" + bullet_list(a["problems"], "note")
        if a.get("conflict"):
            body += f"<p><b>The AI reported a conflict:</b> {esc(a['conflict'])}</p>"
        body += f"<p class='small'>{esc(a['explanation'])}</p><pre>{esc(layout(a['sql']))}</pre>"
        parts.append(f"<details><summary>Attempt {n} ({esc(a['model'])}): {outcome}</summary>{body}</details>")

    parts.append("<h2>5. To approve</h2>")
    if passed and still_matches:
        parts.append(f"<pre>python review_report.py {esc(d['name'])} --approve \"Your Name\"</pre>")
    else:
        parts.append("<p>This SQL cannot be approved. Fix the SOP or the expected output, "
                     "then build the report again.</p>")

    return (f"<!doctype html><html lang='en'><head><meta charset='utf-8'>"
            f"<meta name='viewport' content='width=device-width, initial-scale=1'>"
            f"<title>Review: {esc(d['case']['question'])}</title><style>{STYLE}</style></head>"
            f"<body>{''.join(parts)}</body></html>")


def approve(folder, d, name):
    """Save the SQL as the next numbered version, with who approved it and when."""
    if not d["saved"] or not d["log"]["status"].startswith("PASSED"):
        sys.exit(f"Cannot approve: {d['log']['status']}")
    if any(m["problems"] for m in d["months"]):
        sys.exit("Cannot approve: the SQL no longer matches the expected reports. "
                 "Open review.html to see why.")
    if d["approval"] and d["approval"]["intact"] and d["approval"]["sql"] == d["sql"]:
        sys.exit(f"Already approved as version {d['approval']['version']}.")

    versions = folder / "versions"
    versions.mkdir(exist_ok=True)
    version = len(list(versions.glob("v*.sql"))) + 1
    file = versions / f"v{version}.sql"
    file.write_text(d["sql"], encoding="utf-8")
    approval = {
        "version": version,
        "file": f"versions/v{version}.sql",
        "fingerprint": fingerprint(d["sql"]),
        "approved_by": name,
        "approved_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "warnings_seen_at_approval": d["must_check"],
    }
    (folder / "approved.json").write_text(json.dumps(approval, indent=2), encoding="utf-8")
    print(f"Approved as version {version} by {name}.")
    if d["must_check"]:
        print(f"Recorded {len(d['must_check'])} warning(s) that were on the page at approval.")


def main():
    args = sys.argv[1:]
    if not args:
        sys.exit('Usage: python review_report.py <report_name> [--approve "Your Name"]')
    folder = REPORTS_DIR / args[0]
    if not (folder / "run_log.json").exists():
        sys.exit(f"No built report in {folder}. Run build_report.py first.")
    G, schema = build_graph(), load_schema()
    d = gather(folder, G, schema)

    if "--approve" in args:
        position = args.index("--approve")
        if position + 1 >= len(args):
            sys.exit('Give your name: --approve "Your Name"')
        approve(folder, d, args[position + 1])
        d = gather(folder, G, schema)

    (folder / "review.html").write_text(render(d), encoding="utf-8")
    print(f"Review page: {folder / 'review.html'}")
    print(f"Status: {d['log']['status']}")
    print(f"Things to check: {len(d['must_check'])}")
    for item in d["must_check"]:
        print(f"  [!] {item}")


if __name__ == "__main__":
    main()
