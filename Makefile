CORPUS := $(shell pwd)/corpus.json
export

WIKI_SRC = "https://www.dropbox.com/s/wwnfnu441w1ec9p/wiki-articles.json.bz2"

COMMANDS ?= TOP_10 TOP_100

# ENGINES ?= tantivy-0.13 lucene-8.4.0 pisa-0.8.2 rucene-0.1 bleve-0.8.0-scorch rucene-0.1 tantivy-0.11 tantivy-0.14 tantivy-0.15 tantivy-0.16 tantivy-0.17 tantivy-0.18 tantivy-0.19
# ENGINES ?= tantivy-0.16 lucene-8.10.1 pisa-0.8.2 bleve-0.8.0-scorch bluge-0.2.2 rucene-0.1
# ENGINES ?= tantivy-0.16 tantivy-0.17 tantivy-0.18 tantivy-0.19
# ENGINES ?= tantivy-0.22 tantivy-0.24 tantivy-0.25 tantivy-main lucene-10.3.0 lucene-10.3.0-bp
ENGINES ?= antfly-0.2 elasticsearch-8.15.3 weaviate-1.38.2 quickwit-0.8.2 postgresql-16 milvus-2.5.8 chroma-self-hosted
PORT ?= 8080
WARMUP_TIME ?= 60
NUM_ITER ?= 10
DATABASE_VENV ?= $(shell pwd)/.venv-databases
DATABASE_PYTHON ?= $(DATABASE_VENV)/bin/python

help:
	@grep '^[^#[:space:]].*:' Makefile

all: index

database-setup:
	@uv venv --allow-existing --python 3.13 $(DATABASE_VENV)
	@uv pip install --python $(DATABASE_PYTHON) -r database-requirements.txt

corpus:
	@echo "--- Downloading $(WIKI_SRC) ---"
	@curl -# -L "$(WIKI_SRC)" | bunzip2 -c | python3 corpus_transform.py > $(CORPUS)

clean:
	@echo "--- Cleaning directories ---"
	@rm -fr results
	@for engine in $(ENGINES); do cd ${shell pwd}/engines/$$engine && make clean ; done

index:
	@echo "--- Indexing corpus ---"
	@for engine in $(ENGINES); do \
		$(MAKE) --no-print-directory -C ${shell pwd}/engines/$$engine \
			PYTHON=$(DATABASE_PYTHON) CORPUS=$(CORPUS) index || exit $$?; \
		$(MAKE) --no-print-directory -C ${shell pwd}/engines/$$engine stop >/dev/null 2>&1 || true; \
	done

bench:
	@echo "--- Benchmarking ---"
	@rm -fr results
	@mkdir results
	@$(DATABASE_PYTHON) src/client.py queries.txt $(ENGINES)

compile:
	@echo "--- Compiling binaries ---"
	@for engine in $(ENGINES); do cd ${shell pwd}/engines/$$engine && make compile ; done

serve:
	@echo "--- Serving results ---"
	@cp results.json web/build/results.json
	@cd web/build && python3 -m http.server $(PORT)
