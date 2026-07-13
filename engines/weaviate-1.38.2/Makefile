PYTHON ?= python3
CORPUS ?= corpus.jsonl
WEAVIATE_IMAGE ?= cr.weaviate.io/semitechnologies/weaviate:1.38.2
WEAVIATE_CONTAINER ?= sbg-weaviate-1.38.2
WEAVIATE_VOLUME ?= sbg-weaviate-1.38.2-data
WEAVIATE_PORT ?= 29201
WEAVIATE_URL ?= http://127.0.0.1:$(WEAVIATE_PORT)

.PHONY: clean compile index serve start stop

clean: stop
	docker volume rm $(WEAVIATE_VOLUME) 2>/dev/null || true
	rm -rf __pycache__

compile:
	@$(PYTHON) -m py_compile weaviate_engine.py

start:
	@if ! curl -fsS $(WEAVIATE_URL)/v1/.well-known/ready >/dev/null 2>&1; then \
		docker rm -f $(WEAVIATE_CONTAINER) >/dev/null 2>&1 || true; \
		docker run -d --name $(WEAVIATE_CONTAINER) \
			-p 127.0.0.1:$(WEAVIATE_PORT):8080 \
			-e AUTHENTICATION_ANONYMOUS_ACCESS_ENABLED=true \
			-e PERSISTENCE_DATA_PATH=/var/lib/weaviate \
			-e DEFAULT_VECTORIZER_MODULE=none \
			-e ENABLE_MODULES=none \
			-e CLUSTER_HOSTNAME=sbg-node \
			-e DISABLE_TELEMETRY=true \
			-v $(WEAVIATE_VOLUME):/var/lib/weaviate \
			$(WEAVIATE_IMAGE) >/dev/null; \
	fi
	@for i in $$(seq 1 120); do \
		curl -fsS $(WEAVIATE_URL)/v1/.well-known/ready >/dev/null 2>&1 && exit 0; \
		sleep 1; \
	done; docker logs $(WEAVIATE_CONTAINER) >&2; exit 1

stop:
	@docker rm -f $(WEAVIATE_CONTAINER) >/dev/null 2>&1 || true

index: start
	@WEAVIATE_URL=$(WEAVIATE_URL) $(PYTHON) weaviate_engine.py index < $(CORPUS)

serve: start
	@WEAVIATE_URL=$(WEAVIATE_URL) $(PYTHON) weaviate_engine.py serve
