"""Property tests for RU-01 (only SELECT) and RU-02 (only allowlisted tables). No database needed."""

from __future__ import annotations

import sqlglot
from hypothesis import given
from hypothesis import strategies as st
from sqlglot import exp

from rollup.guards import MART_TABLES, GuardViolation, check_sql

IDENT = st.from_regex(r"[a-z][a-z0-9_]{0,14}", fullmatch=True)
QIDENT = IDENT.map(lambda s: f'"{s}"')
LITERAL = st.one_of(st.integers(-1000, 1000).map(str), IDENT.map(lambda s: f"'{s}'"))
MART = st.sampled_from(sorted(MART_TABLES))
SCHEMA = st.sampled_from(["marts", "staging", "intermediate", "main", "information_schema", "pg_catalog", "temp"])


def _table_ref(schema: str | None, name: str) -> str:
    return f'{schema}."{name}"' if schema else f'"{name}"'


# RU-01 -----------------------------------------------------------------------------------------------------

NON_SELECT_TEMPLATES = [
    "INSERT INTO {t} VALUES ({v})",
    "INSERT INTO {t} SELECT {v}",
    "UPDATE {t} SET {c} = {v}",
    "DELETE FROM {t} WHERE {c} = {v}",
    "DROP TABLE {t}",
    "DROP VIEW IF EXISTS {t}",
    "CREATE TABLE {t} AS SELECT {v} AS {c}",
    "CREATE VIEW {t} AS SELECT {v} AS {c}",
    "CREATE TEMP TABLE {t} ({c} INT)",
    "ALTER TABLE {t} RENAME TO {c}",
    "ALTER TABLE {t} DROP COLUMN {c}",
    "TRUNCATE {t}",
    "COPY {t} TO '/tmp/{c}.csv'",
    "COPY (SELECT {v}) TO '/tmp/{c}.parquet'",
    "ATTACH '/tmp/{c}.duckdb' AS {c}",
    "DETACH {c}",
    "PRAGMA {c}",
    "SET {c} = {v}",
    "SET GLOBAL {c} = {v}",
    "RESET {c}",
    "INSTALL {c}",
    "LOAD {c}",
    "CALL {c}()",
    "USE {c}",
    "EXPORT DATABASE '/tmp/{c}'",
    "IMPORT DATABASE '/tmp/{c}'",
    "CHECKPOINT",
    "BEGIN",
    "ROLLBACK",
    "DESCRIBE {t}",
    "SHOW {t}",
    "SUMMARIZE {t}",
    "EXPLAIN ANALYZE SELECT {v}",
    "WITH x AS (DELETE FROM {t} RETURNING {c}) SELECT {c} FROM x",
    "WITH x AS (INSERT INTO {t} VALUES ({v}) RETURNING {c}) SELECT {c} FROM x",
]


@st.composite
def non_select_statement(draw: st.DrawFn) -> str:
    template = draw(st.sampled_from(NON_SELECT_TEMPLATES))
    schema = draw(st.one_of(st.none(), SCHEMA))
    name = draw(st.one_of(MART, IDENT))
    stmt = template.format(t=_table_ref(schema, name), c=draw(QIDENT), v=draw(LITERAL))
    return draw(st.sampled_from([stmt, stmt.lower(), stmt + ";", f"  /* x */ {stmt}  ", f"\n{stmt}\n;\n"]))


SELECTS = [
    "SELECT 1",
    "SELECT channel_key FROM marts.dim_channel",
    "SELECT count(*) FROM marts.fct_spend",
]


@given(non_select_statement())
def test_ru01_non_select_always_refused(sql: str) -> None:
    try:
        check_sql(sql)
    except GuardViolation:
        return
    raise AssertionError(f"guard accepted a non-SELECT statement: {sql!r}")


@given(st.sampled_from(SELECTS), non_select_statement(), st.booleans())
def test_ru01_stacked_statements_refused(select: str, other: str, select_first: bool) -> None:
    sql = f"{select}; {other}" if select_first else f"{other}; {select}"
    try:
        check_sql(sql)
    except GuardViolation:
        return
    raise AssertionError(f"guard accepted stacked statements: {sql!r}")


@given(st.text(max_size=200))
def test_ru01_arbitrary_text_is_refused_or_a_single_select(sql: str) -> None:
    """Whatever the input, the guard either refuses it or emits exactly one SELECT/set-op of SELECTs."""
    try:
        g = check_sql(sql)
    except GuardViolation:
        return
    statements = [s for s in sqlglot.parse(g.sql, read="duckdb") if s is not None]
    assert len(statements) == 1
    assert isinstance(statements[0], exp.Select | exp.SetOperation)


