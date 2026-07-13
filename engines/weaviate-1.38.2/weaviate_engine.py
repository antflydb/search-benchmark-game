#!/usr/bin/env python3
"""Search Benchmark Game adapter for self-hosted Weaviate BM25F."""

from __future__ import annotations

import argparse
import http.client
import json
import os
import sys
import uuid
from typing import Any
from urllib.parse import urlsplit


CLASS_NAME = "SbgDocument"
NAMESPACE = uuid.UUID("5a31cdde-2189-4c79-9760-76467a8f94ac")


class Client:
    def __init__(self, base_url: str) -> None:
        parsed = urlsplit(base_url.rstrip("/"))
        self.host = parsed.hostname
        self.port = parsed.port
        self.connection: http.client.HTTPConnection | None = None

    def connect(self) -> http.client.HTTPConnection:
        if self.connection is None:
            self.connection = http.client.HTTPConnection(self.host, self.port, timeout=300)
        return self.connection

    def request(self, method: str, path: str, body: Any = None) -> Any:
        data = None if body is None else json.dumps(body, separators=(",", ":")).encode()
        for attempt in range(2):
            try:
                conn = self.connect()
                conn.request(method, path, data, {"Content-Type": "application/json", "Accept": "application/json"})
                response = conn.getresponse()
                raw = response.read()
                if response.status >= 400:
                    raise RuntimeError(f"{method} {path}: {response.status} {raw.decode(errors='replace')}")
                return json.loads(raw) if raw else None
            except (BrokenPipeError, ConnectionResetError, http.client.RemoteDisconnected):
                if self.connection:
                    self.connection.close()
                self.connection = None
                if attempt:
                    raise
        raise AssertionError("unreachable")

    def create_schema(self) -> None:
        try:
            self.request("DELETE", f"/v1/schema/{CLASS_NAME}")
        except RuntimeError as exc:
            if " 404 " not in str(exc) and ": 404 " not in str(exc):
                raise
        self.request("POST", "/v1/schema", {
            "class": CLASS_NAME,
            "vectorizer": "none",
            "vectorIndexConfig": {"skip": True},
            "invertedIndexConfig": {
                "bm25": {"k1": 1.2, "b": 0.75},
                "stopwords": {"preset": "en"},
                "indexTimestamps": False,
            },
            "properties": [
                {"name": "doc_id", "dataType": ["text"], "tokenization": "field", "indexSearchable": False},
                {"name": "text", "dataType": ["text"], "tokenization": "word", "indexFilterable": False},
            ],
        })

    def batch(self, objects: list[dict[str, Any]]) -> None:
        result = self.request("POST", "/v1/batch/objects", {"objects": objects})
        failures = []
        for item in result or []:
            status = ((item.get("result") or {}).get("status")) if isinstance(item, dict) else None
            if status == "FAILED":
                failures.append(item)
        if failures:
            raise RuntimeError(f"Weaviate batch failed: {failures[0]}")

    def search(self, raw_query: str, limit: int) -> list[str]:
        query, operator = translate_query(raw_query)
        search_operator = (
            "{operator:And}" if operator == "And" else "{operator:Or,minimumOrTokensMatch:1}"
        )
        graphql = (
            "{Get{%s(limit:%d,bm25:{query:%s,properties:[\"text\"],searchOperator:%s})"
            "{doc_id}}}" % (CLASS_NAME, limit, json.dumps(query), search_operator)
        )
        payload = self.request("POST", "/v1/graphql", {"query": graphql})
        if payload.get("errors"):
            raise RuntimeError(f"Weaviate GraphQL failed: {payload['errors']}")
        rows = (((payload.get("data") or {}).get("Get") or {}).get(CLASS_NAME) or [])
        return [str(row["doc_id"]) for row in rows]


def translate_query(raw: str) -> tuple[str, str]:
    terms = raw.strip().split()
    if all(term.startswith("+") for term in terms):
        return " ".join(term.removeprefix("+") for term in terms), "And"
    return " ".join(term.removeprefix("+") for term in terms), "Or"


def index_stdin(client: Client) -> dict[str, Any]:
    client.create_schema()
    batch_size = int(os.environ.get("WEAVIATE_BATCH_SIZE", "500"))
    objects: list[dict[str, Any]] = []
    total = 0
    for line in sys.stdin:
        if not line.strip():
            continue
        doc = json.loads(line)
        doc_id = str(doc.get("id") or total)
        objects.append({
            "class": CLASS_NAME,
            "id": str(uuid.uuid5(NAMESPACE, doc_id)),
            "properties": {"doc_id": doc_id, "text": doc.get("text", "")},
        })
        total += 1
        if len(objects) >= batch_size:
            client.batch(objects)
            objects.clear()
            if total % 10000 == 0:
                print(f"indexed {total} documents", file=sys.stderr, flush=True)
    if objects:
        client.batch(objects)
    return {"status": "ok", "indexed_documents": total, "batch_size": batch_size}


def serve(client: Client) -> None:
    for line in sys.stdin:
        if not line.strip():
            continue
        command, query = line.rstrip("\n").split("\t", 1)
        validate = command.startswith("VALIDATE_TOP_")
        value = command.removeprefix("VALIDATE_TOP_") if validate else command.removeprefix("TOP_")
        try:
            limit = int(value.removesuffix("_COUNT"))
        except ValueError:
            print("UNSUPPORTED", flush=True)
            continue
        ids = client.search(query, limit)
        if validate:
            print(json.dumps({"ids": ids, "count": None}, separators=(",", ":")), flush=True)
        elif command.endswith("_COUNT"):
            print("UNSUPPORTED", flush=True)
        else:
            print(1, flush=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", nargs="?", choices=["index", "serve"])
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        assert translate_query("climate policy") == ("climate policy", "Or")
        assert translate_query("+climate +policy") == ("climate policy", "And")
        print(json.dumps({"status": "ok", "translated_queries": 2}))
        return 0
    client = Client(os.environ.get("WEAVIATE_URL", "http://127.0.0.1:29201"))
    if args.mode == "index":
        print(json.dumps(index_stdin(client)))
        return 0
    if args.mode == "serve":
        serve(client)
        return 0
    parser.error("mode is required")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
