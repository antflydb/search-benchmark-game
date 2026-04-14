SRCPATH=$(shell pwd)
PORT ?= 18080
GO := go
LDFLAGS = -ldflags "-s -w"

.PHONY: clean compile index serve

clean:
	rm -fr bin

compile: bin/build_index bin/do_query

bin/build_index: build_index.go go.mod
	@echo "--- Building antfly-go-http indexer ---"
	@mkdir -p bin
	@$(GO) build $(LDFLAGS) -o $(SRCPATH)/bin/build_index $(SRCPATH)/build_index.go

bin/do_query: do_query.go go.mod
	@echo "--- Building antfly-go-http query runner ---"
	@mkdir -p bin
	@$(GO) build $(LDFLAGS) -o $(SRCPATH)/bin/do_query $(SRCPATH)/do_query.go

index: bin/build_index
	@echo "--- Indexing antfly-go-http (server must be running on port $(PORT)) ---"
	bin/build_index -port $(PORT) < $(CORPUS)

serve: bin/do_query
	@bin/do_query -port $(PORT)
