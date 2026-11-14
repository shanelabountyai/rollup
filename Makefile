SEED ?= 27
RAW  ?= data/raw
export ROLLUP_RAW_DIR := $(abspath $(RAW))
export ROLLUP_DUCKDB_PATH := $(abspath data/rollup.duckdb)
DBT = cd warehouse && dbt

.PHONY: install generate build dbt-build docs test test-mutation lint typecheck ci clean

install:
	pip install -e '.[dev]'

generate:
	python -m rollup.generate --seed $(SEED) --out $(RAW)

dbt-build:
	$(DBT) build --profiles-dir .

build: generate dbt-build

docs:
	$(DBT) docs generate --profiles-dir .

test:
	pytest

test-mutation:
	pytest -m mutation -v

lint:
	ruff check .
	ruff format --check .

typecheck:
	mypy

ci: lint typecheck test build docs test-mutation

clean:
	rm -rf data warehouse/target warehouse/logs
