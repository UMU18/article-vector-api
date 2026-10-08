.PHONY: up down stop logs ps migrate seed shell flower test test-unit test-integration clean

COMPOSE = docker compose
COUNT ?= 100

## Start the full stack (build + detach)
up:
	$(COMPOSE) up --build -d

## Stop and remove containers
down:
	$(COMPOSE) down

## Follow API + worker logs
logs:
	$(COMPOSE) logs -f api worker

## Show container status
ps:
	$(COMPOSE) ps

## Apply database migrations (runs inside the api container)
migrate:
	$(COMPOSE) exec api alembic upgrade head

## Seed dummy articles: make seed COUNT=500
seed:
	$(COMPOSE) exec api python -m app.cli seed --count $(COUNT)

## Open a shell in the api container
shell:
	$(COMPOSE) exec api bash

## Start Flower (Celery monitoring UI on :5555)
flower:
	$(COMPOSE) --profile monitoring up -d flower

## Run unit tests (no infrastructure required)
test test-unit:
	pytest tests/unit -v

## Run integration tests (requires the docker compose stack to be up)
test-integration:
	pytest tests/integration -m integration -v

## Remove volumes as well (destructive)
clean:
	$(COMPOSE) down -v
