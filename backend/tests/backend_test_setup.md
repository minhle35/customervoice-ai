# Backend Test Plan — CustomerVoice AI

## Overview

This document defines the testing strategy for the backend. Tests are organised into four layers, each is described with a clear scope, tooling choice, and execution context.

```
┌─────────────────────────────────────────┐
│          E2E Tests (real stack)         │  ← slowest, highest confidence
├─────────────────────────────────────────┤
│     Integration Tests (real DB/API)     │
├─────────────────────────────────────────┤
│   API Tests (TestClient, mocked deps)   │
├─────────────────────────────────────────┤
│      Unit Tests (pure functions)        │  ← fastest, lowest cost
└─────────────────────────────────────────┘
```

---

## Tooling

| Tool | Purpose |
|------|---------|
| `pytest` | Test runner for all layers |
| `pytest-asyncio` | Async test support |
| `httpx` / `fastapi.testclient.TestClient` | API layer testing |
| `respx` | Mock HTTP calls at the transport level (SerpAPI, OpenRouter) |
| `unittest.mock` / `pytest-mock` | Mocking internal dependencies |
| `pytest-cov` | Coverage reporting |
| `factory_boy` | Test data factories for models |
| `docker compose` | Spin up real DB + Redis for integration/E2E |

Install dev extras:
```bash
uv add --dev pytest pytest-asyncio httpx pytest-mock pytest-cov factory-boy respx
```

---

## Directory Structure

```
backend/tests/
├── conftest.py                          # shared fixtures (DB session, app client)
│
├── unit/
│   ├── test_google_reviews_ingestion.py # _stable_id, _parse_datetime, _parse_reviews_from_page,
│   │                                    # fetch_google_reviews (pagination, max_reviews, Z suffix)
│   ├── test_platform_handlers.py        # GoogleHandler.derive_business_id, registry.get_handler
│   ├── test_clean_reviews.py            # text cleaning pipeline
│   ├── test_sentiment_analysis.py       # LLM wrapper (mocked)
│   ├── test_generate_embeddings.py      # embedding wrapper (mocked)
│   └── test_review_schemas.py           # Pydantic schema validation
│
├── integration/
│   ├── test_review_service.py           # ReviewService against real test DB
│   ├── test_embedding_service.py        # EmbeddingService against real test DB
│   └── test_pipeline_runner.py          # ingest() + process_unprocessed() (external APIs mocked)
│
├── api/
│   ├── test_routes_reviews.py           # GET /api/reviews, GET /api/reviews/{id}, GET /api/reviews/businesses
│   ├── test_routes_integrations.py      # POST /api/integrations/{platform}, GET /tasks/{id}, POST /reprocess
│   └── test_routes_health.py            # GET /health
│
└── e2e/
    └── test_full_pipeline.py            # POST → Celery → SerpAPI (respx mock) → DB → GET reviews
```

---

## Layer 1 — Unit Tests

**Scope:** Pure functions and classes with all I/O mocked. No DB, no network.

**Run with:** `uv run pytest tests/unit/ -v`

---

### 1.1 Google Reviews Ingestion (`pipelines/ingestion/google_reviews_ingestion.py`)

File: `tests/unit/test_google_reviews_ingestion.py` ← already exists, gaps marked with ⚠️

