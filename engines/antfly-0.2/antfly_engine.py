#!/usr/bin/env python3
"""Search Benchmark Game adapter for Antfly full-text search."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any


def env(name: str, default: str) -> str:
    return os.environ.get(name, default)


class AntflyClient:
    def __init__(self, base_url: str, table: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.table = table
        self.api_root = env("ANTFLY_API_ROOT", "").rstrip("/") or self.detect_api_root()
        self.index_name = env("ANTFLY_TEXT_INDEX", "text")

    def detect_api_root(self) -> str:
        for root in ("/db/v1", "/api/v1"):
            try:
                req = urllib.request.Request(f"{self.base_url}{root}/tables", method="GET")
                with urllib.request.urlopen(req, timeout=5) as resp:
                    content_type = resp.headers.get("content-type", "")
                    if resp.status < 500 and "json" in content_type:
                        return root
            except Exception:
                continue
        return "/db/v1"

    def request(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        timeout = int(env("ANTFLY_REQUEST_TIMEOUT", "300"))
        data = None if body is None else json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}{path}",
            data=data,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"{method} {path} failed: {exc.code} {exc.read().decode('utf-8', 'replace')}") from exc
        if not raw:
            return None
        return json.loads(raw)

    def create_table(self) -> None:
        table_path = f"{self.api_root}/tables/{self.table}"
        index_name = self.index_name
        try:
            self.request("DELETE", table_path)
        except Exception:
            pass
        self.request("POST", table_path, {"num_shards": int(env("ANTFLY_SHARDS", "1"))})
        index_bodies = [
            {"name": index_name, "type": "full_text"},
            {"name": index_name, "type": "full_text", "field": env("ANTFLY_TEXT_FIELD", "text")},
        ]
        if self.api_root == "/api/v1":
            index_bodies.reverse()
        last_error: Exception | None = None
        for index_body in index_bodies:
            try:
                self.request("POST", f"{table_path}/indexes/{index_name}", index_body)
                return
            except Exception as exc:
                last_error = exc
        self.index_name = "full_text_index_v0"
        print(
            f"warning: could not create full-text index {index_name}; using default {self.index_name}: {last_error}",
            file=sys.stderr,
            flush=True,
        )

    def insert_documents(self, docs: list[dict[str, Any]]) -> None:
        inserts = {}
        text_field = env("ANTFLY_TEXT_FIELD", "text")
        for idx, doc in enumerate(docs):
            doc_id = str(doc.get("id") or doc.get("_id") or idx)
            text = doc.get(text_field) or doc.get("body") or doc.get("contents") or ""
            inserts[doc_id] = {text_field: text}
        if inserts:
            self.request(
                "POST",
                f"{self.api_root}/tables/{self.table}/batch",
                {"inserts": inserts, "sync_level": "full_text"},
            )

    def search(self, query: str, limit: int) -> Any:
        text_field = env("ANTFLY_TEXT_FIELD", "text")
        full_text_search = translate_query(query, text_field)
        body = {
            "limit": limit,
            "full_text_search": full_text_search,
        }
        if self.api_root == "/api/v1":
            body["full_text_search"] = {"query": field_qualify_query(query, text_field)}
            return self.request("POST", f"/api/v1/tables/{self.table}/query", body)
        return self.request("POST", f"{self.api_root}/tables/{self.table}/query", body)


def translate_query(query: str, field: str) -> dict[str, Any]:
    query = query.strip()
    if len(query) >= 2 and query[0] == '"' and query[-1] == '"':
        return {"match_phrase": {"field": field, "text": query[1:-1]}}
    # Search Benchmark Game uses leading plus signs for required terms. Antfly's
    # structured match query is the current API surface; remove Lucene markers
    # and let Antfly tokenize the field text.
    text = " ".join(part.lstrip("+") for part in query.split())
    return {"match": {"field": field, "text": text}}


def field_qualify_query(query: str, field: str) -> str:
    query = query.strip()
    if not query:
        return f"{field}:()"
    if query.startswith(f"{field}:"):
        return query
    return f"{field}:({query})"


def extract_total(resp: Any) -> int:
    if isinstance(resp, dict):
        for key in ("total", "count"):
            value = resp.get(key)
            if isinstance(value, int):
                return value
        hits = resp.get("hits")
        if isinstance(hits, list):
            return len(hits)
        if isinstance(hits, dict):
            total = hits.get("total")
            if isinstance(total, int):
                return total
            nested = hits.get("hits")
            if isinstance(nested, list):
                return len(nested)
        responses = resp.get("responses")
        if isinstance(responses, list) and responses:
            return extract_total(responses[0])
    return 0


def parse_command(line: str) -> tuple[str, str]:
    line = line.strip()
    if "\t" in line:
        command, query = line.split("\t", 1)
        return command.strip(), query.strip()
    parts = line.split(" ", 1)
    if len(parts) == 1:
        return parts[0], ""
    return parts[0].strip(), parts[1].strip()


def command_to_limit(command: str) -> int | None:
    if command == "COUNT":
        return 0
    if command.startswith("TOP_"):
        value = command.removeprefix("TOP_").removesuffix("_COUNT")
        try:
            return int(value)
        except ValueError:
            return None
    return None


def index_stdin(client: AntflyClient) -> dict[str, Any]:
    batch_size = int(env("ANTFLY_BATCH_SIZE", "5000"))
    max_docs_raw = env("ANTFLY_MAX_DOCS", "0")
    max_docs = int(max_docs_raw) if max_docs_raw else 0
    client.create_table()
    docs: list[dict[str, Any]] = []
    total = 0
    for line in sys.stdin:
        if not line.strip():
            continue
        if max_docs and total + len(docs) >= max_docs:
            break
        docs.append(json.loads(line))
        if len(docs) >= batch_size:
            client.insert_documents(docs)
            total += len(docs)
            if total % (batch_size * 10) == 0:
                print(f"indexed {total} documents", file=sys.stderr, flush=True)
            docs.clear()
    if docs:
        client.insert_documents(docs)
        total += len(docs)
    return {
        "status": "ok",
        "indexed_documents": total,
        "batch_size": batch_size,
        "max_documents": max_docs or None,
        "api_root": client.api_root,
    }


def serve_stdin(client: AntflyClient) -> None:
    count_limit = int(env("ANTFLY_COUNT_LIMIT", "250000"))
    for line in sys.stdin:
        if not line.strip():
            continue
        command, query = parse_command(line)
        limit = command_to_limit(command)
        if limit is None:
            print("UNSUPPORTED", flush=True)
            continue
        if command == "COUNT" or command.endswith("_COUNT"):
            resp = client.search(query, max(limit, count_limit))
            print(extract_total(resp), flush=True)
        else:
            resp = client.search(query, max(limit, 1))
            print(1, flush=True)


def self_test() -> int:
    cases = {
        "COUNT hello world": ("COUNT", "hello world", 0),
        "TOP_10\tvector search": ("TOP_10", "vector search", 10),
        "TOP_100 something": ("TOP_100", "something", 100),
        "TOP_100_COUNT something": ("TOP_100_COUNT", "something", 100),
    }
    for line, expected in cases.items():
        command, query = parse_command(line)
        got = (command, query, command_to_limit(command))
        if got != expected:
            print(json.dumps({"status": "failed", "case": line, "got": got, "expected": expected}))
            return 1
    translations = {
        "hello": "text:(hello)",
        "text:(hello)": "text:(hello)",
        "+griffith +observatory": "text:(+griffith +observatory)",
        '"griffith observatory"': 'text:("griffith observatory")',
    }
    for raw, expected in translations.items():
        got = field_qualify_query(raw, "text")
        if got != expected:
            print(json.dumps({"status": "failed", "case": raw, "got": got, "expected": expected}))
            return 1
    structured = {
        "hello": {"match": {"field": "text", "text": "hello"}},
        "+griffith +observatory": {"match": {"field": "text", "text": "griffith observatory"}},
        '"griffith observatory"': {"match_phrase": {"field": "text", "text": "griffith observatory"}},
    }
    for raw, expected in structured.items():
        got = translate_query(raw, "text")
        if got != expected:
            print(json.dumps({"status": "failed", "case": raw, "got": got, "expected": expected}))
            return 1
    print(json.dumps({"status": "ok", "metric": "translated_commands", "value": len(cases), "unit": "commands"}))
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", nargs="?", choices=["index", "serve"])
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)
    if args.self_test:
        return self_test()
    client = AntflyClient(env("ANTFLY_URL", "http://localhost:8080"), env("ANTFLY_TABLE", "sbg_wikipedia"))
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
