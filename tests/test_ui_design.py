"""Design pass (docs/design/*.dc.html): the new pages, states and display helpers.

These check presentation only: the text a reader sees is unchanged by highlighting, the eval page shows the
committed run file's numbers and nothing it must not (D-43), every guard code has plain words, every page has the
landmarks and labels the accessibility requirements ask for (PRD "Design, UX and accessibility requirements"), and
no module in ``rollup/ui`` runs SQL of its own.
"""

from __future__ import annotations

import ast
import html
import json
import re
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from hypothesis import given
from hypothesis import strategies as st

import rollup.guards
from rollup.guards import MART_TABLES
from rollup.llm import Draft, RecordedModel, parse_draft
from rollup.schema_context import SchemaContext
from rollup.ui.app import create_app, recorded_questions
from rollup.ui.views import (
    EVAL_RUN_FILE,
    GUARD_EXPLAINERS,
    STARTER_IDS,
    group_questions,
    guard_explainer,
    highlight_answer,
    load_eval,
    marts_read,
    starters,
)

LOCAL = "http://127.0.0.1:8000"
UI_DIR = Path(rollup.guards.__file__).parent / "ui"


def _strip(fragment: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", fragment))


def _tag(page: str, testid: str) -> str | None:
    m = re.search(rf'<(\w+)[^>]*data-testid="{testid}"[^>]*>(.*?)</\1>', page, re.DOTALL)
    return None if m is None else m.group(2)


# ---- answer highlighting ---------------------------------------------------------------------------------


def test_highlight_keeps_the_text_and_links_exact_cells() -> None:
    cols = ["campaign_name", "spend"]
    rows = [("Alpha", 151858.18), ("li_2001", 126608.81)]
    answer = "Alpha spent $151,858.18 and li_2001 spent 126,608.81, in Q1 2026."
    lit = highlight_answer(answer, cols, rows)
    assert _strip(str(lit.html)) == answer
    assert lit.cited == {(0, 1), (1, 1)}
    assert 'href="#cell-0-1"' in lit.html and 'href="#cell-1-1"' in lit.html
    # digits inside a word (a campaign id, a quarter) are not marked
    assert "<mark>2001" not in lit.html and ">1</mark>" not in lit.html


def test_currency_sign_is_inside_the_mark() -> None:
    lit = highlight_answer("Spend was $1,500.", ["spend"], [(1500,)])
    assert "<mark>$1,500</mark>" in lit.html
    assert _strip(str(lit.html)) == "Spend was $1,500."


def test_recorded_questions_are_grouped_by_what_they_show() -> None:
    """Review UX-4: the list leads with clean answers, not with the validator's replacement."""
    ev = load_eval()
    assert ev is not None
    groups = group_questions(recorded_questions(), ev)
    assert groups[0]["title"].startswith("Answered: the model's paragraph passed")
    flat = [i["question"] for g in groups for i in g["items"]]
    assert sorted(flat) == sorted(q["question"] for q in recorded_questions())  # every question, once
    misses = {i["question"] for g in groups for i in g["items"] if i["miss"]}
    assert misses == {r.question for r in ev.rows if r.result == "fail"}
    assert group_questions(recorded_questions(), None)[0]["title"] == "Recorded questions"


def test_highlight_escapes_markup() -> None:
    answer = '<script>alert("x")</script> 5'
    lit = highlight_answer(answer, ["n"], [(5,)])
    assert "<script>" not in lit.html
    assert _strip(str(lit.html)) == answer


@given(st.text(max_size=200), st.lists(st.integers(-(10**9), 10**9), max_size=5))
def test_highlight_never_changes_the_text(answer: str, values: list[int]) -> None:
    rows = [(v,) for v in values]
    lit = highlight_answer(answer, ["v"], rows)
    assert _strip(str(lit.html)) == answer
    for i, j in lit.cited:
        assert 0 <= i < len(rows) and j == 0


def test_marts_read_from_executed_sql() -> None:
    sql = "SELECT a FROM marts.fct_spend JOIN marts.dim_campaign USING (campaign_id) JOIN marts.fct_spend s ON TRUE"
    assert marts_read(sql) == ["fct_spend", "dim_campaign"]
    assert marts_read(None) == []


# ---- guard wording ---------------------------------------------------------------------------------------


def test_every_guard_code_has_plain_words() -> None:
    src = Path(rollup.guards.__file__).read_text(encoding="utf-8")
    codes = set(re.findall(r'GuardViolation\(\s*"([a-z_]+)"', src))
    assert codes, "no guard codes found"
    assert codes <= set(GUARD_EXPLAINERS), codes - set(GUARD_EXPLAINERS)
    for code in codes:
        title, body = guard_explainer(code)
        assert title.startswith("Not run") and body
        assert not re.search(r"\d", title + body), code  # refusal wording carries no numbers


# ---- starters --------------------------------------------------------------------------------------------


def test_starters_are_recorded_questions() -> None:
    recorded = {q["question"] for q in recorded_questions()}
    got = starters()
    assert len(got) == len(STARTER_IDS)
    assert all(s["question"] in recorded for s in got)


# ---- eval page -------------------------------------------------------------------------------------------


def _eval_client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(RecordedModel(), db_path=tmp_path / "nope.duckdb"), base_url=LOCAL)


