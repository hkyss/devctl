SHELL := /bin/sh

PROJECT ?= $(p)
VERSION ?= $(v)
TAG := v$(patsubst v%,%,$(VERSION))
DEVCTL_WORKSPACE_ROOT ?= $(abspath ..)
DEVCTL_VERSION ?= $(shell git describe --tags --always --dirty 2>/dev/null || echo 0.0.0-dev)
COMPOSE := docker compose -f .docker/docker-compose.yml
DEVCTL := ./devctl
export DEVCTL_WORKSPACE_ROOT
export DEVCTL_VERSION

.PHONY: help install build boot proxy doctor up down stop ls logs validate clean check test release

help:
	@echo "devctl commands:"
	@echo "  make install        Install host wrapper into PATH"
	@echo "  make build          Build devctl container image"
	@echo "  make boot           Initialize state and start proxy"
	@echo "  make proxy          Start Caddy proxy"
	@echo "  make doctor         Check local environment"
	@echo "  make up p=<name>    Start project"
	@echo "  make down p=<name>  Stop project"
	@echo "  make stop           Stop all managed projects"
	@echo "  make ls             List services"
	@echo "  make logs p=<name>  Show project logs"
	@echo "  make clean          Remove devctl containers and state volume"
	@echo "  make validate       Validate example .devctl.json profiles"
	@echo "  make check          Validate code and config"
	@echo "  make test           Run unit tests"
	@echo "  make release v=X.Y.Z  Tag and push a release (CI publishes it)"

install:
	./install.sh

build:
	$(COMPOSE) build devctl

boot: build
	$(DEVCTL) bootstrap
	$(COMPOSE) up -d caddy

proxy:
	$(COMPOSE) up -d caddy

doctor:
	$(DEVCTL) doctor

up:
	@test -n "$(PROJECT)" || { echo "Usage: make up p=<project>"; exit 2; }
	$(DEVCTL) up "$(PROJECT)"

down:
	@test -n "$(PROJECT)" || { echo "Usage: make down p=<project>"; exit 2; }
	$(DEVCTL) down "$(PROJECT)"

stop:
	$(DEVCTL) down --all

ls:
	$(DEVCTL) list

logs:
	@test -n "$(PROJECT)" || { echo "Usage: make logs p=<project>"; exit 2; }
	$(DEVCTL) logs "$(PROJECT)"

clean:
	$(COMPOSE) down --volumes --remove-orphans

validate:
	@set -e; for profile in examples/profiles/*.devctl.json; do \
		echo "Validating $$profile"; \
		$(DEVCTL) validate --file "$$profile"; \
	done

check: build validate
	$(COMPOSE) config >/dev/null
	$(COMPOSE) run --rm --entrypoint sh devctl -c 'python -m py_compile /usr/local/bin/devctl && python -m compileall -q "$$DEVCTL_REPO_ROOT"/src'
	$(COMPOSE) run --rm --entrypoint sh devctl -c 'cd "$$DEVCTL_REPO_ROOT" && ruff check . && ruff format --check .'

test: build
	$(COMPOSE) run --rm --entrypoint sh devctl -c 'cd "$$DEVCTL_REPO_ROOT" && python -m unittest discover -s . -p "test*.py" -v'

release:
	@test -n "$(VERSION)" || { echo "Usage: make release v=X.Y.Z"; exit 2; }
	@echo "$(TAG)" | grep -Eq '^v[0-9]+\.[0-9]+\.[0-9]+$$' || { echo "Version must be X.Y.Z, got: $(VERSION)"; exit 2; }
	@git diff --quiet && git diff --cached --quiet || { echo "Working tree is dirty; commit or stash first."; exit 2; }
	@git fetch origin --tags
	@! git rev-parse -q --verify "refs/tags/$(TAG)" >/dev/null || { echo "Tag $(TAG) already exists."; exit 2; }
	@test "$$(git rev-parse HEAD)" = "$$(git rev-parse @{u})" || { echo "HEAD differs from upstream; push or pull first."; exit 2; }
	git tag -a "$(TAG)" -m "$(TAG)"
	git push origin "$(TAG)"
	@echo "Pushed $(TAG). CI will run checks and publish the release:"
	@echo "  gh run list --workflow=release.yml --limit 1"
	@echo "Then rebuild the local image: make build"
