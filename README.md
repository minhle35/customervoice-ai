# CustomerVoice AI

An end-to-end AI application that aggregates customer reviews from Google Maps, Reddit(future features), and Facebook(future features), enriches them with LLM-powered analysis, and surfaces actionable insights through a real-time dashboard and RAG-based AI assistant.

Built as a personal R&D project to learn and demonstrate production AI engineering practices — from data ingestion pipelines to agentic workflows and vector similarity search.

---

## What It Does

1. **Ingests** reviews from Google Maps (via SerpAPI) into PostgreSQL — deduplicated, cleaned, and normalised
2. **Enriches** each review with LLM-based sentiment classification and topic extraction (Google Gemini 2.0 Flash via OpenRouter)
3. **Embeds** reviews using a local multilingual sentence-transformer model, stored in pgvector with an HNSW index
4. **Retrieves** relevant reviews semantically for any natural language query — cosine similarity search + cross-encoder re-ranking
5. **Answers** business questions grounded in real review data via a RAG pipeline with citation support
6. **Visualises** metrics, sentiment trends, and review volume on a live Next.js dashboard

---

## AI Engineering Skills Demonstrated

### Large Language Models & Prompt Engineering
- Combined sentiment classification + topic extraction in a single LLM call using structured prompt design
- Prompt-based JSON extraction with regex fallback for handling unstructured model output — avoids `response_format` lock-in across providers
- OpenAI-compatible client (OpenRouter) enabling model-agnostic swap between Gemini, Claude, GPT-4o, Llama

### RAG — Retrieval-Augmented Generation
- Vector embeddings generated locally using `intfloat/multilingual-e5-base` (sentence-transformers, 768 dims) — multilingual, Vietnamese-capable, zero API cost
- pgvector with HNSW index for sub-millisecond approximate nearest-neighbour search
- Correct `query:` / `passage:` prefix convention for retrieval quality (multilingual-e5 requirement)
- Cross-encoder re-ranking (`cross-encoder/ms-marco-MiniLM-L-6-v2`): retrieve top-20 candidates → re-rank → keep top-5 for LLM context
- Token-budgeted context builder with citation markers `[1][2][3]` for grounded, traceable answers

### Agentic Workflows & Orchestration *(in progress — Phase 3)*
- LangGraph multi-agent system: Intent Agent → Clarification Agent → Ingestion Agent → Analysis Agent → Insight Agent
- Human-in-the-loop confirmation before triggering ingestion (LangGraph interrupt/resume pattern)
- Tool-calling agents: `search_reviews`, `get_sentiment_summary`, `trigger_ingestion`, `resolve_business`
- LangChain LCEL chains for composable LLM pipelines with provider-agnostic swap

### LLM Observability *(in progress — Phase 2)*
- LangSmith integration for full trace visibility: prompt → retrieval scores → LLM latency → token cost
- Custom metadata per trace: `business_id`, `query`, `retrieved_chunks_count`, `rerank_scores`

### Evaluation Framework *(in progress — Phase 4)*
- DeepEval test suite: `FaithfulnessMetric`, `AnswerRelevancyMetric`, `ContextualRecallMetric`, `HallucinationMetric`
- Golden dataset of 30 QA pairs with ground-truth review citations
- MLflow experiment tracking: compare prompt versions, retrieval configs, eval scores across runs
- CI integration: `pytest -m evaluation` fails build if faithfulness drops below threshold

### Data Pipelines & Async Processing
- Multi-source ingestion pipeline (Google Maps via SerpAPI) with stable deduplication IDs
- Celery + Redis async task queue: ingestion, LLM processing, and embedding generation run as background jobs
- Rate-limit resilience: per-review `RateLimitError` catch stops the loop cleanly without retrying already-processed records
- Alembic schema migrations for vector dimension changes (1536 → 768 with HNSW index rebuild)

### Backend Engineering
- FastAPI with Pydantic v2 schemas, SQLAlchemy 2.0 ORM, dependency injection
- REST API: `POST /api/integrations/{platform}`, `GET /api/reviews` (filtered + paginated), `POST /api/chat`
- PostgreSQL with pgvector extension — relational + vector storage in one database
- Docker Compose: FastAPI, Celery worker, PostgreSQL + pgvector, Redis — one-command local stack

### Frontend
- Next.js 14 App Router with TypeScript and Tailwind CSS
- TanStack Query for server state, optimistic loading states, skeleton UI
- Dashboard: live metric cards, sentiment trend chart, review volume chart, platform distribution donut
- Reviews table: platform filter, sentiment filter, pagination

---

## Architecture

