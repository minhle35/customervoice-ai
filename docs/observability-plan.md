# Phase 2 — Observability Implementation Plan

## 1. Industry Landscape

LLM observability has two distinct layers that the industry handles separately:

| Layer | What it answers | Tools |
|---|---|---|
| **Runtime tracing** | What happened in this request, how long did each step take, what did the LLM say | LangSmith, Langfuse, OpenTelemetry, Arize Phoenix |
| **Evaluation / quality** | Is the system producing good answers, is quality degrading over time | DeepEval, Ragas, MLflow, Langfuse Evals |

Runtime tracing is operational — it tells you when something broke and why. Evaluation is a quality feedback loop — it tells you whether the system is getting better or worse as you change prompts, models, or retrieval parameters.

This system needs both, for different reasons:
- **Tracing** because the RAG pipeline has 5 distinct latency steps (embed → retrieve → rerank → build context → LLM) and you cannot diagnose slowness or failures without visibility into each step.
- **Evaluation** because runtime tracing alone cannot tell you whether the system is producing *good* answers. Frameworks like DeepEval, RAGAS, Langfuse Evals, and MLflow exist to measure generated output against expected output — verifying that retrieved context is faithful, answers are relevant, and hallucinations are absent. Without this layer you can observe that the pipeline ran, but not whether it produced a trustworthy result.

---

## 2. Frameworks Evaluated

### 2.1 LangSmith

**What it is:** A tracing platform from LangChain. Automatically instruments every LangChain and LangGraph call.

**Current state in this codebase:**.
- `LANGCHAIN_TRACING_V2` and `LANGCHAIN_API_KEY` are set in `config.py`.
- `main.py` pushes them into `os.environ` at startup.
- This means every `ChatOpenAI` call in `answer_generator.py`, `intent.py`, and `insight.py` is already traced — but with no custom metadata (no `business_id`, no `question`, no retrieval scores).

**What it does NOT trace in this codebase:**
- `sentiment_analysis.py` — uses raw `openai.OpenAI` client, not LangChain. This is the highest-volume LLM call (one per ingested review). Invisible to LangSmith.
- Embedding latency (`retriever.py:embed_query`)
- pgvector query latency (`retriever.py:retrieve`)
- Cross-encoder rerank latency (`retriever.py:rerank`)
- Intent `confidence` and `reasoning` fields (computed but discarded before the trace sees them)
- Source review IDs used in the cited answer (discarded in `rag_node`)

**Effort to activate properly:** Low. Two env vars already exist in config. Adding custom metadata via `with langsmith.trace(...)` or `run_tree.add_metadata()` adds another hour.

**Cost:** Free tier — 5,000 traces/month. Paid from $39/month.

**Verdict:** Use this first. Already 80% wired. The missing 20% is custom metadata and fixing the `sentiment_analysis.py` gap.

---

### 2.2 Langfuse

**What it is:** Open-source LLM observability platform. Self-hostable (Docker) or cloud. Tracks traces, scores, user feedback, prompt versions, and cost. Integrates with LangChain via a callback handler.

**Current state:** `langfuse>=4.0.1` is installed. Zero imports or initialization anywhere.

**What it offers over LangSmith:**
- **Self-hosted option** — no data leaves your infrastructure. Important if reviews contain PII.
- **User feedback loop** — you can attach thumbs-up/down scores to traces from the frontend, building a labelled dataset from production traffic.
- **Prompt management** — version and A/B test prompts without code deploys.
- **Cost tracking** — computes token cost per trace across providers (OpenRouter/Gemini pricing).
- **Sessions** — groups traces by `thread_id` for multi-turn conversations (maps directly to LangGraph `thread_id`).

**How to wire into this codebase:**

Option A — LangChain callback (covers all LangChain calls):
```python
from langfuse.callback import CallbackHandler
handler = CallbackHandler(public_key="...", secret_key="...", session_id=thread_id)
chain.invoke({"context": context, "question": question}, config={"callbacks": [handler]})
```

