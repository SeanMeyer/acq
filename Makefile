.DEFAULT_GOAL := help

.PHONY: help
help:
	@echo "acq - Q&A knowledge commons for AI agents"
	@echo ""
	@echo "Claude Code (recommended):"
	@echo "  make install-claude                          Install acq plugin"
	@echo "  make uninstall-claude                        Remove acq plugin"
	@echo ""
	@echo "OpenCode:"
	@echo "  make install-opencode                        Install globally (~/.config/opencode/)"
	@echo "  make install-opencode PROJECT=/path/to/app   Install into a specific project"
	@echo "  make uninstall-opencode                      Remove global OpenCode install"
	@echo "  make uninstall-opencode PROJECT=/path/to/app Remove from a specific project"
	@echo ""
	@echo "OMP (oh-my-pi):"
	@echo "  make install-omp                             Install plugin + local team API wiring"
	@echo "  make install-omp TEAM_ADDR=http://host:8742  Point at a specific team API"
	@echo "  make install-omp LOCAL_ONLY=1                Install without any team API"
	@echo "  make uninstall-omp                           Remove OMP install"
	@echo ""
	@echo "pi (upstream):"
	@echo "  make install-pi                              Install package + local team API wiring"
	@echo "  make install-pi TEAM_ADDR=http://host:8742   Point at a specific team API"
	@echo "  make install-pi LOCAL_ONLY=1                 Install without any team API"
	@echo "  make uninstall-pi                            Remove pi install"
	@echo ""
	@echo "Development:"
	@echo "  make setup        Install all dependencies"
	@echo "  make setup-agent  Authenticate against a team API (needs TEAM_ADDR and CLIENT_ID)"
	@echo "  make test         Run all tests"
	@echo "  make lint         Format-check and lint Python components"
	@echo "  make typecheck    Type-check the TypeScript UI"
	@echo ""
	@echo "Deploy:"
	@echo "  make docker-build  Build the deployable Docker image"
	@echo ""
	@echo "Docker Compose:"
	@echo "  make compose-up                              Build and start services"
	@echo "  make compose-down                            Stop services"
	@echo "  make compose-reset                           Stop services and wipe database"
	@echo "  make seed-users USER=demo PASS=demo123       Create a user"

.PHONY: setup
setup:
	(cd shared && uv sync --group dev)
	(cd plugins/acq/server && uv sync --group dev)
	(cd team-api && uv sync --group dev)
	(cd team-ui && pnpm install $(if $(CI),--frozen-lockfile,))

# Separate from `setup` on purpose: this runs an interactive GitHub device
# flow that blocks until a human authorizes it, so it must never be part of
# dependency installation (it would hang CI and every fresh local setup).
.PHONY: setup-agent
setup-agent:
	python scripts/setup-agent.py \
		$(if $(TEAM_ADDR),--team-addr "$(TEAM_ADDR)",) \
		$(if $(CLIENT_ID),--client-id "$(CLIENT_ID)",)

.PHONY: install-claude
install-claude:
	claude plugin install acq@acq

.PHONY: uninstall-claude
uninstall-claude:
	claude plugin uninstall acq@acq

.PHONY: install-opencode
install-opencode:
ifdef PROJECT
	@bash "$(CURDIR)/scripts/install-opencode.sh" install --project "$(PROJECT)"
else
	@bash "$(CURDIR)/scripts/install-opencode.sh" install
endif

.PHONY: uninstall-opencode
uninstall-opencode:
ifdef PROJECT
	@bash "$(CURDIR)/scripts/install-opencode.sh" uninstall --project "$(PROJECT)"
else
	@bash "$(CURDIR)/scripts/install-opencode.sh" uninstall
endif

.PHONY: install-omp
install-omp:
	@bash "$(CURDIR)/scripts/install-omp.sh" install \
		$(if $(LOCAL_ONLY),--local-only,) \
		$(if $(TEAM_ADDR),--team-addr "$(TEAM_ADDR)",) \
		$(if $(API_KEY),--api-key "$(API_KEY)",) \
		$(if $(AGENT_NAME),--agent-name "$(AGENT_NAME)",)

