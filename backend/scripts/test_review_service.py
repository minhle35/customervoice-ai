"""
Manual integration test for ReviewService against the real database.

Covers every method: upsert_review, mark_processed, get_unprocessed_reviews,
get_reviews, get_by_id. Cleans up all inserted rows at the end.

Run from backend/:
    uv run python scripts/test_review_service.py
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

# Must happen before any app.* imports
BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
for p in (str(BACKEND), str(ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

# fmt: off  — keep these below the sys.path block
from app.database.database import SessionLocal  # noqa: E402
from app.models.review import Platform, Review, SentimentLabel  # noqa: E402
from app.schemas.review_schema import ReviewCreate, ReviewUpdate  # noqa: E402
from app.services.review_service import ReviewService  # noqa: E402
# fmt: on


BUSINESS_ID = "test-bien-vinh-hao-2"

SAMPLE_REVIEWS = [
    ReviewCreate(
        platform=Platform.google,
        platform_id="test-review-001",
        business_id=BUSINESS_ID,
        business_name="Nha hang Bien Vinh Hao 2",
        author="Alice",
        rating=5.0,
        content="Quan an sat bien tren QL1, view rat dep, gia mon an binh dan",
    ),
    ReviewCreate(
        platform=Platform.google,
        platform_id="test-review-002",
        business_id=BUSINESS_ID,
        business_name="Nha hang Bien Vinh Hao 2",
        author="Bob",
        rating=4.0,
        content="View dep nhung mon an hoi mac, ko ngon lam",
    ),
    ReviewCreate(
        platform=Platform.google,
        platform_id="test-review-003",
        business_id=BUSINESS_ID,
        business_name="Nha hang Bien Vinh Hao 2",
        author="Charlie",
        rating=4.0,
        content="Food is expensive but very fresh",
    ),
]


def ok(label):
    print(f"  PASS  {label}")


def fail(label, detail):
    print(f"  FAIL  {label}: {detail}")


def cleanup(db, ids):
    db.query(Review).filter(Review.id.in_(ids)).delete(synchronize_session=False)
    db.commit()
    print(f"\nCleaned up {len(ids)} test row(s).")


def main():
    print("=" * 60)
    print("ReviewService integration test")
    print("=" * 60)

    inserted_ids = []

    with SessionLocal() as db:
        svc = ReviewService(db)

        # 1. upsert_review — insert
        print("\n[1] upsert_review — insert")
        reviews = []
        for data in SAMPLE_REVIEWS:
            r = svc.upsert_review(data)
            inserted_ids.append(r.id)
            reviews.append(r)
            ok(f"inserted: {r.author} | id={r.id}")

        # 2. upsert_review — deduplication
        print("\n[2] upsert_review — deduplication")
        duplicate = svc.upsert_review(SAMPLE_REVIEWS[0])
        if duplicate.id == reviews[0].id:
            ok("duplicate returned same row (no new insert)")
        else:
            fail("deduplication", f"expected {reviews[0].id}, got {duplicate.id}")

        # 3. get_unprocessed_reviews
        print("\n[3] get_unprocessed_reviews")
        unprocessed = svc.get_unprocessed_reviews(limit=100)
        test_unprocessed = [r for r in unprocessed if r.business_id == BUSINESS_ID]
        if len(test_unprocessed) == 3:
            ok(f"returned {len(test_unprocessed)} unprocessed reviews")
        else:
            fail("get_unprocessed_reviews", f"expected 3, got {len(test_unprocessed)}")

        # 4. mark_processed
        print("\n[4] mark_processed")
        update = ReviewUpdate(
            sentiment_score=0.85,
            sentiment_label=SentimentLabel.positive,
            topics=["seafood", "ocean view", "value for money"],
            is_processed=True,
        )
        updated = svc.mark_processed(reviews[0].id, update)
        if (
            updated.sentiment_score == 0.85
            and updated.sentiment_label == SentimentLabel.positive
            and updated.topics == ["seafood", "ocean view", "value for money"]
            and updated.is_processed is True
        ):
            ok("sentiment, topics, is_processed written correctly")
        else:
            fail("mark_processed", f"unexpected values: {updated}")

        # 5. get_reviews — filter by business_id
        print("\n[5] get_reviews — filter by business_id")
        total, items = svc.get_reviews(business_id=BUSINESS_ID, limit=10)
        if total == 3 and len(items) == 3:
            ok(f"total={total}, items={len(items)}")
        else:
            fail("get_reviews business_id filter", f"total={total}, items={len(items)}")

        # 6. get_reviews — filter by is_processed
        print("\n[6] get_reviews — filter by is_processed")
        total_done, _ = svc.get_reviews(business_id=BUSINESS_ID, is_processed=True)
        total_pending, _ = svc.get_reviews(business_id=BUSINESS_ID, is_processed=False)
        if total_done == 1 and total_pending == 2:
            ok(f"processed={total_done}, unprocessed={total_pending}")
        else:
            fail(
                "is_processed filter",
                f"processed={total_done}, unprocessed={total_pending}",
            )

        # 7. get_by_id — found
        print("\n[7] get_by_id")
        found = svc.get_by_id(reviews[1].id)
        if found and found.author == "Bob":
            ok(f"found review: author={found.author}")
        else:
            fail("get_by_id", f"expected Bob, got {found}")

        # 7b. get_by_id — not found
        missing = svc.get_by_id(uuid.uuid4())
        if missing is None:
            ok("returns None for unknown id")
        else:
            fail("get_by_id missing", "expected None")

        # 8. mark_processed — invalid id raises ValueError
        print("\n[8] mark_processed — invalid id")
        try:
            svc.mark_processed(
                uuid.uuid4(),
                ReviewUpdate(
                    is_processed=True,
                    sentiment_score=0.5,
                    sentiment_label=SentimentLabel.neutral,
                    topics=[],
                ),
            )
            fail("mark_processed invalid id", "expected ValueError, got none")
        except ValueError:
            ok("ValueError raised for unknown review_id")

        # Cleanup
        cleanup(db, inserted_ids)

    print("\n" + "=" * 60)
    print("All tests complete.")
    print("=" * 60)


if __name__ == "__main__":
    main()
