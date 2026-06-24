# Baseline RAG System — Testing Plan

## System Map

- The baseline RAG pipeline is a linear chain of five distinct operations. 
- This testing document documents test decisions made 

```
User query
    │
    ▼
embed_query()          ← sentence-transformer local model (intfloat/multilingual-e5-base)
    │                     encodes with "query: " prefix, normalizes embeddings
    ▼
retrieve()             ← pgvector cosine distance SQL (<=> operator, HNSW index)
    │                     returns top-20 ReviewChunk objects ordered by similarity
    ▼
rerank()               ← cross-encoder/ms-marco-MiniLM-L-6-v2 re-scores (query, doc) pairs
    │                     sorts descending, returns top-5
    ▼
build_context()        ← packs chunks into [N]-cited text block within token budget
    │                     4 chars ≈ 1 token approximation, stops when budget exceeded
    ▼
generate_answer()      ← LangChain LCEL chain → OpenRouter (Gemini 2.5 Flash)
    │                     CitationPrompt + StrOutputParser, max_tokens=1500
    ▼
rag_node()             ← LangGraph node: reads AgentState, writes AIMessage back
    │
    ▼
POST /api/agent/ask    ← FastAPI route, intent_classifier routes here when intent="rag"
```

Data lives in two tables: `reviews` (content, metadata) and `review_embeddings` (768-dim vector,
foreign key to reviews). The SQL JOIN is the seam between the pipeline and the DB schema.

---

## What's Already Tested

| Component | File | Coverage |
|-----------|------|----------|
| `embed_query` | `test_rag_retriever.py` | query prefix, normalize flag, return type |
| `retrieve` | `test_rag_retriever.py` | chunk mapping, business_id binding, null fields, ordering |
| `rerank` | `test_rag_retriever.py` | top-k slicing, score ordering, pair format, empty input |
| `build_context` | `test_rag_context_builder.py` | citation markers, token budget, metadata fields, separators |
| `generate_answer` | `test_rag_answer_generator.py` | chain invocation, empty fallback, budget propagation, credentials |

These are all unit tests with mocked models and DB. They are well-written and should not be replaced.

---

## The Key Tradeoffs

### What to mock vs what to hit real

| Dependency | Strategy | Reason |
|-----------|----------|--------|
| `SentenceTransformer` | Always mock | 500 MB model load; CI has no GPU; startup cost ~8s |
| `CrossEncoder` | Always mock | Same — 100 MB model, slow startup |
| OpenRouter / LLM | Always mock in unit + integration | API cost, network flakiness in CI, non-deterministic output |
| pgvector DB | **Real in integration tests** | The SQL uses `CAST(:query_vec AS vector)` and `<=>` — non-standard syntax that only pgvector understands. A mock here gives false confidence. |
| `review_embeddings` table | **Real in integration tests** | HNSW index behavior differs from any mock you can write |

The existing unit tests mock the DB correctly — they test the Python logic in isolation. The gap is that nobody has verified that the actual SQL works against a real pgvector instance. That's what integration tests are for.

### pytest over alternatives

`pytest` is already established in this codebase with `conftest.py`, session-scoped engine, and rollback-per-test pattern. Keep it. The infrastructure is correct: function-scoped `db` fixture rolls back after every test, so integration tests don't pollute each other.

`respx` (just added) handles httpx mocking for the SerpAPI route tests. Don't use it for RAG tests — RAG has no HTTP calls (embeddings are local, DB is SQLAlchemy).

### Property-based testing

`hypothesis` is not installed. The context builder's token budget logic (`4 chars ≈ 1 token`, `max(1, len // 4)`) is simple enough that parametrized edge cases cover it better than generated inputs. Skip hypothesis for now.

### Evaluation framework

RAGAS + MLflow is the right choice. It evaluates semantic quality that unit tests cannot: whether the answer is faithful to the retrieved context, whether the right chunks were retrieved. This is a separate concern from correctness tests — run it manually or nightly against a seeded DB, not in the main CI pipeline (it costs LLM tokens per sample).

