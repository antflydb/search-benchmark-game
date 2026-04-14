ANTFLY_ZIG_DIR ?= ../../../antfly-zig
CORPUS ?= ../../corpus.json

.PHONY: clean compile index serve

clean:
	rm -rf idx

compile:
	cd $(ANTFLY_ZIG_DIR) && zig build search-bench-build

index: idx

idx: $(ANTFLY_ZIG_DIR)/zig-out/bin/bench_search_index
	@mkdir -p idx
	$(ANTFLY_ZIG_DIR)/zig-out/bin/bench_search_index idx < $(CORPUS)

serve: $(ANTFLY_ZIG_DIR)/zig-out/bin/bench_search_query
	@$(ANTFLY_ZIG_DIR)/zig-out/bin/bench_search_query idx
