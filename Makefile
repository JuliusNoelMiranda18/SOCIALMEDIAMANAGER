.PHONY: up down test lint seed probe probe5
up:
	docker compose up -d --build --wait
down:
	docker compose down
test:
	docker compose run --rm api pytest -q
lint:
	docker compose run --rm api sh -c "ruff check . && ruff format --check ."
seed:
	@curl -s -X POST http://localhost:8000/posts -H 'Content-Type: application/json' \
	  -d '{"title":"Spring Sale Launch","body":"We launched a new product today. It is fast and cheap! Come and see."}' \
	  | python3 -c "import sys,json; print('post id', json.load(sys.stdin)['id'])"
probe:
	bash scripts/probes/fake_platform.sh
probe5:
	bash scripts/probes/probe5_content.sh
