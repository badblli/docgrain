.PHONY: test lint web-build quality

test:
	python -m pytest -q

lint:
	ruff check apps packages tests benchmarks docs/examples

web-build:
	cd apps/web && npm ci && npm run build

quality: lint test web-build
