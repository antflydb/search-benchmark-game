package main

import (
	"bufio"
	"encoding/json"
	"fmt"
	"io"
	"os"

	"github.com/blevesearch/bleve/v2"
	"github.com/blevesearch/bleve/v2/analysis"
	"github.com/blevesearch/bleve/v2/analysis/token/lowercase"
	"github.com/blevesearch/bleve/v2/analysis/tokenizer/unicode"
	_ "github.com/blevesearch/bleve/v2/config"
	"github.com/blevesearch/bleve/v2/index/scorch"
	"github.com/blevesearch/bleve/v2/registry"
)

const simpleAnalyzerName = "simple-no-stemming"

func init() {
	registry.RegisterAnalyzer(simpleAnalyzerName, func(config map[string]interface{}, cache *registry.Cache) (analysis.Analyzer, error) {
		tokenizer, err := cache.TokenizerNamed(unicode.Name)
		if err != nil {
			return nil, err
		}
		toLowerFilter, err := cache.TokenFilterNamed(lowercase.Name)
		if err != nil {
			return nil, err
		}
		return &analysis.DefaultAnalyzer{
			Tokenizer:    tokenizer,
			TokenFilters: []analysis.TokenFilter{toLowerFilter},
		}, nil
	})
}

func main() {
	outputDir := os.Args[1]

	textFieldMapping := bleve.NewTextFieldMapping()
	textFieldMapping.Analyzer = simpleAnalyzerName
	textFieldMapping.Store = false
	textFieldMapping.IncludeTermVectors = false
	textFieldMapping.IncludeInAll = false

	docMapping := bleve.NewDocumentMapping()
	docMapping.AddFieldMappingsAt("text", textFieldMapping)

	indexMapping := bleve.NewIndexMapping()
	indexMapping.DefaultMapping = docMapping
	indexMapping.DefaultField = "text"

	index, err := bleve.NewUsing(outputDir, indexMapping, scorch.Name, scorch.Name, nil)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	defer index.Close()

	batchSize := 20000
	batch := index.NewBatch()
	count := 0

	reader := bufio.NewReaderSize(os.Stdin, 4*1024*1024)
	for {
		lineBytes, err := reader.ReadBytes('\n')
		if err != nil && err != io.EOF {
			fmt.Fprintln(os.Stderr, err)
			break
		}

		if len(lineBytes) > 0 {
			var data map[string]interface{}
			if jsonErr := json.Unmarshal(lineBytes, &data); jsonErr != nil {
				if err == io.EOF {
					break
				}
				continue
			}
			id, _ := data["id"].(string)
			fields := map[string]interface{}{}
			for k, v := range data {
				if k != "id" {
					fields[k] = v
				}
			}
			if batchErr := batch.Index(id, fields); batchErr != nil {
				fmt.Fprintln(os.Stderr, batchErr)
				continue
			}
			count++

			if batch.Size() >= batchSize {
				if batchErr := index.Batch(batch); batchErr != nil {
					fmt.Fprintln(os.Stderr, batchErr)
					break
				}
				batch = index.NewBatch()
				if count%100000 == 0 {
					fmt.Fprintf(os.Stderr, "%d docs indexed\n", count)
				}
			}
		}

		if err == io.EOF {
			break
		}
	}

	if batch.Size() > 0 {
		if err := index.Batch(batch); err != nil {
			fmt.Fprintln(os.Stderr, err)
		}
	}

	fmt.Fprintf(os.Stderr, "Indexed %d docs. Optimizing...\n", count)

	// Force merge to single segment for optimal query performance
	// Bleve v2 Scorch supports this via the internal API
	if impl, ok := index.(interface{ ForceMerge() error }); ok {
		if err := impl.ForceMerge(); err != nil {
			fmt.Fprintf(os.Stderr, "warning: force merge: %v\n", err)
		}
	} else {
		fmt.Fprintln(os.Stderr, "warning: ForceMerge not available")
	}

	docCount, _ := index.DocCount()
	fmt.Println(docCount)
}
