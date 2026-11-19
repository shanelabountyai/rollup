"""FastAPI + HTMX query UI (Phase 4, D-03).

The UI is a thin view over ``rollup.ask.ask``: it never runs SQL itself. Each request opens a fresh read-only
connection (``open_readonly``) and hands the question to ``ask``, which drafts, guards (``check_sql`` inside
``execute_guarded``), runs, and validates the answer (RU-03). The page shows:

  question -> drafted SQL -> guard result (passed + executed SQL, or refused + code + reason)
           -> result table -> one-paragraph answer (already validated) -> chart picked from the result shape

What is never rendered (D-43): the model's paragraph when RU-03 rejected it, and the violation messages (both
contain the numbers that were not in the result). The page says a paragraph was rejected and shows the fallback.

Model (D-41): the recorded model by default (offline, no key). The live adapter only when the owner asks for it
(``--model live`` or ``ROLLUP_UI_MODEL=live``) and has ``ANTHROPIC_API_KEY`` and ``ROLLUP_LLM_MODEL`` set.
"""

from __future__ import annotations

import json
import os
import re
import threading
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from markupsafe import Markup

from rollup.ask import AskResult, ask
from rollup.llm import DEFAULT_RECORDING, DraftModel, RecordedModel
from rollup.runner import default_db_path, open_readonly
from rollup.schema_context import SchemaContext, load_context
from rollup.ui.chart import choose_chart, fmt_cell, is_number, render_svg
from rollup.ui.views import (
    TIMEOUT_S,
    EvalRow,
    guard_explainer,
    highlight_answer,
    load_eval,
    marts_summary,
    passed_checks,
    starters,
)

UI_DIR = Path(__file__).resolve().parent
MAX_QUESTION_CHARS = 500

STATUS_LABELS = {
    "answered": "Answered",
    "refused_question": "Refused: the marts can't answer this",
    "refused_guard": "Refused by a guard: nothing was run",
    "query_error": "Query error",
    "timeout": "Timed out",
    "model_error": "No usable draft",
}


def select_model(choice: str | None = None) -> DraftModel:
    """``recorded`` (default) or ``live``. Live needs the owner's key and model id at his own runtime (D-41)."""
    choice = (choice or os.environ.get("ROLLUP_UI_MODEL") or "recorded").strip().lower()
    if choice == "recorded":
        return RecordedModel()
    if choice == "live":
        from rollup.llm import AnthropicModel  # raises ModelUnavailable without a key and a model id

        return AnthropicModel()
    raise ValueError(f"unknown model {choice!r}; use 'recorded' or 'live'")


def recorded_questions(path: Path = DEFAULT_RECORDING) -> list[dict[str, str]]:
    """The questions the recorded model can answer, for the example list (golden first, then refusal set)."""
    data = json.loads(path.read_text(encoding="utf-8"))
    return [{"set": str(r.get("set", "")), "question": str(r["question"])} for r in data["responses"]]


@dataclass
class ResultView:
    """Everything the result panel shows. Built only from ``AskResult`` fields that are safe to render."""

    question: str
    status: str
    status_label: str
    draft_sql: str | None
    guard: str  # "passed", "refused" or "not reached"
    guard_code: str | None
    reason: str | None
    executed_sql: str | None
    columns: list[str]
    rows: list[list[str]]
    truncated: bool
    elapsed_ms: float | None
    answer: str
    answer_source: str | None
    ru03_rejected: bool
    ru03_violation_count: int
    chart_kind: str
    chart_reason: str
    chart_svg: Markup
    # Display-only additions for the design pass (docs/design/*.dc.html); none changes what is shown as data.
    # ``answer`` with its numbers highlighted; the same text once the tags are stripped
    answer_html: Markup = field(default_factory=Markup)
    cited: frozenset[tuple[int, int]] = frozenset()  # (row, column) cells a highlighted number links to
    numeric_cols: tuple[bool, ...] = ()  # right-align columns whose non-NULL cells are all numbers
    checks: tuple[str, ...] = ()  # the passed-guard list for an answered question
    chart_title: str = ""
    explain_title: str = ""  # plain-words headline for a guard refusal
    explain_body: str = ""
    touch_note: bool = False  # the result involves first/last-touch credit: say which is primary (owner call, D-20)
    eval: EvalRow | None = None  # this question's row in the committed eval run, if it is a recorded question


_DIGIT = re.compile(r"\d")

WITHHELD_REASONS = {
    "refused_question": (
        "The model said the marts can't answer this; its explanation contained numbers, so it is not shown."
    ),
    "query_error": (
        "The database returned an error; its message contained numbers (it can quote cell values), so it is not shown."
    ),
    "timeout": "The query ran past the time limit and was stopped.",
    "model_error": "The model returned no usable draft; its message contained numbers, so it is not shown.",
}


