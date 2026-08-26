"""
Backfill GraphRAG entity/relationship extraction for reviews ingested before
GraphRAG existed.

extract_unprocessed_graph_entities() (pipelines/orchestration/pipeline_runner.py)
processes one bounded batch (graph_extracted=False, is_processed=True) and stops
early on a rate limit. This script just calls it repeatedly until every pending
review is caught up, or a rate limit is hit — in which case it prints a message
so the same LLM free-tier budget already documented for sentiment analysis
(pipelines/orchestration/pipeline_runner.py's 3s/review sleep) doesn't need a
second explanation here.

Usage:
    cd backend
    uv run python scripts/backfill_graph_extraction.py
    uv run python scripts/backfill_graph_extraction.py --batch-size 50
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
_ROOT = _BACKEND.parent
for _p in (str(_BACKEND), str(_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from dotenv import load_dotenv

load_dotenv(_ROOT / ".env", override=False)

from app.database.database import init_db

from pipelines.orchestration.pipeline_runner import (
    extract_unprocessed_graph_entities,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="Reviews to extract per batch (default: 100)",
    )
    args = parser.parse_args()

    init_db()

    total_processed = 0
    total_triples = 0

    while True:
        result = extract_unprocessed_graph_entities(limit=args.batch_size)
        total_processed += result["processed"]
        total_triples += result["triples_stored"]

        print(
            f"Batch: {result['processed']}/{result['total']} extracted, "
            f"{result['triples_stored']} triples stored, "
            f"{result['rate_limited']} rate-limited"
        )

        if result["rate_limited"] > 0:
            print(
                f"\nRate limited after {total_processed} review(s) "
                f"({total_triples} triples stored). Re-run this script later "
                "to continue from where it left off."
            )
            return

        if result["total"] == 0:
            break

    print(
        f"\nDone. {total_processed} review(s) extracted, {total_triples} triples stored."
    )


if __name__ == "__main__":
    main()
