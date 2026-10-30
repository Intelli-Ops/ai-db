"""
Step 3: table understanding (the schema the AI will see).

Combines three things into one schema:
  catalog/catalog.json   Step 1: what exists (tables, views, columns, types, keys)
  catalog/profile.json   Step 2: how full each table and column is in this database
  knowledge/tables.yaml  Step 3: what it means, written by hand (tier, description, column notes)

Every table and view ends up in a tier (core / support / archive / answer_key)
or left out with a reason. Every column of a kept table gets a role (date,
amount, link, flag…), a plain-English meaning and a sensitivity label for the
privacy step. Columns that are empty here stay visible with a label (this is a
staging copy: they may be full in production); only secrets are hidden.
Nothing is judged by dates. No database access, no AI.
Explained in docs/01_project_steps.md, Step 3.

Writes (git-ignored, this machine only)
  catalog/schema.json - the schema, for the next steps
  catalog/schema.md   - the same, readable

Run:  python step03_schema.py
"""
import json
import os
import re
from collections import Counter
from datetime import datetime

import yaml

OUT_DIR = "catalog"
KNOWLEDGE = os.path.join("knowledge", "tables.yaml")
TIERS = ["core", "support", "archive", "answer_key"]
AI_TIERS = ["core", "support", "archive"]         # answer_key tables are only for checking our answers
SCHEMA_TOPIC = {"EAMS": "liens_court", "EDEX": "liens_court", "edi": "edi", "edc": "edi", "settle": "settlements"}

DATE_TYPES = {"date", "datetime", "datetime2", "smalldatetime", "datetimeoffset"}
DECIMAL_TYPES = {"money", "smallmoney", "decimal", "numeric", "float", "real"}
INTEGER_TYPES = {"int", "bigint", "smallint", "tinyint"}
TEXT_TYPES = {"char", "varchar", "nchar", "nvarchar", "sysname", "text", "ntext"}

SECRET = re.compile(r"passw|forgotkey|smtp", re.I)
PERSONAL = re.compile(r"first_?name|last_?name|middle_?name|patient_?name|real ?name|^name$|ssn|birth|(^|_)dob$|"
                      r"address|phone|mobile|fax|e_?mail|gmail|zip|city|signature", re.I)
IDENTIFIER = re.compile(r"mrn|claim_?n(o|umber)|adj_?n(o|umber)|adjnumber|wcabnumber|check_?number|"
                        r"icn_dcn|license|npi|taxid|tax_id", re.I)
FREE_TEXT = re.compile(r"note|comment|review_detail|justification|rebuttal|eventddl|eventxml", re.I)
AMOUNT = re.compile(r"amount|paid|billed|outs|charge|payment|balance|price|fee|settle|value|omfs|cnr|credit|"
                    r"reduction|target|cost|rate", re.I)
MONEY_WORD = re.compile(r"amount|paid|billed|charge|payment|balance|price|fee", re.I)  # for whole-number columns
LINK = re.compile(r"(id|regid|lookupid)$", re.I)
FLAG = re.compile(r"^(is|has)(_|[A-Z])|^for_", re.I)
CODE = re.compile(r"status|type|code|mode|category|level|priority|grade|validity", re.I)
# Tables about running the software, found by name (checked on the table name, not the schema)
SYSTEM_NAME = re.compile(r"ddlevents|sp_who|replicatedarticles|backup|_demo_|^dummy$|^sheet\d|\$'?$|my_activities|"
                         r"(^|_)log$|^log|audit_|session|token|ftpsetup|^menu$|recent_?search|advancesearch|"
                         r"sign_?up|^support|listoffiles|^jobs|t(e|me)mp(?!lat)|"
                         r"\d{1,2}(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)$", re.I)


def words(name):
    """CREATEDON -> createdon, DATE_OF_INJURY_START -> date of injury start, BillByEDIDate -> bill by EDI date."""
    s = re.sub(r"([a-z])([A-Z])", r"\1 \2", name).replace("_", " ")
    return re.sub(r"\s+", " ", s).strip().lower()


def role(col, is_key):
    t, name = col["type"].split("(")[0], col["name"]
    if is_key:
        return "key"
    if t in DATE_TYPES:
        return "date"
    if t == "bit" or FLAG.search(name):
        return "flag"
    if LINK.search(name) and t in INTEGER_TYPES | {"uniqueidentifier", "varchar", "nvarchar"}:
        return "link"
    if t in DECIMAL_TYPES or (t in INTEGER_TYPES and MONEY_WORD.search(name) and not LINK.search(name)):
        return "amount" if AMOUNT.search(name) else "number"
    if CODE.search(name):
        return "code"
    if t in TEXT_TYPES:
        return "text"
    return "number" if t in INTEGER_TYPES else "other"


def sensitivity(name):
    for label, pattern in (("secret", SECRET), ("personal", PERSONAL), ("identifier", IDENTIFIER), ("free text", FREE_TEXT)):
        if pattern.search(name):
            return label
    return None


