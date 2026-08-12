#!/usr/bin/env python3
"""Capability-aware database driver for Search Benchmark Game."""

from __future__ import annotations

import json
import os
import random
import statistics
import subprocess
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from queue import Queue
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
ENGINES_DIR = ROOT / "engines"
RESULTS_PATH = Path(os.environ.get("RESULTS_PATH", ROOT / "results.json"))
VALIDATION_PATH = Path(os.environ.get("VALIDATION_PATH", ROOT / "validation.json"))
COMMANDS = os.environ.get("COMMANDS", "TOP_10 TOP_100").split()
PRIMARY_TAGS = ("term", "union", "intersection", "phrase")
WARMUP_TIME = float(os.environ.get("WARMUP_TIME", "5"))
NUM_ITER = int(os.environ.get("NUM_ITER", "2"))
CONCURRENCY_LEVELS = [
    int(value) for value in os.environ.get("CONCURRENCY_LEVELS", "1,8").replace(" ", ",").split(",") if value
]


class SearchClient:
    def __init__(self, engine: str) -> None:
        self.engine = engine
        self.process = subprocess.Popen(
            ["make", "--no-print-directory", "serve"],
            cwd=ENGINES_DIR / engine,
            stdout=subprocess.PIPE,
            stdin=subprocess.PIPE,
            stderr=None,
        )

    def _request(self, query: str, command: str) -> bytes:
        assert self.process.stdin is not None
        assert self.process.stdout is not None
        self.process.stdin.write(f"{command}\t{query}\n".encode())
        self.process.stdin.flush()
        response = self.process.stdout.readline().strip()
        if not response and self.process.poll() is not None:
            raise RuntimeError(f"{self.engine} adapter exited with {self.process.returncode}")
        return response

    def query(self, query: str, command: str) -> int | None:
        response = self._request(query, command)
        if response == b"UNSUPPORTED":
            return None
        return int(response)

    def query_json(self, query: str, command: str) -> dict[str, Any] | None:
        response = self._request(query, command)
        if response == b"UNSUPPORTED":
            return None
        payload = json.loads(response)
        if not isinstance(payload, dict):
            raise RuntimeError(f"invalid JSON response from {self.engine}")
        return payload

    def close(self) -> None:
        if self.process.stdin:
            self.process.stdin.close()
        if self.process.stdout:
            self.process.stdout.close()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            self.process.wait(timeout=5)


class Query:
    def __init__(self, query: str, tags: list[str]) -> None:
        self.query = query
        self.tags = tags
        matches = [tag for tag in PRIMARY_TAGS if tag in tags]
        if len(matches) != 1:
            raise ValueError(f"query must have one primary tag: {query!r} {tags!r}")
        self.primary_tag = matches[0]


def read_queries(query_path: str) -> list[Query]:
    selected = set(os.environ.get("QUERY_TAGS", "").replace(",", " ").split())
    queries = []
    with open(query_path, encoding="utf-8") as source:
        for line in source:
            payload = json.loads(line)
            tags = payload["tags"]
            if selected and not selected.intersection(tags):
                continue
            queries.append(Query(payload["query"], tags))
    return queries


def load_capabilities(engine: str) -> dict[str, dict[str, Any]]:
    path = ENGINES_DIR / engine / "capabilities.json"
    if not path.exists():
        return {tag: {"supported": True} for tag in PRIMARY_TAGS}
    payload = json.loads(path.read_text(encoding="utf-8"))
    classes = payload.get("query_classes", {})
    return {
        tag: classes.get(tag, {"supported": False, "reason": "not declared by adapter"})
        for tag in PRIMARY_TAGS
    }


def supported_queries(queries: list[Query], capabilities: dict[str, dict[str, Any]]) -> list[Query]:
    return [query for query in queries if capabilities[query.primary_tag].get("supported")]


def validate_results(queries: list[Query], engines: list[str], capabilities: dict[str, Any], limit: int) -> dict[str, Any]:
    command = f"VALIDATE_TOP_{limit}"
    raw: dict[str, dict[str, Any]] = {}
    for engine in engines:
        selected = supported_queries(queries, capabilities[engine])
        if not selected:
            raw[engine] = {}
            continue
        client = SearchClient(engine)
        engine_results: dict[str, Any] = {}
        try:
            for query in selected:
                payload = client.query_json(query.query, command)
                if payload is None:
                    raise RuntimeError(f"{engine} advertises {query.primary_tag} but lacks {command}")
                ids = payload.get("ids")
                count = payload.get("count")
                if not isinstance(ids, list) or len(ids) != len(set(ids)):
                    raise RuntimeError(f"invalid validation IDs from {engine} for {query.query!r}")
                if count is not None and not isinstance(count, int):
                    raise RuntimeError(f"invalid validation count from {engine} for {query.query!r}")
                engine_results[query.query] = {"ids": [str(value) for value in ids], "count": count}
        finally:
            client.close()
            stop_engine(engine)
        raw[engine] = engine_results

    reference = engines[0]
    comparisons: dict[str, Any] = {}
    for engine in engines[1:]:
        by_class: dict[str, list[float]] = defaultdict(list)
        exact_counts = 0
        comparable_counts = 0
        for query in queries:
            if query.query not in raw[reference] or query.query not in raw[engine]:
                continue
            expected = raw[reference][query.query]
            actual = raw[engine][query.query]
            denominator = max(1, min(limit, len(expected["ids"]), len(actual["ids"])))
            overlap = len(set(expected["ids"]) & set(actual["ids"])) / denominator
            by_class[query.primary_tag].append(overlap)
            if expected["count"] is not None and actual["count"] is not None:
                comparable_counts += 1
                exact_counts += int(expected["count"] == actual["count"])
        comparisons[engine] = {
            "reference": reference,
            "classes": {
                tag: {
                    "queries": len(values),
                    "mean_overlap_at_%d" % limit: statistics.fmean(values) if values else None,
                    "median_overlap_at_%d" % limit: statistics.median(values) if values else None,
                }
                for tag, values in by_class.items()
            },
            "comparable_exact_counts": comparable_counts,
            "exact_match_counts": exact_counts,
        }
    report = {"command": command, "engines": engines, "comparisons": comparisons}
    VALIDATION_PATH.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def run_concurrent_batch(clients: list[SearchClient], queries: list[Query], command: str) -> tuple[list[tuple[Query, int, int]], float]:
    available: Queue[SearchClient] = Queue()
    for client in clients:
        available.put(client)

    def execute(query: Query) -> tuple[Query, int, int]:
        client = available.get()
        try:
            started = time.perf_counter_ns()
            count = client.query(query.query, command)
            elapsed_us = (time.perf_counter_ns() - started) // 1000
            if count is None:
                raise RuntimeError(f"{client.engine} returned UNSUPPORTED for advertised {query.primary_tag}")
            return query, count, int(elapsed_us)
        finally:
            available.put(client)

    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=len(clients)) as executor:
        futures = [executor.submit(execute, query) for query in queries]
        rows = [future.result() for future in as_completed(futures)]
    return rows, time.monotonic() - started


