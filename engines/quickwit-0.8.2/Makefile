PYTHON ?= python3
CORPUS ?= corpus.jsonl
QUICKWIT_IMAGE ?= quickwit/quickwit:0.8.2
QUICKWIT_CONTAINER ?= sbg-quickwit-0.8.2
QUICKWIT_VOLUME ?= sbg-quickwit-0.8.2-data
QUICKWIT_PORT ?= 29203
QUICKWIT_URL ?= http://127.0.0.1:$(QUICKWIT_PORT)

.PHONY: clean compile index serve start stop

clean: stop
	docker volume rm $(QUICKWIT_VOLUME) 2>/dev/null || true
	rm -rf __pycache__

compile:
	@$(PYTHON) -m py_compile quickwit_engine.py

start:
	@if ! curl -fsS $(QUICKWIT_URL)/api/v1/version >/dev/null 2>&1; then \
		docker rm -f $(QUICKWIT_CONTAINER) >/dev/null 2>&1 || true; \
		docker run -d --name $(QUICKWIT_CONTAINER) \
			-p 127.0.0.1:$(QUICKWIT_PORT):7280 \
			-e QW_DISABLE_TELEMETRY=1 \
			-v $(QUICKWIT_VOLUME):/quickwit/qwdata \
			$(QUICKWIT_IMAGE) run >/dev/null; \
	fi
	@for i in $$(seq 1 120); do \
		curl -fsS $(QUICKWIT_URL)/api/v1/version >/dev/null 2>&1 && exit 0; \
		sleep 1; \
	done; docker logs $(QUICKWIT_CONTAINER) >&2; exit 1

stop:
	@docker rm -f $(QUICKWIT_CONTAINER) >/dev/null 2>&1 || true

index: start
	@QUICKWIT_URL=$(QUICKWIT_URL) $(PYTHON) quickwit_engine.py index < $(CORPUS)

serve: start
	@QUICKWIT_URL=$(QUICKWIT_URL) $(PYTHON) quickwit_engine.py serve