def describe(name, notes, common, col_role, row):
    """Hand note for this table first, then the shared meaning, then words made from the name."""
    for key, text in notes.items():
        if key.lower() == name.lower():
            return text, "hand"
    if col_role == "key":
        return f"The ID of this row ({row}).", "common"
    if name.lower() in common:
        return common[name.lower()], "common"
    w = words(name)
    return {"flag": f"Yes/no: {w}.", "date": f"Date: {w}.", "link": f"Points to another row: {w}."}.get(
        col_role, w[0].upper() + w[1:] + "."), "from name"


def archive_entry(obj):
    """A table or view not described by hand: described from its name, in the archive tier."""
    w = words(obj["name"])
    if obj["kind"] == "view":
        about = f"A saved query (view); its code can't be read with this login. The name suggests: {w}."
    else:
        about = f"Not described by hand yet. The name suggests: {w}."
    return {"tier": "archive", "topic": SCHEMA_TOPIC.get(obj["schema"], "other"), "about": about,
            "row": "not known yet", "by_name_only": True}


def build(catalog, profile, know):
    entries, archive, left_out = know["tables"], set(know.get("archive") or []), {}
    for reason, names in know["leave_out"].items():
        for n in names:
            left_out[n] = reason
    problems = [f"{n}: in knowledge/tables.yaml but not in the database"
                for n in list(entries) + list(archive) + list(left_out) if n not in catalog]
    problems += [f"{n}: listed twice (tables / archive / leave_out)" for n in catalog
                 if (n in entries) + (n in archive) + (n in left_out) > 1]
    common = {k.lower(): v for k, v in know["common_columns"].items()}

    kept, out_list = {}, {}
    for name, obj in catalog.items():
        p = profile.get(name, {})
        if name in entries:
            kept[name] = make_table(name, obj, p, entries[name], common, problems)
        elif name in archive or obj["kind"] == "view":
            kept[name] = make_table(name, obj, p, archive_entry(obj), common, problems)
        elif name in left_out:
            out_list[name] = left_out[name]
        elif p.get("looks_like_copy"):
            out_list[name] = "Backup, copy, temporary or test table (found by name in Step 2)"
        elif SYSTEM_NAME.search(obj["name"]):
            out_list[name] = "Log, system or scratch table (found by name)"
        else:
            kept[name] = make_table(name, obj, p, archive_entry(obj), common, problems)
    return kept, out_list, problems


def make_table(name, obj, p, entry, common, problems):
    if entry.get("tier") not in TIERS:
        problems.append(f"{name}: unknown tier {entry.get('tier')!r}")
    measured = {c["name"]: c for c in p.get("columns", [])}
    notes = entry.get("columns") or {}
    for key in notes:
        if key.lower() not in {c["name"].lower() for c in obj["columns"]}:
            problems.append(f"{name}.{key}: note for a column that does not exist")
    rows = p.get("rows", obj["rows"]) if obj["kind"] != "view" else None    # views were not counted
    columns, hidden = [], []
    for col in obj["columns"]:
        m = measured.get(col["name"], {})
        fill = m.get("fill_pct") if rows else None
        r = role(col, col["name"] in obj["primary_key"])
        sens = sensitivity(col["name"])
        if sens == "secret":
            hidden.append({"name": col["name"], "reason": "holds a secret (password or login detail)"})
            continue
        text, source = describe(col["name"], notes, common, r, entry["row"])
        c = {"name": col["name"], "type": col["type"], "role": r, "meaning": text, "meaning_from": source,
             "fill_pct": fill}
        if rows and not m.get("filled"):
            c["note"] = "empty in this database"
        elif rows and fill < 1:
            c["note"] = f"almost empty in this database ({fill}% filled)"
        if sens:
            c["sensitive"] = sens
        columns.append(c)
    t = {"tier": entry["tier"], "topic": entry["topic"], "about": entry["about"], "row": entry["row"],
         "check": entry.get("check"), "kind": obj["kind"], "rows": rows, "added_column": p.get("added_column"),
         "primary_key": obj["primary_key"], "columns": columns, "hidden_columns": hidden}
    if entry.get("by_name_only"):
        t["by_name_only"] = True
    if rows == 0:
        t["note"] = "empty in this database"
    return t


