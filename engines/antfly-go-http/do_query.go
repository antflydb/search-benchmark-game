package main

import (
	"bufio"
	"bytes"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"net/http"
	"os"
	"strings"
)

const tableName = "bench"

type queryResponse struct {
	Responses []struct {
		Hits struct {
			Total int `json:"total"`
		} `json:"hits"`
	} `json:"responses"`
}

func main() {
	port := flag.Int("port", 18080, "antfly server port")
	flag.Parse()
	baseURL := fmt.Sprintf("http://localhost:%d/api/v1", *port)

	writer := bufio.NewWriter(os.Stdout)
	defer writer.Flush()

	scanner := bufio.NewScanner(os.Stdin)
	scanner.Buffer(make([]byte, 64*1024), 64*1024)

	client := &http.Client{}

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

		limit := 10
		switch command {
		case "COUNT":
			limit = 0
		case "TOP_10", "TOP_10_COUNT":
			limit = 10
		case "TOP_100", "TOP_100_COUNT":
			limit = 100
		case "TOP_1000", "TOP_1000_COUNT":
			limit = 1000
		default:
			fmt.Fprintln(writer, "UNSUPPORTED")
			writer.Flush()
			continue
		}

		reqBody := map[string]interface{}{
			"full_text_search": map[string]interface{}{
				"query": queryStr,
			},
			"limit": limit,
		}
		body, _ := json.Marshal(reqBody)

		resp, err := client.Post(baseURL+"/tables/"+tableName+"/query", "application/json", bytes.NewReader(body))
		if err != nil {
			fmt.Fprintf(os.Stderr, "query error: %v\n", err)
			fmt.Fprintln(writer, 0)
			writer.Flush()
			continue
		}
		respBody, _ := io.ReadAll(resp.Body)
		resp.Body.Close()

		var result queryResponse
		json.Unmarshal(respBody, &result)

		total := 0
		if len(result.Responses) > 0 {
			total = result.Responses[0].Hits.Total
		}

		switch command {
		case "COUNT", "TOP_10_COUNT", "TOP_100_COUNT", "TOP_1000_COUNT":
			fmt.Fprintln(writer, total)
		default:
			fmt.Fprintln(writer, 1)
		}
		writer.Flush()
	}
}
