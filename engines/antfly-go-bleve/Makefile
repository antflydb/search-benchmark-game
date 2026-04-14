SRCPATH=$(shell pwd)
GO := CGO_ENABLED=0 go
LDFLAGS = -ldflags "-s -w"

.PHONY: clean compile index serve

clean:
	rm -fr idx bin

compile: bin/build_index bin/do_query

bin/build_index: build_index.go go.mod go.sum
	@echo "--- Building antfly-go-bleve indexer ---"
	@mkdir -p bin
	@$(GO) build $(LDFLAGS) -o $(SRCPATH)/bin/build_index $(SRCPATH)/build_index.go

bin/do_query: do_query.go go.mod go.sum
	@echo "--- Building antfly-go-bleve query runner ---"
	@mkdir -p bin
	@$(GO) build $(LDFLAGS) -o $(SRCPATH)/bin/do_query $(SRCPATH)/do_query.go

index: idx

idx: bin/build_index
	@echo "--- Indexing antfly-go-bleve ---"
	@mkdir -p idx
	bin/build_index idx < $(CORPUS)

serve: bin/do_query
	@bin/do_query idx