```
Google Maps (SerpAPI)
        │
        ▼
Celery Worker (async)
  ├── clean_review_text()
  ├── analyze_sentiment_and_topics()  ← Google Gemini 2.0 Flash via OpenRouter
  ├── generate_embedding()            ← sentence-transformers (local, free)
  └── upsert → PostgreSQL + pgvector
        │
        ▼
POST /api/chat  (RAG pipeline)
  ├── embed_query()                   ← `query:` prefix
  ├── pgvector cosine search (HNSW)   ← top-20 candidates
  ├── cross-encoder rerank()          ← top-5 final context
  ├── build_context()                 ← token-budgeted, cited [1][2][3]
  └── LangChain LLM chain             ← grounded answer with citations
        │
        ▼
Next.js Dashboard
  └── metrics / charts / AI chat UI
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| **LLM** | Google Gemini 2.0 Flash (via OpenRouter), LangChain LCEL |
| **Embeddings** | `intfloat/multilingual-e5-base` (sentence-transformers, local) |
| **Vector DB** | PostgreSQL + pgvector, HNSW index |
| **Re-ranking** | `cross-encoder/ms-marco-MiniLM-L-6-v2` |
| **Agents** | LangGraph (multi-agent orchestration) |
| **Observability** | LangSmith |
| **Evaluation** | DeepEval + MLflow |
| **Backend** | FastAPI, SQLAlchemy 2.0, Pydantic v2, Alembic |
| **Task Queue** | Celery + Redis |
| **Database** | PostgreSQL 16 (pgvector) |
| **Frontend** | Next.js 14, TypeScript, Tailwind CSS, TanStack Query |
| **Infrastructure** | Docker Compose (local) · AWS ECS Fargate + RDS + ElastiCache (production) |
| **IaC** | Terraform |

---

## Project Structure

```
customervoice-ai/
├── backend/
│   ├── app/
│   │   ├── api/          # FastAPI routes (reviews, chat, integrations)
│   │   ├── models/       # SQLAlchemy models (Review, ReviewEmbedding)
│   │   ├── schemas/      # Pydantic request/response schemas
│   │   └── services/     # ReviewService, EmbeddingService, RAGService
│   ├── alembic/          # Database migrations
│   └── tests/            # Unit + integration + evaluation tests
├── pipelines/
│   ├── ingestion/        # Google Maps, Reddit, Facebook scrapers
│   ├── processing/       # Text cleaning, sentiment analysis (LangChain)
│   ├── embeddings/       # generate_embedding() with passage: prefix
│   ├── rag/              # retriever, context_builder, answer_generator
│   └── orchestration/    # pipeline_runner
├── workers/
│   ├── celery_app.py
│   └── tasks.py          # ingest_platform, process_unprocessed_reviews
├── frontend/             # Next.js 14 dashboard
├── infrastructure/       # Terraform — AWS ECS, RDS, ElastiCache, WAF
└── docs/
    ├── RAG_plan.md
    ├── Checklist_March_24.md
    ├── AI_engineer_role_research.md
    └── aws-production-checklist.md
```

---

## Key Design Decisions

**Why Google Gemini 2.0 Flash via OpenRouter?**
Gemini 2.0 Flash offers a strong balance of speed, cost, and instruction-following quality for structured JSON extraction tasks (sentiment + topic). Accessing it through OpenRouter keeps the integration provider-agnostic — swapping to Claude or GPT-4o requires changing one config value, not rewriting API clients. Gemini 2.0 Flash also has full system prompt support, which is required for the structured output prompts used in this pipeline.

**Why local embeddings instead of OpenAI?**
`intfloat/multilingual-e5-base` runs locally (zero API cost), produces 768-dimensional vectors, and handles Vietnamese natively — critical for a review dataset that mixes English and Vietnamese. OpenAI's `text-embedding-3-small` charges per token and has weaker multilingual performance on Southeast Asian languages. The model requires `query:` / `passage:` prefix convention to distinguish retrieval queries from indexed documents, which is a deliberate design detail that improves recall quality.

**Why retrieve-20 then re-rank to 5?**
HNSW is fast but approximate — it finds vectors that are close in embedding space, not necessarily the most semantically relevant to the query. The cross-encoder reads query and document together (slower, more accurate). Retrieving 20 cheap candidates then re-ranking to 5 precise ones is the industry-standard two-stage retrieval pattern.

**Why Celery instead of FastAPI background tasks?**
Review ingestion calls SerpAPI (external HTTP), runs LLM inference (slow), and generates embeddings (CPU-intensive). Celery decouples this from the HTTP request lifecycle, handles retries with exponential backoff, and allows horizontal worker scaling independently from the API server.