---

## Testing Pyramid

```
         ┌────────────────────────────────────────────┐
         │  Evaluation (RAGAS + MLflow)               │  ← quality gate, manual / nightly
         │  eval_rag.py + golden_dataset.json         │    8 questions → expand to 20+
         └────────────────────────────────────────────┘
              ┌──────────────────────────────────────┐
              │  API tests  (TestClient, real DB)    │  ← 3–5 tests, LLM mocked
              │  POST /api/agent/ask intent=rag      │
              └──────────────────────────────────────┘
           ┌────────────────────────────────────────────┐
           │  Integration tests  (real pgvector)        │  ← 4–6 tests, models mocked
           │  retrieve() + embedding store round-trip   │
           └────────────────────────────────────────────┘
        ┌──────────────────────────────────────────────────┐
        │  Unit tests  (all external deps mocked)          │  ← already done, maintain
        │  embed_query / retrieve / rerank / build / gen   │
        └──────────────────────────────────────────────────┘
```

---

## Layer 1 — Unit Test Gaps

The existing unit tests are good. These are the specific holes that should be filled.

### `test_rag_retriever.py` additions

**Singleton caching** — `_get_encoder()` and `_get_cross_encoder()` use module-level globals to
avoid reloading the model on every call. This needs a test because if the global is accidentally
reset (e.g. in a test that replaces the module attribute), every subsequent call re-loads the
500MB model.

```python
def test_encoder_singleton_not_reloaded():
    """_get_encoder() returns same object on repeated calls (no reload)."""
    with patch("pipelines.vector_rag.retriever.SentenceTransformer") as MockST:
        MockST.return_value = MagicMock()
        import pipelines.vector_rag.retriever as mod
        mod._encoder = None  # reset global
        first = mod._get_encoder()
        second = mod._get_encoder()
    assert first is second
    assert MockST.call_count == 1
```

**pgvector vector format** — The SQL passes `str(query_embedding)` as the `:query_vec` param,
which pgvector expects in `[0.1, 0.2, ...]` format. If `embed_query` ever returns a numpy array
instead of a list, `str()` produces a different format and the query silently returns no rows.

```python
def test_embed_query_returns_plain_list_not_ndarray():
    """Output must be a Python list — str() of ndarray breaks pgvector cast."""
    mock_model = MagicMock()
    mock_model.encode.return_value = MagicMock(tolist=lambda: [0.1, 0.2, 0.3])
    with patch("pipelines.vector_rag.retriever._get_encoder", return_value=mock_model):
        result = embed_query("test")
    assert isinstance(result, list)
    assert all(isinstance(v, float) for v in result)
```

**rerank with fewer chunks than final_top_k** — currently not tested. If only 3 chunks are
retrieved but `final_top_k=5`, the function should return all 3, not crash.

```python
def test_rerank_returns_all_chunks_when_fewer_than_top_k():
    chunks = [_make_chunk() for _ in range(2)]
    mock_ce = MagicMock()
    mock_ce.predict.return_value = [0.8, 0.3]
    with patch("pipelines.vector_rag.retriever._get_cross_encoder", return_value=mock_ce):
        result = rerank("q", chunks, final_top_k=5)
    assert len(result) == 2
```

### `test_rag_answer_generator.py` additions

**LLM exception propagation** — if the LLM call raises (network error, rate limit), the exception
currently propagates up through `generate_answer` to `rag_node`. The caller needs to know this
will raise, not silently return empty.

```python
def test_llm_exception_propagates():
    chunks = [_make_chunk()]
    fake_chain = MagicMock()
    fake_chain.invoke.side_effect = RuntimeError("LLM unavailable")
    with patch("pipelines.vector_rag.answer_generator._build_chain", return_value=fake_chain):
        with pytest.raises(RuntimeError, match="LLM unavailable"):
            generate_answer("q", chunks, **_LLM_KWARGS)
```

