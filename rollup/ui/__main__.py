"""``python -m rollup.ui`` / ``make ui``: serve the query UI locally (default http://127.0.0.1:8000)."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from rollup.llm import ModelUnavailable


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="rollup.ui", description="Serve the Rollup query UI.")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument(
        "--model",
        choices=["recorded", "live"],
        default=None,
        help="recorded responses (default, offline) or the live adapter (needs ANTHROPIC_API_KEY + ROLLUP_LLM_MODEL)",
    )
    p.add_argument("--db", default=None)
    p.add_argument("--manifest", default=None)
    args = p.parse_args(argv)

    import uvicorn

    from rollup.ui.app import create_app, select_model

    try:
        model = select_model(args.model)
    except ModelUnavailable as e:
        print(f"live model unavailable: {e}", file=sys.stderr)
        return 2
    from rollup.ui.app import LOCAL_HOSTS

    hosts = LOCAL_HOSTS if args.host in LOCAL_HOSTS else (*LOCAL_HOSTS, args.host)
    app = create_app(model, db_path=args.db, manifest_path=args.manifest, allowed_hosts=hosts)
    print(f"Rollup UI on http://{args.host}:{args.port}  (model: {model.name})")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    sys.exit(main())
