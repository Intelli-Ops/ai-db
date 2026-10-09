"""
SQL checks: things our code can tell a reviewer about AI-written SQL.

A report can match the expected output and still be wrong in ways the
test months do not reveal. These checks read the SQL (no AI) and point
out what a person should look at before approving it:

  known_traps()      common mistakes, e.g. a date filter that misses
                     orders placed during the last day
  check_joins()      joins that do not follow a real link in the database
  changes_between()  what the AI changed from one attempt to the next

We use the parser only to READ the SQL. We never let it rewrite the SQL,
because rewriting can quietly change what the query does.
"""
import difflib
import re

import sqlglot
from sqlglot import exp

from schema_graph import describe_link

DATE_TYPES = {"date", "datetime", "datetime2", "smalldatetime", "datetimeoffset"}
DATE_TEXT = re.compile(r"\d{4}-\d{2}-\d{2}|\d{8}")
CLAUSES = re.compile(
    # not after INNER/LEFT/..., so "INNER JOIN" stays together
    r"(?<!\bINNER)(?<!\bLEFT)(?<!\bRIGHT)(?<!\bFULL)(?<!\bCROSS)(?<!\bOUTER)"
    r"\s+(?=\b(?:FROM|WHERE|GROUP BY|HAVING|ORDER BY|UNION"
    r"|(?:(?:INNER|LEFT|RIGHT|FULL|CROSS)(?: OUTER)? )?JOIN)\b)",
    re.IGNORECASE,
)


def parse(sql):
    return sqlglot.parse_one(sql, read="tsql")


def layout(sql):
    """Put each clause on its own line so a person can read it. Only spacing changes."""
    lines = []
    for line in sql.strip().splitlines():
        if line.lstrip().startswith("--"):
            lines.append(line)
        else:
            line = CLAUSES.sub("\n", line.strip())
            lines.append(re.sub(r"\s+(?=\bON\b)", "\n    ", line, flags=re.IGNORECASE))
    return "\n".join(lines)


def same_sql(a, b):
    """True if two queries are the same apart from spacing and capitals."""
    def squash(sql):
        return " ".join(sql.lower().split()).rstrip("; ")
    return squash(a) == squash(b)


class SqlReader:
    """Reads one query and answers: which real table and column is this?"""

    def __init__(self, sql, schema):
        self.tree = parse(sql)
        self.schema = schema
        real_names = {name.lower(): name for name in schema}
        # alias (or bare table name) -> real table name, in order of appearance
        self.aliases = {}
        for t in self.tree.find_all(exp.Table):
            real = real_names.get(f"{t.db}.{t.name}".lower())
            if real:
                self.aliases[t.alias_or_name.lower()] = real
        self.tables = list(dict.fromkeys(self.aliases.values()))

    def column(self, col):
        """(table, column) for a column in the SQL, or None if we cannot tell."""
        if col.table:
            candidates = [self.aliases.get(col.table.lower())]
        else:
            candidates = self.tables
        owners = []
        for table in candidates:
            if not table:
                continue
            for c in self.schema[table]["columns"]:
                if c["name"].lower() == col.name.lower():
                    owners.append((table, c["name"]))
        return owners[0] if len(owners) == 1 else None

    def column_type(self, table, column):
        for c in self.schema[table]["columns"]:
            if c["name"] == column:
                return c["type"]

    def columns_used(self):
        used = {self.column(c) for c in self.tree.find_all(exp.Column)}
        return used - {None}

    def period_columns(self):
        """Date columns that are compared with a report parameter."""
        found = set()
        comparisons = (exp.GT, exp.GTE, exp.LT, exp.LTE, exp.Between)
        for node in self.tree.find_all(*comparisons):
            if not isinstance(node.this, exp.Column) or not node.find(exp.Parameter):
                continue
            owner = self.column(node.this)
            if owner and self.column_type(*owner) in DATE_TYPES:
                found.add(owner)
        return found


def known_traps(sql, schema, params):
    """Common mistakes that the test months may not reveal."""
    reader = SqlReader(sql, schema)
    traps = []

    # "OrderDate <= @end_date" stops at midnight at the START of the end date,
    # so an order placed at 3pm on the last day is left out.
    for node in reader.tree.find_all(exp.LTE, exp.Between):
        limit = node.expression if isinstance(node, exp.LTE) else node.args.get("high")
        if not isinstance(node.this, exp.Column) or not isinstance(limit, exp.Parameter):
            continue
        owner = reader.column(node.this)
        if owner and reader.column_type(*owner) in {"datetime", "datetime2", "smalldatetime"}:
            traps.append(
                f"Date filter: {owner[1]} is compared with '<= @{limit.name}' (or BETWEEN). "
                f"{owner[1]} holds a date AND a time, so rows with a time during the last "
                f"day are left out. Safer: {owner[1]} < DATEADD(day, 1, @{limit.name})."
            )

    for literal in reader.tree.find_all(exp.Literal):
        if literal.is_string and DATE_TEXT.fullmatch(literal.this.strip()):
            traps.append(
                f"A date is typed into the SQL ('{literal.this}'). The report would "
                f"give that period's numbers whatever dates it is run for."
            )

    for name in params:
        if f"@{name}".lower() not in sql.lower():
            traps.append(f"The parameter @{name} is never used, so it has no effect.")

    if any(select.args.get("distinct") for select in reader.tree.find_all(exp.Select)):
        traps.append(
            "SELECT DISTINCT is used. It can hide rows that a join has duplicated. "
            "Check that the join is right rather than relying on DISTINCT."
        )
    return list(dict.fromkeys(traps))