**Citation markers in answer** — the prompt instructs the LLM to use [N] markers. Test that
`used_chunks` index aligns with context numbering (the Nth chunk corresponds to [N] in context).
This is a contract test: if `build_context` changes its numbering scheme, this breaks.

```python
def test_used_chunks_order_matches_context_numbering():
    chunks = [_make_chunk(content=f"Review about topic {i}") for i in range(3)]
    fake_chain = MagicMock()
    fake_chain.invoke.return_value = "Answer [1] and [2]."
    with patch("pipelines.vector_rag.answer_generator._build_chain", return_value=fake_chain):
        _, used = generate_answer("q", chunks, token_budget=10000, **_LLM_KWARGS)
    # First used chunk content should appear as [1] in what was passed to context
    invoke_kwargs = fake_chain.invoke.call_args[0][0]
    assert "[1]" in invoke_kwargs["context"]
    assert used[0].content in invoke_kwargs["context"]
```

### `test_rag_node.py` — new file (does not exist yet)

`agents/nodes/rag.py` is the orchestration layer that wires all five steps together. It is
currently completely untested. This is the highest-risk gap because it contains the only code
path that actually calls all five functions in sequence.

```python
# tests/unit/test_rag_node.py

class TestRagNode:
    def _make_state(self, question="What do customers say?", business_id="biz-1"):
        from langchain_core.messages import HumanMessage
        from agents.state import AgentState
        return AgentState(
            messages=[HumanMessage(content=question)],
            business_id=business_id,
            thread_id="thread-1",
            intent="rag",
            intent_confidence=0.95,
            intent_reasoning="retrieval question",
            pending_ingestion=None,
            approved=None,
        )

    def test_returns_ai_message(self, mock_settings):
        """rag_node must append an AIMessage to messages."""
        state = self._make_state()
        with patch("agents.nodes.rag.embed_query", return_value=[0.1] * 768), \
             patch("agents.nodes.rag.retrieve", return_value=[_make_chunk()]), \
             patch("agents.nodes.rag.rerank", return_value=[_make_chunk()]), \
             patch("agents.nodes.rag.generate_answer", return_value=("Great food [1].", [_make_chunk()])):
            result = rag_node(state, db=MagicMock(), settings=mock_settings)
        from langchain_core.messages import AIMessage
        assert any(isinstance(m, AIMessage) for m in result["messages"])

    def test_no_reviews_returns_graceful_message(self, mock_settings):
        """When retrieve() returns empty, answer should say no reviews found."""
        state = self._make_state()
        with patch("agents.nodes.rag.embed_query", return_value=[0.1] * 768), \
             patch("agents.nodes.rag.retrieve", return_value=[]), \
             patch("agents.nodes.rag.rerank", return_value=[]):
            result = rag_node(state, db=MagicMock(), settings=mock_settings)
        answer_text = result["messages"][-1].content.lower()
        assert "no" in answer_text or "couldn't" in answer_text or "not found" in answer_text

    def test_uses_business_id_from_state(self, mock_settings):
        """retrieve() must be called with the business_id from AgentState."""
        state = self._make_state(business_id="specific-biz-123")
        with patch("agents.nodes.rag.embed_query", return_value=[0.1] * 768) as mock_embed, \
             patch("agents.nodes.rag.retrieve", return_value=[]) as mock_retrieve, \
             patch("agents.nodes.rag.rerank", return_value=[]):
            rag_node(state, db=MagicMock(), settings=mock_settings)
        call_kwargs = mock_retrieve.call_args
        assert "specific-biz-123" in call_kwargs[0] or call_kwargs[1].get("business_id") == "specific-biz-123"
```

---

## Layer 2 — Integration Tests

**Location:** `tests/integration/test_rag_pipeline.py`

These tests use the real DB (pgvector) via the session-scoped `db_engine` and function-scoped
`db` fixtures from `conftest.py`. The embedding model and LLM are mocked — only the SQL and
pgvector extension are real.

### What to test

**Retrieve round-trip with real pgvector**

