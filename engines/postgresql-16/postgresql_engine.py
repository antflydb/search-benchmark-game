#!/usr/bin/env python3
"""Search Benchmark Game adapter for PostgreSQL full-text search."""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

import psycopg


class Client:
    def __init__(self, dsn: str) -> None:
        self.connection = psycopg.connect(dsn, autocommit=True)

    def create_index(self) -> None:
        with self.connection.cursor() as cursor:
            cursor.execute("DROP TABLE IF EXISTS sbg_documents")
            cursor.execute(
                """CREATE TABLE sbg_documents (
                    id text PRIMARY KEY,
                    text text NOT NULL,
                    search tsvector GENERATED ALWAYS AS (to_tsvector('english', text)) STORED
                )"""
            )

    def load(self, rows: list[tuple[str, str]]) -> None:
        with self.connection.cursor() as cursor:
            with cursor.copy("COPY sbg_documents (id, text) FROM STDIN") as copy:
                for row in rows:
                    copy.write_row(row)

    def finish(self) -> None:
        with self.connection.cursor() as cursor:
            cursor.execute("CREATE INDEX sbg_documents_search_idx ON sbg_documents USING GIN (search)")
            cursor.execute("ANALYZE sbg_documents")

    def search(self, raw: str, limit: int, count: bool = False) -> tuple[list[str], int | None]:
        expression, params = query_expression(raw)
        if count:
            sql = f"WITH q AS (SELECT {expression} AS query) SELECT count(*) FROM sbg_documents, q WHERE search @@ q.query"
            with self.connection.cursor() as cursor:
                cursor.execute(sql, params)
                return [], int(cursor.fetchone()[0])
        sql = f"""WITH q AS (SELECT {expression} AS query)
            SELECT id FROM sbg_documents, q
            WHERE search @@ q.query
            ORDER BY ts_rank_cd(search, q.query) DESC, id
            LIMIT %s"""
        with self.connection.cursor() as cursor:
            cursor.execute(sql, [*params, limit])
            ids = [str(row[0]) for row in cursor.fetchall()]
        return ids, None


def query_expression(raw: str) -> tuple[str, list[str]]:
    query = raw.strip()
    if len(query) >= 2 and query.startswith('"') and query.endswith('"'):
        return "phraseto_tsquery('english', %s)", [query[1:-1]]
    terms = query.split()
    operator = " && " if all(term.startswith("+") for term in terms) else " || "
    expression = operator.join("plainto_tsquery('english', %s)" for _ in terms)
    return expression, [term.removeprefix("+") for term in terms]


def index_stdin(client: Client) -> dict[str, Any]:
    client.create_index()
    rows = []
    for position, line in enumerate(sys.stdin):
        if not line.strip():
            continue
        doc = json.loads(line)
        rows.append((str(doc.get("id") or position), str(doc.get("text") or "")))
    client.load(rows)
    client.finish()
    return {"status": "ok", "indexed_documents": len(rows), "load_method": "COPY"}


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
        ids, _ = client.search(query, limit)
        if validate:
            _, count = client.search(query, limit, count=True)
            print(json.dumps({"ids": ids, "count": count}, separators=(",", ":")), flush=True)
        elif command.endswith("_COUNT"):
            _, count = client.search(query, limit, count=True)
            print(count, flush=True)
        else:
            print(1, flush=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", nargs="?", choices=["index", "serve"])
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        assert query_expression("foo bar")[0].count(" || ") == 1
        assert query_expression("+foo +bar")[0].count(" && ") == 1
        assert query_expression('"foo bar"')[0].startswith("phraseto_tsquery")
        print(json.dumps({"status": "ok", "translated_queries": 3}))
        return 0
    client = Client(os.environ.get("POSTGRES_DSN", "postgresql://postgres:postgres@127.0.0.1:29202/postgres"))
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
