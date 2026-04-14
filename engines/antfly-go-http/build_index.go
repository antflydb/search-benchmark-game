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
	"time"
)

const tableName = "bench"

func main() {
	port := flag.Int("port", 18080, "antfly server port")
	flag.Parse()
	baseURL := fmt.Sprintf("http://localhost:%d/api/v1", *port)

	// Delete old table (ignore errors)
	req, _ := http.NewRequest("DELETE", baseURL+"/tables/"+tableName, nil)
	http.DefaultClient.Do(req)
	time.Sleep(500 * time.Millisecond)

	// Create table
	resp, err := http.Post(baseURL+"/tables/"+tableName, "application/json", bytes.NewReader([]byte("{}")))
	if err != nil {
		fmt.Fprintf(os.Stderr, "create table: %v\n", err)
		os.Exit(1)
	}
	resp.Body.Close()

	// Create full-text index with simple analyzer
	indexConfig := `{"analysis_config":{"field_analyzers":{"text":"simple"}}}`
	resp, err = http.Post(baseURL+"/tables/"+tableName+"/indexes/full_text_index_v0", "application/json",
		bytes.NewReader([]byte(indexConfig)))
	if err != nil {
		fmt.Fprintf(os.Stderr, "create index: %v\n", err)
		os.Exit(1)
	}
	resp.Body.Close()

	// Batch insert from stdin
	batchSize := 1000
	count := 0
	inserts := make(map[string]json.RawMessage, batchSize)

	reader := bufio.NewReaderSize(os.Stdin, 4*1024*1024)
	for {
		lineBytes, err := reader.ReadBytes('\n')
		if err != nil && err != io.EOF {
			break
		}
		if len(lineBytes) > 0 {
			var doc map[string]json.RawMessage
			if jsonErr := json.Unmarshal(lineBytes, &doc); jsonErr != nil {
				if err == io.EOF {
					break
				}
				continue
			}
			var id string
			json.Unmarshal(doc["id"], &id)
			inserts[id] = lineBytes
			count++

			if len(inserts) >= batchSize {
				if flushErr := flushBatch(baseURL, inserts); flushErr != nil {
					fmt.Fprintf(os.Stderr, "batch: %v\n", flushErr)
				}
				inserts = make(map[string]json.RawMessage, batchSize)
				if count%100000 == 0 {
					fmt.Fprintf(os.Stderr, "%d docs indexed\n", count)
				}
			}
		}
		if err == io.EOF {
			break
		}
	}

	if len(inserts) > 0 {
		if err := flushBatch(baseURL, inserts); err != nil {
			fmt.Fprintf(os.Stderr, "final batch: %v\n", err)
		}
	}

	fmt.Fprintf(os.Stderr, "Indexed %d docs. Waiting for full-text sync...\n", count)

	// Wait for index to be ready by polling
	for i := 0; i < 600; i++ {
		time.Sleep(1 * time.Second)
		resp, err := http.Get(baseURL + "/tables/" + tableName + "/indexes/full_text_index_v0")
		if err != nil {
			continue
		}
		body, _ := io.ReadAll(resp.Body)
		resp.Body.Close()
		if bytes.Contains(body, []byte(`"ready":true`)) || bytes.Contains(body, []byte(`"ready": true`)) {
			break
		}
		if i%30 == 0 {
			fmt.Fprintf(os.Stderr, "waiting for index (%ds)...\n", i)
		}
	}

	fmt.Println(count)
}

func flushBatch(baseURL string, inserts map[string]json.RawMessage) error {
	// Build batch request: {"inserts": {"key": {doc}, ...}}
	batch := map[string]interface{}{
		"inserts":    inserts,
		"sync_level": "write",
	}
	body, err := json.Marshal(batch)
	if err != nil {
		return err
	}
	resp, err := http.Post(baseURL+"/tables/"+tableName+"/batch", "application/json", bytes.NewReader(body))
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 400 {
		respBody, _ := io.ReadAll(resp.Body)
		return fmt.Errorf("status %d: %s", resp.StatusCode, string(respBody))
	}
	return nil
}
