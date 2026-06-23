# AI Operational Intelligence — RAG Research Platform

A research and production engineering platform for **operational intelligence over customer signals**: ingest business reviews, extract entity relationships, and generate grounded answers using two RAG architectures evaluated head-to-head.

> **Research question:** For customer review Q&A, does GraphRAG's structural retrieval produce more faithful and complete answers than VectorRAG's semantic similarity — and at what latency/cost tradeoff?

---

## The Problem

A business operator asks:

```
"Why are customers complaining more about delivery delays this month?"
```

Answering this correctly requires:
- Evidence from **Google Reviews** (customer sentiment)
- Evidence from **Support Tickets** (escalation patterns)
- Evidence from **Call Logs** (voice complaint transcripts)
- Evidence from **Incident Data** (system outages, logistics events)
- **Correlation** across all sources — not retrieval from one

No single RAG architecture handles this well. This platform is designed to measure exactly where each one breaks.

---

## Data Sources — Business Signals

| Source | Signal Type | Ingestion Method |
|--------|-------------|-----------------|
|  Google Reviews | Customer sentiment, ratings | SerpAPI |

The data source is independently ingested, cleaned, chunked, embedded, and stored. Cross-source retrieval is the core technical challenge.

---

## RAG System Architectures Under Evaluation

Two architectures are benchmarked head-to-head — chosen because they represent fundamentally different retrieval strategies, not incremental tweaks:

### 1. VectorRAG *(baseline)*
Chunk → embed → top-K cosine search (pgvector HNSW) → cross-encoder rerank → LLM answer. The control system. Measures the floor: what you get with semantic similarity alone.

### 2. Graph RAG
Reviews are parsed into an entity-relationship graph. Queries traverse entity nodes and relationship edges — enabling reasoning like: "Which staff members are linked to both praise and complaints?". Structured retrieval over implicit connections that vector similarity misses.

**Why these two?** VectorRAG establishes a reproducible reference point. GraphRAG is the most architecturally distinct comparison — it changes *what* is retrieved (relationships vs. chunks), not just *how* chunks are ranked. This gives the clearest signal on whether structural understanding improves answer quality for customer review queries.

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        INGESTION LAYER                                  │
│  Google Reviews · Support Tickets · Call Logs · Docs · GitHub · Incidents│
│                              ↓                                          │
│              Celery Workers (async, per-source)                         │
│         clean → chunk → enrich → embed → store                         │
└─────────────────────────────────────────────────────────────────────────┘
                               ↓
┌─────────────────────────────────────────────────────────────────────────┐
│                         STORAGE LAYER                                   │
│                                                                         │
│  PostgreSQL + pgvector    ←──  primary vector store (HNSW)              │
│  Graph DB (networkx / Neo4j)   ←──  entity + relationship store         │
└─────────────────────────────────────────────────────────────────────────┘
                               ↓
┌─────────────────────────────────────────────────────────────────────────┐
│                    RAG EXECUTION LAYER                                  │
│                                                                         │
│        ┌──────────────────────────┐  ┌──────────────────────────┐       │
│        │       VectorRAG          │  │        GraphRAG          │       │
│        │  chunk → embed → HNSW    │  │  entity-relationship     │       │
│        │  → rerank → LLM answer   │  │  graph traversal → LLM   │       │
│        └──────────────────────────┘  └──────────────────────────┘       │
│                                                                         │
│  Each system exposes: POST /api/rag/{system_type}/query                 │
└─────────────────────────────────────────────────────────────────────────┘
                               ↓
┌─────────────────────────────────────────────────────────────────────────┐
│                     EVALUATION LAYER                                    │
│                                                                         │
│  Retrieval:   Recall@K · Precision@K · MRR · nDCG                      │
│  Answer:      Faithfulness · Relevance · Completeness · Hallucination   │
│  Evidence:    Citation coverage · Source diversity · Consistency        │
│  System:      Latency · Cost/query · Token usage · Failure rate         │
│                                                                         │
│  MLflow  ←── experiment tracking (all runs, all systems)               │
│  LangSmith ←── trace visibility (prompt → retrieval → LLM)             │
│  RAGAS + DeepEval ←── automated metric computation                     │
└─────────────────────────────────────────────────────────────────────────┘
                               ↓