```python
class TestStableId:
    def test_deterministic(self): ...
    def test_different_inputs_give_different_ids(self): ...
    def test_returns_32_char_hex(self): ...
    def test_handles_none_parts(self): ...


class TestParseDatetime:
    def test_none_returns_none(self): ...
    def test_unix_timestamp_int(self): ...
    def test_unix_timestamp_float(self): ...
    def test_iso_string_without_timezone(self): ...
    def test_invalid_string_returns_none(self): ...
    def test_unsupported_type_returns_none(self): ...

    # ⚠️ MISSING — Z suffix bug we fixed; must not regress
    def test_iso_string_with_z_suffix(self):
        # "2025-11-17T13:48:47Z" must parse correctly on Python 3.10
        dt = _parse_datetime("2025-11-17T13:48:47Z")
        assert dt == datetime(2025, 11, 17, 13, 48, 47, tzinfo=timezone.utc)

    # ⚠️ MISSING
    def test_iso_string_with_utc_offset(self):
        dt = _parse_datetime("2025-11-17T13:48:47+00:00")
        assert dt.tzinfo is not None


class TestParseReviewsFromPage:
    # ⚠️ MISSING — _parse_reviews_from_page is not tested directly

    def test_parses_iso_date_field(self):
        # SerpAPI primary date field
        payload = {"reviews": [{"review_id": "r1", "user": "Alice",
                                "snippet": "Good", "rating": 5,
                                "iso_date": "2025-01-15T10:00:00Z"}]}
        reviews = _parse_reviews_from_page(payload, "biz-1", "Café")
        assert reviews[0].published_at == datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc)

    def test_falls_back_to_iso_date_of_last_edit(self):
        # iso_date absent, iso_date_of_last_edit present
        payload = {"reviews": [{"review_id": "r1", "user": "Bob",
                                "snippet": "Nice", "rating": 4,
                                "iso_date_of_last_edit": "2025-03-01T00:00:00Z"}]}
        reviews = _parse_reviews_from_page(payload, "biz-1", None)
        assert reviews[0].published_at is not None

    def test_user_as_dict(self):
        # ⚠️ MISSING — SerpAPI returns user as {"name": ..., "reviews": ..., "photos": ...}
        payload = {"reviews": [{"review_id": "r1",
                                "user": {"name": "Alice", "reviews": 10, "photos": 2},
                                "snippet": "Great!", "rating": 5}]}
        reviews = _parse_reviews_from_page(payload, "biz-1", None)
        assert reviews[0].author == "Alice"

    def test_skips_empty_content(self): ...
    def test_stable_id_generated_when_review_id_missing(self): ...
    def test_none_rating_stored_as_none(self): ...


class TestFetchGoogleReviews:
    def test_raises_when_no_api_key(self): ...
    def test_returns_list_of_review_create(self): ...
    def test_maps_fields_correctly(self): ...
    def test_skips_empty_content(self): ...
    def test_http_error_propagates(self): ...
    def test_serpapi_called_with_correct_params(self): ...

    # ⚠️ MISSING — pagination is the core new feature
    def test_paginates_until_max_reviews_reached(self, mocker):
        # page 1 returns 10 reviews + next_page_token
        # page 2 returns 10 reviews + next_page_token
        # max_reviews=15 → stops mid-way, returns exactly 15
        ...

    def test_stops_when_no_next_page_token(self, mocker):
        # page 1 returns 5 reviews, no next_page_token
        # → returns 5 reviews, only 1 HTTP call made
        ...

    def test_max_reviews_cap_truncates_last_page(self, mocker):
        # page 1 returns 10 reviews, max_reviews=7 → returns exactly 7
        ...

    def test_place_name_not_sent_to_serpapi(self, mocker):
        # place_name is a DB-only field — must not appear in HTTP query params
        ...
```

---

### 1.2 Platform Handler & Registry (`app/integrations/`)

File: `tests/unit/test_platform_handlers.py` ← new file

```python
class TestGoogleHandlerDeriveBusinessId:
    def test_prefers_place_id_over_data_id(self):
        handler = GoogleHandler()
        bid = handler.derive_business_id({"place_id": "ChIJ123", "data_id": "0xabc"})
        assert bid == "ChIJ123"

    def test_falls_back_to_data_id_when_no_place_id(self):
        handler = GoogleHandler()
        bid = handler.derive_business_id({"data_id": "0xabc"})
        assert bid == "0xabc"

    def test_raises_when_both_missing(self):
        with pytest.raises(ValueError, match="place_id or data_id"):
            GoogleHandler().derive_business_id({})

    def test_raises_when_both_none(self):
        with pytest.raises(ValueError):
            GoogleHandler().derive_business_id({"place_id": None, "data_id": None})


class TestRegistry:
    def test_get_handler_google_returns_google_handler(self):
        assert isinstance(get_handler("google"), GoogleHandler)

    def test_get_handler_unsupported_raises_key_error(self):
        with pytest.raises(KeyError, match="tiktok"):
            get_handler("tiktok")

    def test_supported_platforms_contains_google(self):
        assert "google" in SUPPORTED_PLATFORMS
```

---

### 1.3 Text Cleaning (`pipelines/processing/clean_reviews.py`)

