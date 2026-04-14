package main

import (
	"bufio"
	"fmt"
	"os"
	"strings"

	"github.com/blevesearch/bleve/v2"
	"github.com/blevesearch/bleve/v2/analysis"
	"github.com/blevesearch/bleve/v2/analysis/token/lowercase"
	"github.com/blevesearch/bleve/v2/analysis/tokenizer/unicode"
	_ "github.com/blevesearch/bleve/v2/config"
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
	indexDir := os.Args[1]

	index, err := bleve.Open(indexDir)
	if err != nil {
		fmt.Fprintf(os.Stderr, "ERROR: %v\n", err)
		os.Exit(1)
	}
	defer index.Close()

	writer := bufio.NewWriter(os.Stdout)
	defer writer.Flush()

	scanner := bufio.NewScanner(os.Stdin)
	scanner.Buffer(make([]byte, 64*1024), 64*1024)

	for scanner.Scan() {
		line := scanner.Text()
		fields := strings.SplitN(line, "\t", 2)
		if len(fields) != 2 {
			fmt.Fprintln(writer, "UNSUPPORTED")
			writer.Flush()
			continue
		}
		command := fields[0]
		queryStr := fields[1]

		query := bleve.NewQueryStringQuery(queryStr)
		searchRequest := bleve.NewSearchRequest(query)

		var count uint64

		switch command {
		case "COUNT":
			searchRequest.Size = 0
			result, err := index.Search(searchRequest)
			if err != nil {
				fmt.Fprintf(os.Stderr, "ERROR: %v\n", err)
				fmt.Fprintln(writer, 0)
				writer.Flush()
				continue
			}
			count = result.Total
		case "TOP_10":
			searchRequest.Size = 10
			_, err := index.Search(searchRequest)
			if err != nil {
				fmt.Fprintf(os.Stderr, "ERROR: %v\n", err)
				fmt.Fprintln(writer, 0)
				writer.Flush()
				continue
			}
			count = 1
		case "TOP_100":
			searchRequest.Size = 100
			_, err := index.Search(searchRequest)
			if err != nil {
				fmt.Fprintln(writer, "UNSUPPORTED")
				writer.Flush()
				continue
			}
			count = 1
		case "TOP_1000":
			searchRequest.Size = 1000
			_, err := index.Search(searchRequest)
			if err != nil {
				fmt.Fprintln(writer, "UNSUPPORTED")
				writer.Flush()
				continue
			}
			count = 1
		case "TOP_10_COUNT":
			searchRequest.Size = 10
			result, err := index.Search(searchRequest)
			if err != nil {
				fmt.Fprintf(os.Stderr, "ERROR: %v\n", err)
				fmt.Fprintln(writer, 0)
				writer.Flush()
				continue
			}
			count = result.Total
		case "TOP_100_COUNT":
			searchRequest.Size = 100
			result, err := index.Search(searchRequest)
			if err != nil {
				fmt.Fprintln(writer, "UNSUPPORTED")
				writer.Flush()
				continue
			}
			count = result.Total
		case "TOP_1000_COUNT":
			searchRequest.Size = 1000
			result, err := index.Search(searchRequest)
			if err != nil {
				fmt.Fprintln(writer, "UNSUPPORTED")
				writer.Flush()
				continue
			}
			count = result.Total
		default:
			fmt.Fprintln(writer, "UNSUPPORTED")
			writer.Flush()
			continue
		}

		fmt.Fprintln(writer, count)
		writer.Flush()
	}
}