def shown_reason(status: str, reason: str | None) -> str | None:
    """The reason text a non-answer page may render (D-47).

    RU-03 checks only the answer. A refusal reason can be free model output (``REFUSE: ...``) and a DuckDB error can
    quote a cell value, so a reason with any digit is replaced by a fixed message for its status. Guard reasons are
    kept as written: they come from ``rollup.guards`` and describe the drafted SQL, which the page already shows.
    """
    if status == "refused_guard" or reason is None or not _DIGIT.search(reason):
        return reason
    return WITHHELD_REASONS.get(status, "The message contained numbers, so it is not shown.")


def build_view(r: AskResult) -> ResultView:
    if r.executed_sql:
        guard = "passed"
    elif r.status == "refused_guard":
        guard = "refused"
    else:
        guard = "not reached"
    rejected = bool(r.answered and r.validation is not None and not r.validation.ok)
    chart_title = ""
    if r.answered:
        spec = choose_chart(r.columns, r.rows, truncated=r.truncated)
        chart_kind, chart_reason, svg = spec.kind, spec.reason, render_svg(spec)
        if spec.kind != "none":
            chart_title = f"{spec.y_column} by {spec.x_column}"
        lit = highlight_answer(r.answer, r.columns, r.rows) if r.answer_source is not None else None
    else:
        chart_kind, chart_reason, svg = "none", "No result, so no chart.", ""
        lit = None
    numeric = tuple(
        bool(r.rows)
        and all(v is None or is_number(v) for v in (row[j] for row in r.rows))
        and any(row[j] is not None for row in r.rows)
        for j in range(len(r.columns))
    )
    explain_title, explain_body = guard_explainer(r.guard_code) if r.status == "refused_guard" else ("", "")
    return ResultView(
        question=r.question,
        status=r.status,
        status_label=STATUS_LABELS.get(r.status, r.status),
        draft_sql=r.draft_sql,
        guard=guard,
        guard_code=r.guard_code,
        reason=shown_reason(r.status, r.reason),
        executed_sql=r.executed_sql,
        columns=list(r.columns),
        rows=[[fmt_cell(v) for v in row] for row in r.rows],
        truncated=r.truncated,
        elapsed_ms=None if r.elapsed_ms is None else round(r.elapsed_ms, 1),
        answer=r.answer,  # validated by ask(): the model's paragraph if it passed RU-03, else the fallback
        answer_source=r.answer_source,
        ru03_rejected=rejected,
        ru03_violation_count=len(r.validation.violations) if rejected and r.validation else 0,
        chart_kind=chart_kind,
        chart_reason=chart_reason,
        chart_svg=Markup(svg),  # built by chart.render_svg, which escapes every cell and column name
        answer_html=lit.html if lit is not None else Markup("") + r.answer,  # Markup + str escapes the str
        cited=frozenset(lit.cited) if lit is not None else frozenset(),
        numeric_cols=numeric,
        checks=tuple(passed_checks(r.executed_sql, None if r.elapsed_ms is None else round(r.elapsed_ms, 1)))
        if r.answered
        else (),
        chart_title=chart_title,
        explain_title=explain_title,
        explain_body=explain_body,
        touch_note=r.answered
        and ("touch" in (r.executed_sql or "").lower() or any("touch" in c.lower() for c in r.columns)),
    )


LOCAL_HOSTS: tuple[str, ...] = ("127.0.0.1", "localhost", "::1")


def _hostname(value: str) -> str | None:
    """Host name of a ``Host`` header value or an origin URL, lower-cased, without port or IPv6 brackets."""
    netloc = value if "//" in value else f"//{value}"
    try:
        host = urlsplit(netloc).hostname
    except ValueError:
        return None
    return host.lower() if host else None


def request_refusal(method: str, headers: Any, allowed: Sequence[str]) -> tuple[int, str] | None:
    """D-50: only local, same-origin requests reach the app (DNS rebinding and cross-site form POSTs).

    ``Host`` must name an allowed host. A POST is refused when the browser marks it cross-site or sends an
    ``Origin`` (including ``null``) whose host is not allowed. A POST with no ``Origin`` (curl, tests) is allowed.
    """
    if _hostname(headers.get("host", "")) not in allowed:
        return 400, "Host not allowed: this UI only answers on its local address."
    if method in ("GET", "HEAD", "OPTIONS"):
        return None
    if headers.get("sec-fetch-site", "").lower() == "cross-site":
        return 403, "Cross-site request refused."
    origin = headers.get("origin")
    if origin is not None and _hostname(origin) not in allowed:
        return 403, "Cross-site request refused."
    return None


