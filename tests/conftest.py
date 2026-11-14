from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from rollup.generate import generate


@pytest.fixture(scope="session")
def tables() -> dict[str, pd.DataFrame]:
    return generate(27)


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]