Option B — decorator for non-LangChain code (covers `sentiment_analysis.py`):
```python
from langfuse import observe

@observe(name="sentiment_analysis")
def analyze_sentiment_and_topics(text: str) -> dict:
    ...
```

Option C — manual span for retrieval stages (covers embed/retrieve/rerank):
```python
from langfuse import Langfuse
langfuse = Langfuse()

with langfuse.span(name="pgvector_retrieve", metadata={"business_id": business_id, "top_k": top_k}) as span:
    chunks = retrieve(db, query_vec, business_id, top_k)
    span.update(output={"rows_returned": len(chunks), "min_similarity": min(c.similarity_score for c in chunks)})
```

**Effort:** Medium. Relatively less effort (A day for LangChain callback wiring + half a day for manual spans on retrieval stages.)

**Cost:** Free self-hosted. Cloud: free tier (50k observations/month), paid from $59/month.

**Verdict:** Right choice for production or if PII matters. More powerful than LangSmith for the feedback loop use case. Adds complexity vs LangSmith — use LangSmith first to get value quickly, migrate to Langfuse when you need self-hosting or user feedback.

---

### 2.3 OpenTelemetry (OTel)

**What it is:** CNCF standard for distributed tracing, metrics, and logs. Vendor-neutral — traces export to Jaeger, Grafana Tempo, Datadog, AWS X-Ray, or any OTel-compatible backend. `opentelemetry-instrumentation-fastapi` auto-instruments every HTTP request.

**Current state:** Not installed. Not in `pyproject.toml`.

**What it adds that LangSmith/Langfuse don't:**
- **HTTP-level request tracing** — every `POST /api/agent/ask` gets a trace ID that propagates into all downstream work. This is the missing correlation layer — right now a log line from `retriever.py` cannot be linked to the HTTP request that triggered it.
- **Infra metrics** — database query counts, connection pool saturation, Redis latency — outside LLM calls.
- **Cross-service correlation** — if Celery workers and FastAPI share OTel, a worker trace links back to the API call that triggered it.

**How to wire:**
```python
# main.py
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
FastAPIInstrumentor.instrument_app(app)
SQLAlchemyInstrumentor().instrument(engine=engine)
```

**Effort:** Low to install, medium to configure an exporter (Jaeger local or Grafana Cloud).

**Verdict:** Right choice if you want to correlate HTTP requests → LLM calls → DB queries in a single trace. Not needed for LLM quality metrics — that's LangSmith/Langfuse territory. Adds operational overhead (another service to run). Skip for now unless you move to GCP/AWS where OTel exporters are native.

---

### 2.4 MLflow

**What it is:** ML experiment tracking. Records parameters, metrics, and artifacts per run. Primary use case: compare RAG configurations (different `top_k`, different reranker thresholds, different prompt versions) against quality metrics.

**Current state:** `mlflow>=3.10.1` installed. Zero initialization anywhere.

**What it's for in this codebase:** Evaluation experiments, not runtime tracing. When you run DeepEval tests with different pipeline configs, MLflow records which config produced the best faithfulness score.

**How to wire:**
```python
# backend/tests/evaluation/test_rag_quality.py
import mlflow

with mlflow.start_run(run_name="top_k=20_rerank=5"):
    mlflow.log_params({"retrieve_top_k": 20, "rerank_top_k": 5, "model": "gemini-2.0-flash"})
    # run DeepEval tests
    mlflow.log_metrics({"faithfulness": 0.87, "answer_relevancy": 0.91, "hallucination_rate": 0.04})
```

**Effort:** Low to instrument evaluation runs. Medium to set up MLflow tracking server (or use `mlflow ui` locally).

**Verdict:** Useful only after DeepEval tests exist. Do this in Phase 4 (evaluation), not Phase 2.

---

### 2.5 DeepEval

**What it is:** LLM evaluation framework. Runs metrics like `FaithfulnessMetric` (does the answer follow from the retrieved context?), `AnswerRelevancyMetric` (does the answer address the question?), `HallucinationMetric`.

