.PHONY: test lint web-build quality

test:
	PYTHONPATH=apps/api:apps/worker:packages/domain pytest -q

lint:
	ruff check apps packages tests

web-build:
	cd apps/web && npm install && npm run build

quality: lint test web-build