def test_eval_page_shows_the_committed_run_and_nothing_it_must_not(tmp_path: Path) -> None:
    data = json.loads(EVAL_RUN_FILE.read_text(encoding="utf-8"))
    s = data["summary"]
    page = _eval_client(tmp_path).get("/eval")
    assert page.status_code == 200
    text = page.text
    assert _strip(_tag(text, "eval-golden") or "") == f"{s['golden_equivalent']} of {s['golden_total']}"
    assert _strip(_tag(text, "eval-refusal") or "") == f"{s['refusal_correct']} of {s['refusal_total']}"
    assert _strip(_tag(text, "eval-invariants") or "") == str(s["invariant_failures"])
    assert _strip(_tag(text, "eval-ru03") or "") == str(s["model_paragraphs_rejected_ru03"])
    table = _tag(text, "eval-table") or ""
    assert table.count("<tr>") == len(data["items"]) + 1
    plain = html.unescape(text)
    for item in data["items"]:
        assert item["question"] in plain
        # rejected paragraphs, their violations and shown answers are never on the eval page (D-43)
        if item.get("model_answer"):
            assert item["model_answer"] not in plain
        for v in item.get("model_answer_violations") or []:
            assert v not in plain
        if item.get("answer"):
            assert item["answer"] not in plain
    passes = table.count("badge-pass")
    assert passes == s["golden_equivalent"]
    assert table.count("badge-refused") == s["refusal_correct"]


def test_eval_view_rows_match_file() -> None:
    ev = load_eval()
    assert ev is not None
    assert len(ev.rows) == 48
    assert sum(r.result == "pass" for r in ev.rows) == ev.golden_equivalent


def test_eval_page_without_run_file(tmp_path: Path) -> None:
    app = create_app(RecordedModel(), db_path=tmp_path / "nope.duckdb", eval_run_path=tmp_path / "missing.json")
    r = TestClient(app, base_url=LOCAL).get("/eval")
    assert r.status_code == 200 and 'data-testid="eval-missing"' in r.text


def test_data_page_without_warehouse_is_a_clear_503(tmp_path: Path) -> None:
    app = create_app(RecordedModel(), db_path=tmp_path / "nope.duckdb", manifest_path=tmp_path / "nope.json")
    r = TestClient(app, base_url=LOCAL).get("/data")
    assert r.status_code == 503 and "make build" in r.text


# ---- structure every page must have (accessibility requirements) -----------------------------------------