**Current state:** `deepeval>=2.6.7` installed. Explicitly disabled in pytest via `-p no:plugins` because its pytest plugin crashes collection.

**When it belongs:** Phase 4. Requires a golden dataset (30+ QA pairs with ground-truth answers and source citations). That dataset doesn't exist yet.

**Verdict:** Not part of Phase 2. Defer to Phase 4.

---

### 2.6 Structured Logging (Python `logging` → JSON)

**What it is:** Replace the current plain-text log format with JSON so log lines are parseable by any log aggregator (Datadog, CloudWatch Logs Insights, Loki/Grafana).

**Current state:** `logger.py` uses `%(asctime)s - %(name)s - %(levelname)s - %(message)s`. Unstructured. Cannot be queried.

**The specific gap:** The catch-all exception handler in `main.py` returns a 500 with no log line at all. If the RAG pipeline raises, there is no stack trace anywhere.

**How to wire:** Replace the formatter:
```python
import json, logging

class JsonFormatter(logging.Formatter):
    def format(self, record):
        return json.dumps({
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "exc_info": self.formatException(record.exc_info) if record.exc_info else None,
        })
```

And fix the catch-all handler:
```python
@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})
```

**Effort:** S — under 1 hour.

---

## 3. What to Instrument in This Codebase

Ranked by value-to-effort ratio:

### Tier 1 — Most practical solution

**A. Fix the silent 500 handler** (`backend/app/main.py`)

The catch-all `Exception` handler has no logging call. Every unhandled error produces a 500 with zero diagnostic information.

```python
# main.py
@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})
```

**B. Enable LangSmith with metadata** (`backend/app/config.py` + `.env`)

LangSmith is already wired via env vars. Just need to set the key and add `business_id` + `question` as trace metadata using `langsmith.traceable` on `run_rag_pipeline` and `run_agent`.

```python
# rag_service.py
from langsmith import traceable

@traceable(name="rag_pipeline", metadata={"pipeline": "two-stage-rag"})
def run_rag_pipeline(db, question, business_id, ...):
    ...
```

**C. Stop discarding intent confidence** (`agents/nodes/intent.py`)

The LLM returns `confidence` and `reasoning` but they are dropped. Write them to agent state so they appear in traces and can be logged.

```python
# agents/state.py — add fields
intent_confidence: float | None
intent_reasoning: str | None

# agents/nodes/intent.py
return {"intent": result.intent, "intent_confidence": result.confidence, "intent_reasoning": result.reasoning}
```

**D. Stop discarding source IDs in rag_node** (`agents/nodes/rag.py`)

```python
answer, source_ids = run_rag_pipeline(db=db, question=question, business_id=business_id)
# log source_ids, or write to state for the critic agent later
```

---

### Tier 2 — Retrieval stage timing

**E. Time each RAG stage** (`pipelines/rag/retriever.py`, `rag_service.py`)

The biggest user-facing latency is in cross-encoder rerank. Without timing, we cannot know which stage to optimise.

```python
import time

def run_rag_pipeline(db, question, business_id, ...):
    t0 = time.perf_counter()
    query_vec = embed_query(question)
    t1 = time.perf_counter()

    candidates = retrieve(db, query_vec, business_id, top_k)
    t2 = time.perf_counter()

    reranked = rerank(question, candidates, rerank_top_k)
    t3 = time.perf_counter()

    logger.info(
        "rag_pipeline_latency",
        extra={
            "business_id": business_id,
            "embed_ms": round((t1 - t0) * 1000),
            "retrieve_ms": round((t2 - t1) * 1000),
            "rerank_ms": round((t3 - t2) * 1000),
            "candidates_returned": len(candidates),
            "chunks_used": len(reranked),
        }
    )
```

**F. Log retrieval quality signals**

```python
if reranked:
    logger.info(
        "rag_rerank_scores",
        extra={
            "business_id": business_id,
            "top_rerank_score": reranked[0].rerank_score,
            "bottom_rerank_score": reranked[-1].rerank_score,
            "top_similarity": reranked[0].similarity_score,
        }
    )
```

