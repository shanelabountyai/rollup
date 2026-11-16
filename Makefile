SEED ?= 27
RAW  ?= data/raw
export ROLLUP_RAW_DIR := $(abspath $(RAW))
export ROLLUP_DUCKDB_PATH := $(abspath data/rollup.duckdb)
DBT = cd warehouse && dbt

.PHONY: install generate build dbt-build docs test test-warehouse test-mutation lint typecheck query queries ask eval ci clean

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

test-warehouse:
	pytest -m warehouse

query:
	python -m rollup.query "$(Q)"

queries:
	python -m rollup.query --all

ask:
	python -m rollup.ask "$(Q)"

# Golden-set eval on the recorded drafts (D-29): measures the pipeline, not a live model.
eval:
	python -m rollup.eval.run --out data/eval/run.json

test-mutation:
	pytest -m mutation -v

lint:
	ruff check .
	ruff format --check .

typecheck:
	mypy

ci: lint typecheck test build test-warehouse eval docs test-mutation

clean:
	rm -rf data warehouse/target warehouse/logs