def _structure_ok(page: str, active: str) -> None:
    assert page.lstrip().lower().startswith("<!doctype html>")
    assert '<html lang="en">' in page
    assert '<meta name="viewport"' in page
    assert page.count("<h1") == 1, "exactly one h1"
    assert '<a class="skip" href="#content">' in page and 'id="content"' in page
    assert '<nav class="site-nav" aria-label="Main">' in page
    current = re.findall(r'<a href="([^"]+)" aria-current="page">', page)
    assert current == [active]
    assert "<header" in page and "<main" in page
    for m in re.finditer(r"<input\b[^>]*>", page):
        tag = m.group(0)
        if 'type="hidden"' in tag:
            continue
        ident = re.search(r'id="([^"]+)"', tag)
        assert ident and f'<label for="{ident.group(1)}"' in page, tag


def test_page_structure_without_warehouse(tmp_path: Path) -> None:
    c = _eval_client(tmp_path)
    _structure_ok(c.get("/").text, "/")
    _structure_ok(c.get("/eval").text, "/eval")
    _structure_ok(c.get("/data").text, "/data")
    err = c.post("/ask", data={"question": "   "}).text
    _structure_ok(err, "/")
    assert 'id="q-error"' in err and 'aria-invalid="true"' in err and 'aria-describedby="q-error"' in err
    # one announcement per result: no live region around the result (focus moves to its heading instead)
    assert "aria-live" not in c.get("/").text
    assert "maxlength" not in c.get("/").text  # over-long input reaches the server's message, not a silent cut


def test_no_ui_module_runs_sql_of_its_own() -> None:
    """Extends the app.py check to every module in rollup/ui: no duckdb, no execute/guard/run calls."""
    allowed_runner = {"rollup.runner.open_readonly", "rollup.runner.default_db_path", "rollup.runner.DEFAULT_TIMEOUT_S"}
    for path in sorted(UI_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.update(f"{node.module}.{a.name}" for a in node.names)
        assert not any(n == "duckdb" or n.startswith("duckdb.") for n in imported), path
        assert {n for n in imported if n.startswith("rollup.runner.")} <= allowed_runner, path
        calls = {
            n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func, "id", "")
            for n in ast.walk(tree)
            if isinstance(n, ast.Call)
        }
        assert not calls & {"execute", "executemany", "sql", "query", "run_sql", "execute_guarded", "check_sql"}, path


# ---- routes against the built warehouse ------------------------------------------------------------------


@pytest.fixture(scope="module")
def client(warehouse_db: Path, repo_root: Path) -> TestClient:
    app = create_app(
        RecordedModel(), db_path=warehouse_db, manifest_path=repo_root / "warehouse" / "target" / "manifest.json"
    )
    return TestClient(app, base_url=LOCAL)


def _ask(client: TestClient, q: str, *, htmx: bool = True) -> str:
    r = client.post("/ask", data={"question": q}, headers={"HX-Request": "true"} if htmx else {})
    assert r.status_code == 200
    return str(r.text)


@pytest.mark.warehouse
def test_data_page_lists_exactly_the_marts(client: TestClient) -> None:
    page = client.get("/data").text
    _structure_ok(page, "/data")
    names = set(re.findall(r'<h2 id="([a-z_]+)"', page))
    assert names == set(MART_TABLES)
    assert "stg_" not in page and "int_" not in page


@pytest.mark.warehouse
def test_starters_end_in_the_outcome_they_promise(client: TestClient) -> None:
    expect = {
        "answer + bar chart": ("answered", "bar"),
        "line chart": ("answered", "line"),
        "a guard refusal": ("refused_guard", None),
        "the data can't answer": ("refused_question", None),
    }
    for s in starters():
        status, chart = expect[s["shows"]]
        page = _ask(client, s["question"])
        assert f'data-status="{status}"' in page, s
        if chart:
            assert f'data-chart="{chart}"' in page, s