def create_app(
    model: DraftModel | None = None,
    *,
    db_path: Path | str | None = None,
    manifest_path: Path | str | None = None,
    allowed_hosts: Sequence[str] = LOCAL_HOSTS,
    eval_run_path: Path | None = None,
) -> FastAPI:
    the_model = model if model is not None else select_model()
    db = Path(db_path) if db_path is not None else default_db_path()
    templates = Jinja2Templates(directory=str(UI_DIR / "templates"))
    examples = recorded_questions() if isinstance(the_model, RecordedModel) else []
    starter_list = starters()
    eval_path = eval_run_path
    _ev = load_eval(eval_path) if eval_path is not None else load_eval()
    is_recorded = isinstance(the_model, RecordedModel)
    eval_by_question = {row.question: row for row in _ev.rows} if _ev is not None and is_recorded else {}
    ctx_lock = threading.Lock()
    ctx_cache: list[SchemaContext] = []

    def context() -> SchemaContext:
        with ctx_lock:
            if not ctx_cache:
                ctx_cache.append(load_context(manifest_path, db))
            return ctx_cache[0]

    app = FastAPI(title="Rollup", docs_url=None, redoc_url=None, openapi_url=None)
    allowed = tuple(h.lower() for h in allowed_hosts)

    @app.middleware("http")
    async def local_only(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        refused = request_refusal(request.method, request.headers, allowed)
        if refused is not None:
            return PlainTextResponse(refused[1], status_code=refused[0])
        return await call_next(request)

    app.mount("/static", StaticFiles(directory=str(UI_DIR / "static")), name="static")

    recorded = isinstance(the_model, RecordedModel)

    def page_context(**extra: Any) -> dict[str, Any]:
        return {
            "active": "ask",
            "model_name": the_model.name,
            "model_label": "the recorded model (no API key in this build)" if recorded else f"{the_model.name}",
            "recorded": recorded,
            "examples": examples,
            "starters": starter_list,
            "timeout_s": f"{TIMEOUT_S:g}",
            "marts": [],
            "error_title": None,
            **extra,
        }

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(request, "index.html", page_context(result=None, error=None, question=""))

    @app.get("/eval", response_class=HTMLResponse)
    def eval_page(request: Request) -> HTMLResponse:
        view = load_eval(eval_path) if eval_path is not None else load_eval()
        return templates.TemplateResponse(request, "eval.html", page_context(active="eval", ev=view))

    @app.get("/data", response_class=HTMLResponse)
    def data_page(request: Request) -> HTMLResponse:
        try:
            ctx = context()
        except FileNotFoundError:
            return templates.TemplateResponse(
                request, "data.html", page_context(active="data", ctx=None), status_code=503
            )
        return templates.TemplateResponse(request, "data.html", page_context(active="data", ctx=ctx))

    @app.get("/healthz")
    def healthz() -> JSONResponse:
        return JSONResponse({"ok": True, "model": the_model.name, "db_exists": db.exists()})

    @app.post("/ask", response_class=HTMLResponse)
    def ask_route(request: Request, question: str = Form("")) -> HTMLResponse:
        partial = request.headers.get("HX-Request") == "true"
        q = " ".join(question.split())
        result: ResultView | None = None
        error: str | None = None
        status_code = 200
        error_title: str | None = None
        marts: list[dict[str, str]] = []
        if not q:
            error, status_code, error_title = "Type a question first.", 400, "No question yet"
        elif len(q) > MAX_QUESTION_CHARS:
            error, status_code = f"Questions are limited to {MAX_QUESTION_CHARS} characters.", 400
            error_title = "That question is too long"
        else:
            try:
                ctx = context()
                con = open_readonly(db)
            except FileNotFoundError:
                error, status_code = "The warehouse is not built yet. Run `make build`, then reload.", 503
                error_title = "The warehouse is not built yet"
            else:
                try:
                    result = build_view(ask(q, the_model, con, ctx))
                finally:
                    con.close()
                result.eval = eval_by_question.get(q)
                if result.status == "refused_question":
                    marts = marts_summary(ctx)
        # htmx does not swap 4xx/5xx responses by default, so a partial carries its error with a 200.
        name = "_result.html" if partial else "index.html"
        return templates.TemplateResponse(
            request,
            name,
            page_context(result=result, error=error, question=q, error_title=error_title, marts=marts),
            status_code=200 if partial else status_code,
        )

    return app
