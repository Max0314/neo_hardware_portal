PYTHON ?= python3

.DEFAULT_GOAL := help

.PHONY: help compile test docker-build check

help:
	@echo "Neo Hardware Portal commands:"
	@echo "  make compile      Compile-check Python files"
	@echo "  make test         Run available Python tests"
	@echo "  make docker-build Build Docker Compose services"
	@echo "  make check        Run compile"

compile:
	$(PYTHON) -m compileall -q htmlsystm neo_ai_chatroom/backend scripts migration

test:
	@if [ -d neo_ai_chatroom/backend/tests ]; then $(PYTHON) -m pytest -q neo_ai_chatroom/backend/tests; else echo "No backend tests found"; fi

docker-build:
	docker compose build

check: compile