File: `tests/unit/test_clean_reviews.py`

```python
class TestCleanReviewText:
    def test_strips_html_tags(self):
        # "<p>Great food</p><br/>" → "Great food"

    def test_collapses_whitespace(self):
        # "good   food\n\nreally" → "good food really"

    def test_empty_string_returns_empty_result(self):
        # "" → CleanResult(cleaned_text="", language=None)

    def test_whitespace_only_returns_empty(self):
        # "   \n\t  " → cleaned_text == ""

    def test_preserves_unicode_letters(self):
        # Vietnamese: "Nhà hàng ngon" → survives cleaning intact
```

---

### 1.4 Sentiment Analysis (`pipelines/processing/sentiment_analysis.py`)

File: `tests/unit/test_sentiment_analysis.py`

All tests mock the LLM call — zero real API calls.

```python
class TestAnalyseSentimentAndTopics:
    def test_happy_path(self, mock_llm): ...
    def test_empty_text_skips_api_call(self, mock_llm): ...
    def test_unknown_sentiment_label_defaults_to_neutral(self, mock_llm): ...
    def test_rate_limit_error_propagates(self, mock_llm):
        # RateLimitError must not be swallowed
    def test_malformed_response_returns_defaults(self, mock_llm): ...
```

---

### 1.5 Pydantic Schema Validation (`app/schemas/review_schema.py`)

File: `tests/unit/test_review_schemas.py`

```python
class TestReviewCreate:
    def test_valid_review_passes(self): ...
    def test_empty_content_rejected(self): ...
    def test_platform_enum_invalid_value_rejected(self): ...

class TestIngestRequest:
    def test_valid_google_request(self): ...
    def test_missing_platform_rejected(self): ...
```

---

## Layer 2 — Integration Tests

**Scope:** Real PostgreSQL (test DB), no external HTTP. External APIs mocked.

**Setup:** Requires a running Postgres with pgvector. Use a dedicated `customer_voice_ai_test` DB.

```bash
# one-time setup
docker compose up db -d
psql -U postgres -c "CREATE DATABASE customer_voice_ai_test;"
DATABASE_URL=postgresql+psycopg2://postgres:postgres@localhost:5432/customer_voice_ai_test \
  uv run alembic upgrade head
```

**Run with:**
```bash
DATABASE_URL=postgresql+psycopg2://postgres:postgres@localhost:5432/customer_voice_ai_test \
  uv run pytest tests/integration/ -v
```

---

### Shared fixture (`conftest.py`)

```python
@pytest.fixture(scope="session")
def engine():
    return create_engine(os.environ["TEST_DATABASE_URL"])

@pytest.fixture()
def db(engine):
    """Each test gets a transaction rolled back on teardown — no cleanup needed."""
    with engine.connect() as conn:
        tx = conn.begin()
        session = Session(bind=conn)
        yield session
        tx.rollback()
        session.close()
```

---

### 2.1 ReviewService (`app/services/review_service.py`)

File: `tests/integration/test_review_service.py`

```python
class TestUpsertReview:
    def test_inserts_new_review(self, db): ...
    def test_deduplicates_on_platform_and_platform_id(self, db):
        # upsert twice with same platform+platform_id → only 1 row
    def test_updates_fields_on_conflict(self, db):
        # first: rating=3 / second: rating=5 → stored rating is 5

class TestMarkProcessed:
    def test_sets_is_processed_true(self, db): ...
    def test_stores_sentiment_score_label_and_topics(self, db): ...
    def test_raises_on_unknown_id(self, db): ...

class TestGetUnprocessedReviews:
    def test_returns_only_unprocessed(self, db):
        # insert 3 processed + 2 unprocessed → returns 2
    def test_respects_limit(self, db):
        # insert 10 unprocessed, limit=3 → returns 3
    def test_returns_empty_list_when_all_processed(self, db): ...

class TestGetReviews:
    def test_filters_by_business_id(self, db): ...
    def test_filters_by_platform(self, db): ...
    def test_filters_by_is_processed(self, db): ...
    def test_pagination_offset_and_limit(self, db): ...
    def test_total_count_unaffected_by_limit(self, db): ...
    def test_no_filters_returns_all(self, db): ...

class TestGetDistinctBusinesses:
    def test_returns_one_entry_per_business(self, db):
        # insert 3 reviews for biz-1, 2 for biz-2 → 2 business entries
    def test_returns_business_name(self, db): ...
    def test_returns_empty_when_no_reviews(self, db): ...
```