def benchmark_cell(engine: str, queries: list[Query], command: str, concurrency: int) -> dict[str, Any]:
    clients = [SearchClient(engine) for _ in range(concurrency)]
    shuffled = list(queries)
    random.Random(2).shuffle(shuffled)
    try:
        warmup_started = time.monotonic()
        while time.monotonic() - warmup_started < WARMUP_TIME:
            run_concurrent_batch(clients, shuffled, command)

        query_rows = {
            query.query: {"query": query.query, "tags": query.tags, "count": 0, "duration": []}
            for query in queries
        }
        elapsed = 0.0
        for iteration in range(NUM_ITER):
            iteration_queries = list(shuffled)
            random.Random(2 + iteration).shuffle(iteration_queries)
            rows, iteration_elapsed = run_concurrent_batch(clients, iteration_queries, command)
            elapsed += iteration_elapsed
            for query, count, duration in rows:
                query_rows[query.query]["count"] = count
                query_rows[query.query]["duration"].append(duration)
        samples = len(queries) * NUM_ITER
        return {
            "status": "measured",
            "queries": list(query_rows.values()),
            "samples": samples,
            "elapsed_seconds": elapsed,
            "qps": samples / elapsed if elapsed else None,
        }
    finally:
        for client in clients:
            client.close()


def stop_engine(engine: str) -> None:
    subprocess.run(
        ["make", "--no-print-directory", "stop"],
        cwd=ENGINES_DIR / engine,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        raise SystemExit("usage: client.py QUERY_FILE ENGINE...")
    run_started = time.monotonic()
    random.seed(2)
    queries = read_queries(argv[0])
    engines = argv[1:]
    capabilities = {engine: load_capabilities(engine) for engine in engines}
    details = {}
    for engine in engines:
        path = ENGINES_DIR / engine / "details.json"
        details[engine] = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []

    validation = None
    if os.environ.get("VALIDATE_RESULTS", "1") != "0" and len(engines) > 1:
        validation = validate_results(
            queries, engines, capabilities, int(os.environ.get("VALIDATE_TOP_K", "10"))
        )
        if os.environ.get("VALIDATE_ONLY", "0") == "1":
            print("VALIDATION " + json.dumps(validation, sort_keys=True))
            return 0

    results: dict[str, Any] = {
        command: {str(concurrency): {} for concurrency in CONCURRENCY_LEVELS}
        for command in COMMANDS
    }
    for engine in engines:
        try:
            for command in COMMANDS:
                for concurrency in CONCURRENCY_LEVELS:
                    classes: dict[str, Any] = {}
                    for tag in PRIMARY_TAGS:
                        capability = capabilities[engine][tag]
                        class_queries = [query for query in queries if query.primary_tag == tag]
                        if not capability.get("supported"):
                            classes[tag] = {
                                "status": "unsupported",
                                "reason": capability.get("reason", "unsupported by database"),
                                "queries": len(class_queries),
                            }
                            continue
                        print(f"BENCHMARKING {engine} {command} C{concurrency} {tag}", flush=True)
                        try:
                            classes[tag] = benchmark_cell(engine, class_queries, command, concurrency)
                        except Exception as exc:
                            classes[tag] = {
                                "status": "failed",
                                "reason": f"{type(exc).__name__}: {exc}",
                                "queries": len(class_queries),
                            }
                    results[command][str(concurrency)][engine] = {"classes": classes}
        finally:
            stop_engine(engine)

    payload = {
        "schema_version": 2,
        "metadata": {
            "query_count": len(queries),
            "warmup_seconds": WARMUP_TIME,
            "iterations": NUM_ITER,
            "concurrency_levels": CONCURRENCY_LEVELS,
            "query_classes": list(PRIMARY_TAGS),
            "driver_wall_seconds": time.monotonic() - run_started,
        },
        "details": details,
        "capabilities": capabilities,
        "validation": validation,
        "results": results,
    }
    RESULTS_PATH.write_text(json.dumps(payload, separators=(",", ":")) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
