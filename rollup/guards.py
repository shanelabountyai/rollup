"""SQL guards for the text-to-SQL path (PRD "Guards"; Phase 2).

Every check is in code, not prompt. ``check_sql`` either returns a ``GuardedQuery`` whose ``sql`` is regenerated
from the checked syntax tree (so what runs is exactly what was checked, with the row limit injected), or raises
``GuardViolation`` with a stable ``code``.

Guards:
  G1 parse with sqlglot (DuckDB dialect)
  G2 single SELECT only: one statement, root is a SELECT or a set operation of SELECTs, and no DML/DDL/command
     node anywhere in the tree (RU-01)
  G3 only allowlisted ``marts`` tables are read; CTE references are resolved per scope; table functions,
     catalog qualifiers, file paths and system functions are refused (RU-02)
  G4 no ``*`` projection in a query that reads a fact table (``fct_*``); ``COUNT(*)`` is not a projection
  G5 row limit injected on the outer query

G6 (read-only connection) and G7 (5-second timeout) live in ``rollup.runner``.
"""

from __future__ import annotations

from dataclasses import dataclass

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError
from sqlglot.optimizer.scope import Scope, traverse_scope

DIALECT = "duckdb"
ALLOWED_SCHEMA = "marts"
# D-12: the marts are the only queryable layer. test_allowlist_matches_marts keeps this in sync with dbt.
MART_TABLES: frozenset[str] = frozenset(
    {
        "dim_campaign",
        "dim_channel",
        "fct_pipeline",
        "fct_spend",
        "fct_touches",
        "mart_cac_by_channel",
        "mart_funnel_weekly",
    }
)
FACT_PREFIX = "fct_"
DEFAULT_MAX_ROWS = 1000
MAX_SQL_CHARS = 20_000

# Expression types that must never appear anywhere in a query tree (RU-01). Looked up by name so the list
# survives sqlglot versions that lack one of them.
_FORBIDDEN_NODE_NAMES = (
    "Insert",
    "Update",
    "Delete",
    "Merge",
    "Create",
    "Drop",
    "Alter",
    "AlterColumn",
    "TruncateTable",
    "Command",
    "Copy",
    "Set",
    "SetItem",
    "Pragma",
    "Use",
    "Attach",
    "Detach",
    "Install",
    "Load",
    "Export",
    "Summarize",
    "Describe",
    "Show",
    "Transaction",
    "Commit",
    "Rollback",
    "Into",
    "Lock",
    "Placeholder",
    "Parameter",
)
_FORBIDDEN_NODES: tuple[type[exp.Expression], ...] = tuple(
    t for t in (getattr(exp, n, None) for n in _FORBIDDEN_NODE_NAMES) if isinstance(t, type)
)

# DuckDB functions that reach files, the catalog, settings or run nested SQL. The read-only, external-access-off
# connection blocks the dangerous ones again (D-23); refusing them here gives a clear reason up front.
_DENIED_FUNCTION_PREFIXES = (
    "read_",
    "duckdb_",
    "pragma_",
    "parquet_",
    "sniff_",
    "glob",
    "query",
    "iceberg_",
    "delta_",
    "json_execute",
    "getenv",
    "current_setting",
    "getvariable",
    "set_variable",
    "which_secret",
    "sql_auto_complete",
    "install",
    "load",
    "checkpoint",
    "force_checkpoint",
    "enable_",
    "disable_",
    "test_",
    "repository",
    "pg_",
    "has_",
)


