"""Result-set equivalence scorer for the golden-set eval (D-33)."""

from __future__ import annotations

import datetime as dt
import itertools
from collections import Counter
from decimal import Decimal
from typing import Any

from hypothesis import given
from hypothesis import strategies as st

from rollup.eval.equivalence import normalize, results_equivalent

REF: list[tuple[Any, ...]] = [("paid_search", Decimal("504434.47"), 19), ("paid_social", Decimal("369325.12"), 8)]


def test_identical_results_are_equivalent() -> None:
    assert results_equivalent(REF, list(REF))
    assert results_equivalent([], [])


def test_row_order_ignored_unless_ordered() -> None:
    flipped = list(reversed(REF))
    assert results_equivalent(REF, flipped)
    assert not results_equivalent(REF, flipped, ordered=True)
    assert results_equivalent(REF, list(REF), ordered=True)


def test_column_order_names_and_extra_columns_ignored() -> None:
    draft = [(19, "paid_search", 504434.47, "extra"), (8, "paid_social", 369325.12, "extra")]
    assert results_equivalent(REF, draft)
    assert results_equivalent(REF, draft, ordered=True)


def test_numeric_types_compare_by_value() -> None:
    assert results_equivalent([(1, Decimal("2.50"))], [(1.0, 2.5)])
    assert results_equivalent([(0.1 + 0.2,)], [(0.3,)])  # float noise below 9 significant digits
    assert not results_equivalent([(Decimal("2.50"),)], [(2.51,)])
    assert not results_equivalent([(0.24291497975,)], [(0.2429,)])  # rounding is a different answer


def test_dates_and_midnight_timestamps_match() -> None:
    assert results_equivalent([(dt.date(2025, 7, 1), 3)], [(dt.datetime(2025, 7, 1), 3)])
    assert not results_equivalent([(dt.date(2025, 7, 1), 3)], [(dt.datetime(2025, 7, 1, 4), 3)])


def test_bool_is_not_a_number_and_null_matches_null() -> None:
    assert not results_equivalent([(True,)], [(1,)])
    assert results_equivalent([(None, 1)], [(None, 1)])
    assert not results_equivalent([(None,)], [(0,)])


def test_missing_rows_columns_and_changed_values_fail() -> None:
    assert not results_equivalent(REF, REF[:1])
    assert not results_equivalent(REF, [*REF, ("email", Decimal(0), 0)])
    assert not results_equivalent(REF, [(r[0], r[1]) for r in REF])
    assert not results_equivalent(
        REF, [("paid_search", Decimal("504434.47"), 8), ("paid_social", Decimal("369325.12"), 19)]
    )


def test_column_mapping_must_be_consistent_across_rows() -> None:
    # Each column alone matches some draft column, but no single mapping reproduces the rows.
    ref = [(1, 2), (2, 1)]
    assert results_equivalent(ref, [(2, 1), (1, 2)])
    assert not results_equivalent([(1, 1), (2, 2)], [(1, 2), (2, 1)])


def test_normalize_folds_negative_zero_and_nan() -> None:
    assert normalize(-0.0) == normalize(0)
    assert normalize(float("nan")) == ("nan", None)


values = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(-1000, 1000),
    st.decimals(min_value=-1000, max_value=1000, places=2, allow_nan=False, allow_infinity=False),
    st.dates(),
    st.text(max_size=4),
)


@st.composite
def result_sets(draw: st.DrawFn) -> list[tuple[Any, ...]]:
    n_cols = draw(st.integers(1, 4))
    return draw(st.lists(st.tuples(*[values] * n_cols), min_size=1, max_size=8))


@given(result_sets(), st.randoms(use_true_random=False))
def test_permuting_rows_and_columns_keeps_equivalence(rows: list[tuple[Any, ...]], rnd: Any) -> None:
    perm = list(range(len(rows[0])))
    rnd.shuffle(perm)
    shuffled = [tuple(r[i] for i in perm) for r in rows]
    rnd.shuffle(shuffled)
    assert results_equivalent(rows, shuffled)


def _oracle(ref: list[tuple[Any, ...]], got: list[tuple[Any, ...]], ordered: bool) -> bool:
    """Brute force over every injective column mapping."""
    if len(ref) != len(got):
        return False
    norm = [tuple(normalize(v) for v in r) for r in ref]
    for mapping in itertools.permutations(range(len(got[0])), len(ref[0])):
        proj = [tuple(normalize(r[j]) for j in mapping) for r in got]
        if (proj == norm) if ordered else (Counter(proj) == Counter(norm)):
            return True
    return False


@given(result_sets(), st.data(), st.booleans())
def test_scorer_agrees_with_brute_force_after_one_change(
    rows: list[tuple[Any, ...]], data: st.DataObject, ordered: bool
) -> None:
    i = data.draw(st.integers(0, len(rows) - 1))
    j = data.draw(st.integers(0, len(rows[0]) - 1))
    new = data.draw(values)
    changed = [tuple(new if (a, b) == (i, j) else v for b, v in enumerate(r)) for a, r in enumerate(rows)]
    assert results_equivalent(rows, changed, ordered=ordered) == _oracle(rows, changed, ordered)
    if len(rows[0]) == 1 and normalize(new) != normalize(rows[i][j]):
        assert not results_equivalent(rows, changed, ordered=ordered)