---

### 2.2 EmbeddingService (`app/services/embedding_service.py`)

File: `tests/integration/test_embedding_service.py`

```python
class TestUpsertEmbedding:
    def test_inserts_new_embedding(self, db):
        # stores 768-dim vector, review_id FK, model string
    def test_updates_on_conflict(self, db):
        # upsert twice same review_id → only 1 row, second vector wins
    def test_stores_correct_dimension(self, db):
        # len(stored.embedding) == 768
    def test_raises_on_invalid_review_id(self, db):
        # FK violation → exception
```

---

### 2.3 Pipeline Runner (`pipelines/orchestration/pipeline_runner.py`)

File: `tests/integration/test_pipeline_runner.py`

External APIs mocked; DB is real.

**Important:** `GoogleHandler.fetch_reviews` does a local import inside the method body,
so the correct mock target is the module where the function is *defined*, not where it is called from.

```python
@pytest.fixture
def mock_serpapi(mocker):
    return mocker.patch(
        "pipelines.ingestion.google_reviews_ingestion.fetch_google_reviews",  # ← correct path
        return_value=[ReviewCreate(platform="google", platform_id="r1",
                                  business_id="biz-1", content="Great!", ...)]
    )

@pytest.fixture
def mock_sentiment(mocker):
    return mocker.patch(
        "pipelines.orchestration.pipeline_runner.analyze_sentiment_and_topics",
        return_value=SentimentResult(score=0.8, label="positive", topics=["food"])
    )

@pytest.fixture
def mock_embedding(mocker):
    return mocker.patch(
        "pipelines.orchestration.pipeline_runner.generate_embedding",
        return_value=[0.0] * 768
    )


class TestIngest:
    def test_stores_review_in_db(self, db, mock_serpapi, mock_sentiment, mock_embedding):
        result = ingest("google", "biz-1", {})
        assert result["processed"] == 1
        # query DB: review exists, is_processed=True, embedding row exists

    def test_sets_is_processed_true_after_success(self, db, ...): ...

    def test_stores_embedding_with_correct_dimensions(self, db, ...):
        # query review_embeddings: len(embedding) == 768

    def test_deduplicates_same_platform_id(self, db, mock_serpapi, ...):
        # mock returns 2 reviews with same platform_id
        # → only 1 row in reviews table

    def test_skips_already_processed_review(self, db, ...):
        # run ingest twice → second run: skipped==1, processed==0

    def test_stops_on_rate_limit_cleanly(self, db, mock_serpapi, mocker):
        # mock_sentiment raises RateLimitError on second call
        # → first processed, rest left as is_processed=False
        # → result["rate_limited"] == 1

    def test_unsupported_platform_raises(self, db):
        with pytest.raises(KeyError):
            ingest("tiktok", "biz-1", {})


class TestProcessUnprocessed:
    def test_processes_all_unprocessed(self, db, mock_sentiment, mock_embedding):
        # seed 3 unprocessed reviews → result["processed"] == 3

    def test_respects_limit_param(self, db, ...):
        # seed 10 unprocessed, limit=3 → processed == 3

    def test_stops_cleanly_on_rate_limit(self, db, ...):
        # mock raises RateLimitError after first → processed==1, rate_limited==1
```

---

## Layer 3 — API Tests

**Scope:** FastAPI `TestClient` (in-process, no real network). DB overridden with the test transaction session.

**Run with:** `uv run pytest tests/api/ -v`

---

### Shared fixture

```python
@pytest.fixture()
def client(db):
    """Override get_db dependency to use the test transaction session."""
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
```

---

### 3.1 GET /api/reviews (`routes_reviews.py`)

File: `tests/api/test_routes_reviews.py`