┌─────────────────────────────────────────────────────────────────────────┐
│                      INTELLIGENCE LAYER                                 │
│                                                                         │
│  Cross-source correlation engine                                        │
│  Root cause hypothesis ranking                                          │
│  Temporal trend detection (before/after event windows)                  │
│  Actionable recommendation synthesis                                    │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Evaluation Framework

### Evaluation Dataset Schema

```json
{
  "query": "Why are delivery complaints increasing?",
  "expected_sources": ["google_reviews", "support_tickets", "call_logs"],
  "expected_signals": ["late_delivery", "driver_shortage", "logistics_delay"],
  "expected_root_causes": ["warehouse backlog", "courier capacity drop"],
  "time_window": "last_30_days"
}
```

### Metrics — Common Across All Systems

**Retrieval Quality**
- `Recall@K` — did the top-K results contain the expected evidence?
- `Precision@K` — what fraction of top-K results were actually relevant?
- `MRR` — how high did the first relevant result rank?
- `nDCG` — did more relevant results rank higher than less relevant ones?

**Answer Quality**
- `Faithfulness` — is every claim in the answer grounded in retrieved evidence?
- `Answer Relevance` — does the answer address what was asked?
- `Completeness` — did it cover all expected signals?
- `Hallucination Rate` — claims made with no supporting evidence

**Evidence Quality**
- `Citation Coverage` — percentage of answer claims with a cited source
- `Source Diversity` — how many distinct sources contributed to the answer
- `Evidence Consistency` — do sources agree, or contradict each other?

**System Metrics**
- `End-to-end latency` (P50, P99)
- `Cost per query` (token usage × model price)
- `Failure rate` (no answer, timeout, error)

### Metrics — System-Specific

| RAG System | Additional Metric | Why |
|------------|------------------|-----|
| VectorRAG | Retrieval latency · token cost per query | Efficiency baseline for comparison |
| GraphRAG | Edge/path accuracy · false relationship rate | Graph correctness independent of answer quality |

### Evaluation Best Practices

**1. Evaluate per layer, not just end-to-end**
```
Retrieval → Ranking → Reasoning → Final Answer
```
An end-to-end score masks where the system broke. A correct retrieval + bad reasoning is a different failure than bad retrieval + correct reasoning.

**2. Track failure modes explicitly**
- Missing retrieval (relevant chunk not returned)
- Wrong retrieval (irrelevant chunk ranked first)
- Correct retrieval, wrong reasoning
- Hallucination despite correct evidence

**3. Cross-source evaluation**
Every test query must involve at least two sources. Single-source retrieval tests don't reveal cross-modal alignment failures.

**4. Temporal evaluation**
- Before/after event comparisons
- Trend detection accuracy
- Causal ordering correctness (did the incident precede the complaints?)

### Cross-System Comparison

| System | Core Strength | Key Metric Focus | Main Weakness |
|--------|--------------|-----------------|---------------|
| VectorRAG | Simplicity, speed | Faithfulness · Recall@K | Misses entity relationships |
| GraphRAG | Relational reasoning | Context precision · Edge accuracy | Slower, graph quality-dependent |

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| **LLM** | Google Gemini 2.0 Flash via OpenRouter (OpenAI-compatible) |
| **Embeddings** | Google text-embedding-004 / benchmarked against Cohere, OpenAI |
| **Vector Store** | PostgreSQL + pgvector (HNSW index) |
| **Graph Store** | networkx / Neo4j (Graph RAG) |
| **Agents** | LangGraph (stateful multi-agent orchestration, HITL) |
| **Observability** | LangSmith (traces) · MLflow (experiments) |
| **Evaluation** | RAGAS · DeepEval · custom metrics |
| **Backend** | FastAPI · SQLAlchemy 2.0 · Pydantic v2 · Alembic |
| **Task Queue** | Celery + Redis |
| **Frontend** | Next.js 14 · TypeScript · Tailwind CSS · TanStack Query |
| **Infrastructure** | Docker Compose (local) · AWS ECS Fargate + RDS + ElastiCache (production) |
| **IaC** | Terraform |
