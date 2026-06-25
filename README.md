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
Chunk → embed → top-K cosine search (pgvector HNSW) → cross-encoder rerank → LLM answer. The control system. Measures the floor: what you get with semantic similarity alone. This is the architecture from the original RAG paper, Lewis et al. 2020, *[Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks](https://arxiv.org/abs/2005.11401)* — combine pretrained parametric memory (the LLM) with non-parametric memory (a retrievable corpus) to reduce hallucination on knowledge-intensive tasks.

### 2. GraphRAG
Reviews are parsed into an entity-relationship graph. Queries traverse entity nodes and relationship edges — enabling reasoning like: "Which staff members are linked to both praise and complaints?". Structured retrieval over implicit connections that vector similarity misses. Follows the design introduced by Microsoft Research's *[From Local to Global: A Graph RAG Approach to Query-Focused Summarization](https://arxiv.org/abs/2404.16130)* (Edge et al., 2024) — automate entity/relationship extraction with an LLM, build a knowledge graph, and traverse it instead of nearest-neighbor search. Reference implementation: [microsoft/graphrag](https://github.com/microsoft/graphrag).

**Why these two?** VectorRAG establishes a reproducible reference point. GraphRAG is the most architecturally distinct comparison — it changes *what* is retrieved (relationships vs. chunks), not just *how* chunks are ranked. This gives the clearest signal on whether structural understanding improves answer quality for customer review queries.

**This is genuinely an open question, not a foregone conclusion.** A 2025 benchmark, *[When to use Graphs in RAG: A Comprehensive Analysis for Graph Retrieval-Augmented Generation](https://arxiv.org/abs/2506.05690)* (Xiang et al.), reports that GraphRAG **frequently underperforms vanilla vector RAG** on real-world tasks despite its added complexity and cost — graph structure only pays off on queries that genuinely require multi-hop reasoning. That's exactly the empirical question this platform's benchmark is built to answer for *this* dataset and *these* query types, rather than assuming either architecture wins by default.

### What the two architectures share

Despite the radically different internal data structures, both systems exist to solve the same underlying problem and follow the same operational shape:

- **The grounding premise** — both inject external, non-parametric evidence into the prompt before generation, to keep answers within the model's actual context window and reduce hallucination (Lewis et al., 2020, [arXiv:2005.11401](https://arxiv.org/abs/2005.11401)).
- **The same Index → Retrieve → Generate loop** — only the indexing/retrieval stage differs; the final generation step (prompt the LLM with a payload of grounding text) is identical.
- **Embeddings aren't exclusive to VectorRAG** — Microsoft's own GraphRAG implementation still uses vector embeddings internally, for entity resolution (merging synonymous mentions into one node) and for indexing community summary text ([arXiv:2404.16130](https://arxiv.org/abs/2404.16130)).
- **Both risk context fragmentation** — VectorRAG can retrieve chunks that share surface keywords but not real relevance; GraphRAG can pull oversized subgraphs or community reports that bury the LLM in irrelevant relational detail.

### Shared output contract

Both systems return the same `RAGResult` shape (`pipelines/base.py`), which is what makes a single evaluation harness possible:

```python
@dataclass
class RAGResult:
    answer: str           # grounded LLM answer with citation markers
    contexts: list[str]    # grounding evidence as flat text — review chunks for
                            # VectorRAG, serialized graph paths for GraphRAG
    source_ids: list[UUID] # review ids cited, for provenance
```

`contexts: list[str]` is the load-bearing field — it's exactly the shape RAGAS's `SingleTurnSample.retrieved_contexts` expects, regardless of whether the underlying retrieval was a vector search or a graph traversal. Each system can additionally return a richer subclass (`VectorRAGResult` with per-chunk scores, `GraphRAGResult` with node/edge topology) for debugging or UI rendering, without breaking anything that only consumes the base `RAGResult` contract — `pipelines/registry.py`, the eval harness, and the FastAPI route all only need `answer`/`contexts`/`source_ids`.

### Distinguishing features

```
  [ VECTORRAG ]                              [ GRAPHRAG ]
┌────────────────┐                         ┌────────────────┐
│ ┌───┐    ┌───┐ │                         │  (A) ───► (B)  │
│ │   │ ↔  │   │ │    vs.                  │   │        │   │
│ └───┘    └───┘ │                         │   ▼        ▼   │
│ Semantic Space │                         │  (C) ◄─── (D)  │
└────────────────┘                         └────────────────┘
```

| | VectorRAG | GraphRAG |
|---|---|---|
| **Data layout** | Flat pool of isolated, high-dimensional points (text chunks) | Structured nodes (entities) + edges (explicit relationships) |
| **Retrieval logic** | Local semantic similarity — cosine/Euclidean distance | Relational intelligence — subgraph extraction, traversal, community detection |
| **Answers** | "What text sounds similar to this question?" | "How are the entities in this question connected?" |
| **Optimal query type** | Single-hop, localized fact lookups | Multi-hop reasoning, cross-document aggregation, thematic summarization |
| **Indexing cost** | Low — one-pass embed-and-store | High — multi-pass LLM extraction, ongoing graph schema maintenance |

### Key Implementation Decisions

Four decisions, each with a deliberate tradeoff, shape how both systems are actually built:

| Decision | Choice | Why | Tradeoff accepted |
|---|---|---|---|
| **Package structure** | `pipelines/vector_rag/` + `pipelines/graph_rag/` as sibling packages, registered by name in `pipelines/registry.py` | Symmetric naming matches the VectorRAG/GraphRAG framing above; makes it obvious these are interchangeable implementations of one contract, not "the real one" plus an add-on | One-time import-path churn across ~8 files during the rename |
| **Entity/relationship extraction** | LLM-based (reusing the existing OpenRouter/LangChain setup), not a dedicated NER library | Matches Microsoft's GraphRAG paper design already cited above; zero new dependencies; NER libraries extract entities but not relationships, so an LLM step would be needed regardless | One LLM call per review at ingestion time — acceptable since ingestion is an async Celery task, not a latency-sensitive user-facing path |
| **Graph storage** | New Postgres tables (`entities`, `entity_relationships`, FK'd to `reviews.id`) + `networkx` for in-memory traversal at query time — no dedicated graph database | Zero new infrastructure; same connection pool, backup, and transactional consistency as everything else; preserves "scientific control" for the benchmark — both systems run on identical hardware and storage engine, so a quality difference is attributable to algorithm, not database vendor | `networkx` reloads the relevant subgraph fresh per query and doesn't scale past what comfortably fits in memory — acceptable at this project's per-business scale (hundreds of reviews); revisit (Apache AGE or Neo4j) only if a real bottleneck shows up in practice |
| **Answer generation** | One shared `generate_answer(question, contexts: list[str], ...)` used by both systems, instead of two system-specific copies | The prompt only needs a question and budget-limited citation text — it doesn't care whether that text came from review chunks or serialized graph paths. Duplicating LLM-calling/prompt logic means every future prompt tweak has to be made twice and kept in sync by hand | A small refactor of already-working VectorRAG code (and its callers) was required up front, before any GraphRAG-specific code existed |

The graph-storage decision is deliberately cheap to revisit later: `pipelines/graph_rag/retriever.py`'s subgraph-loading function is the only place that would need to change to swap `networkx` for Apache AGE or Neo4j — everything above it (`service.py`, `context_builder.py`, the registry, the eval harness, all tests) only consumes the `GraphNode`/`GraphEdge`/`RAGResult` contract, never the storage engine that produced them.

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
│  PostgreSQL entities/entity_relationships + networkx ←── graph store    │
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

A golden dataset of business questions with human-written ground-truth answers, run through both systems identically (`backend/tests/evaluation/golden_dataset.json`):

```json
{
  "question": "What do customers say about the food quality?",
  "ground_truth": "Customers generally praise the food quality, mentioning specific dishes positively and describing flavours as good value for money.",
  "expected_signals": ["food quality", "dishes", "flavour"],
  "min_faithfulness": 0.7,
  "min_context_recall": 0.5
}
```

A valid comparison needs three layers of metrics: a level playing field both systems are judged on equally, plus diagnostics specific to each retrieval mechanism.

### Layer 1 — Common Metrics (the level playing field)

Computed identically for both systems via [RAGAS](https://github.com/explodinggradients/ragas) ([Es et al., 2023, arXiv:2309.15217](https://arxiv.org/abs/2309.15217)) against the same golden dataset — see `backend/tests/evaluation/eval_rag.py`:

- `Faithfulness` — is every claim in the answer grounded in the retrieved context, with no hallucination?
- `Answer Relevance` — does the answer actually address the question asked?
- `Context Precision` — are the most relevant pieces of evidence ranked highest?
- `Context Recall` — did retrieval capture everything needed to support the ground-truth answer?
- `End-to-end latency` and `cost per query` — GraphRAG's multi-pass indexing and multi-hop traversal are expected to cost more; this is the metric that makes the cost/quality tradeoff explicit.

### Layer 2 — VectorRAG-specific diagnostics

These measure the math of the embedding space and the quality of retrieval ranking, independent of the final answer:

- `Hit Rate` / `MRR` (Mean Reciprocal Rank) — classic IR metrics: was the right chunk retrieved at all, and how high did it rank?
- `Context noise ratio` — how many of the top-K chunks share surface keywords with the query but aren't actually relevant (the "context fragmentation" failure mode common to dense retrieval)?
- `Embedding space distribution` — cosine-distance clustering across the corpus, to catch embedding drift or over-crowded vector regions.

### Layer 3 — GraphRAG-specific diagnostics

Chunk-similarity metrics don't apply to a graph — correctness here is topological, following [GraphRAG-Bench](https://arxiv.org/abs/2506.02404) ([Xiao et al., 2025](https://github.com/GraphRAG-Bench/GraphRAG-Benchmark)):

- `Triple accuracy` — are extracted (subject, predicate, object) relationships correctly mapped and relevant to the query?
- `Entity connectivity` — ratio of connected vs. isolated nodes at index time, as a graph-quality signal.
- `Rationale realization (R-Score)` — does the actual traversal path match a logically sound expert reasoning path, or did the system arrive at a lucky-guess answer via an unjustified route?
- `Global vs. local search efficiency` — does following immediate node neighbors (local) or summarizing whole node clusters (global) work better for a given query type?

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
| VectorRAG | Simplicity, speed | Faithfulness · Context Recall | Misses entity relationships |
| GraphRAG | Relational reasoning | Context Precision · Triple accuracy | Slower, graph quality-dependent |

---

## Designed for Debuggability

A wrong answer from either system is not a single failure — it's the *output* of a multi-stage pipeline, and the fix is completely different depending on which stage actually broke. This platform's architecture is built around isolating those stages, following the same per-stage diagnostic principle used in production RAG research rather than treating "the answer was wrong" as one undifferentiated bug.

### The research behind it

**[The RAG Triad](https://www.trulens.org/getting_started/core_concepts/rag_triad/)** (TruLens/TruEra, 2023) is the foundational framework: score **Context Relevance** (did retrieval pull back the right evidence?), **Groundedness** (does the answer logically follow from that evidence?), and **Answer Relevance** (does the final answer address the question?) *separately*. A wrong answer with high groundedness but low context relevance is a retrieval bug; high context relevance with low groundedness is a generation bug. Conflating the two and only measuring the end-to-end answer hides which stage to actually fix.

**[Barnett et al., 2024, "Seven Failure Points When Engineering a Retrieval Augmented Generation System"](https://arxiv.org/abs/2401.05856)** — an empirical taxonomy from three production RAG deployments. Failure points directly relevant to this codebase: *Missing Content* (the answer isn't in the corpus — an ingestion gap, not a retrieval bug), *Missed Top-Ranked Documents* (the answer exists but didn't survive top-K — a retrieval/reranking bug), and *Not Extracted* (the right evidence was retrieved but the LLM failed to use it — a generation bug).

**[Liu et al., 2023, "Lost in the Middle: How Language Models Use Long Contexts"](https://arxiv.org/abs/2307.03172)** ([code](https://github.com/nelson-liu/lost-in-the-middle)) — LLMs attend far more to the start/end of a prompt than the middle (U-shaped attention). A correctly retrieved, correctly reranked chunk can still be ignored if it lands in the middle of the context window — a distinct failure mode from retrieval *or* reasoning, specifically about chunk ordering.

**GraphRAG failure analysis** (2026 research, including [a model-internal study of why RAG fails](https://arxiv.org/abs/2605.14192)) converges on a three-way split unique to graph-based retrieval: **extraction errors** (the LLM mis-extracts entities/relationships when building the graph — wrong triples baked in at index time, a stage VectorRAG doesn't have at all), **retrieval errors** (correct graph, but traversal follows the wrong relation or neighbor at query time), and **generation errors** (the right subgraph was retrieved, but the LLM still reasoned over it incorrectly).

**GraphRAG failure taxonomy**
(practitioner research, 2026) — three-way split: extraction errors (graph construction), retrieval errors (traversal/relation selection), generation errors (reasoning over a correct subgraph) — GraphRAG's extraction stage is the failure mode VectorRAG doesn't have.

### How the codebase applies this

| Stage | VectorRAG | GraphRAG |
|---|---|---|
| **Index/Extraction** | `pipelines/vector_rag/retriever.py::embed_query` — unit-tested in isolation against a mocked encoder | Entity/relationship extraction into the graph store — the failure mode VectorRAG structurally cannot have |
| **Retrieval** | `retrieve()` — pgvector HNSW cosine search, tested against a *real* Postgres instance in `backend/tests/integration/test_rag_pipeline.py` so retrieval bugs show up against the actual index, not a mock | Graph traversal/relation selection — same principle once implemented: test against a real graph, not a mocked one |
| **Reranking** | `rerank()` — cross-encoder scores are inspectable per-chunk; `backend/tests/evaluation/debug_eval_rag.py` prints each of the top-5 reranked chunks with the RAGAS judge's per-chunk verdict, making it possible to see *exactly* which chunk should have ranked higher | Equivalent: which node/edge in the retrieved subgraph should have been prioritized |
| **Generation** | RAGAS `Faithfulness` isolates "the LLM had correct evidence and still got it wrong" from retrieval/reranking failures | Same metric, same isolation — `pipelines/base.py`'s shared `RAGResult.contexts` contract means generation-stage debugging works identically for both systems |
| **Full-pipeline tracing** | `@traceable` on `run_rag_pipeline` (`backend/app/services/rag_service.py`) sends the complete prompt → retrieval → LLM trace to LangSmith for every request, regardless of which system served it | Same decorator, same trace visibility — debugging tooling doesn't need to be rebuilt per system |

This is also why `pipelines/registry.py` and the shared `RAGResult` contract matter for debugging, not just for benchmarking: because both systems return the same shape (`answer`, `contexts`, `source_ids`), a bad answer can be diagnosed with the same per-stage checklist regardless of which architecture produced it — only the *internals* of the retrieval stage differ.

### From manual debugging to automated self-correction

Everything above is a human-in-the-loop workflow: a developer runs `eval_rag.py` or `debug_eval_rag.py`, reads the output, and decides what to fix. The natural next step is closing that loop automatically — when a metric fails its threshold (`eval_rag.py`'s existing `THRESHOLDS` dict), have the system request a new answer itself rather than just reporting failure. There's a meaningful skill progression in *how* that retry is implemented:


**1. Feedback-conditioned regeneration.** A blind retry can fail the same way twice. Following [Shinn et al., 2023, "Reflexion: Language Agents with Verbal Reinforcement Learning"](https://arxiv.org/abs/2303.11366) ([code](https://github.com/noahshinn/reflexion)) — verbal feedback from a failed attempt fed back into the next attempt's prompt, with no model retraining required — capture *why* the metric failed (e.g., the Faithfulness judge's stated `reason`, or which specific chunk `NoiseSensitivity`/`ContextPrecision` flagged as unhelpful) and inject it as an explicit correction instruction into the next `generate_answer` call: *"Your previous answer included claims not supported by the reviews below: \<reason\>. Regenerate using only what these reviews actually say."* This requires extending `generate_answer`'s prompt template to accept optional prior-attempt feedback, but reuses every other part of the pipeline unchanged.

**2. Stage-aware corrective routing.** Not every failure should be fixed by regenerating the answer. Following [Gu et al., 2024, "Corrective Retrieval Augmented Generation" (CRAG)](https://arxiv.org/abs/2401.15884) ([code](https://github.com/HuskyInSalt/CRAG)) and [Asai et al., 2023, "Self-RAG"](https://arxiv.org/abs/2310.11511), route the corrective action based on *which* metric failed — using exactly the stage table above:
   - **Low Context Precision/Recall** (a retrieval-stage failure) → don't regenerate with the same context at all. Re-retrieve first: widen `retrieve_top_k`, adjust `rerank_top_k`, or — once GraphRAG exists — fall back to the other system entirely via `pipelines.registry.get_rag_system()`, since the shared `RAGResult` contract makes that swap a one-line change. Only regenerate once the context itself has actually improved.
   - **Low Faithfulness / high Noise Sensitivity** (a generation-stage failure) → the context was fine; drop the specific chunks flagged "not useful" by `ContextPrecision`'s per-chunk verdicts (exactly what `debug_eval_rag.py` already computes) and regenerate from the trimmed context, with Reflexion-style feedback layered on top.
   - Every attempt — including which corrective action fired and why — flows through the existing `@traceable` decorator on `run_rag_pipeline`, so the retry history is auditable in LangSmith, not a silent black box.
   - A hard circuit breaker (cap total attempts, e.g. 3) falls back to an explicit "could not produce a grounded answer after N corrective attempts" message — the same honest-failure pattern already used for "no reviews ingested yet" in `pipelines/vector_rag/service.py` — rather than looping indefinitely or silently returning a low-quality answer.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| **LLM** | Google Gemini 2.0 Flash via OpenRouter (OpenAI-compatible) |
| **Embeddings** | Google text-embedding-004 / benchmarked against Cohere, OpenAI |
| **Vector Store** | PostgreSQL + pgvector (HNSW index) |
| **Graph Store** | PostgreSQL (`entities`/`entity_relationships` tables) + networkx (in-memory traversal) |
| **Agents** | LangGraph (stateful multi-agent orchestration, HITL) |
| **Observability** | LangSmith (traces) · MLflow (experiments) |
| **Evaluation** | RAGAS · DeepEval · custom metrics |
| **Backend** | FastAPI · SQLAlchemy 2.0 · Pydantic v2 · Alembic |
| **Task Queue** | Celery + Redis |
| **Frontend** | Next.js 14 · TypeScript · Tailwind CSS · TanStack Query |
| **Infrastructure** | Docker Compose (local) · AWS ECS Fargate + RDS + ElastiCache (production) |
| **IaC** | Terraform |