```python
class TestListReviews:
    def test_returns_200_with_empty_list(self, client): ...
    def test_response_shape(self, client, seeded_reviews):
        # {"total": N, "items": [...]} each item has id, platform, content, published_at, ...
    def test_filter_by_business_id(self, client, seeded_reviews): ...
    def test_filter_by_platform(self, client, seeded_reviews): ...
    def test_filter_by_is_processed_true(self, client, seeded_reviews): ...
    def test_filter_by_is_processed_false(self, client, seeded_reviews): ...
    def test_pagination_limit_and_offset(self, client, seeded_reviews): ...

class TestGetReviewById:
    def test_returns_200_with_correct_review(self, client, seeded_reviews): ...
    def test_returns_404_for_unknown_id(self, client): ...
    def test_returns_422_for_invalid_uuid(self, client):
        assert client.get("/api/reviews/not-a-uuid").status_code == 422

class TestListBusinesses:
    def test_returns_distinct_businesses(self, client, seeded_reviews): ...
    def test_returns_empty_when_no_reviews(self, client): ...
    def test_includes_business_name(self, client, seeded_reviews): ...
```

---

### 3.2 POST /api/integrations/{platform} (`routes_integrations.py`)

File: `tests/api/test_routes_integrations.py`

```python
@pytest.fixture
def mock_celery(mocker):
    task = mocker.MagicMock()
    task.id = "test-task-id-123"
    return mocker.patch(
        "app.api.routes_integrations.ingest_platform.delay", return_value=task
    )


class TestTriggerIngestion:
    def test_valid_google_request_returns_queued_and_task_id(self, client, mock_celery):
        resp = client.post("/api/integrations/google", json={
            "platform": "google", "business_id": "biz-1",
            "params": {"data_id": "0x123"}
        })
        assert resp.status_code == 200
        assert resp.json() == {"status": "queued", "task_id": "test-task-id-123"}

    def test_unsupported_platform_returns_422(self, client):
        resp = client.post("/api/integrations/tiktok", json={
            "platform": "tiktok", "params": {}
        })
        assert resp.status_code == 422

    def test_missing_data_id_and_place_id_returns_422(self, client, mock_celery):
        resp = client.post("/api/integrations/google", json={
            "platform": "google", "params": {}
        })
        assert resp.status_code == 422

    def test_celery_called_with_correct_args(self, client, mock_celery):
        client.post("/api/integrations/google", json={
            "platform": "google", "business_id": "biz-1",
            "params": {"data_id": "0x123"}
        })
        mock_celery.assert_called_once_with("google", "biz-1", {"data_id": "0x123"})

    def test_max_reviews_forwarded_in_params(self, client, mock_celery):
        client.post("/api/integrations/google", json={
            "platform": "google", "params": {"data_id": "0x123", "max_reviews": 50}
        })
        _, _, params = mock_celery.call_args[0]
        assert params["max_reviews"] == 50


class TestGetTaskStatus:
    def test_pending_task(self, client, mocker):
        mocker.patch("app.api.routes_integrations.celery_app.AsyncResult",
                     return_value=mocker.MagicMock(state="PENDING"))
        resp = client.get("/api/integrations/tasks/fake-id")
        assert resp.json()["status"] == "PENDING"

    def test_progress_includes_stage_fields(self, client, mocker):
        result = mocker.MagicMock(state="PROGRESS",
                                  info={"stage": "saving", "total": 10, "saved": 3})
        mocker.patch("app.api.routes_integrations.celery_app.AsyncResult", return_value=result)
        resp = client.get("/api/integrations/tasks/fake-id")
        assert resp.json()["progress"]["stage"] == "saving"

    def test_success_includes_result(self, client, mocker):
        result = mocker.MagicMock(state="SUCCESS",
                                  result={"processed": 5, "skipped": 0})
        mocker.patch("app.api.routes_integrations.celery_app.AsyncResult", return_value=result)
        resp = client.get("/api/integrations/tasks/fake-id")
        assert resp.json()["result"]["processed"] == 5

    def test_failure_returns_error_message(self, client, mocker):
        result = mocker.MagicMock(state="FAILURE", info=Exception("boom"))
        mocker.patch("app.api.routes_integrations.celery_app.AsyncResult", return_value=result)
        resp = client.get("/api/integrations/tasks/fake-id")
        assert "error" in resp.json()


class TestReprocess:
    def test_queues_task_and_returns_task_id(self, client, mocker):
        task = mocker.MagicMock(id="reprocess-task-id")
        mocker.patch("app.api.routes_integrations.process_unprocessed_reviews.delay",
                     return_value=task)
        resp = client.post("/api/integrations/reprocess")
        assert resp.json()["task_id"] == "reprocess-task-id"
```

