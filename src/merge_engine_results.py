#!/usr/bin/env python3
"""Merge a single-engine incremental run into an existing schema-v2 result."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("base", type=Path)
    parser.add_argument("incremental", type=Path)
    parser.add_argument("--validation", type=Path)
    parser.add_argument("--validation-output", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    base = read(args.base)
    incremental = read(args.incremental)
    if base.get("schema_version") != 2 or incremental.get("schema_version") != 2:
        raise SystemExit("both inputs must use schema version 2")
    engines = list(incremental.get("details", {}))
    if len(engines) != 1:
        raise SystemExit(f"incremental result must contain exactly one engine, got {engines}")
    engine = engines[0]
    base["details"][engine] = incremental["details"][engine]
    base["capabilities"][engine] = incremental["capabilities"][engine]
    for command, concurrency_rows in incremental["results"].items():
        for concurrency, engine_rows in concurrency_rows.items():
            base["results"][command][concurrency][engine] = engine_rows[engine]

    if args.validation:
        validation = read(args.validation)
        if engine not in validation.get("comparisons", {}):
            raise SystemExit(f"validation does not contain comparison for {engine}")
        current = base["validation"]
        if engine not in current["engines"]:
            current["engines"].append(engine)
        current["comparisons"][engine] = validation["comparisons"][engine]
        if args.validation_output:
            args.validation_output.write_text(
                json.dumps(current, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )

    incremental_wall = incremental.get("metadata", {}).get("driver_wall_seconds")
    if incremental_wall is not None:
        base["metadata"].setdefault("incremental_runs", {})[engine] = {
            "driver_wall_seconds": incremental_wall
        }
    output = args.output or args.base
    output.write_text(json.dumps(base, separators=(",", ":")) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