This is the highest-value integration test. It validates that:
- The `CAST(:query_vec AS vector)` syntax actually works
- The `<=>` operator returns the closest vector
- The JOIN between `review_embeddings` and `reviews` works correctly
- `business_id` filtering works (reviews from other businesses are excluded)

```python
def test_retrieve_returns_closest_vector(db):
    """Insert two embeddings, query closer to one — that one should rank first."""
    from app.services.review_service import ReviewService
    from app.services.embedding_service import EmbeddingService
    from pipelines.vector_rag.retriever import retrieve
    from tests.conftest import make_review_create

    rs = ReviewService(db)
    es = EmbeddingService(db)

    r1 = rs.upsert_review(make_review_create(content="Excellent food", business_id="biz-A"))
    r2 = rs.upsert_review(make_review_create(content="Terrible service", business_id="biz-A"))

    # Manually craft vectors: query is close to r1
    vec_r1 = [1.0] + [0.0] * 767      # unit vector in dim 0
    vec_r2 = [0.0, 1.0] + [0.0] * 766 # unit vector in dim 1
    query_vec = [0.99] + [0.0] * 767  # almost identical to vec_r1

    es.upsert_embedding(r1.id, vec_r1, model="test")
    es.upsert_embedding(r2.id, vec_r2, model="test")
    db.flush()

    results = retrieve(db, query_vec, "biz-A", top_k=2)

    assert len(results) == 2
    assert results[0].review_id == r1.id  # closest should rank first
    assert results[0].similarity_score > results[1].similarity_score
```

**business_id isolation**

Critical for multi-tenant correctness: a query for business A must never return reviews from
business B, even if their embeddings are closer.

```python
def test_retrieve_excludes_other_businesses(db):
    rs = ReviewService(db)
    es = EmbeddingService(db)

    r_a = rs.upsert_review(make_review_create(business_id="biz-A", content="Review A"))
    r_b = rs.upsert_review(make_review_create(business_id="biz-B", content="Review B"))

    identical_vec = [1.0] + [0.0] * 767
    es.upsert_embedding(r_a.id, identical_vec, model="test")
    es.upsert_embedding(r_b.id, identical_vec, model="test")
    db.flush()

    results = retrieve(db, identical_vec, "biz-A", top_k=10)
    returned_ids = {r.review_id for r in results}
    assert r_a.id in returned_ids
    assert r_b.id not in returned_ids
```

**top_k is respected**

```python
def test_retrieve_respects_top_k(db):
    rs = ReviewService(db)
    es = EmbeddingService(db)
    for i in range(10):
        r = rs.upsert_review(make_review_create(content=f"Review {i}", business_id="biz-A"))
        es.upsert_embedding(r.id, [float(i) / 10] + [0.0] * 767, model="test")
    db.flush()

    results = retrieve(db, [0.5] + [0.0] * 767, "biz-A", top_k=3)
    assert len(results) <= 3
```

**Empty DB returns empty list**

```python
def test_retrieve_empty_db_returns_empty(db):
    results = retrieve(db, [0.1] * 768, "no-such-business", top_k=20)
    assert results == []
```

**Full pipeline: embed → retrieve → rerank (models mocked)**

This is the integration test that runs the full pipeline except LLM and model inference.
It proves all five functions compose correctly end to end.

```python
def test_full_pipeline_no_llm(db):
    """embed_query (mocked) → retrieve (real pgvector) → rerank (mocked) → build_context."""
    rs = ReviewService(db)
    es = EmbeddingService(db)
    r = rs.upsert_review(make_review_create(content="Amazing dim sum", business_id="biz-C"))
    es.upsert_embedding(r.id, [0.5] * 768, model="test")
    db.flush()

    fake_vec = [0.5] * 768
    with patch("pipelines.vector_rag.retriever._get_encoder") as mock_enc, \
         patch("pipelines.vector_rag.retriever._get_cross_encoder") as mock_ce:
        mock_enc.return_value.encode.return_value = MagicMock(tolist=lambda: fake_vec)
        mock_ce.return_value.predict.return_value = [0.9]

        query_vec = embed_query("dim sum quality")
        candidates = retrieve(db, query_vec, "biz-C", top_k=20)
        reranked = rerank("dim sum quality", candidates, final_top_k=5)
        context, used = build_context(reranked)

    assert len(candidates) == 1
    assert len(reranked) == 1
    assert "Amazing dim sum" in context
    assert "[1]" in context
```