def link_pairs(link):
    return {
        frozenset({(link["child"], child_col), (link["parent"], parent_col)})
        for child_col, parent_col in link["pairs"]
    }


def check_joins(sql, G, schema):
    """
    Compare every join in the SQL with the links the database really has.
    Returns {"problems": [...], "notes": [...]}. Problems need a close look;
    notes are things to be aware of.
    """
    reader = SqlReader(sql, schema)
    problems, notes = [], []

    # Collect "table A column = table B column" conditions, grouped by table pair.
    joined = {}
    for eq in reader.tree.find_all(exp.EQ):
        if not isinstance(eq.this, exp.Column) or not isinstance(eq.expression, exp.Column):
            continue
        left, right = reader.column(eq.this), reader.column(eq.expression)
        if left and right and left[0] != right[0]:
            pair = tuple(sorted((left[0], right[0]), key=reader.tables.index))
            joined.setdefault(pair, set()).add(frozenset({left, right}))

    for (a, b), conditions in joined.items():
        written = " AND ".join(
            " = ".join(f"{t.split('.')[1]}.{c}" for t, c in sorted(cond, key=lambda x: x[0] != a))
            for cond in conditions
        )
        if not G.has_edge(a, b):
            # Not a link the database declares. It is still safe from
            # duplicated rows if it lands on a table's whole primary key,
            # because then each row can find at most one match.
            lookup = [
                t for t in (b, a)
                if schema[t]["primary_key"]
                and set(schema[t]["primary_key"])
                <= {c for cond in conditions for tt, c in cond if tt == t}
            ]
            text = (f"{a} is joined straight to {b} ({written}). The database "
                    f"does not declare this link.")
            if lookup:
                notes.append(text + f" It matches on the primary key of {lookup[0]}, so it "
                             f"cannot duplicate rows, but confirm it means what the SOP intends.")
            else:
                problems.append(text + " It does not match on either table's primary key, "
                                "so one row may match many. Check it carefully.")
            continue

        links = G[a][b]["fks"]
        match = [l for l in links if link_pairs(l) == conditions]
        if not match:
            real = "; or ".join(l["condition"] for l in links)
            problems.append(f"{a} and {b} are joined on {written}, but the database "
                            f"links them on: {real}.")
            continue
        for w in describe_link(match[0], a, b)["warnings"]:
            notes.append(f"Join {a} -> {b} - {w['type']}: {w['message']}")
        if len(links) > 1:
            others = "; ".join(l["condition"] for l in links if l is not match[0])
            notes.append(f"{a} and {b} can be linked in {len(links)} ways. This SQL uses "
                         f"{match[0]['condition']}. The other option: {others}. "
                         f"Confirm this is the one the SOP means.")

    cross = [j for j in reader.tree.find_all(exp.Join) if j.kind == "CROSS"]
    if cross:
        problems.append("A CROSS JOIN is used. It pairs every row with every row.")
    return {"problems": problems, "notes": list(dict.fromkeys(notes))}


def changes_between(old_sql, new_sql, schema):
    """What the AI changed from one attempt to the next, in plain words."""
    if same_sql(old_sql, new_sql):
        return ["Nothing: this is the same SQL as the attempt before."]
    try:
        old = SqlReader(old_sql, schema).columns_used()
        new = SqlReader(new_sql, schema).columns_used()
    except sqlglot.errors.SqlglotError:
        old = new = set()
    changes = [f"Started using {t}.{c}" for t, c in sorted(new - old)]
    changes += [f"Stopped using {t}.{c}" for t, c in sorted(old - new)]
    if not changes:
        # Same columns, so show the lines that differ.
        diff = difflib.unified_diff(
            layout(old_sql).splitlines(), layout(new_sql).splitlines(), lineterm="", n=0
        )
        changes = [
            ("Removed: " if d[0] == "-" else "Added: ") + d[1:].strip()
            for d in diff
            if d[:1] in "+-" and not d.startswith(("+++", "---"))
        ]
    return changes