# RU-02 -----------------------------------------------------------------------------------------------------


@st.composite
def table_choice(draw: st.DrawFn) -> tuple[str, bool]:
    """A real-table reference and whether it is allowlisted."""
    kind = draw(st.sampled_from(["mart_qualified", "mart_bare", "other_schema_mart_name", "random"]))
    if kind == "mart_qualified":
        return _table_ref("marts", draw(MART)), True
    if kind == "mart_bare":
        return _table_ref(None, draw(MART)), True
    if kind == "other_schema_mart_name":
        other = draw(SCHEMA.filter(lambda s: s != "marts"))
        return _table_ref(other, draw(MART)), False
    schema = draw(st.one_of(st.none(), SCHEMA))
    name = draw(IDENT.filter(lambda n: not n.startswith("cte_")))
    allowed = schema in (None, "marts") and name in MART_TABLES
    return _table_ref(schema, name), allowed


@st.composite
def query_over_tables(draw: st.DrawFn) -> tuple[str, bool]:
    """A SELECT whose real tables appear in FROM, JOIN, subquery, CTE and set-op positions."""
    refs = draw(st.lists(table_choice(), min_size=1, max_size=5))
    tables = [r for r, _ in refs]
    allowed = all(a for _, a in refs)
    shape = draw(st.sampled_from(["from", "join", "in_subquery", "scalar_subquery", "cte", "union", "exists"]))
    first, rest = tables[0], tables[1:]
    if shape == "from" or not rest:
        sql = f"SELECT count(*) AS n FROM {', '.join(tables)}"
    elif shape == "join":
        sql = f"SELECT count(*) AS n FROM {first} AS t0 " + " ".join(
            f"JOIN {t} AS t{i} ON true" for i, t in enumerate(rest, 1)
        )
    elif shape == "in_subquery":
        sql = f"SELECT count(*) AS n FROM {first} WHERE 1 IN (" + " UNION ALL ".join(f"SELECT 1 FROM {t}" for t in rest)
        sql += ")"
    elif shape == "scalar_subquery":
        subqueries = ", ".join(f"(SELECT count(*) FROM {t}) AS c{i}" for i, t in enumerate(rest))
        sql = f"SELECT {subqueries} FROM {first}"
    elif shape == "cte":
        ctes = ", ".join(f"cte_{i} AS (SELECT count(*) AS n FROM {t})" for i, t in enumerate(rest))
        refs_sql = ", ".join(f"cte_{i}" for i in range(len(rest)))
        sql = f"WITH {ctes} SELECT count(*) AS n FROM {first}, {refs_sql}"
    elif shape == "union":
        sql = " UNION ALL ".join(f"SELECT count(*) AS n FROM {t}" for t in tables)
    else:
        sql = f"SELECT count(*) AS n FROM {first} WHERE " + " AND ".join(f"EXISTS (SELECT 1 FROM {t})" for t in rest)
    return sql, allowed


@given(query_over_tables())
def test_ru02_accepted_iff_every_table_is_allowlisted(case: tuple[str, bool]) -> None:
    sql, allowed = case
    try:
        g = check_sql(sql)
    except GuardViolation as e:
        assert not allowed, f"allowlisted query refused ({e.code}): {sql}"
        assert e.code == "table_not_allowed", f"wrong refusal {e.code}: {sql}"
        return
    assert allowed, f"guard accepted a non-allowlisted table: {sql}"
    assert g.tables <= MART_TABLES
    # Every real table in the executed SQL is schema-qualified to marts and allowlisted.
    tree = sqlglot.parse_one(g.sql, read="duckdb")
    cte_names = {c.alias for c in tree.find_all(exp.CTE)}
    for table in tree.find_all(exp.Table):
        if table.name in cte_names and not table.db:
            continue
        assert table.db == "marts" and table.name.lower() in MART_TABLES, g.sql


@given(MART, IDENT.filter(lambda n: n not in MART_TABLES))
def test_ru02_cte_shadowing_cannot_reach_outer_table(mart: str, name: str) -> None:
    """A CTE scoped inside a derived table must not legitimise a same-named real table outside it."""
    inner = f'WITH "{name}" AS (SELECT 1 AS a FROM marts."{mart}") SELECT a FROM "{name}"'
    sql = f'SELECT count(*) FROM ({inner}) s, "{name}"'
    try:
        check_sql(sql)
    except GuardViolation as e:
        assert e.code == "table_not_allowed"
        return
    raise AssertionError(sql)
