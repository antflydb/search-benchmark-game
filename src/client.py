import subprocess
import os
from os import path
import time
import json
import random
import statistics
from collections import defaultdict

COMMANDS = os.environ['COMMANDS'].split(' ')

class SearchClient:

    def __init__(self, engine):
        self.engine = engine
        dirname = os.path.split(os.path.abspath(__file__))[0]
        dirname = path.dirname(dirname)
        dirname = path.join(dirname, "engines")
        cwd = path.join(dirname, engine)
        print(cwd)
        self.process = subprocess.Popen(["make", "--no-print-directory", "serve"],
            cwd=cwd,
            stdout=subprocess.PIPE,
            stdin=subprocess.PIPE)

    def query(self, query, command):
        query_line = "%s\t%s\n" % (command, query)
        self.process.stdin.write(query_line.encode("utf-8"))
        self.process.stdin.flush()
        recv = self.process.stdout.readline().strip()
        if recv == b"UNSUPPORTED":
            return None
        cnt = int(recv)
        return cnt

    def query_json(self, query, command):
        query_line = "%s\t%s\n" % (command, query)
        self.process.stdin.write(query_line.encode("utf-8"))
        self.process.stdin.flush()
        recv = self.process.stdout.readline().strip()
        if recv == b"UNSUPPORTED":
            return None
        return json.loads(recv)

    def close(self):
        self.process.stdin.close()
        self.process.stdout.close()

def drive(queries, client, command):
    for query in queries:
        start = time.monotonic()
        count = client.query(query.query, command)
        stop = time.monotonic()
        duration = int((stop - start) * 1e6)
        yield (query, count, duration)

class Query(object):
    def __init__(self, query, tags):
        self.query = query
        self.tags = tags

def read_queries(query_path):
    selected_tags = set(os.environ.get("QUERY_TAGS", "").replace(",", " ").split())
    for q in open(query_path):
        c = json.loads(q)
        tags = c["tags"]
        if selected_tags and not selected_tags.intersection(tags):
            continue
        yield Query(c["query"], tags)


def validate_results(queries, engines, limit=10):
    command = "VALIDATE_TOP_%d" % limit
    results = {}
    for engine in engines:
        client = SearchClient(engine)
        engine_results = {}
        try:
            for query in queries:
                payload = client.query_json(query.query, command)
                if payload is None:
                    raise RuntimeError("%s does not support %s" % (engine, command))
                ids = payload.get("ids") if isinstance(payload, dict) else None
                count = payload.get("count") if isinstance(payload, dict) else None
                if not isinstance(ids, list) or len(ids) != len(set(ids)) or not isinstance(count, int):
                    raise RuntimeError("invalid validation result from %s for %r" % (engine, query.query))
                engine_results[query.query] = {
                    "ids": [str(doc_id) for doc_id in ids],
                    "count": count,
                }
        finally:
            client.close()
        results[engine] = engine_results

    reference = engines[0]
    comparisons = {}
    for engine in engines[1:]:
        overlaps = []
        by_tag = defaultdict(list)
        count_matches_by_tag = defaultdict(list)
        count_ratios_by_tag = defaultdict(list)
        exact = 0
        exact_counts = 0
        mismatch_examples = []
        for query in queries:
            expected_result = results[reference][query.query]
            actual_result = results[engine][query.query]
            expected = expected_result["ids"]
            actual = actual_result["ids"]
            if expected == actual:
                exact += 1
            if expected_result["count"] == actual_result["count"]:
                exact_counts += 1
                count_matches = 1.0
            else:
                count_matches = 0.0
                if len(mismatch_examples) < 10:
                    mismatch_examples.append({
                        "query": query.query,
                        "tags": query.tags,
                        "reference_count": expected_result["count"],
                        "engine_count": actual_result["count"],
                    })
            denominator = max(1, min(limit, len(expected), len(actual)))
            overlap = len(set(expected) & set(actual)) / denominator
            overlaps.append(overlap)
            for tag in query.tags:
                by_tag[tag].append(overlap)
                count_matches_by_tag[tag].append(count_matches)
                if expected_result["count"] > 0:
                    count_ratios_by_tag[tag].append(actual_result["count"] / expected_result["count"])
        comparisons[engine] = {
            "reference": reference,
            "queries": len(queries),
            "exact_rankings": exact,
            "exact_match_counts": exact_counts,
            "count_mismatch_examples": mismatch_examples,
            "mean_overlap_at_%d" % limit: statistics.fmean(overlaps),
            "median_overlap_at_%d" % limit: statistics.median(overlaps),
            "by_primary_tag": {
                tag: {
                    "mean_overlap_at_%d" % limit: statistics.fmean(values),
                    "exact_match_count_rate": statistics.fmean(count_matches_by_tag[tag]),
                    "median_engine_to_reference_count_ratio": (
                        statistics.median(count_ratios_by_tag[tag])
                        if count_ratios_by_tag[tag]
                        else None
                    ),
                }
                for tag, values in sorted(by_tag.items())
                if tag in {"term", "intersection", "phrase", "union"}
            },
        }
    report = {"command": command, "engines": engines, "comparisons": comparisons}
    with open("validation.json", "w") as validation_file:
        json.dump(report, validation_file, indent=2, sort_keys=True)
    print("VALIDATION " + json.dumps(report, sort_keys=True))
    minimum_overlap = float(os.environ.get("MIN_VALIDATION_OVERLAP", "0.0"))
    for comparison in comparisons.values():
        if comparison["mean_overlap_at_%d" % limit] < minimum_overlap:
            raise RuntimeError("validation overlap below MIN_VALIDATION_OVERLAP")

