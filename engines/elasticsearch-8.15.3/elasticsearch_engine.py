#!/usr/bin/env python3
"""Search Benchmark Game adapter for self-hosted Elasticsearch."""

from __future__ import annotations

import argparse
import http.client
import json
import os
import sys
from typing import Any
from urllib.parse import urlsplit


def env(name: str, default: str) -> str:
    return os.environ.get(name, default)


class ElasticsearchClient:
    def __init__(self, base_url: str, index: str) -> None:
        parsed = urlsplit(base_url.rstrip("/"))
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError(f"invalid ELASTICSEARCH_URL: {base_url}")
        self.index = index
        self._connection_type = (
            http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
        )
        self._host = parsed.hostname
        self._port = parsed.port
        self._base_path = parsed.path.rstrip("/")
        self._connection: http.client.HTTPConnection | None = None

    def _connect(self) -> http.client.HTTPConnection:
        if self._connection is None:
            self._connection = self._connection_type(
                self._host,
                self._port,
                timeout=int(env("ELASTICSEARCH_REQUEST_TIMEOUT", "300")),
            )
        return self._connection

    def _close_connection(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | bytes | None = None,
        content_type: str = "application/json",
    ) -> Any:
        if isinstance(body, dict):
            data = json.dumps(body, separators=(",", ":")).encode("utf-8")
        else:
            data = body
        headers = {"Accept": "application/json"}
        if data is not None:
            headers["Content-Type"] = content_type
        raw = b""
        status = 0
        reason = ""
        for attempt in range(2):
            try:
                connection = self._connect()
                connection.request(method, f"{self._base_path}{path}", body=data, headers=headers)
                response = connection.getresponse()
                status = response.status
                reason = response.reason
                raw = response.read()
                break
            except (BrokenPipeError, ConnectionResetError, http.client.RemoteDisconnected):
                self._close_connection()
                if attempt:
                    raise
        if status >= 400:
            raise RuntimeError(
                f"{method} {path} failed: {status} {reason} {raw.decode('utf-8', 'replace')}"
            )
        return json.loads(raw) if raw else None

    def create_index(self) -> None:
        try:
            self.request("DELETE", f"/{self.index}")
        except RuntimeError as exc:
            if " 404 " not in str(exc):
                raise
        self.request(
            "PUT",
            f"/{self.index}",
            {
                "settings": {
                    "number_of_shards": 1,
                    "number_of_replicas": 0,
                    "refresh_interval": "-1",
                    "analysis": {
                        "analyzer": {
                            "antfly_standard": {
                                "type": "custom",
                                "tokenizer": "standard",
                                "filter": ["lowercase", "antfly_english_stop"],
                            }
                        },
                        "filter": {
                            "antfly_english_stop": {"type": "stop", "stopwords": "_english_"}
                        },
                    },
                },
                "mappings": {
                    "properties": {
                        "id": {"type": "keyword", "store": True},
                        "text": {"type": "text", "analyzer": "antfly_standard"},
                        "sort_field": {"type": "long"},
                    }
                },
            },
        )

    def bulk(self, lines: list[bytes]) -> None:
        payload = b"\n".join(lines) + b"\n"
        result = self.request("POST", "/_bulk", payload, "application/x-ndjson")
        if not isinstance(result, dict) or result.get("errors"):
            first_error = None
            for item in (result or {}).get("items", []):
                operation = item.get("index", {}) if isinstance(item, dict) else {}
                if operation.get("error"):
                    first_error = operation["error"]
                    break
            raise RuntimeError(f"Elasticsearch bulk indexing failed: {first_error or result}")

    def finish_index(self, expected: int) -> None:
        self.request("PUT", f"/{self.index}/_settings", {"index": {"refresh_interval": "1s"}})
        self.request("POST", f"/{self.index}/_refresh")
        self.request("POST", f"/{self.index}/_forcemerge?max_num_segments=1")
        count = self.request("GET", f"/{self.index}/_count").get("count")
        if count != expected:
            raise RuntimeError(f"Elasticsearch count mismatch: indexed {expected}, reports {count}")

    def search(self, query: str, limit: int, validate: bool = False) -> dict[str, Any]:
        body = {
            "size": limit,
            "query": translate_query(query),
            "_source": False,
            "stored_fields": [],
            "track_total_hits": validate,
        }
        result = self.request("POST", f"/{self.index}/_search", body)
        if not isinstance(result, dict):
            raise RuntimeError(f"invalid Elasticsearch search response: {result}")
        return result


