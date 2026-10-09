"""
Schema graph: tables are nodes, foreign keys are edges.

Given a set of tables a question needs, find_join_path() finds the
smallest set of joins that connects them all, including any
in-between tables needed to get from one to another.

Each join also comes with warnings about what it can do to the numbers:
  - MULTIPLIES ROWS: one row can match many, so sums get overstated
  - MAY DROP ROWS:   rows with no match silently disappear
  - AMBIGUOUS:       the two tables are linked in more than one way

Run:  python schema_graph.py
"""
import json
from collections import defaultdict

import networkx as nx
from networkx.algorithms.approximation import steiner_tree


def build_graph(schema_file="schema.json"):
    with open(schema_file, encoding="utf-8") as f:
        schema = json.load(f)

    G = nx.Graph()
    for t in schema:
        G.add_node(t["name"], description=t["description"])

    for t in schema:
        nullable = {c["name"]: c["nullable"] for c in t["columns"]}
        primary_key = set(t["primary_key"])

        # A foreign key can span several columns (a "composite" key).
        # Group its columns so they become one join condition joined by AND.
        groups = defaultdict(list)
        for fk in t["foreign_keys"]:
            groups[(fk["fk_name"], fk["references_table"])].append(fk)

        for (fk_name, ref_table), cols in groups.items():
            if ref_table == t["name"]:
                continue  # skip tables that point to themselves
            condition = " AND ".join(
                f"{t['name']}.{c['column']} = {ref_table}.{c['references_column']}"
                for c in cols
            )
            fk_columns = [c["column"] for c in cols]
            link = {
                "fk_name": fk_name,
                "child": t["name"],    # the table that holds the foreign key
                "parent": ref_table,   # the table the foreign key points to
                "condition": condition,
                "columns": fk_columns,
                # [child column, parent column] for each column of the key
                "pairs": [[c["column"], c["references_column"]] for c in cols],
                # If the linking column can be empty, some child rows
                # point to nothing and will not survive a join.
                "nullable": any(nullable[c] for c in fk_columns),
                # If the foreign key covers the child's whole primary key,
                # a parent can have at most one child row (one-to-one).
                "child_unique": bool(primary_key) and primary_key <= set(fk_columns),
            }
            # Two tables can be linked in more than one way
            # (e.g. billing address and shipping address), so keep a list.
            if G.has_edge(t["name"], ref_table):
                G[t["name"]][ref_table]["fks"].append(link)
            else:
                G.add_edge(t["name"], ref_table, fks=[link])
    return G


def describe_link(link, frm, to):
    """Work out what joining frm -> to through this foreign key does to the rows."""
    child, parent = link["child"], link["parent"]
    columns = ", ".join(link["columns"])
    warnings = []

    if frm == child:
        # Child -> parent: a foreign key always points at one parent row,
        # so this direction can never multiply rows.
        relationship = "one-to-one" if link["child_unique"] else "many-to-one"
    else:
        # Parent -> child: one parent row can have many child rows.
        relationship = "one-to-one" if link["child_unique"] else "one-to-many"
        if relationship == "one-to-many":
            warnings.append({
                "type": "MULTIPLIES ROWS",
                "message": (
                    f"one {parent} row can match many {child} rows, so values from "
                    f"{parent} (and tables joined before it) repeat. "
                    f"Do not sum them after this join."
                ),
            })
        warnings.append({
            "type": "MAY DROP ROWS",
            "message": f"{parent} rows with no matching {child} row are left out.",
        })

    if link["nullable"]:
        warnings.append({
            "type": "MAY DROP ROWS",
            "message": f"{child} rows where {columns} is empty are left out.",
        })

    return {
        "fk_name": link["fk_name"],
        "condition": link["condition"],
        "relationship": relationship,
        "warnings": warnings,
    }


def find_join_path(G, tables):
    """Return the joins needed to connect all the given tables."""
    for t in tables:
        if t not in G:
            raise ValueError(f"Unknown table: {t}")
    if len(tables) == 1:
        return []

    for t in tables[1:]:
        if not nx.has_path(G, tables[0], t):
            raise ValueError(f"No link between {tables[0]} and {t}")

    # Only keep the "island" of tables connected to the requested ones.
    # Tables with no links (like dbo.ErrorLog) would otherwise break
    # the algorithm, and they can never be part of a join anyway.
    component = G.subgraph(nx.node_connected_component(G, tables[0]))

    # Steiner tree = the smallest set of edges that connects all the
    # requested tables, adding in-between tables where necessary.
    tree = steiner_tree(component, tables, method="mehlhorn")

    joins = []
    for parent, child in nx.bfs_edges(tree, tables[0]):
        options = [describe_link(link, parent, child) for link in G[parent][child]["fks"]]
        joins.append({
            "from": parent,
            "to": child,
            "options": options,
            # More than one link means a human has to say which one is meant.
            "ambiguous": len(options) > 1,
        })
    return joins


def print_join_path(G, tables):
    print("\nTables needed:", ", ".join(tables))
    joins = find_join_path(G, tables)
    print(f"FROM {tables[0]}")
    for j in joins:
        chosen = j["options"][0]
        print(f"JOIN {j['to']}")
        print(f"  ON {chosen['condition']}")
        if not chosen["warnings"]:
            print(f"  [ok] safe ({chosen['relationship']}): "
                  f"each {j['from']} row matches exactly one {j['to']} row")
        for w in chosen["warnings"]:
            print(f"  [!] {w['type']}: {w['message']}")
        if j["ambiguous"]:
            print(f"  [!] AMBIGUOUS: {len(j['options'])} possible links between these "
                  f"tables. Showing the first; a person must confirm which is meant:")
            for n, opt in enumerate(j["options"], start=1):
                print(f"        {n}. {opt['condition']}")


def main():
    G = build_graph()
    print(f"Graph built: {G.number_of_nodes()} tables, {G.number_of_edges()} connections")

    print("\nMost connected tables (hubs):")
    for name, degree in sorted(G.degree, key=lambda x: x[1], reverse=True)[:5]:
        print(f"  {name}: {degree} connections")

    isolated = [n for n in G.nodes if G.degree(n) == 0]
    print(f"\nTables with no links to anything: {len(isolated)}")
    for n in isolated:
        print(f"  {n}")

    # Demo questions and the tables each would need
    demos = [
        # "Total sales by territory"
        ["Sales.SalesOrderHeader", "Sales.SalesTerritory"],
        # "Sales by product category"
        ["Sales.SalesOrderHeader", "Production.ProductCategory"],
        # "Which department do our salespeople belong to, and what did they sell?"
        ["HumanResources.Department", "Sales.SalesOrderHeader"],
        # "Sales by customer city"
        ["Sales.SalesOrderHeader", "Person.Address"],
    ]
    for tables in demos:
        print_join_path(G, tables)

    # Save the graph so later phases can load it
    with open("schema_graph.json", "w", encoding="utf-8") as f:
        json.dump(nx.node_link_data(G, edges="links"), f, indent=2)
    print("\nSaved to schema_graph.json")


if __name__ == "__main__":
    main()