# Print progress, borrowed from https://stackoverflow.com/questions/3173320/text-progress-bar-in-terminal-with-block-characters
def printProgressBar (progress, prefix = '', suffix = '', decimals = 1, length = 100, fill = '█', printEnd = "\r"):
    """
    Call in a loop to create terminal progress bar
    @params:
        progress    - Required  : current progress in [0,1] (Float)
        prefix      - Optional  : prefix string (Str)
        suffix      - Optional  : suffix string (Str)
        decimals    - Optional  : positive number of decimals in percent complete (Int)
        length      - Optional  : character length of bar (Int)
        fill        - Optional  : bar fill character (Str)
        printEnd    - Optional  : end character (e.g. "\r", "\r\n") (Str)
    """
    percent = ("{0:." + str(decimals) + "f}").format(100 * progress)
    filledLength = int(length * progress)
    bar = fill * filledLength + '-' * (length - filledLength)
    print(f'\r{prefix} |{bar}| {percent}% {suffix}', end = printEnd)
    # Print New Line on Complete
    if progress >= 1:
        print()

WARMUP_TIME = int(os.environ.get('WARMUP_TIME', '60'))
NUM_ITER = int(os.environ.get('NUM_ITER', '10'))

if __name__ == "__main__":
    import sys
    random.seed(2)
    query_path = sys.argv[1]
    engines = sys.argv[2:]
    queries = list(read_queries(query_path))

    if os.environ.get("VALIDATE_RESULTS", "1") != "0" and len(engines) > 1:
        validate_results(queries, engines, int(os.environ.get("VALIDATE_TOP_K", "10")))
        if os.environ.get("VALIDATE_ONLY", "0") == "1":
            raise SystemExit(0)

    details = {}
    for engine in engines:
      dirname = os.path.split(os.path.abspath(__file__))[0]
      dirname = path.dirname(dirname)
      dirname = path.join(dirname, "engines")
      details_file = path.join(dirname, engine, "details.json")
      if os.path.exists(details_file):
        with open(details_file, "r") as f:
          details[engine] = json.loads(f.read())
      else:
        details[engine] = []

    results = {}
    for command in COMMANDS:
        results_commands = {}
        for engine in engines:
            engine_results = []
            query_idx = {}
            for query in queries:
                query_result = {
                    "query": query.query,
                    "tags": query.tags,
                    "count": 0,
                    "duration": []
                }
                query_idx[query.query] = query_result
                engine_results.append(query_result)
            print("======================")
            print("BENCHMARKING %s %s" % (engine, command))
            search_client = SearchClient(engine)
            queries_shuffled = list(queries[:])
            random.seed(2)
            random.shuffle(queries_shuffled)
            warmup_start = time.monotonic()
            printProgressBar(0, prefix = 'Warmup:', suffix = 'Complete', length = 50)
            while True:
                for _ in drive(queries_shuffled, search_client, command):
                    pass
                progress = min(1, (time.monotonic() - warmup_start) / WARMUP_TIME)
                printProgressBar(progress, prefix = 'Warmup:', suffix = 'Complete', length = 50)
                if progress == 1:
                    break
            printProgressBar(0, prefix = 'Run:   ', suffix = 'Complete', length = 50)
            for i in range(NUM_ITER):
                for (query, count, duration) in drive(queries_shuffled, search_client, command):
                    if count is None:
                        query_idx[query.query] = {count: -1, duration: []}
                    else:
                        query_idx[query.query]["count"] = count
                        query_idx[query.query]["duration"].append(duration)
                printProgressBar(float(i + 1) / NUM_ITER, prefix = 'Run:   ', suffix = 'Complete', length = 50)
            for query in engine_results:
                query["duration"].sort()
            results_commands[engine] = engine_results
            search_client.close()
        print(results_commands.keys())
        results[command] = results_commands
    with open("results.json" , "w") as f:
        json.dump({ "details": details, "results": results }, f, default=lambda obj: obj.__dict__)