Low `top_rerank_score` is a signal that the query has no good matches in the database (wrong business, no ingested reviews, poor query formulation).

---

### Tier 3 — Celery pipeline instrumentation

**G. Instrument `sentiment_analysis.py`** with Langfuse `@observe` or manual timing

This is the highest-volume LLM call in the system and is completely invisible. One call per ingested review.

```python
from langfuse import observe

@observe(name="sentiment_analysis", capture_input=False)  # PII: don't log raw review text
def analyze_sentiment_and_topics(text: str) -> dict:
    ...
```

Or without Langfuse, at minimum log token usage from the response:

```python
resp = client.chat.completions.create(...)
logger.info("sentiment_llm_usage", extra={
    "prompt_tokens": resp.usage.prompt_tokens,
    "completion_tokens": resp.usage.completion_tokens,
    "model": resp.model,
})
```

**H. Emit rate-limit events in the recovery path** (`pipeline_runner.py`)

`process_unprocessed` catches `RateLimitError` but never calls `_emit()`, so Celery's result backend shows no progress update when rate-limited in recovery.

---

### Tier 4 — Structured logging

**I. Replace plain-text logger with JSON formatter** (`backend/app/logger.py`)

Replace the `%(asctime)s - %(name)s...` format with a JSON formatter so log lines are queryable in CloudWatch Logs Insights, Datadog, or Grafana Loki. This is 20 lines of code and unlocks log analytics without any new infrastructure.

---

## 4. Implementation Order

| Step | What | File(s) | Effort | Value |
|---|---|---|---|---|
| 1 | Fix silent 500 handler | `main.py` | Low | Critical — no more invisible errors |
| 2 | Enable LangSmith + add metadata | `.env`, `rag_service.py`, `graph.py` | Low | Immediate trace visibility on all LangChain calls |
| 3 | Stop discarding intent confidence | `state.py`, `intent.py` | Low | Confidence signal for monitoring classifier drift |
| 4 | Stop discarding source IDs in rag_node | `rag_node.py` | Low | Citation provenance at agent layer |
| 5 | Time RAG pipeline stages + log scores | `rag_service.py`, `retriever.py` | Medium | Latency breakdown, retrieval quality signal |
| 6 | Instrument Celery sentiment LLM calls | `sentiment_analysis.py` | Medium | Cost visibility on highest-volume LLM calls |
| 7 | Fix rate-limit emit in recovery path | `pipeline_runner.py` | Medium | Accurate Celery progress in recovery |
| 8 | Structured JSON logging | `logger.py` | Medium | Log aggregator compatibility |

Total: Steps 1–4 and Steps 5–8 can be combined

---

## 5. What Not to Do Now

- **OpenTelemetry** — correct long-term choice if moving to GCP/AWS, but adds a new service dependency (OTel collector) with no immediate payoff over LangSmith.
- **Langfuse self-hosted** — right if PII policy prohibits data leaving the infra, or when we need user feedback scoring. Too much infrastructure overhead for the current stage.
- **MLflow** — belongs in Phase 4 alongside DeepEval. Zero value without evaluation tests.
- **DeepEval** — belongs in Phase 4. Requires a golden dataset that doesn't exist yet.

---

## 6. Questions to answer in After Phase 2

| Question | Answered by |
|---|---|
| Which step in the RAG pipeline is slowest? | Stage timing logs (Step 5) |
| Are there queries with no good matches in the DB? | Low `top_rerank_score` signal (Step 5) |
| How often does the intent classifier say "clarification"? | LangSmith intent traces (Step 2) |
| How confident is the classifier on edge cases? | `intent_confidence` in state (Step 3) |
| How many tokens does sentiment analysis consume per review? | Celery instrumentation (Step 6) |
| What reviews were cited in a specific answer? | `source_ids` in rag_node (Step 4) |
| When a 500 fires, what was the exception? | Fixed 500 handler (Step 1) |
