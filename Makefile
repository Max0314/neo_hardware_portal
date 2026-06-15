PYTHON ?= python3

.DEFAULT_GOAL := help

.PHONY: help compile test docker-build quick check release-check

help:
	@echo "Neo Hardware Portal commands:"
	@echo "  make compile      Compile-check Python files"
	@echo "  make test         Run available Python tests"
	@echo "  make quick        Run compile and available tests"
	@echo "  make docker-build Build Docker Compose services"
	@echo "  make check        Run local quick checks"
	@echo "  make release-check Run quick checks and docker-build"

compile:
	$(PYTHON) -m compileall -q htmlsystm neo_ai_chatroom/backend scripts migration

test:
	@if [ -d neo_ai_chatroom/backend/tests ]; then $(PYTHON) -m pytest -q neo_ai_chatroom/backend/tests; else echo "No backend tests found"; fi

docker-build:
	docker compose build

quick: compile test

check: quick

release-check: quick docker-build