---

### 3.3 GET /health

File: `tests/api/test_routes_health.py`

```python
class TestHealthEndpoint:
    def test_returns_200(self, client): ...
    def test_returns_status_ok(self, client):
        assert client.get("/health").json()["status"] == "ok"
    def test_does_not_expose_secrets(self, client):
        body = str(client.get("/health").json()).lower()
        assert "api_key" not in body
        assert "password" not in body
```

---

## Layer 4 — End-to-End Tests

**Scope:** Full stack — real FastAPI, real Celery worker, real PostgreSQL, real Redis.
SerpAPI and OpenRouter mocked at the HTTP transport level with `respx`.

**Run with:**
```bash
docker compose up -d
uv run pytest tests/e2e/ -v --timeout=60
```

---

### 4.1 Full Ingestion Pipeline

File: `tests/e2e/test_full_pipeline.py`

```python
import time, respx, httpx

SERPAPI_FIXTURE = {
    "reviews": [{
        "review_id": "e2e-review-1",
        "user": {"name": "E2E User", "reviews": 5, "photos": 0},
        "snippet": "Full stack smoke test — works great!",
        "rating": 5,
        "iso_date": "2025-01-01T00:00:00Z",
    }]
}

@pytest.fixture
def mock_serpapi():
    with respx.mock:
        respx.get("https://serpapi.com/search.json").mock(
            return_value=httpx.Response(200, json=SERPAPI_FIXTURE)
        )
        yield

@pytest.fixture
def mock_openrouter(mocker):
    mocker.patch(
        "pipelines.processing.sentiment_analysis.analyze_sentiment_and_topics",
        return_value=SentimentResult(score=0.9, label="positive", topics=["food"])
    )
    mocker.patch(
        "pipelines.orchestration.pipeline_runner.generate_embedding",
        return_value=[0.0] * 768
    )


def wait_for_task(client, task_id: str, timeout: int = 30) -> dict:
    for _ in range(timeout):
        status = client.get(f"/api/integrations/tasks/{task_id}").json()
        if status["status"] in ("SUCCESS", "FAILURE"):
            return status
        time.sleep(1)
    raise TimeoutError(f"Task {task_id} did not complete within {timeout}s")


class TestFullIngestionFlow:
    def test_ingest_review_visible_via_api(self, live_client, mock_serpapi, mock_openrouter):
        # 1. Trigger ingestion
        resp = live_client.post("/api/integrations/google", json={
            "platform": "google",
            "params": {"data_id": "0xe2e123", "place_name": "E2E Restaurant", "max_reviews": 10}
        })
        assert resp.status_code == 200
        task_id = resp.json()["task_id"]

        # 2. Wait for worker to finish
        status = wait_for_task(live_client, task_id)
        assert status["status"] == "SUCCESS"
        assert status["result"]["processed"] == 1

        # 3. Review visible via GET /api/reviews
        reviews = live_client.get("/api/reviews?business_id=0xe2e123").json()
        assert reviews["total"] == 1
        item = reviews["items"][0]
        assert item["content"] == "Full stack smoke test — works great!"
        assert item["published_at"] == "2025-01-01T00:00:00+00:00"
        assert item["sentiment_label"] == "positive"
        assert item["is_processed"] is True

    def test_duplicate_ingestion_does_not_create_extra_rows(self, live_client, mock_serpapi, mock_openrouter):
        for _ in range(2):
            resp = live_client.post("/api/integrations/google", json={
                "platform": "google",
                "params": {"data_id": "0xdupe", "max_reviews": 10}
            })
            wait_for_task(live_client, resp.json()["task_id"])

        reviews = live_client.get("/api/reviews?business_id=0xdupe").json()
        assert reviews["total"] == 1  # not 2

    def test_business_appears_in_businesses_list(self, live_client, mock_serpapi, mock_openrouter):
        resp = live_client.post("/api/integrations/google", json={
            "platform": "google",
            "params": {"data_id": "0xbiz", "place_name": "E2E Café", "max_reviews": 10}
        })
        wait_for_task(live_client, resp.json()["task_id"])

        businesses = live_client.get("/api/reviews/businesses").json()
        business_ids = [b["business_id"] for b in businesses]
        assert "0xbiz" in business_ids
```

