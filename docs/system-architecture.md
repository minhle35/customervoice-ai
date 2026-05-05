# CustomerVoice AI — System Architecture

See [system-diagram.md](system-diagram.md) for Mermaid diagrams of each layer.

---

## Table of Contents

1. [What this system does](#what-this-system-does)
2. [Ingestion Layer](#1-ingestion-layer)
3. [ETL / Processing Layer](#2-etl--processing-layer)
4. [Storage + Embeddings](#3-storage--embeddings)
5. [RAG Pipeline](#4-rag-pipeline)
6. [Multi-Agent Layer](#5-multi-agent-layer)
7. [Critic / Validator Agent](#6-critic--validator-agent)
8. [Backend API](#7-backend-api)
9. [Frontend](#8-frontend)
10. [MCP Layer](#9-mcp-layer)
11. [Observability](#10-observability)

---

## What this system does

CustomerVoice AI ingests customer reviews from Google, Reddit, and Facebook; enriches them with NLP (sentiment, topics, embeddings); and lets business owners ask natural language questions. Answers are grounded in real review data — not hallucinated — using a RAG pipeline. A LangGraph multi-agent system routes questions to the right specialist handler. An MCP server exposes all capabilities to AI assistants like Claude Desktop.

---

## 1. Ingestion Layer

### What we built

Custom Python adapters in `pipelines/ingestion/`:

| Adapter | Source | Method |
|---|---|---|
| `google_reviews_ingestion.py` | Google Maps reviews | SerpAPI `google_maps_reviews` engine |
| `reddit_ingestion.py` | Reddit posts/comments | PRAW (official Reddit API wrapper) |
| `facebook_ingestion.py` | Facebook page reviews | Facebook Graph API |

Ingestion is triggered on-demand via `POST /api/integrations/{platform}`, which queues a Celery task and returns immediately with a `task_id`. The caller polls `/api/tasks/{task_id}` for progress.

### Why not Airbyte?

Airbyte is the right tool for teams running scheduled batch syncs across many data sources with a UI for non-engineers to manage connectors. The tradeoffs:

| | Airbyte | Custom adapters (current) |
|---|---|---|
| Setup | 30-min Docker stack, UI config | Code-first, version controlled |
| Scheduling | Built-in cron + UI | Celery beat (add 5 lines) |
| Custom logic | Plugin model, complex | Direct Python, easy |
| On-demand trigger | API, but complex setup | Direct `.delay()` call |
| Operational cost | Extra Docker service, memory | Zero |
| Right for | Teams, 20+ sources, non-engineers | Developers, ≤5 custom sources |

**Verdict:** Airbyte would add a third orchestration layer (Airbyte → Celery → FastAPI) for no benefit at this scale. If the team grows and a non-engineer needs to add a new data source without code, migrate to Airbyte then.

### Why SerpAPI for Google?

Google has no public reviews API. The options are:
- **SerpAPI**: paid, reliable, handles rate limiting — `$50/month` for 5,000 searches
- **Places API**: returns max 5 reviews per place, no pagination — useless for bulk ingestion
- **Scraping directly**: fragile, breaks on DOM changes, violates ToS
- **Apify**: similar to SerpAPI, slightly higher cost

SerpAPI is the only practical choice for pulling more than 5 reviews per business from Google Maps.

---

## 2. ETL / Processing Layer

### What we built

A sequential pipeline in `pipelines/orchestration/pipeline_runner.py` executed inside a Celery worker:

```
fetch → clean → sentiment + topics (HuggingFace) → embed → upsert DB
```

Each stage emits `PROGRESS` state to Redis so the frontend can poll task progress in real time.

**Cleaning** (`pipelines/processing/clean_reviews.py`): deduplication by `platform_id`, HTML stripping, whitespace normalisation, language detection.

**Enrichment** (`pipelines/processing/sentiment_analysis.py`): HuggingFace transformers classify each review as positive/neutral/negative and extract topic keywords. These are stored as structured fields on the `reviews` table, enabling SQL analytics without re-querying the LLM.

### Why Celery + Redis over Apache Airflow?

| | Celery + Redis (current) | Apache Airflow |
|---|---|---|
| Model | Event-driven task queue | DAG-based scheduled batch |
| Trigger | API call → `.delay()` | Cron schedule or API trigger |
| Latency | Milliseconds to start | Scheduler polls every ~5 seconds |
| Setup | 2 Docker services (Redis + worker) | 5+ services (scheduler, webserver, DB, executor) |
| Visibility | Celery result backend (Redis) | Full DAG UI with history |
| Retry logic | Built-in `max_retries`, `countdown` | Built-in with visual status |
| Right for | On-demand tasks, API-triggered jobs | Complex batch pipelines, dependencies between steps |

**Verdict:** Airflow is worth migrating to if later we need scheduled nightly ingestion runs, dependency chaining between DAG steps (e.g. "only embed after all sentiment is done"), and a UI for engineers to monitor pipeline health. Current Celery setup can be wrapped in an Airflow `PythonOperator` with relatively low effort.

### Airflow migration effort (if needed)

1. **Low effort** (~2 hours): wrap `pipeline_runner.ingest()` in an Airflow `PythonOperator`. No logic changes needed — the pipeline function is already self-contained.
2. **Medium effort** (~1 day): split the monolithic pipeline into separate Airflow tasks (fetch → clean → enrich → embed → store) to get per-stage retries and visibility.
3. **High effort** (~1 week): replace Celery entirely — move task triggering from FastAPI to Airflow REST API, update frontend progress polling, add authentication.

Recommendation: start with step 1. Get the Airflow UI for free; keep Celery for on-demand triggers.

---

## 3. Storage + Embeddings

### What we built

Single PostgreSQL instance with the `pgvector` extension:

```sql
-- reviews: structured fields enable SQL analytics without LLM
reviews (
    id UUID PRIMARY KEY,
    business_id TEXT,
    platform TEXT,
    content TEXT,
    author TEXT,
    rating FLOAT,
    sentiment_label TEXT,       -- positive / neutral / negative
    sentiment_score FLOAT,
    topics JSONB,               -- ["service quality", "parking", ...]
    is_processed BOOLEAN,
    published_at TIMESTAMP
)

-- review_embeddings: separate table keeps the vector index lean
review_embeddings (
    id UUID PRIMARY KEY,
    review_id UUID REFERENCES reviews(id),
    embedding VECTOR(768)       -- HNSW cosine index
)

-- chat_messages: persists conversation history per business
chat_messages (
    id UUID PRIMARY KEY,
    business_id TEXT,
    role TEXT,                  -- user / assistant
    content TEXT,
    source_review_ids TEXT      -- comma-separated UUIDs for citations
)
```

**Embedding model:** `intfloat/multilingual-e5-base` — 768 dimensions, multilingual support (handles non-English reviews), runs locally in Docker (no API cost per embedding).

**HNSW index:** approximate nearest-neighbour search. Trades a small recall loss (~2%) for query times under 10ms even at 1M vectors.

### Why pgvector over Pinecone / Weaviate?

| | pgvector (current) | Pinecone | Weaviate |
|---|---|---|---|
| Operations | Single DB | Separate managed service | Separate Docker service |
| Join with structured data | Native SQL JOIN | Not possible (separate system) | GraphQL, complex |
| Cost | Included in PostgreSQL | $70+/month for production | Free self-hosted |
| Scale ceiling | ~10M vectors with HNSW | Unlimited managed | Unlimited |
| Operational complexity | Low | Low (managed) | Medium |

**Verdict:** pgvector is a safe and simple choice until the system hits ~10M vectors or need multi-region replication. At that scale, migrate to Pinecone for vectors and keep Postgres for structured data. For this project, keeping everything in one database makes joins, transactions, and schema migrations simpler.

---

## 4. RAG Pipeline

### Why RAG at all?

Without RAG, an LLM answering "what do customers complain about?" would hallucinate — it has no access to your specific business's reviews. RAG solves this by retrieving relevant reviews first, injecting them into the prompt as context, and forcing the LLM to answer from that context only.

**The alternative** — fine-tuning — would require thousands of labelled examples, GPU compute, and retraining whenever new reviews arrive. RAG retrieves fresh data at query time; no retraining needed.

### Two-stage retrieval: why both stages?

**Stage 1 — bi-encoder + pgvector (fast, approximate)**

The query and each document are embedded independently using `multilingual-e5-base`. Similarity is computed as cosine distance in vector space. This scales to millions of documents in milliseconds because HNSW reduces the search to logarithmic complexity. However, bi-encoders embed query and document separately, so they miss fine-grained relevance signals.

```python
# pipelines/rag/retriever.py
vector = model.encode(f"query: {query_text}", normalize_embeddings=True)
# pgvector HNSW: retrieve top-20 candidates
SELECT ... ORDER BY embedding <=> query_vec LIMIT 20
```

The `query:` prefix is required by multilingual-e5-base — it was trained with `passage:` for documents and `query:` for queries. Using the wrong prefix degrades recall measurably.

**Stage 2 — cross-encoder rerank (slow, precise)**

The cross-encoder reads the query and each candidate document **jointly** as a single input. This lets it model interactions between query terms and document terms — much more accurate than bi-encoder similarity. The tradeoff: it cannot be precomputed, so it runs at query time over all candidates. We apply it only to the 20 candidates from stage 1 to keep latency under 2 seconds.

```python
# pipelines/rag/retriever.py
pairs = [(query, chunk.content) for chunk in chunks]
scores = cross_encoder.predict(pairs)   # ms-marco-MiniLM-L6-v2
```

**Why this matters:** retrieve-20 then rerank-5 gives you the recall of returning 20 results with the precision of showing only the 5 best. A single-stage bi-encoder at top-5 misses relevant reviews that scored lower due to embedding approximation. A single cross-encoder over all documents would be seconds per query.

### Context builder and citations

`pipelines/rag/context_builder.py` formats the top-5 chunks into a numbered list with `[1]`, `[2]`, `[3]` citation markers. The system prompt instructs the LLM to cite every factual claim using these markers. The response includes `source_review_ids` so the frontend can link citations to the original reviews in the database.

### LangChain LCEL

The answer generation chain uses LangChain's LCEL (LangChain Expression Language):

```
prompt_template | llm | output_parser
```

LangChain is used here because it provides a clean abstraction over the OpenRouter API (OpenAI-compatible), handles streaming, and integrates with LangSmith tracing. The chain is simple enough that vanilla `httpx` would work, but LangChain makes it observable and swappable.

**Why OpenRouter instead of OpenAI directly?** OpenRouter is a proxy that gives access to Gemini, Mistral, LLaMA, and other models through a single OpenAI-compatible API. The model is configurable via `OPENAI_CHAT_MODEL` env var — switching from Gemini to Claude or GPT-4 requires changing one env var, no code changes.

---

## 5. Multi-Agent Layer

### Why multi-agent instead of a single agent with tools?

A single agent with all tools attached works but becomes unreliable as the number of tools grows (as demands grow). The LLM has to decide between retrieval, aggregation, ingestion, and clarification in every call — and with ambiguous queries it often picks the wrong tool.

The intent classifier solves this with **structured routing**: the first LLM call classifies the query into exactly one of four intents using `llm.with_structured_output(IntentClassification)`. The output is a Pydantic model — the LLM cannot return free-form text or an invalid intent label. The graph then routes to a specialist node that has exactly the tools and prompts it needs.

### Why LangGraph over a custom orchestration loop?

A custom loop (`while not done: call_llm()`) requires you to build state serialisation, interrupt/resume logic, and multi-turn memory from scratch. LangGraph provides all of this:

- **TypedDict state** (`AgentState`) — typed, validated at every node transition
- **MemorySaver** — serialises state per `thread_id` so the graph survives across HTTP requests
- **`interrupt()`** — pauses the graph mid-execution for human approval, then resumes exactly where it stopped
- **Conditional edges** — declarative routing, readable as a graph not spaghetti code

### The graph

```
START → intent_classifier → (conditional)
    → rag_node         (intent = "rag")
    → insight_node     (intent = "insight")
    → ingestion_node   (intent = "ingestion")  ← interrupt() here
    → clarification_node (intent = "clarification")
→ END
```

**`intent_classifier`** uses `llm.with_structured_output(IntentClassification)` — the Pydantic schema is injected into the API call as a JSON schema constraint. The LLM must return `intent`, `confidence`, and `reasoning` fields. This is the "structured prompts" pattern: instead of parsing free text, you enforce schema compliance at the API level.

**`rag_node`** calls `run_rag_pipeline()` — the same two-stage retrieval used by the direct `/api/chat` endpoint.

**`insight_node`** runs a SQL GROUP BY for sentiment distribution, aggregates topics with a Counter, then asks the LLM to synthesise a structured report with fixed sections (Overall Sentiment, Platform Breakdown, Top Topics, Recommendation).

**`ingestion_node`** parses the request, calls `interrupt()` with an approval message, and pauses. The HTTP response returns `pending_approval: true`. When the user calls `POST /{thread_id}/approve`, the graph resumes via `Command(resume=True)` and dispatches the Celery task.

### Human-in-the-loop — why it matters

Ingestion is a side-effect: it costs API credits, triggers background workers, and modifies the database. Letting an LLM trigger this autonomously based on a misclassified intent is risky. The `interrupt()` pattern forces explicit human confirmation before any external action, while keeping the flow conversational.

---

## 6. Critic / Validator Agent

### Current state: not built

This is the most significant gap vs the design spec. The current system has no mechanism to verify whether the RAG answer is actually grounded in the retrieved reviews. The LLM is instructed to only use provided context, but it can still hallucinate.

### What it would do

A critic node runs after `rag_node` and checks:
1. Every factual claim in the answer maps to a cited review `[1]`, `[2]`, etc.
2. The cited review actually contains the claimed information.
3. The answer does not contradict any retrieved review.

If the check fails, the critic either rewrites the answer (constrained to grounded facts) or returns a fallback ("I found reviews but couldn't generate a reliable answer").

### Implementation sketch

```python
class CriticOutput(BaseModel):
    is_grounded: bool
    issues: list[str]
    revised_answer: str | None

def critic_node(state: AgentState, settings: ServerSettings) -> dict:
    # extract citations from answer, match to source chunks
    # ask LLM: "does this answer follow only from these reviews?"
    classifier = llm.with_structured_output(CriticOutput)
    result = classifier.invoke([...])
    if not result.is_grounded:
        return {"messages": [AIMessage(content=result.revised_answer or FALLBACK)]}
    return {}  # no change
```

Add to graph: `rag_node → critic_node → END` with a conditional edge that skips the critic for insight and ingestion nodes.

---

## 7. Backend API

### What we built

FastAPI with six route groups:

| Route | Purpose |
|---|---|
| `POST /api/chat` | Direct RAG pipeline (no agent overhead) |
| `POST /api/agent/ask` | Full LangGraph agent (intent → specialist) |
| `POST /api/agent/{thread_id}/approve` | Resume HITL ingestion |
| `POST /api/agent/tools/*` | Direct tool endpoints (used by MCP server) |
| `POST /api/integrations/{platform}` | Trigger Celery ingestion task |
| `GET /api/reviews` | Filtered, paginated review list |
| `GET /api/insights/*` | Aggregated sentiment and topic stats |

### Why FastAPI?

- **Pydantic v2 validation**: request and response schemas are enforced at the framework level — no manual validation code
- **Async-ready**: `async def` routes handle concurrent requests without blocking; Celery handles CPU-bound work in separate processes
- **OpenAPI docs**: automatically generated at `/docs` — useful for testing and for the MCP server developer who needs to know endpoint contracts
- **Dependency injection**: `SessionDep` and `SettingsDep` inject DB sessions and config into routes without boilerplate

### Why two chat endpoints?

`POST /api/chat` skips intent classification and goes directly to RAG. It's faster (one fewer LLM call) and predictable — use it when you know the user is asking a retrieval question. `POST /api/agent/ask` adds intent routing, insight synthesis, and HITL ingestion — use it for open-ended questions. The frontend currently uses `/api/chat`; the MCP server uses `/api/agent/ask`.

---

## 8. Frontend

### What we built

Next.js 14 with App Router, TypeScript, Tailwind CSS:

| Page | What it does |
|---|---|
| `/dashboard` | Sentiment metrics, platform breakdown, review table with filters |
| `/ai-chat` | Chat interface calling `POST /api/chat`, citation display |
| `/reviews` | Full review browser with platform/sentiment/rating filters |
| `/settings/data-sources` | Trigger ingestion, search for businesses by name |

### Why custom frontend over Apache Superset?

| | Custom Next.js (current) | Apache Superset |
|---|---|---|
| Audience | End users (business owners) | Data analysts |
| Chat interface | Built-in | Not possible |
| Customisation | Full control | Limited to chart types |
| Maintenance | You own it | Superset upgrades |
| Setup | npm install | Docker stack + config |

Superset is the right tool for an internal analytics team that wants to write SQL and build charts without engineering. For an end-user product where the UI is part of the product, custom frontend is the correct choice. If you need to add complex charting (time series, funnel analysis), add `recharts` or `plotly` to the existing Next.js app.

### Current limitation

The `/ai-chat` page calls the **direct RAG endpoint** (`POST /api/chat`), not the full LangGraph agent (`POST /api/agent/ask`). This means intent routing, insight synthesis, and HITL ingestion are only accessible via MCP/Claude Desktop — not the web UI. Wiring the frontend to `/api/agent/ask` is a small change in `useChat.ts`.

---

## 9. MCP Layer

### Why MCP at all?

MCP solves a specific problem: AI assistants (Claude Desktop, Cursor, VS Code Copilot) cannot call arbitrary HTTP APIs by default. They need a standardised protocol to discover tools and call them. Without MCP, a user would have to copy-paste review data into Claude Desktop manually to get AI analysis.

With MCP, Claude Desktop can:
- Discover available tools automatically
- Choose which tool to call based on user intent
- Chain multiple tool calls (list businesses → search reviews → get sentiment)

MCP is the integration protocol layer. It does not contain business logic — every MCP tool is a thin HTTP wrapper over a FastAPI endpoint.

### Why FastMCP?

FastMCP generates the JSON schema from Python type annotations and docstrings, handles the stdio transport loop, and registers tools with `@mcp.tool()`. Without FastMCP you would write raw JSON-RPC 2.0 messages over stdin/stdout — ~500 lines of boilerplate.

### Transport: stdio vs SSE

The current setup uses `stdio` transport — Claude Desktop spawns `server.py` as a subprocess. This requires Claude Desktop to be installed locally.

To make the MCP server accessible remotely (Claude.ai web, custom clients, remote agents):

```python
# Change one line in mcp_server/server.py
mcp.run(transport="sse", host="0.0.0.0", port=8001)
```

Then add `mcp` as a service in `docker-compose.yml`. The server becomes a persistent HTTP service at `http://yourserver:8001/sse` that any MCP-compatible client can connect to by URL — no local install required.

### Tool design principle

Each MCP tool follows the same pattern:
1. Validate required args (return error string if missing, not exception)
2. One `httpx` call to the corresponding FastAPI endpoint
3. Return a plain string

Claude reads error strings and can recover (e.g. call `list_businesses()` if `business_id` is missing). If tools raise exceptions, the MCP client gets an opaque error with no recovery path.

### How Claude decides which tool to call

Claude reads the tool descriptions (docstrings) and decides based on the user's message. The descriptions are the interface contract between your code and Claude — they must be precise enough to distinguish between similar tools (`search_reviews` vs `ask_agent`), and they must tell Claude what to do when it's missing required information (call `list_businesses()` first).

---

## 10. Observability

### Current state

| Tool | Status | Config |
|---|---|---|
| LangSmith | Installed, disabled | `LANGCHAIN_TRACING_V2=false` in `.env` |
| Langfuse | Installed, not wired | No integration code |
| MLflow | Installed, not wired | No integration code |
| Structured logging | Active | `app/logger.py`, JSON format |

### What's missing

Without observability you cannot answer:
- Which intent does the classifier get wrong most often?
- How long does each node take? Where is the latency?
- Which queries return low-similarity results (RAG quality signal)?
- How often does the critic agent reject answers?

### Enabling LangSmith (30 minutes)

LangSmith traces every LangChain/LangGraph call automatically once the env vars are set:

```bash
# .env
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=ls__your_key_here
LANGCHAIN_PROJECT=customervoice-ai
```

No code changes needed. LangSmith captures: intent classification input/output, RAG retrieval results, node execution times, full message history per thread.

### What Langfuse adds over LangSmith

Langfuse tracks evaluation scores and lets you annotate traces with thumbs-up/down feedback. This enables building a labelled dataset from production traffic — the foundation for fine-tuning or systematic RAG evaluation. LangSmith is for debugging; Langfuse is for improvement loops.

### What MLflow adds

MLflow tracks experiments: if you test different embedding models, reranker thresholds, or prompt templates, MLflow records the parameters and metrics so you can compare runs. Relevant when you want to answer "does changing from top-20 retrieve to top-30 improve answer quality?"

### Recommended observability stack for this project

1. **Enable LangSmith now** — 30-minute setup, immediate value for debugging agent routing
2. **Add Langfuse** when you have real users — capture feedback to build an evaluation dataset
3. **MLflow** when you start experimenting with model parameters — not needed until then