def translate_query(query: str) -> dict[str, Any]:
    query = query.strip()
    if len(query) >= 2 and query[0] == '"' and query[-1] == '"':
        return {"match_phrase": {"text": query[1:-1]}}
    terms = query.split()
    clauses = [{"match": {"text": term.lstrip("+")}} for term in terms]
    if len(clauses) == 1:
        return clauses[0]
    if all(term.startswith("+") for term in terms):
        return {"bool": {"must": clauses}}
    return {"bool": {"should": clauses, "minimum_should_match": 1}}


def index_stdin(client: ElasticsearchClient) -> dict[str, Any]:
    batch_size = int(env("ELASTICSEARCH_BATCH_SIZE", "1000"))
    client.create_index()
    lines: list[bytes] = []
    total = 0
    for line in sys.stdin:
        if not line.strip():
            continue
        doc = json.loads(line)
        doc_id = str(doc.get("id") or doc.get("_id") or total)
        lines.append(json.dumps({"index": {"_index": client.index, "_id": doc_id}}).encode("utf-8"))
        lines.append(
            json.dumps(
                {
                    "id": doc_id,
                    "text": doc.get("text") or doc.get("body") or doc.get("contents") or "",
                    "sort_field": doc.get("sort_field", 0),
                },
                ensure_ascii=False,
            ).encode("utf-8")
        )
        total += 1
        if total % batch_size == 0:
            client.bulk(lines)
            lines.clear()
            if total % (batch_size * 10) == 0:
                print(f"indexed {total} documents", file=sys.stderr, flush=True)
    if lines:
        client.bulk(lines)
    client.finish_index(total)
    return {"status": "ok", "indexed_documents": total, "batch_size": batch_size}


def parse_command(line: str) -> tuple[str, str]:
    line = line.strip()
    if "\t" in line:
        command, query = line.split("\t", 1)
        return command.strip(), query.strip()
    parts = line.split(" ", 1)
    return (parts[0], parts[1] if len(parts) > 1 else "")


def top_limit(command: str) -> int | None:
    prefix = "VALIDATE_TOP_" if command.startswith("VALIDATE_TOP_") else "TOP_"
    if not command.startswith(prefix):
        return None
    value = command.removeprefix(prefix).removesuffix("_COUNT")
    try:
        return int(value)
    except ValueError:
        return None


def serve_stdin(client: ElasticsearchClient) -> None:
    for line in sys.stdin:
        if not line.strip():
            continue
        command, query = parse_command(line)
        if command.startswith("VALIDATE_TOP_"):
            limit = top_limit(command)
            if limit is None:
                print("UNSUPPORTED", flush=True)
                continue
            result = client.search(query, limit, validate=True)
            hits = result.get("hits", {})
            total = hits.get("total", {})
            count = total.get("value", 0) if isinstance(total, dict) else int(total or 0)
            ids = [str(hit.get("_id")) for hit in hits.get("hits", []) if hit.get("_id") is not None]
            print(json.dumps({"ids": ids, "count": count}, separators=(",", ":")), flush=True)
            continue
        if command == "COUNT":
            result = client.request("POST", f"/{client.index}/_count", {"query": translate_query(query)})
            print(int(result.get("count", 0)), flush=True)
            continue
        limit = top_limit(command)
        if limit is None:
            print("UNSUPPORTED", flush=True)
            continue
        result = client.search(query, limit, validate=command.endswith("_COUNT"))
        if command.endswith("_COUNT"):
            total = result.get("hits", {}).get("total", {})
            print(total.get("value", 0) if isinstance(total, dict) else int(total or 0), flush=True)
        else:
            print(1, flush=True)


def self_test() -> int:
    cases = {
        "the": {"match": {"text": "the"}},
        "+griffith +observatory": {
            "bool": {
                "must": [
                    {"match": {"text": "griffith"}},
                    {"match": {"text": "observatory"}},
                ]
            }
        },
        "griffith observatory": {
            "bool": {
                "should": [
                    {"match": {"text": "griffith"}},
                    {"match": {"text": "observatory"}},
                ],
                "minimum_should_match": 1,
            }
        },
        '"griffith observatory"': {"match_phrase": {"text": "griffith observatory"}},
    }
    for raw, expected in cases.items():
        actual = translate_query(raw)
        if actual != expected:
            print(json.dumps({"status": "failed", "query": raw, "expected": expected, "actual": actual}))
            return 1
    print(json.dumps({"status": "ok", "translated_queries": len(cases)}))
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", nargs="?", choices=["index", "serve"])
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)
    if args.self_test:
        return self_test()
    client = ElasticsearchClient(
        env("ELASTICSEARCH_URL", "http://127.0.0.1:29200"),
        env("ELASTICSEARCH_INDEX", "sbg-wikipedia"),
    )
    if args.mode == "index":
        print(json.dumps(index_stdin(client)))
        return 0
    if args.mode == "serve":
        serve_stdin(client)
        return 0
    parser.error("mode is required unless --self-test is used")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
