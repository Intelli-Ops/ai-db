"""
Compare: check a report against the expected output, cell by cell.

This is the objective test. No AI is involved: either every cell
matches or we get a plain list of what is different. That list is
what gets sent back to the AI so it can fix its SQL.
"""
import pandas as pd

MAX_SHOWN = 10      # do not flood the AI with thousands of differences
TOLERANCE = 0.005   # numbers must agree to the cent


def tidy(df):
    """Make both tables comparable: numbers as numbers, text trimmed."""
    out = pd.DataFrame(index=df.index)
    for column in df.columns:
        as_number = pd.to_numeric(df[column], errors="coerce")
        if as_number.notna().sum() == df[column].notna().sum():
            out[column] = as_number.astype(float)
        else:
            out[column] = df[column].astype(str).str.strip()
    return out


def show(items):
    items = list(items)
    text = "; ".join(str(i) for i in items[:MAX_SHOWN])
    if len(items) > MAX_SHOWN:
        text += f"; ... and {len(items) - MAX_SHOWN} more"
    return text


def compare(result, expected, key):
    """
    Return a list of differences. An empty list means a perfect match.

    key is the list of columns that identify a row (e.g. ["Territory"]),
    so we compare Canada with Canada even if the rows are in another order.
    """
    if list(result.columns) != list(expected.columns):
        return [
            f"Columns are wrong. Expected exactly {list(expected.columns)} "
            f"in that order, but got {list(result.columns)}."
        ]

    r, e = tidy(result), tidy(expected)
    problems = []

    if r.duplicated(subset=key).any():
        repeated = r.loc[r.duplicated(subset=key), key].drop_duplicates()
        problems.append(
            f"The result has more than one row for the same {key}: "
            f"{show(repeated.itertuples(index=False, name=None))}"
        )
        return problems

    r_rows, e_rows = r.set_index(key), e.set_index(key)
    if len(r) != len(e):
        problems.append(f"Row count is wrong: expected {len(e)} rows, got {len(r)}.")
    missing = e_rows.index.difference(r_rows.index)
    extra = r_rows.index.difference(e_rows.index)
    if len(missing):
        problems.append(f"Rows that should be there but are missing ({key}): {show(missing)}")
    if len(extra):
        problems.append(f"Rows that should not be there ({key}): {show(extra)}")

    different = []
    for row in e_rows.index.intersection(r_rows.index):
        for column in e_rows.columns:
            want, got = e_rows.at[row, column], r_rows.at[row, column]
            if pd.isna(want) and pd.isna(got):
                continue
            both_numbers = isinstance(want, float) and isinstance(got, float)
            same = abs(want - got) <= TOLERANCE if both_numbers else want == got
            if not same:
                different.append(f"[{row}] {column}: expected {want}, got {got}")
    if different:
        problems.append(f"{len(different)} cell(s) have the wrong value: {show(different)}")

    if not problems and list(r_rows.index) != list(e_rows.index):
        problems.append(
            "All values are right, but the rows are in the wrong order. "
            f"Expected order starts: {show(e_rows.index)}"
        )
    return problems
