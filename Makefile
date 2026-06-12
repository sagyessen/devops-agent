.PHONY: setup lint typecheck test gates evals smoke guardrails-verify guardrails-generate

setup:
	pip install -e ".[dev]"
	pre-commit install

lint:
	ruff check src tests
	ruff format --check src tests

typecheck:
	mypy --strict src

test:
	pytest -q

gates: lint typecheck test

evals:
	pytest -q tests/evals

smoke:
	bash tests/smoke.sh

guardrails-verify:
	./scripts/guardrails.sh verify

# Human-only: regenerate after a reviewed guardrail change.
guardrails-generate:
	./scripts/guardrails.sh generate