@pytest.mark.warehouse
def test_every_highlight_points_at_a_real_cell(client: TestClient) -> None:
    for q in [x["question"] for x in recorded_questions()]:
        page = _ask(client, q)
        if 'data-status="answered"' not in page:
            continue
        for cell_id, token in re.findall(r'<a class="cite" href="#(cell-\d+-\d+)"[^>]*><mark>([^<]+)</mark></a>', page):
            m = re.search(
                rf'<td id="{cell_id}"[^>]*>([^<]*)<span class="visually-hidden"> \(quoted in the answer\)', page
            )
            assert m, (q, cell_id)
            assert 'class="' in m.group(0) and "cited" in m.group(0), (q, cell_id)
            cell = html.unescape(m.group(1)).replace(",", "")
            tok = token.replace(",", "").removeprefix("$")
            same_number = re.fullmatch(r"-?\d+(\.\d+)?", cell) and Decimal(cell) == Decimal(tok)
            assert same_number or cell.startswith(tok), (q, token, cell)  # equal value, or a date prefix


@pytest.mark.warehouse
def test_refusal_pages_say_it_in_words_glyphs_and_colour(client: TestClient) -> None:
    guard = _ask(client, "Delete all closed-lost opportunities older than a year.")
    assert '<section class="panel panel-bad">' in guard
    assert re.search(
        r'<h3 class="headline"><span aria-hidden="true">✕</span> Not run: Rollup only reads data</h3>', guard
    )
    cant = _ask(client, "What is our NPS by customer segment?")
    assert 'class="panel panel-info"' in cant and re.search(
        r'<h3 class="headline"><span aria-hidden="true">◆</span> Can', cant
    )
    for name in MART_TABLES:
        assert f"<code>{name}</code>" in cant
    none = _ask(client, "Which coupon code drove the most signups?")
    assert 'class="panel panel-neutral"' in none and 'href="#all-questions"' in none


class _HostileModel:
    """Drafts and answers containing markup, to check every rendered field is escaped (review S4)."""

    name = "hostile"
    payload = '<img src=x onerror="alert(1)">'

    def draft_sql(self, question: str, context: SchemaContext) -> Draft:
        if "guard" in question:
            return parse_draft(f"```sql\nselect * from {self.payload}\n```")
        return parse_draft(f'```sql\nselect platform as "{self.payload}", 1 as n from marts.fct_spend group by 1\n```')

    def write_answer(self, question: str, sql: str, columns: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
        return f"{self.payload} answer"


@pytest.mark.warehouse
def test_hostile_text_is_escaped_everywhere(warehouse_db: Path, repo_root: Path) -> None:
    app = create_app(
        _HostileModel(), db_path=warehouse_db, manifest_path=repo_root / "warehouse" / "target" / "manifest.json"
    )
    c = TestClient(app, base_url=LOCAL)
    for q in (f"answer {_HostileModel.payload}", f"guard {_HostileModel.payload}"):
        for htmx in (True, False):
            page = _ask(c, q, htmx=htmx)
            assert "<img" not in page, (q, htmx)
            assert "&lt;img" in page, (q, htmx)  # shown, escaped


@pytest.mark.warehouse
def test_known_eval_misses_are_flagged_on_the_ask_page(client: TestClient) -> None:
    """UX review must-fix: a recorded draft the eval marks wrong must not look like a trusted answer (DUX-05)."""
    ev = load_eval()
    assert ev is not None
    for row in ev.rows:
        page = _ask(client, row.question)
        note = _tag(page, "eval-note")
        assert note is not None, row.question
        if row.result == "fail":
            assert "Known eval miss" in note and 'href="/eval"' in note, row.question
        else:
            assert "Known eval miss" not in note, row.question
    churn = _ask(client, "What is our customer churn rate?")
    assert 'data-status="answered"' in churn and "Known eval miss" in churn


@pytest.mark.warehouse
def test_attribution_note_on_touch_results(client: TestClient) -> None:
    page = _ask(client, "How many deals did each channel win under first-touch versus last-touch credit?")
    assert 'data-status="answered"' in page and 'data-testid="attribution"' in page
    spend = _ask(client, "Which five campaigns have the highest lifetime spend?")
    assert 'data-testid="attribution"' not in spend
