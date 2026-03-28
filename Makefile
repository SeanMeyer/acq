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
	@echo "Development:"
	@echo "  make setup     Install all dependencies"
	@echo "  make test      Run all tests"
	@echo "  make lint      Format, lint, and type-check all components"
	@echo ""
	@echo "Deploy:"
	@echo "  make deploy    Deploy to Howler (staging)"
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

HOWLER_SERVICE_ID ?= 222
HOWLER_URL ?= https://howler.us1.staging.dog

.PHONY: deploy
deploy:
	@tmpdir=$$(mktemp -d) && \
	cp team-api/Dockerfile "$$tmpdir/Dockerfile" && \
	cp -r shared team-api team-ui "$$tmpdir/" && \
	tar czf /tmp/acq-deploy.tar.gz -C "$$tmpdir" . && \
	rm -rf "$$tmpdir" && \
	echo "Deploying to Howler (service $(HOWLER_SERVICE_ID))..." && \
	curl -X POST "$(HOWLER_URL)/api/services/$(HOWLER_SERVICE_ID)/builds/" \
		-F "build-context.tgz=@/tmp/acq-deploy.tar.gz" && \
	rm -f /tmp/acq-deploy.tar.gz

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

# Fail if any lock file contains internal-mirror URLs that CI can't reach.
.PHONY: check-lockfiles
check-lockfiles:
	@if grep -rq 'depot-read-api-python' shared/uv.lock plugins/acq/server/uv.lock team-api/uv.lock 2>/dev/null; then \
		echo "ERROR: lock files contain internal PyPI mirror URLs."; \
		echo "Run 'make lock' to regenerate with public PyPI."; \
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
