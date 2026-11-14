"""Mutation test: switching off each defect fix makes its custom dbt test fail.

Slow (four dbt runs), so deselected by default. Run with `make test-mutation` after
`make build` (CI does).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from rollup.defects import DEFECTS, Defect

pytestmark = pytest.mark.mutation


def _dbt(warehouse: Path, env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["dbt", *args, "--profiles-dir", "."],
        cwd=warehouse,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize("defect", DEFECTS, ids=[d.code for d in DEFECTS])
def test_unfixed_defect_is_caught(defect: Defect, repo_root: Path, tmp_path: Path) -> None:
    if shutil.which("dbt") is None or not (repo_root / "data/raw/web_sessions.parquet").exists():
        pytest.skip("needs dbt and generated data (run `make build`)")
    warehouse = repo_root / "warehouse"
    env = {
        **os.environ,
        "ROLLUP_DUCKDB_PATH": str(tmp_path / "mut.duckdb"),
        "ROLLUP_RAW_DIR": str(repo_root / "data/raw"),
    }
    vars_ = f"{{unfix: {defect.code}}}"
    run = _dbt(warehouse, env, "run", "--vars", vars_)
    assert run.returncode == 0, run.stdout[-2000:]
    test = _dbt(warehouse, env, "test", "--vars", vars_, "--select", defect.dbt_test)
    assert test.returncode != 0, f"{defect.dbt_test} did not catch {defect.code}"
    assert "FAIL" in test.stdout
