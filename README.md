# AI Operational Intelligence — RAG Research Platform

A research and production engineering platform for **cross-source operational intelligence**: ingest multi-modal business signals, correlate evidence across data streams, and generate grounded root-cause hypotheses using multiple RAG system architectures evaluated head-to-head.

> **Research question:** Given the same business query and the same data, which RAG architecture produces the most faithful, complete, and actionable answer — and at what cost?

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

## Data Sources — Multi-Modal Business Signals

| Source | Signal Type | Ingestion Method |
|--------|-------------|-----------------|
|  Google Reviews | Customer sentiment, ratings | SerpAPI |

The data source is independently ingested, cleaned, chunked, embedded, and stored. Cross-source retrieval is the core technical challenge.

---

## RAG System Architectures Under Evaluation

Six architectures are benchmarked against the same queries, the same data, and the same evaluation framework:

### 1. Baseline RAG
Chunk → embed → top-K cosine search → LLM answer. The control system. Measures the floor: what you get with no architectural sophistication.

### 2. Hybrid RAG
BM25 keyword search + vector cosine search, results fused via RRF (Reciprocal Rank Fusion). Stronger recall on named entities, product names, and rare terms that dense embeddings miss.

### 3. RAG-as-a-Service
Delegates retrieval and generation to a managed API (OpenAI Assistants, Vertex AI Search, Glean). Measures the tradeoff: zero infrastructure cost vs. observability black-box.

### 4. Graph RAG
Reviews, tickets, and incidents are parsed into an entity-relationship graph. Queries traverse entity nodes and relationship edges — enabling reasoning like: "What engineering incidents correlate with spikes in delivery complaints?". Structured reasoning over implicit connections.

### 5. Agentic RAG
A multi-step reasoning agent decides which sources to query, in what order, and whether intermediate results warrant a follow-up retrieval. Models the diagnostic workflow of a human analyst: hypothesis → evidence → refine.

### 6. Multi-Modal RAG
Embeds and retrieves across modalities: text reviews, audio call transcripts, image attachments, structured log tables. Cross-modal alignment is the key metric challenge.

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
│  Graph DB (Neo4j / networkx)   ←──  entity + relationship store         │
│  BM25 Index (Elasticsearch / Tantivy) ←──  keyword search index         │
│  Object Store (S3)        ←──  raw audio, PDFs, images                  │
└─────────────────────────────────────────────────────────────────────────┘
                               ↓
┌─────────────────────────────────────────────────────────────────────────┐
│                    RAG EXECUTION LAYER                                  │
│                                                                         │
│  ┌──────────────┐  ┌────────────┐  ┌───────────┐  ┌─────────────────┐  │
│  │ Baseline RAG │  │ Hybrid RAG │  │ Graph RAG │  │  Agentic RAG    │  │
│  │ chunk→embed  │  │ BM25+vec   │  │ entity    │  │  LangGraph      │  │
│  │ →top-K→LLM   │  │ →RRF→LLM  │  │ traversal │  │  multi-step     │  │
│  └──────────────┘  └────────────┘  └───────────┘  └─────────────────┘  │
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
| Hybrid RAG | Ranking stability (BM25 vs vector conflict rate) | Measures fusion quality |
| Graph RAG | Edge/path accuracy, false relationship rate | Graph correctness |
| Agentic RAG | Task success rate, planning efficiency (steps taken vs optimal) | Agent reasoning quality |
| Multi-Modal RAG | Cross-modal alignment score | Modality mismatch detection |
| RAG-as-a-Service | Traceability score (can you explain why this was retrieved?) | Black-box risk |

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
| Baseline RAG | Simplicity | Recall@K | Missing cross-source context |
| Hybrid RAG | Better recall | Ranking stability | Retrieval conflict |
| RAG-as-a-Service | Scalability | Traceability | Black box |
| Graph RAG | Relational reasoning | Edge/path accuracy | False relationships |
| Agentic RAG | Autonomy | Task success rate | Poor planning |
| Multi-Modal RAG | Signal richness | Cross-modal alignment | Modality mismatch |

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| **LLM** | Google Gemini 2.0 Flash via OpenRouter (OpenAI-compatible) |
| **Embeddings** | Google text-embedding-004 / benchmarked against Cohere, OpenAI |
| **Vector Store** | PostgreSQL + pgvector (HNSW index) |
| **Graph Store** | Neo4j / networkx (Graph RAG) |
| **Keyword Index** | BM25 via Elasticsearch / Tantivy (Hybrid RAG) |
| **Agents** | LangGraph (stateful multi-agent orchestration, HITL) |
| **Observability** | LangSmith (traces) · MLflow (experiments) |
| **Evaluation** | RAGAS · DeepEval · custom metrics |
| **Backend** | FastAPI · SQLAlchemy 2.0 · Pydantic v2 · Alembic |
| **Task Queue** | Celery + Redis |
| **Frontend** | Next.js 14 · TypeScript · Tailwind CSS · TanStack Query |
| **Infrastructure** | Docker Compose (local) · AWS ECS Fargate + RDS + ElastiCache (production) |
| **IaC** | Terraform |
