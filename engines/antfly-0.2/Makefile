PYTHON ?= python3
CORPUS ?= corpus.jsonl

.PHONY: clean compile index serve self-test stop

clean:
	rm -rf __pycache__

compile:
	@$(PYTHON) -m py_compile antfly_engine.py

index:
	@$(PYTHON) antfly_engine.py index < $(CORPUS)

serve:
	@$(PYTHON) antfly_engine.py serve

self-test:
	@$(PYTHON) antfly_engine.py --self-test

stop:
	@true
