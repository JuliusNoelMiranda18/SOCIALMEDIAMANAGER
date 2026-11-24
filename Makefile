.PHONY: up down test lint seed probe
up:
	docker compose up -d --build --wait
down:
	docker compose down
test:
	docker compose run --rm api pytest -q
lint:
	docker compose run --rm api sh -c "ruff check . && ruff format --check ."
seed:
	@echo "nothing to seed yet"
probe:
	bash scripts/probes/fake_platform.sh