---

## Layer 3 — API Tests

**Location:** `tests/api/test_routes_agent_rag.py`

Use FastAPI `TestClient` with the `client` fixture from `conftest.py`. Mock the LLM and embedding
model; use the real DB (rolled back after each test).

### Setup pattern

```python
@pytest.fixture()
def rag_client(client, db):
    """TestClient with LLM and embedding models mocked."""
    with patch("agents.nodes.rag.embed_query", return_value=[0.5] * 768), \
         patch("agents.nodes.rag.rerank", side_effect=lambda q, chunks, **kw: chunks[:5]), \
         patch("agents.nodes.rag.generate_answer", return_value=("Mocked answer [1].", [])):
        yield client
```

### What to test

**Successful rag intent flow**

```python
def test_ask_agent_rag_intent_returns_answer(rag_client, db):
    """Full path: POST /api/agent/ask → intent=rag → answer returned."""
    # Seed a review so retrieve() has something to find
    rs = ReviewService(db)
    es = EmbeddingService(db)
    r = rs.upsert_review(make_review_create(business_id="biz-test", content="Great ramen"))
    es.upsert_embedding(r.id, [0.5] * 768, model="test")
    db.flush()

    with patch("agents.nodes.intent.intent_node", return_value={
        "intent": "rag", "intent_confidence": 0.95, "intent_reasoning": "retrieval"
    }):
        resp = rag_client.post("/api/agent/ask", json={
            "question": "What do customers say about the food?",
            "business_id": "biz-test",
            "thread_id": "thread-abc",
        })

    assert resp.status_code == 200
    data = resp.json()
    assert "answer" in data
    assert data["pending_approval"] is False
    assert data["thread_id"] == "thread-abc"
```

**No reviews — graceful degradation**

```python
def test_ask_agent_no_reviews_graceful_response(client):
    """When the business has no reviews, should return a message, not 500."""
    with patch("agents.nodes.intent.intent_node", return_value={
        "intent": "rag", "intent_confidence": 0.95, "intent_reasoning": "retrieval"
    }), patch("agents.nodes.rag.embed_query", return_value=[0.1] * 768), \
       patch("agents.nodes.rag.generate_answer", return_value=("No reviews found.", [])):
        resp = client.post("/api/agent/ask", json={
            "question": "Tell me about the menu",
            "business_id": "non-existent-biz",
            "thread_id": "thread-xyz",
        })

    assert resp.status_code == 200
    assert resp.json()["answer"]
```

**thread_id is echoed back**

```python
def test_ask_agent_echoes_thread_id(rag_client):
    resp = rag_client.post("/api/agent/ask", json={
        "question": "Any good?",
        "business_id": "biz-1",
        "thread_id": "my-session-id",
    })
    assert resp.json()["thread_id"] == "my-session-id"
```

**LLM error returns 500**

```python
def test_ask_agent_llm_error_returns_500(client, db):
    with patch("agents.nodes.intent.intent_node", return_value={
        "intent": "rag", "intent_confidence": 0.9, "intent_reasoning": "r"
    }), patch("agents.nodes.rag.embed_query", return_value=[0.1] * 768), \
       patch("agents.nodes.rag.generate_answer", side_effect=RuntimeError("LLM down")):
        resp = client.post("/api/agent/ask", json={
            "question": "question", "business_id": "biz", "thread_id": "t"
        })
    assert resp.status_code == 500
```

---

## Layer 4 — Evaluation (RAGAS + MLflow)

