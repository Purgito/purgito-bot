#!/usr/bin/env python3
"""Microbenchmark sintético de enqueue; no conecta a una DB ni guarda actividad."""

import argparse
import json
from pathlib import Path
import platform
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from studio.model import Settings  # noqa: E402
from studio.runtime import Collector  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", type=int, default=20_000)
    args = parser.parse_args()
    if not 1 <= args.events <= 1_000_000:
        parser.error("events debe estar entre 1 y 1000000")
    collector = Collector(
        None, Settings(enabled=True, key="synthetic-benchmark-key-not-a-real-secret")
    )
    start = time.perf_counter_ns()
    for i in range(args.events):
        collector.record(1 + i % 126, "chat", source="mention", duration_ms=50)
    elapsed = time.perf_counter_ns() - start
    print(
        json.dumps(
            {
                "synthetic": True,
                "database_io": False,
                "python": platform.python_version(),
                "events": args.events,
                "microseconds_per_event_including_loop": round(
                    elapsed / args.events / 1000, 3
                ),
                "pending_aggregate_keys": len(collector.usage),
                "dropped": collector.dropped,
                "measures": "Solo record() y el bucle: no mide envío a Discord ni latencia de flush SQL.",
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
