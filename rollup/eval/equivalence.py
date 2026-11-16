"""Result-set equivalence for the golden-set eval (D-33).

A draft result is equivalent to the reference result when:

* both have the same number of rows;
* every reference column maps to a distinct draft column (names and column order are ignored; extra draft columns
  are allowed, so a draft that also shows a helper column still scores);
* under that mapping the projected rows are equal as a multiset, or as a sequence when the question is ``ordered``.

Values are compared after normalising: numbers (int, DECIMAL, DOUBLE) to 9 significant digits, so ``count`` vs
``sum`` and DECIMAL vs DOUBLE arithmetic agree; a TIMESTAMP at midnight equals the DATE; booleans stay distinct
from numbers; NULL equals NULL.
"""

from __future__ import annotations

import datetime as dt
import math
from collections import Counter
from collections.abc import Sequence
from decimal import Decimal
from typing import Any

Norm = tuple[str, Any]


def normalize(v: Any) -> Norm:
    if v is None:
        return ("null", None)
    if isinstance(v, bool):
        return ("bool", v)
    if isinstance(v, int | float | Decimal):
        f = float(v)
        if math.isnan(f):
            return ("nan", None)
        if math.isinf(f):
            return ("num", f)
        return ("num", float(f"{f:.9g}") + 0.0)  # + 0.0 folds -0.0 into 0.0
    if isinstance(v, dt.datetime):
        if v.time() == dt.time(0) and v.tzinfo is None:
            return ("date", v.date().isoformat())
        return ("ts", v.isoformat(sep=" "))
    if isinstance(v, dt.date):
        return ("date", v.isoformat())
    return ("str", str(v))


def _sort_key(n: Norm) -> tuple[str, str]:
    return (n[0], repr(n[1]))


def results_equivalent(
    ref_rows: Sequence[Sequence[Any]],
    draft_rows: Sequence[Sequence[Any]],
    *,
    ordered: bool = False,
) -> bool:
    if len(ref_rows) != len(draft_rows):
        return False
    ref = [tuple(normalize(v) for v in r) for r in ref_rows]
    got = [tuple(normalize(v) for v in r) for r in draft_rows]
    n_ref = len(ref[0]) if ref else 0
    n_got = len(got[0]) if got else 0
    if not ref:
        return True  # both empty
    if n_got < n_ref:
        return False

    def column(rows: list[tuple[Norm, ...]], i: int) -> list[Norm]:
        return [r[i] for r in rows]

    def col_match(i: int, j: int) -> bool:
        a, b = column(ref, i), column(got, j)
        return a == b if ordered else sorted(a, key=_sort_key) == sorted(b, key=_sort_key)

    candidates = [[j for j in range(n_got) if col_match(i, j)] for i in range(n_ref)]
    if any(not c for c in candidates):
        return False
    target_seq = ref
    target_bag = Counter(ref)

    def rows_match(mapping: list[int]) -> bool:
        projected = [tuple(r[j] for j in mapping) for r in got]
        return projected == target_seq if ordered else Counter(projected) == target_bag

    order = sorted(range(n_ref), key=lambda i: len(candidates[i]))
    chosen: dict[int, int] = {}

    def search(k: int) -> bool:
        if k == n_ref:
            return rows_match([chosen[i] for i in range(n_ref)])
        i = order[k]
        for j in candidates[i]:
            if j in chosen.values():
                continue
            chosen[i] = j
            if search(k + 1):
                return True
            del chosen[i]
        return False

    return search(0)
