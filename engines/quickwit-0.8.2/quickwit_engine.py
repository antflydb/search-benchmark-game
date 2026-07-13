#!/usr/bin/env python3
"""Search Benchmark Game adapter for self-hosted Quickwit."""

from __future__ import annotations

import argparse
import http.client
import json
import os
import sys
from typing import Any
from urllib.parse import urlsplit


INDEX_ID = "sbg-wikipedia"


class Client:
    def __init__(self, base_url: str) -> None:
        parsed = urlsplit(base_url.rstrip("/"))
        if parsed.scheme != "http" or not parsed.hostname:
            raise ValueError(f"invalid QUICKWIT_URL: {base_url}")
        self.host = parsed.hostname
        self.port = parsed.port
        self.connection: http.client.HTTPConnection | None = None

    def connect(self) -> http.client.HTTPConnection:
        if self.connection is None:
            self.connection = http.client.HTTPConnection(self.host, self.port, timeout=300)
        return self.connection

    def request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | bytes | None = None,
        content_type: str = "application/json",
    ) -> Any:
        data = json.dumps(body, separators=(",", ":")).encode() if isinstance(body, dict) else body
        headers = {"Accept": "application/json"}
        if data is not None:
            headers["Content-Type"] = content_type
        for attempt in range(2):
            try:
                connection = self.connect()
                connection.request(method, path, data, headers)
                response = connection.getresponse()
                raw = response.read()
                if response.status >= 400:
                    raise RuntimeError(
                        f"{method} {path}: {response.status} {raw.decode(errors='replace')}"
                    )
                return json.loads(raw) if raw else None
            except (BrokenPipeError, ConnectionResetError, http.client.RemoteDisconnected):
                if self.connection:
                    self.connection.close()
                self.connection = None
                if attempt:
                    raise
        raise AssertionError("unreachable")

    def create_index(self) -> None:
        try:
            self.request("DELETE", f"/api/v1/indexes/{INDEX_ID}")
        except RuntimeError as exc:
            if ": 404 " not in str(exc):
                raise
        self.request(
            "POST",
            "/api/v1/indexes",
            {
                "version": "0.8",
                "index_id": INDEX_ID,
                "doc_mapping": {
                    "mode": "strict",
                    "field_mappings": [
                        {
                            "name": "id",
                            "type": "text",
                            "stored": True,
                            "indexed": False,
                        },
                        {
                            "name": "text",
                            "type": "text",
                            "tokenizer": "default",
                            "record": "position",
                            "fieldnorms": True,
                            "stored": False,
                        },
                    ],
                },
                "search_settings": {"default_search_fields": ["text"]},
                "indexing_settings": {"commit_timeout_secs": 10},
            },
        )

    def ingest(self, documents: list[bytes], force: bool = False) -> None:
        commit = "force" if force else "auto"
        self.request(
            "POST",
            f"/api/v1/{INDEX_ID}/ingest?commit={commit}",
            b"\n".join(documents) + b"\n",
            "application/x-ndjson",
        )

    def search(self, raw_query: str, limit: int) -> dict[str, Any]:
        result = self.request(
            "POST",
            f"/api/v1/{INDEX_ID}/search",
            {
                "query": translate_query(raw_query),
                "max_hits": limit,
                "sort_by": "_score",
                "format": "json",
            },
        )
        if not isinstance(result, dict):
            raise RuntimeError(f"invalid Quickwit search response: {result}")
        return result


def quote_term(term: str) -> str:
    return json.dumps(term.removeprefix("+"))


def translate_query(raw: str) -> str:
    raw = raw.strip()
    if len(raw) >= 2 and raw.startswith('"') and raw.endswith('"'):
        return raw
    terms = raw.split()
    operator = " AND " if all(term.startswith("+") for term in terms) else " OR "
    return operator.join(quote_term(term) for term in terms)


def index_stdin(client: Client) -> dict[str, Any]:
    client.create_index()
    max_batch_bytes = int(os.environ.get("QUICKWIT_BATCH_BYTES", str(8 * 1024 * 1024)))
    documents: list[bytes] = []
    batch_bytes = 0
    total = 0
    for line in sys.stdin:
        if not line.strip():
            continue
        source = json.loads(line)
        document = json.dumps(
            {"id": str(source.get("id") or total), "text": source.get("text", "")},
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode()
        if documents and batch_bytes + len(document) + 1 > max_batch_bytes:
            client.ingest(documents)
            documents.clear()
            batch_bytes = 0
        documents.append(document)
        batch_bytes += len(document) + 1
        total += 1
        if total % 10000 == 0:
            print(f"queued {total} documents", file=sys.stderr, flush=True)
    if documents:
        client.ingest(documents, force=True)
    description = client.request("GET", f"/api/v1/indexes/{INDEX_ID}/describe")
    indexed = int(description.get("num_published_docs", -1))
    if indexed != total:
        raise RuntimeError(f"Quickwit count mismatch: indexed {total}, reports {indexed}")
    return {"status": "ok", "indexed_documents": total, "batch_bytes": max_batch_bytes}


def top_limit(command: str) -> int | None:
    prefix = "VALIDATE_TOP_" if command.startswith("VALIDATE_TOP_") else "TOP_"
    if not command.startswith(prefix):
        return None
    try:
        return int(command.removeprefix(prefix).removesuffix("_COUNT"))
    except ValueError:
        return None


def serve(client: Client) -> None:
    for line in sys.stdin:
        if not line.strip():
            continue
        command, query = line.rstrip("\n").split("\t", 1)
        limit = top_limit(command)
        if limit is None:
            print("UNSUPPORTED", flush=True)
            continue
        result = client.search(query, limit)
        if command.startswith("VALIDATE_TOP_"):
            ids = [str(hit["id"]) for hit in result.get("hits", [])]
            print(
                json.dumps({"ids": ids, "count": int(result.get("num_hits", 0))}, separators=(",", ":")),
                flush=True,
            )
        elif command.endswith("_COUNT"):
            print(int(result.get("num_hits", 0)), flush=True)
        else:
            print(1, flush=True)


def self_test() -> int:
    cases = {
        "the": '"the"',
        "+climate +policy": '"climate" AND "policy"',
        "climate policy": '"climate" OR "policy"',
        '"climate policy"': '"climate policy"',
    }
    for raw, expected in cases.items():
        assert translate_query(raw) == expected, (raw, translate_query(raw), expected)
    print(json.dumps({"status": "ok", "translated_queries": len(cases)}))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", nargs="?", choices=["index", "serve"])
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    client = Client(os.environ.get("QUICKWIT_URL", "http://127.0.0.1:29203"))
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