**Location:** `tests/evaluation/eval_rag.py` — already implemented.

### Current state

- Script is complete: retrieves, reranks, generates, computes Faithfulness / AnswerRelevancy /
  ContextPrecision / ContextRecall, logs to MLflow.
- `golden_dataset.json` has 8 generic restaurant questions with loose ground truths.
- Run command: `cd backend && python tests/evaluation/eval_rag.py --business-id <PLACE_ID>`

### What needs improving

**Expand the golden dataset** — 8 generic questions are not enough to detect regressions.
The current ground truths are also too vague ("customers generally praise...") to give
ContextRecall meaningful signal. Target: 20+ questions, ground truths written against specific
ingested reviews.

Structure to add per sample:
```json
{
  "question": "What specific menu items do reviewers mention negatively?",
  "ground_truth": "Reviewers mention the tonkotsu broth was too salty and the gyoza was undercooked.",
  "expected_signals": ["salty broth", "undercooked gyoza"],
  "min_faithfulness": 0.7,
  "min_context_recall": 0.6
}
```

**Add per-metric pass/fail thresholds** — so the eval script can exit non-zero when quality
drops, enabling it to run as a nightly CI gate:

```python
THRESHOLDS = {
    "faithfulness": 0.70,
    "answer_relevancy": 0.75,
    "context_precision": 0.60,
    "context_recall": 0.55,
}
# After results = evaluate(...):
failed = [k for k, v in scores.items() if v < THRESHOLDS.get(k, 0)]
sys.exit(1 if failed else 0)
```

**When to run** — not in the main `pytest` suite (costs LLM tokens, requires seeded DB).
Run nightly via CI scheduled job, or manually before merging a change to the RAG pipeline.

---

## Gaps Not Worth Fixing Now

| Gap | Reason to skip |
|-----|---------------|
| Testing `_build_chain()` directly | It's a thin LangChain wrapper; testing it means testing LangChain's LCEL API |
| Testing pgvector HNSW index parameters | Index tuning is a deployment concern, not a code concern |
| Testing `SentenceTransformer` model weights | Model quality is evaluated via RAGAS, not unit tests |
| Testing MLflow logging | MLflow is a side effect; test that the script runs, not that MLflow stores correctly |
| `resolve_data_id` in serpapi_service | Already async-fixed; covered when serpapi route tests land via respx |

---

## Implementation Order

Work through layers bottom-up — unit gaps are quick and unblock higher layers.

1. **Unit gaps** (`test_rag_retriever.py`, `test_rag_answer_generator.py`)
   - Singleton caching, vector return type, rerank with fewer chunks than top_k, LLM exception propagation
   - Estimated: 1–2 hours

2. **`test_rag_node.py`** — new file, tests the orchestration layer
   - Estimated: 1–2 hours

3. **Integration tests** (`tests/integration/test_rag_pipeline.py`)
   - Requires Docker DB running (`docker-compose up db`)
   - Most important: round-trip with real pgvector, business_id isolation
   - Estimated: 2–3 hours

4. **API tests** (`tests/api/test_routes_agent_rag.py`)
   - Depends on integration layer being stable
   - Estimated: 1–2 hours

5. **Evaluation dataset expansion** (`tests/evaluation/golden_dataset.json`)
   - Business-specific ground truths, pass/fail thresholds in `eval_rag.py`
   - Estimated: ongoing — add questions each time new reviews are ingested

---

## Running the Tests

```bash
# Unit + integration (requires DB)
cd backend
TEST_DATABASE_URL=postgresql+psycopg2://postgres:postgres@localhost:5432/customer_voice_ai_test \
  uv run pytest tests/unit tests/integration -v

# Coverage report
./scripts/coverage.sh tests/unit tests/integration

# RAG evaluation (manual — costs LLM tokens)
python tests/evaluation/eval_rag.py --business-id <GOOGLE_PLACE_ID> --retrieve-top-k 20 --rerank-top-k 5
mlflow ui  # view at http://localhost:5000
```
