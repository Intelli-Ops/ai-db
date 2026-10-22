"""
Build schema.json: the tables the AI may use, with descriptions and links.

Reads what explore_db.py and the description step saved (no database
query, no AI):
  EPM/<schema>/catalog.json       tables, columns, primary keys, foreign keys
  EPM/<schema>/descriptions.json  one description and a kind per table

Leaves out tables of kind backup, empty and system (copies, temp tables,
users/permissions/jobs): they would only confuse the search.

Our database defines very few foreign keys, so links are also INFERRED
from column names. If a table's whole primary key is one column, say
CASEINFO.CASEID, then a CASEID column in another table points to it.
  PAYMENT.BILLID  -> BILL.BILLID
  BILL.CASEID     -> CASEINFO.CASEID
Spelling differences are ignored (STUDY_ID = StudyID = Study_Id).
Inferred links are marked, so the join step warns about them.

schema.json is the raw material for:
  schema_search.py  (finds tables by meaning)
  schema_graph.py   (works out joins)

Run:  python extract_schema.py            (uses DB_NAME and the dbo schema)
"""
import json
import os
import re
import sys
from collections import defaultdict

from db import DB_NAME

LEAVE_OUT = {"backup", "empty", "system"}

# Key names held by more than one table: which table is the real home.
PREFERRED_HOME = {
    "appointmenttypeid": "APPOINTMENTTYPE",
    "insurancelookupid": "INSURANCECOMPANYLOOKUP2",
    "paymentid": "PAYMENT",
    "documentid": "PATIENT_DOCUMENTS",
    "verificationid": "VERIFICATION",
    "hcfaid": "HCFA1500",
}

# Other names used for the same key.
SYNONYMS = {
    "mrn": "patientregid",          # MRN is the patient ID (PATIENTREGID)
    "patientmrn": "patientregid",
}

# Generic key names that say nothing about which table they point to.
TOO_GENERIC = {"id", "statusid", "logid"}


def type_family(sql_type):
    """'bigint' -> 'number', 'varchar(50)' -> 'text'. Links need the same family."""
    t = sql_type.split("(")[0].lower()
    if t in ("bigint", "int", "smallint", "tinyint", "numeric", "decimal", "float"):
        return "number"
    if t in ("varchar", "nvarchar", "char", "nchar"):
        return "text"
    return t


def key_name(column):
    """CASEID, CaseId, Case_ID -> 'caseid'."""
    k = re.sub(r"[^a-z0-9]", "", column.lower())
    return SYNONYMS.get(k, k)


def main():
    schema = sys.argv[1] if len(sys.argv) > 1 else "dbo"
    folder = os.path.join(DB_NAME, schema)
    with open(os.path.join(folder, "catalog.json"), encoding="utf-8") as f:
        catalog = json.load(f)
    with open(os.path.join(folder, "descriptions.json"), encoding="utf-8") as f:
        described = {d["table"]: d for d in json.load(f)}

    tables = {}
    for o in catalog["objects"]:
        d = described.get(o["name"])
        if o["kind"] != "table" or not d or d["kind"] in LEAVE_OUT:
            continue
        tables[o["name"]] = {
            "name": o["name"],
            "kind": d["kind"],
            "rows": o["row_count"],
            "description": d["description"],
            "columns": [{"name": c["name"], "type": c["type"], "nullable": c["nullable"],
                         "description": c["description"]} for c in o["columns"]],
            "primary_key": o["primary_key"],
            "foreign_keys": [],
        }

    # Declared foreign keys (only those between tables we keep).
    declared = 0
    for o in catalog["objects"]:
        t = tables.get(o["name"])
        if not t:
            continue
        for fk in o["foreign_keys"]:
            ref_table, ref_column = fk["references"].rsplit(".", 1)
            if ref_table in tables:
                t["foreign_keys"].append({
                    "fk_name": f"FK {t['name']}.{fk['column']}",
                    "column": fk["column"],
                    "references_table": ref_table,
                    "references_column": ref_column,
                    "inferred": False,
                })
                declared += 1

    # Where each single-column primary key lives.
    homes = defaultdict(list)
    for t in tables.values():
        if len(t["primary_key"]) == 1:
            homes[key_name(t["primary_key"][0])].append(t["name"])
    home = {}
    for k, names in homes.items():
        if k in TOO_GENERIC:
            continue
        if len(names) == 1:
            home[k] = names[0]
        elif k in PREFERRED_HOME:
            home[k] = f"{schema}.{PREFERRED_HOME[k]}"

    inferred = 0
    for t in tables.values():
        linked = {fk["column"] for fk in t["foreign_keys"]}
        for c in t["columns"]:
            target = home.get(key_name(c["name"]))
            if not target or target == t["name"] or c["name"] in linked:
                continue
            target_key = tables[target]["primary_key"][0]
            target_type = next(x["type"] for x in tables[target]["columns"] if x["name"] == target_key)
            if type_family(c["type"]) != type_family(target_type):
                continue  # e.g. a text PAYMENTID cannot hold PAYMENT's number IDs
            t["foreign_keys"].append({
                "fk_name": f"inferred {t['name']}.{c['name']}",
                "column": c["name"],
                "references_table": target,
                "references_column": target_key,
                "inferred": True,
            })
            inferred += 1

    with open("schema.json", "w", encoding="utf-8") as f:
        json.dump(list(tables.values()), f, indent=2, ensure_ascii=False)

    kinds = defaultdict(int)
    for t in tables.values():
        kinds[t["kind"]] += 1
    print(f"Tables:          {len(tables)}  {dict(kinds)}")
    print(f"Columns:         {sum(len(t['columns']) for t in tables.values())}")
    print(f"Declared links:  {declared}")
    print(f"Inferred links:  {inferred}")
    print("Saved to schema.json")


if __name__ == "__main__":
    main()
