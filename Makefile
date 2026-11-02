.PHONY: dev down test lint typecheck migrate seed sim

dev:
	docker compose up --build

down:
	docker compose down

test:
	docker compose run --rm backend python -m pytest -q
	docker compose run --rm frontend npm test
	docker compose run --rm frontend npm run typecheck
	docker compose run --rm frontend npm run build

lint:
	docker compose run --rm backend ruff check app tests scripts
	docker compose run --rm frontend npm run lint

typecheck:
	docker compose run --rm frontend npm run typecheck

migrate:
	docker compose run --rm backend alembic upgrade head

seed:
	docker compose run --rm backend python -m scripts.seed

sim:
	docker compose build backend
	docker compose up -d db
	docker compose run --rm backend alembic upgrade head
	docker compose run --rm backend python -m scripts.sim
