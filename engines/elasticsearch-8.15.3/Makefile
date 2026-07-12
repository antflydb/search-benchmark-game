PYTHON ?= python3
CORPUS ?= corpus.jsonl
ELASTICSEARCH_IMAGE ?= docker.elastic.co/elasticsearch/elasticsearch:8.15.3
ELASTICSEARCH_CONTAINER ?= sbg-elasticsearch-8.15.3
ELASTICSEARCH_VOLUME ?= sbg-elasticsearch-8.15.3-data
ELASTICSEARCH_PORT ?= 29200
ELASTICSEARCH_URL ?= http://127.0.0.1:$(ELASTICSEARCH_PORT)

.PHONY: clean compile index serve start stop

clean: stop
	docker volume rm $(ELASTICSEARCH_VOLUME) 2>/dev/null || true
	rm -rf __pycache__

compile:
	@$(PYTHON) -m py_compile elasticsearch_engine.py

start:
	@if ! curl -fsS $(ELASTICSEARCH_URL) >/dev/null 2>&1; then \
		docker rm -f $(ELASTICSEARCH_CONTAINER) >/dev/null 2>&1 || true; \
		docker run -d --name $(ELASTICSEARCH_CONTAINER) \
			-p 127.0.0.1:$(ELASTICSEARCH_PORT):9200 \
			-e discovery.type=single-node \
			-e xpack.security.enabled=false \
			-e ingest.geoip.downloader.enabled=false \
			-e 'ES_JAVA_OPTS=-Xms1g -Xmx1g' \
			-v $(ELASTICSEARCH_VOLUME):/usr/share/elasticsearch/data \
			$(ELASTICSEARCH_IMAGE) >/dev/null; \
	fi
	@for i in $$(seq 1 120); do \
		curl -fsS $(ELASTICSEARCH_URL)/_cluster/health?wait_for_status=yellow >/dev/null 2>&1 && exit 0; \
		sleep 1; \
	done; \
	echo 'Elasticsearch did not become ready' >&2; \
	docker logs $(ELASTICSEARCH_CONTAINER) >&2; \
	exit 1

stop:
	@docker rm -f $(ELASTICSEARCH_CONTAINER) >/dev/null 2>&1 || true

index: start
	@ELASTICSEARCH_URL=$(ELASTICSEARCH_URL) $(PYTHON) elasticsearch_engine.py index < $(CORPUS)

serve: start
	@ELASTICSEARCH_URL=$(ELASTICSEARCH_URL) $(PYTHON) elasticsearch_engine.py serve