def write_markdown(know, kept, out_list, problems):
    cols = [c for t in kept.values() for c in t["columns"]]
    hidden = [h for t in kept.values() for h in t["hidden_columns"]]
    L = ["# Schema (Step 3)", "", f"Made on {datetime.now():%Y-%m-%d %H:%M} from catalog.json, profile.json and "
         "knowledge/tables.yaml. Descriptions were drafted from names only; items marked *check* need a person "
         "who knows the system. Answer-key tables are not shown to the AI; they are only for checking answers.",
         "", "## Totals", "", "| Tier | Tables | Views | Empty here | Rows here |", "|---|---:|---:|---:|---:|"]
    for tier in TIERS:
        ts = [t for t in kept.values() if t["tier"] == tier]
        L.append(f"| {tier} | {len(ts)} | {sum(t['kind'] == 'view' for t in ts)} | {sum(t['rows'] == 0 for t in ts)} "
                 f"| {sum(t['rows'] or 0 for t in ts):,} |")
    L.append(f"| left out | {len(out_list)} | | | |")
    L += ["", f"Columns of kept tables: {len(cols):,} shown, of which {sum('note' in c for c in cols):,} are empty or "
          f"almost empty in this database (labelled); {len(hidden):,} hidden (secrets). "
          f"Meanings: {', '.join(f'{v:,} {k}' for k, v in Counter(c['meaning_from'] for c in cols).items())}. "
          f"Sensitive: {', '.join(f'{v:,} {k}' for k, v in Counter(c.get('sensitive') for c in cols if c.get('sensitive')).items())}.",
          "", "## Tables per topic", "", "| Topic | " + " | ".join(TIERS) + " |", "|---|" + "---:|" * len(TIERS)]
    for topic in know["topics"]:
        n = Counter(t["tier"] for t in kept.values() if t["topic"] == topic)
        L.append(f"| {topic} | " + " | ".join(str(n[tier]) for tier in TIERS) + " |")
    L += ["", "## Left out, by reason", "", "| Reason | Tables |", "|---|---:|"]
    L += [f"| {r} | {n} |" for r, n in Counter(out_list.values()).most_common()]
    questions = [(n, t["check"]) for n, t in kept.items() if t.get("check")]
    L += ["", f"## Open questions ({len(questions)})", "", "The full list, sorted, is in "
          "docs/02_questions_for_manager.md.", ""] + [f"- **{n}**: {q}" for n, q in questions]
    if problems:
        L += ["", "## Problems", ""] + [f"- {p}" for p in problems]
    for tier in TIERS:
        L += ["", f"## {tier.replace('_', ' ').capitalize()} tables" + ("" if tier in AI_TIERS else " (not shown to the AI)")]
        for n, t in sorted(kept.items()):
            if t["tier"] != tier:
                continue
            size = "A view (not counted)" if t["rows"] is None else f"{t['rows']:,} rows here"
            L += ["", f"### {n}", "", f"{t['about']} One row = {t['row']}. {size}."]
            if t.get("by_name_only"):      # described from names only: list the columns, no table
                L += ["", "Columns: " + ", ".join(f"{c['name']} ({c['role']}{', empty here' if 'note' in c else ''})"
                                                  for c in t["columns"])]
            else:
                L += ["", "| Column | Role | Meaning | Filled here | Sensitive |", "|---|---|---|---:|---|"]
                L += [f"| {c['name']} | {c['role']} | {c['meaning']}{'' if c['meaning_from'] == 'hand' else ' *'} | "
                      f"{'' if c['fill_pct'] is None else str(c['fill_pct']) + '%'}{' (empty here)' if 'note' in c else ''} "
                      f"| {c.get('sensitive', '')} |" for c in t["columns"]]
            if t["hidden_columns"]:
                L.append(f"\nHidden: {', '.join(h['name'] + ' (' + h['reason'] + ')' for h in t['hidden_columns'])}")
    L += ["", "\\* meaning not written by hand: shared meaning or made from the column name."]
    with open(os.path.join(OUT_DIR, "schema.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")


def main():
    with open(os.path.join(OUT_DIR, "catalog.json"), encoding="utf-8") as f:
        catalog = json.load(f)["objects"]
    with open(os.path.join(OUT_DIR, "profile.json"), encoding="utf-8") as f:
        profile = json.load(f)["tables"]
    with open(KNOWLEDGE, encoding="utf-8") as f:
        know = yaml.safe_load(f)
    kept, out_list, problems = build(catalog, profile, know)
    with open(os.path.join(OUT_DIR, "schema.json"), "w", encoding="utf-8") as f:
        json.dump({"made_at": f"{datetime.now():%Y-%m-%d %H:%M}", "business": know["business"],
                   "abbreviations": know["abbreviations"], "topics": know["topics"], "ai_tiers": AI_TIERS,
                   "tables": kept, "left_out": out_list}, f, indent=1)
    write_markdown(know, kept, out_list, problems)
    print("Kept:", dict(Counter(t["tier"] for t in kept.values())), "| left out:", len(out_list))
    print(f"Columns shown: {sum(len(t['columns']) for t in kept.values()):,} "
          f"(labelled empty here: {sum('note' in c for t in kept.values() for c in t['columns']):,}), "
          f"hidden (secrets): {sum(len(t['hidden_columns']) for t in kept.values()):,}")
    print("Left out:", dict(Counter(out_list.values())))
    print(f"Problems: {len(problems)}")
    for p in problems:
        print("  -", p)
    print(f"Saved {OUT_DIR}/schema.json and {OUT_DIR}/schema.md")


if __name__ == "__main__":
    main()
