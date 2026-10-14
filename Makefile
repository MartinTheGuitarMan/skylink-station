SHELL := /bin/bash
ENV = set -a; . ./.env; set +a; export INFLUX_URL=http://localhost:8086
SCENARIO ?= config/scenario-smoke.toml
RUN ?= smoke-1
SPEED ?= 60

.PHONY: help init up down logs build test flows dashboards smoke stats wipe
help:           ## list targets
	@grep -E '^[a-z-]+:.*##' Makefile | sed 's/:.*##/ -/'
init:           ## create .env with random secrets (never overwrites)
	@test -f .env || { awk -v t=$$(openssl rand -hex 24) -v p=$$(openssl rand -hex 8) -v g=$$(openssl rand -hex 8) \
	  '/^INFLUX_TOKEN/{print "INFLUX_TOKEN=" t; next} /^INFLUX_PASSWORD/{print "INFLUX_PASSWORD=" p; next} /^GRAFANA_PASSWORD/{print "GRAFANA_PASSWORD=" g; next} {print}' .env.example > .env; echo ".env created"; }
up: init flows dashboards   ## build and start the whole stack
	docker compose up -d --build
down:           ## stop the stack (data kept)
	docker compose down
logs:           ## follow logs
	docker compose logs -f --tail=50
test:           ## unit tests (no docker needed)
	uv run pytest -q
flows:          ## rebuild nodered/flows.json from nodered/functions
	python3 scripts/build_flows.py
dashboards:     ## regenerate the Grafana dashboard JSON
	uv run python scripts/gen_dashboard.py
smoke:          ## short end-to-end run: simulator -> Node-RED -> Influx/River -> Grafana
	$(ENV); uv run skylink-sim run --config $(SCENARIO) --run-id $(RUN) --speed $(SPEED)
stats:          ## container resource use right now
	docker stats --no-stream
wipe:           ## DELETE all stored data (volumes)
	docker compose down -v
