"""Accessibility check of the running UI: axe-core (WCAG 2.1 A/AA rules) on every page and state, light and dark,
desktop and 390 px, plus a keyboard pass. Local tool, not part of ``make ci`` (CI installs no browser; D-56).

    make build && make ui &                      # the UI on http://127.0.0.1:8000, recorded model
    npm install --prefix /tmp/axe axe-core@4.10.2
    make a11y AXE=/tmp/axe/node_modules/axe-core/axe.min.js

Needs Python Playwright with Chromium. Exits 1 if axe reports any violation or a keyboard check fails.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PAGES: list[tuple[str, str, str | None]] = [
    ("start", "/", None),
    ("eval", "/eval", None),
    ("data", "/data", None),
    ("answered-bar", "/", "Which five campaigns have the highest lifetime spend?"),
    ("answered-line", "/", "How much revenue was won each month (by close date), in date order?"),
    ("answered-fallback", "/", "What was total ad spend by platform?"),
    ("answered-no-chart", "/", "What is the total value of open (not closed) pipeline?"),
    ("refused-guard", "/", "Delete all closed-lost opportunities older than a year."),
    ("cant-answer", "/", "What is our NPS by customer segment?"),
    ("query-error", "/", "Which campaigns have been renamed, and what were their previous names?"),
    ("no-draft", "/", "Which coupon code drove the most signups?"),
]
TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "best-practice"]


def run(base: str, axe_js: str, out: Path | None) -> int:
    from playwright.sync_api import sync_playwright

    report: dict[str, Any] = {}
    failures = 0
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for scheme in ("light", "dark"):
            for width in (1280, 390):
                page = browser.new_page(viewport={"width": width, "height": 900}, color_scheme=scheme)
                for name, path, question in PAGES:
                    page.goto(base + path)
                    if question:
                        page.fill("#q", question)
                        page.click("form.ask button[type=submit]")
                        page.wait_for_selector("#result [data-status]")
                    page.add_script_tag(content=axe_js)
                    res = page.evaluate("async t => await axe.run(document, {runOnly: {type: 'tag', values: t}})", TAGS)
                    v = [
                        {"id": x["id"], "impact": x["impact"], "nodes": [n["target"] for n in x["nodes"]][:5]}
                        for x in res["violations"]
                    ]
                    key = f"{name}/{scheme}/{width}"
                    report[key] = v
                    failures += len(v)
                    print(f"{key:40s} violations={len(v)} " + " ".join(x["id"] for x in v))
                page.close()

        # keyboard pass: skip link first, focus visible, Ask reachable by Tab, focus lands on the result heading
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto(base + "/")
        page.keyboard.press("Tab")
        first = page.evaluate("document.activeElement.className + '|' + document.activeElement.textContent")
        ok_skip = first.startswith("skip|")
        outline = page.evaluate("getComputedStyle(document.activeElement).outlineStyle")
        page.keyboard.press("Enter")
        on_main = page.evaluate("document.activeElement.id") == "content"
        page.focus("#q")
        page.keyboard.type("Which five campaigns have the highest lifetime spend?")
        page.keyboard.press("Enter")
        page.wait_for_selector("#result [data-status]")
        page.wait_for_timeout(200)
        landed = page.evaluate("document.activeElement.id")
        checks = {
            "first Tab reaches the skip link": ok_skip,
            "focus outline is visible": outline not in ("none", ""),
            "skip link moves focus to main": on_main,
            "after Ask, focus is on the result heading": landed == "result-heading",
        }
        for k, v in checks.items():
            print(f"keyboard: {k}: {'ok' if v else 'FAIL'}")
            failures += 0 if v else 1
        report["keyboard"] = checks
        page.close()
        browser.close()
    if out:
        out.write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    print(f"total problems: {failures}")
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--axe", required=True, help="path to axe.min.js (npm package axe-core)")
    ap.add_argument("--out", type=Path, default=None, help="write the JSON report here")
    a = ap.parse_args(argv)
    return run(a.base, Path(a.axe).read_text(encoding="utf-8"), a.out)


if __name__ == "__main__":
    sys.exit(main())
