"""
Web app: the page management sees. Pick an approved report and a month,
see the table, download it as Excel.

It only runs SQL a person has already approved (through run_report.py,
with all its checks). It never calls the AI: the AI connection is
switched off when this file starts, so a mistake cannot spend money.

Run:  python web_app.py
Then open http://localhost:5000 in a browser.
"""
import calendar
import html
import json
from pathlib import Path

from flask import Flask, abort, request, send_from_directory

import llm
import run_report
from review_report import read_approval


def no_ai(*args, **kwargs):
    raise RuntimeError("The web page never calls the AI.")


llm.httpx.post = no_ai  # switched off for the whole web app

app = Flask(__name__)
REPORTS_DIR = run_report.REPORTS_DIR
OUTPUT_DIR = run_report.OUTPUT_DIR
DEFAULT_MONTH = "2025-05"

STYLE = """
body { font-family: Segoe UI, Arial, sans-serif; margin: 0; background: #f4f6f8; color: #1d2733; }
header { background: #1f4e78; color: white; padding: 18px 32px; }
header h1 { margin: 0; font-size: 22px; } header p { margin: 4px 0 0; opacity: .85; }
main { max-width: 960px; margin: 24px auto; padding: 0 16px; }
.card { background: white; border-radius: 8px; padding: 18px 22px; margin-bottom: 16px;
        box-shadow: 0 1px 3px rgba(0,0,0,.08); }
.card h2 { margin: 0 0 6px; font-size: 18px; }
.status { display: inline-block; padding: 2px 10px; border-radius: 12px; font-size: 13px; }
.ok { background: #e3f4e8; color: #1e6b34; } .wait { background: #fff4d6; color: #7a5600; }
.bad { background: #fde4e4; color: #8a1f1f; }
form { margin-top: 10px; } input, button { font-size: 15px; padding: 6px 10px; }
button { background: #1f4e78; color: white; border: 0; border-radius: 4px; cursor: pointer; }
button:disabled, input:disabled { background: #ccd3da; color: #6b7682; cursor: not-allowed; }
table { border-collapse: collapse; margin: 12px 0; }
th { background: #1f4e78; color: white; text-align: left; padding: 6px 14px; }
td { padding: 6px 14px; border-bottom: 1px solid #e3e7eb; } td.num { text-align: right; }
.note { color: #7a5600; } .small { font-size: 13px; color: #5b6673; } a { color: #1f4e78; }
"""


def page(title, body):
    return (f"<!doctype html><html><head><meta charset='utf-8'><title>{html.escape(title)}</title>"
            f"<style>{STYLE}</style></head><body><header><h1>AI Reporting POC</h1>"
            f"<p>Reports written once by AI, checked and approved by a person, "
            f"then run every month without AI.</p></header><main>{body}</main></body></html>")


def report_names():
    return sorted(p.parent.name for p in REPORTS_DIR.glob("*/case.json"))


def report_status(name):
    """(css class, text, approval or None) for one report."""
    folder = REPORTS_DIR / name
    approval = read_approval(folder)
    if approval and approval["intact"]:
        return "ok", (f"Approved: version {approval['version']}, by {approval['approved_by']} "
                      f"on {approval['approved_at']}"), approval
    if approval:
        return "bad", "The approved SQL was changed after approval. It will not run.", None
    log_file = folder / "run_log.json"
    status = json.loads(log_file.read_text(encoding="utf-8"))["status"] if log_file.exists() \
        else "Not built yet"
    if status.startswith("PASSED"):
        return "wait", "Passed its tests. Waiting for a person to approve it.", None
    return "bad", f"Not ready: {status}", None


def month_range(month):
    """'2025-05' -> ('2025-05-01', '2025-05-31')"""
    year, number = (int(x) for x in month.split("-"))
    last = calendar.monthrange(year, number)[1]
    return f"{year:04d}-{number:02d}-01", f"{year:04d}-{number:02d}-{last:02d}"


def table_html(df):
    head = "".join(f"<th>{html.escape(str(c))}</th>" for c in df.columns)
    rows = []
    for _, row in df.iterrows():
        cells = []
        for value in row:
            try:
                number = float(value)
                text = f"{number:,.0f}" if number == int(number) else f"{number:,.2f}"
                cells.append(f"<td class='num'>{text}</td>")
            except (TypeError, ValueError):
                cells.append(f"<td>{html.escape(str(value))}</td>")
        rows.append(f"<tr>{''.join(cells)}</tr>")
    return f"<table><tr>{head}</tr>{''.join(rows)}</table>"


@app.route("/")
def home():
    cards = []
    for name in report_names():
        case = json.loads((REPORTS_DIR / name / "case.json").read_text(encoding="utf-8"))
        css, text, approval = report_status(name)
        review = (f" <a class='small' href='/review/{name}'>review page</a>"
                  if (REPORTS_DIR / name / "review.html").exists() else "")
        if approval:
            action = (f"<form action='/run' method='get'><input type='hidden' name='report' "
                      f"value='{name}'><input type='month' name='month' value='{DEFAULT_MONTH}' "
                      f"required> <button>Run report</button></form>")
        else:
            action = "<p class='small'>Only approved reports can be run.</p>"
        cards.append(f"<div class='card'><h2>{html.escape(case['question'])}</h2>"
                     f"<span class='status {css}'>{html.escape(text)}</span>{review}{action}</div>")
    ask = ("<div class='card'><h2>Ask a question</h2><p class='small'>Coming later: type a "
           "question in plain English and get a table back.</p><input disabled size='60' "
           "placeholder='e.g. Payments received by insurance company last month'> "
           "<button disabled>Ask</button></div>")
    return page("Reports", "".join(cards) + ask)


@app.route("/run")
def run():
    name, month = request.args.get("report", ""), request.args.get("month", "")
    if name not in report_names():
        abort(404)
    try:
        start, end = month_range(month)
    except ValueError:
        return page("Error", "<div class='card bad'>Pick a month.</div>")
    back = "<p><a href='/'>&larr; All reports</a></p>"
    try:
        result, warnings, out_file, approval = run_report.run_report(name, [start, end])
    except run_report.Stop as e:
        run_report.record(name, "", {}, 0, "STOPPED", [f"{start} {end}: {e}"])
        return page("Stopped", back + f"<div class='card'><h2>No report produced</h2>"
                    f"<span class='status bad'>Stopped</span><p>{html.escape(str(e))}</p></div>")
    case = json.loads((REPORTS_DIR / name / "case.json").read_text(encoding="utf-8"))
    notes = "".join(f"<p class='note'>Check: {html.escape(w)}</p>" for w in warnings)
    body = (back + f"<div class='card'><h2>{html.escape(case['question'])}</h2>"
            f"<p class='small'>{start} to {end}. Approved version {approval['version']} "
            f"(by {html.escape(approval['approved_by'])} on {approval['approved_at']}). "
            f"No AI was used to produce this.</p>{notes}{table_html(result)}"
            f"<form action='/download/{out_file.name}'><button>Download Excel</button></form></div>")
    return page(case["question"], body)


@app.route("/download/<path:filename>")
def download(filename):
    return send_from_directory(OUTPUT_DIR.resolve(), filename, as_attachment=True)


@app.route("/review/<name>")
def review(name):
    if name not in report_names() or not (REPORTS_DIR / name / "review.html").exists():
        abort(404)
    return send_from_directory((REPORTS_DIR / name).resolve(), "review.html")


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000)