---

## Running Tests

### The `TEST_DATABASE_URL` environment variable

Integration and API tests need a real Postgres database. The variable that controls which DB is used is:

```
TEST_DATABASE_URL=postgresql+psycopg2://postgres:postgres@127.0.0.1:5432/customer_voice_ai_test
```

**Do you have to set it every time?** No. `conftest.py` has a hardcoded fallback:

```python
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg2://postgres:postgres@localhost:5432/customer_voice_ai_test",
)
```

So if your Docker DB is running on the default port with the default credentials, you can omit the variable entirely.

**⚠️ `127.0.0.1` vs `localhost`**

On macOS, `localhost` resolves to `::1` (IPv6). If you also have a local Homebrew Postgres installed, it listens on IPv6 and will intercept the connection — bypassing Docker's container entirely. The Homebrew Postgres does not have `pgvector`, so tests will fail with extension errors.

Use `127.0.0.1` explicitly to force IPv4 and always hit Docker:

```bash
export TEST_DATABASE_URL=postgresql+psycopg2://postgres:postgres@127.0.0.1:5432/customer_voice_ai_test
```

Add this export to your shell profile (`~/.zshrc`) or a local `.env.test` file to avoid repeating it.

---

### One-time DB setup (Docker)

```bash
# 1. Start the database container
docker compose up db -d

# 2. Create the test database
docker compose exec db psql -U postgres -c "CREATE DATABASE customer_voice_ai_test;"

# 3. Run migrations against the test DB
DB__NAME=customer_voice_ai_test uv run alembic upgrade head
```

> `DB__NAME` overrides the nested pydantic `DatabaseSettings.name` field.
> Do not use `DATABASE_URL=...` — it does not map to the nested settings structure.

---

### Run all tests

```bash
# With env var set in shell
uv run pytest tests/ -v

# Passing the env var inline (useful for one-off runs)
TEST_DATABASE_URL=postgresql+psycopg2://postgres:postgres@127.0.0.1:5432/customer_voice_ai_test \
  uv run pytest tests/ -v
```

### Run a specific layer

```bash
uv run pytest tests/unit/        -v   # no DB needed
uv run pytest tests/api/         -v   # no DB needed (uses test transaction session)
uv run pytest tests/integration/ -v   # requires Docker DB
uv run pytest tests/e2e/         -v --timeout=60   # requires full docker compose stack
```

### Run a specific file

```bash
uv run pytest tests/unit/test_platform_handlers.py -v
uv run pytest tests/integration/test_review_service.py -v
```

### Run a specific class or test

```bash
# Single class
uv run pytest tests/unit/test_platform_handlers.py::TestRegistry -v

# Single test
uv run pytest tests/unit/test_platform_handlers.py::TestRegistry::test_get_handler_unsupported_raises_key_error -v
```

### Run with coverage and HTML report

```bash
# Using the convenience script (sets TEST_DATABASE_URL automatically)
./scripts/coverage.sh

# Target a specific path
./scripts/coverage.sh tests/unit

# Or manually
uv run pytest tests/ --cov --cov-report=html:htmlcov --cov-report=term-missing
# Report written to htmlcov/index.html
```

### Coverage targets
| Layer | Target |
|-------|--------|
| Unit | ≥ 90% |
| Integration | ≥ 75% |
| API | ≥ 85% |
| E2E | smoke only |

---

## What is NOT Tested Here

| Item | Reason |
|------|--------|
| Real SerpAPI HTTP calls | Costs money, rate-limited, non-deterministic |
| Real OpenRouter/Gemini calls | Costs money, rate-limited |
| Celery broker/worker internals | Trust the library; test task logic directly |
| Embedding model download | Slow; mocked in all layers except E2E |
| Frontend | Separate suite (Playwright for E2E, Vitest for unit) |

---

## CI Integration

```yaml
# .github/workflows/test.yml
```

Unit + API run on every PR. Integration runs on merge to main. E2E runs nightly.