.PHONY: uninstall-omp
uninstall-omp:
	@bash "$(CURDIR)/scripts/install-omp.sh" uninstall

.PHONY: install-pi
install-pi:
	@bash "$(CURDIR)/scripts/install-pi.sh" install \
		$(if $(LOCAL_ONLY),--local-only,) \
		$(if $(TEAM_ADDR),--team-addr "$(TEAM_ADDR)",) \
		$(if $(API_KEY),--api-key "$(API_KEY)",) \
		$(if $(AGENT_NAME),--agent-name "$(AGENT_NAME)",)

.PHONY: uninstall-pi
uninstall-pi:
	@bash "$(CURDIR)/scripts/install-pi.sh" uninstall

.PHONY: compose-up
compose-up:
	docker compose up --build

.PHONY: compose-down
compose-down:
	docker compose down

.PHONY: compose-reset
compose-reset:
	docker compose down -v

.PHONY: seed-users
seed-users:
ifndef USER
	$(error USER is required. Usage: make seed-users USER=peter PASS=changeme)
endif
ifndef PASS
	$(error PASS is required. Usage: make seed-users USER=peter PASS=changeme)
endif
	docker compose exec acq-team-api /app/team-api/.venv/bin/python /app/scripts/seed-users.py --username "$(USER)" --password "$(PASS)"

# Build the deployable image. The Dockerfile produces a single self-contained
# image that serves both the API and the compiled review UI, so it can run on
# any container host. Push it wherever you deploy.
IMAGE ?= acq-team-api
TAG ?= latest

.PHONY: docker-build
docker-build:
	docker build -f team-api/Dockerfile -t "$(IMAGE):$(TAG)" .

.PHONY: dev-api
dev-api:
	cd team-api && ACQ_DB_PATH=./dev.db ACQ_JWT_SECRET=dev-secret ACQ_API_KEYS='{"dev-key":"dev-agent"}' uv run acq-team-api

.PHONY: dev-ui
dev-ui:
	cd team-ui && pnpm dev

# Re-lock dependencies using public PyPI regardless of local env vars.
.PHONY: lock
lock:
	cd shared && UV_DEFAULT_INDEX= UV_INDEX= uv lock
	cd plugins/acq/server && UV_DEFAULT_INDEX= UV_INDEX= uv lock
	cd team-api && UV_DEFAULT_INDEX= UV_INDEX= uv lock

# Fail if any lock file references a package index other than public PyPI.
# Lock files generated behind a private mirror are not resolvable by CI or by
# anyone else cloning this repo.
.PHONY: check-lockfiles
check-lockfiles:
	@bad=$$(grep -ho 'https://[^/"]*' shared/uv.lock plugins/acq/server/uv.lock team-api/uv.lock 2>/dev/null \
		| sort -u | grep -v -e '^https://files.pythonhosted.org$$' -e '^https://pypi.org$$' || true); \
	if [ -n "$$bad" ]; then \
		echo "ERROR: lock files reference non-public package indexes:"; \
		echo "$$bad" | sed 's/^/  /'; \
		echo "Run 'make lock' to regenerate against public PyPI."; \
		exit 1; \
	fi

.PHONY: lint
lint:
	cd shared && uv run ruff check . && uv run ruff format --check .
	cd plugins/acq/server && uv run ruff check . && uv run ruff format --check .
	cd team-api && uv run ruff check . && uv run ruff format --check .

.PHONY: format
format:
	cd shared && uv run ruff format .
	cd plugins/acq/server && uv run ruff format .
	cd team-api && uv run ruff format .

.PHONY: format-check
format-check:
	cd shared && uv run ruff format --check .
	cd plugins/acq/server && uv run ruff format --check .
	cd team-api && uv run ruff format --check .

.PHONY: typecheck
typecheck:
	cd team-ui && pnpm tsc -b

.PHONY: test
test:
	cd shared && uv run pytest tests/ -v
	cd team-api && uv run pytest tests/ -v
	cd plugins/acq/server && uv run pytest tests/ -v
