from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import pytest
from hypothesis import HealthCheck, settings

from rollup.generate import generate

# Property tests are derandomized so CI and local runs see the same examples (D-21); raise max_examples locally
# with HYPOTHESIS_PROFILE=deep.
settings.register_profile(
    "default", max_examples=300, derandomize=True, deadline=None, suppress_health_check=[HealthCheck.too_slow]
)
settings.register_profile("deep", max_examples=5000, deadline=None, suppress_health_check=[HealthCheck.too_slow])
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "default"))


@pytest.fixture(scope="session")
def tables() -> dict[str, pd.DataFrame]:
    return generate(27)


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def warehouse_db(repo_root: Path) -> Path:
    """The built warehouse. Warehouse tests fail (never skip) when it is missing: run `make build` first."""
    path = Path(os.environ.get("ROLLUP_DUCKDB_PATH", repo_root / "data" / "rollup.duckdb"))
    if not path.exists():
        pytest.fail(f"{path} not found: run `make build` before `make test-warehouse`")
    return path