class GuardViolation(Exception):
    """A query refused by a guard. ``code`` is stable and machine-readable."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


@dataclass(frozen=True)
class GuardedQuery:
    original_sql: str
    sql: str  # regenerated from the checked tree, row limit injected
    tables: frozenset[str]  # allowlisted mart tables read
    row_cap: int  # rows the runner returns at most; the injected LIMIT is row_cap + 1 to detect truncation


def check_sql(sql: str, max_rows: int = DEFAULT_MAX_ROWS) -> GuardedQuery:
    """Run guards G1-G5. Returns the query to execute or raises ``GuardViolation``."""
    if max_rows < 1:
        raise ValueError("max_rows must be >= 1")
    if not sql or not sql.strip():
        raise GuardViolation("empty", "no SQL given")
    if len(sql) > MAX_SQL_CHARS:
        raise GuardViolation("too_long", f"SQL longer than {MAX_SQL_CHARS} characters")

    tree = _parse_single(sql)
    _check_statement_kind(tree)
    tables = _check_tables(tree)
    _check_functions(tree)
    _check_star(tree, tables)
    _inject_limit(tree, max_rows + 1)
    return GuardedQuery(original_sql=sql, sql=tree.sql(dialect=DIALECT), tables=frozenset(tables), row_cap=max_rows)


# G1 + G2 ---------------------------------------------------------------------------------------------------


def _parse_single(sql: str) -> exp.Expression:
    try:
        statements = [s for s in sqlglot.parse(sql, read=DIALECT) if s is not None]
    except SqlglotError as e:
        raise GuardViolation("parse_error", str(e).splitlines()[0][:300]) from e
    if not statements:
        raise GuardViolation("empty", "no statement found")
    if len(statements) > 1:
        raise GuardViolation("multiple_statements", f"{len(statements)} statements; exactly one SELECT is allowed")
    tree = statements[0]
    if not isinstance(tree, exp.Expression):
        raise GuardViolation("not_select", f"unsupported statement {type(tree).__name__}")
    return tree


def _check_statement_kind(tree: exp.Expression) -> None:
    if not isinstance(tree, exp.Select | exp.SetOperation):
        raise GuardViolation("not_select", f"only SELECT is allowed, got {type(tree).__name__.upper()}")
    for node in tree.walk():
        if isinstance(node, _FORBIDDEN_NODES):
            raise GuardViolation("not_select", f"{type(node).__name__.upper()} is not allowed inside a SELECT")
    for node in tree.find_all(exp.Select, exp.SetOperation):
        if isinstance(node, exp.Select) and node.args.get("into") is not None:
            raise GuardViolation("not_select", "SELECT ... INTO is not allowed")


# G3 --------------------------------------------------------------------------------------------------------


def _check_tables(tree: exp.Expression) -> set[str]:
    try:
        scopes = traverse_scope(tree)
    except SqlglotError as e:
        raise GuardViolation("unresolvable", f"could not resolve table references: {e}") from e

    # Table nodes that refer to a CTE visible in their own scope: unqualified, and the table's *name* (not its
    # alias) resolves to a CTE scope. A derived table that shares the name is not a CTE (found by hypothesis:
    # ``FROM (...) s, "s"`` must not let the real table "s" through).
    cte_refs: set[int] = set()
    for scope in scopes:
        for table in scope.tables:
            if table.args.get("db") or table.args.get("catalog"):
                continue
            source = scope.sources.get(table.name)
            if isinstance(source, Scope) and source.is_cte:
                cte_refs.add(id(table))

    read: set[str] = set()
    for table in tree.find_all(exp.Table):
        if not isinstance(table.this, exp.Identifier):
            raise GuardViolation(
                "table_function", f"table functions are not allowed: {table.this.sql(dialect=DIALECT)[:80]}"
            )
        if id(table) in cte_refs:
            continue
        name = table.name.lower()
        catalog = table.catalog
        schema = table.db.lower()
        if catalog:
            raise GuardViolation("table_not_allowed", f"catalog-qualified names are not allowed: {table.sql(DIALECT)}")
        if schema and schema != ALLOWED_SCHEMA:
            raise GuardViolation("table_not_allowed", f"{schema}.{name} is outside the allowlist (marts only)")
        if name not in MART_TABLES:
            raise GuardViolation("table_not_allowed", f"{table.sql(DIALECT)} is not an allowlisted mart table")
        # Unqualified allowlisted names are pinned to the marts schema (D-26).
        table.set("db", exp.to_identifier(ALLOWED_SCHEMA))
        table.this.set("quoted", False)
        read.add(name)
    return read


def _check_functions(tree: exp.Expression) -> None:
    for func in tree.find_all(exp.Func):
        name = (func.name if isinstance(func, exp.Anonymous) else func.sql_name()).lower()
        if name.startswith(_DENIED_FUNCTION_PREFIXES):
            raise GuardViolation("function_not_allowed", f"function {name}() is not allowed")


# G4 --------------------------------------------------------------------------------------------------------


def _is_projection_star(node: exp.Expression) -> bool:
    """True for a star that selects columns (``*``, ``t.*``, ``COLUMNS(*)``), not ``COUNT(*)``."""
    parent = node.parent
    while isinstance(parent, exp.Column | exp.Columns):
        node, parent = parent, parent.parent
    return not isinstance(parent, exp.AggFunc)


def _check_star(tree: exp.Expression, tables: set[str]) -> None:
    facts = sorted(t for t in tables if t.startswith(FACT_PREFIX))
    if not facts:
        return
    for node in tree.find_all(exp.Star, exp.Columns):
        if _is_projection_star(node):
            raise GuardViolation(
                "star_on_fact_table", f"SELECT * is not allowed when reading fact tables ({', '.join(facts)})"
            )


# G5 --------------------------------------------------------------------------------------------------------


def _inject_limit(tree: exp.Expression, limit: int) -> None:
    current = tree.args.get("limit")
    if current is None:
        tree.set("limit", exp.Limit(expression=exp.Literal.number(limit)))
        return
    if not isinstance(current, exp.Limit):
        raise GuardViolation("bad_limit", "use LIMIT n, not FETCH")
    options = current.args.get("limit_options")
    if options is not None and (options.args.get("percent") or options.args.get("with_ties")):
        raise GuardViolation("bad_limit", "LIMIT must be a row count, not a percentage")
    value = current.expression
    if not (isinstance(value, exp.Literal) and not value.is_string and value.this.isdigit()):
        raise GuardViolation("bad_limit", "LIMIT must be a non-negative integer literal")
    if int(value.this) > limit:
        current.set("expression", exp.Literal.number(limit))
