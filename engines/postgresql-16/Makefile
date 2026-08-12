PYTHON ?= ../../.venv-databases/bin/python
CORPUS ?= corpus.jsonl
POSTGRES_IMAGE ?= pgvector/pgvector:pg16
POSTGRES_CONTAINER ?= sbg-postgresql-16
POSTGRES_VOLUME ?= sbg-postgresql-16-data
POSTGRES_PORT ?= 29202
POSTGRES_DSN ?= postgresql://postgres:postgres@127.0.0.1:$(POSTGRES_PORT)/postgres

.PHONY: clean compile index serve start stop

clean: stop
	docker volume rm $(POSTGRES_VOLUME) 2>/dev/null || true
	rm -rf __pycache__

compile:
	@$(PYTHON) -m py_compile postgresql_engine.py

start:
	@if ! docker exec $(POSTGRES_CONTAINER) pg_isready -U postgres >/dev/null 2>&1; then \
		docker rm -f $(POSTGRES_CONTAINER) >/dev/null 2>&1 || true; \
		docker run -d --name $(POSTGRES_CONTAINER) \
			-p 127.0.0.1:$(POSTGRES_PORT):5432 \
			--shm-size=1g \
			-e POSTGRES_PASSWORD=postgres \
			-v $(POSTGRES_VOLUME):/var/lib/postgresql/data \
			$(POSTGRES_IMAGE) >/dev/null; \
	fi
	@for i in $$(seq 1 120); do \
		docker exec $(POSTGRES_CONTAINER) pg_isready -U postgres >/dev/null 2>&1 && exit 0; \
		sleep 1; \
	done; docker logs $(POSTGRES_CONTAINER) >&2; exit 1

stop:
	@docker rm -f $(POSTGRES_CONTAINER) >/dev/null 2>&1 || true

index: start
	@POSTGRES_DSN=$(POSTGRES_DSN) $(PYTHON) postgresql_engine.py index < $(CORPUS)

serve: start
	@POSTGRES_DSN=$(POSTGRES_DSN) $(PYTHON) postgresql_engine.py serve
