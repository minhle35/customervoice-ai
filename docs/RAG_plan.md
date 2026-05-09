# RAG System — Plan & Implementation Guide

## What is RAG?

RAG (Retrieval-Augmented Generation) means: instead of asking an LLM a question and hoping it knows the answer, you first **retrieve** relevant documents from your own database, then **give those documents to the LLM as context**, and ask it to answer *based only on what you retrieved*.

```
User: "What do customers complain about most?"
         │
         ▼
  [1] Embed the query into a vector
         │
         ▼
  [2] Search pgvector for similar review vectors
         │
         ▼
  [3] Re-rank top results for precision
         │
         ▼
  [4] Build a context string from the reviews
         │
         ▼
  [5] LLM answers using ONLY those reviews
         │
         ▼
  "Customers mainly complain about slow service [1] and parking [2]"
       (citations point back to specific reviews)
```

Without RAG, the LLM has no idea what reviews exist in your database — it would make things up (hallucinate). With RAG, every sentence in the answer is grounded in real reviews you retrieved.

---

## Current State vs Target State

### What exists now
- ✅ `review_embeddings` table — stores a 768-dim vector for each review
- ✅ HNSW index on that table — fast approximate nearest-neighbour search
- ✅ `generate_embedding(text)` — embeds review text with `passage:` prefix during ingestion
- ✅ Reviews stored with `sentiment_label`, `topics`, `rating`

### What's implemented
- ✅ `embed_query(text)` — embed the *user's question* with `query:` prefix (`pipelines/rag/retriever.py`)
- ✅ `retrieve()` — query pgvector to find reviews similar to the question (`pipelines/rag/retriever.py`)
- ✅ `rerank()` — re-order results with a cross-encoder for higher precision (`pipelines/rag/retriever.py`)
- ✅ `build_context()` — format retrieved reviews into a text block for the LLM (`pipelines/rag/context_builder.py`)
- ✅ `answer_generator` — LangChain LCEL chain that reads context and produces an answer (`pipelines/rag/answer_generator.py`)
- ✅ `POST /api/chat` — HTTP endpoint that wires all of the above together (`backend/app/api/routes_chat.py`)

### Still pending
- ⏳ Switch cross-encoder from `ms-marco-MiniLM-L-6-v2` → `BAAI/bge-reranker-v2-m3` (multilingual, needed for Vietnamese reviews)
- ⏳ Contextual embeddings — prepend metadata prefix before embedding at ingestion time (see Research Notes below)
- ⏳ Refactor `sentiment_analysis.py` to use LangChain (currently uses raw `openai.OpenAI` client — invisible to LangSmith)

---

## File: `pipelines/rag/retriever.py` — Explained Step by Step

### Step 1 — Why two prefixes? (`passage:` vs `query:`)

The model `intfloat/multilingual-e5-base` was trained to expect:
- `passage: <text>` for documents being indexed (reviews stored in the DB)
- `query: <text>` for questions being searched at retrieval time

If you use the wrong prefix, the vectors live in different parts of the embedding space and similarity scores drop significantly. This is already correct for ingestion (`generate_embeddings.py` uses `passage:`). The retriever must use `query:`.

```
embed_query("What do customers complain about?")
  → SentenceTransformer.encode("query: What do customers complain about?")
  → [0.021, -0.143, 0.887, ...]  ← 768 numbers
```

### Step 2 — Vector similarity search in pgvector

pgvector adds a `<=>` operator to PostgreSQL which computes cosine distance between two vectors.

```sql
SELECT r.content, 1 - (re.embedding <=> '[0.021, -0.143, ...]'::vector) AS similarity
FROM review_embeddings re
JOIN reviews r ON r.id = re.review_id
WHERE r.business_id = 'bien-vinh-hao-2'
ORDER BY re.embedding <=> '[0.021, -0.143, ...]'::vector
LIMIT 20;
```

- `<=>` = cosine distance (0 means identical, 2 means opposite)
- `1 - distance` = cosine similarity (1 = identical, -1 = opposite)
- `ORDER BY distance ASC LIMIT 20` = the 20 most similar reviews
- The HNSW index makes this fast even with thousands of reviews

**Why 20 candidates?** Because we re-rank next and only keep 5. Retrieving 20 gives the re-ranker enough to work with.

---

## Deep Dive: Why Cosine Similarity, Why pgvector, and the Re-ranking Decision

*Written as a senior engineer decision log — honest tradeoffs included.*

---

### Why Cosine Similarity (not Euclidean or Dot Product)?

There are three common distance metrics for vector search:

| Metric | What it measures | pgvector operator |
|--------|-----------------|-------------------|
| Cosine distance | Angle between two vectors | `<=>` |
| L2 / Euclidean | Geometric distance | `<->` |
| Dot product | Raw projection | `<#>` |

**Cosine is the right choice for text embeddings.** Here's why:

Text embedding models encode the *direction* of meaning, not the *magnitude*. A short review ("Great food!") and a long review ("The food was absolutely fantastic, best I've had in years") about the same topic will produce vectors pointing in roughly the same direction — but the long review's vector might have a larger magnitude simply because there's more text. Cosine similarity ignores magnitude entirely; it only measures the angle between vectors. This is what you want: two reviews about the same topic should score high regardless of length.

**L2 distance penalises magnitude differences.** If one vector is [0.9, 0.1] and another is [0.45, 0.05], L2 says they're far apart — but they're actually pointing in the same direction (same topic). For images or audio, L2 can make sense. For text semantics, it's the wrong tool.

**Dot product is equivalent to cosine when vectors are L2-normalised.** Our embedding model uses `normalize_embeddings=True`, which means all vectors are already unit-length. On unit vectors: `dot_product = cosine_similarity`. So mathematically it doesn't matter which you use for normalised vectors. We use cosine explicitly because it signals intent clearly to anyone reading the code.

---

### Why pgvector? Honest Assessment.

pgvector is not the best vector database. Let's be direct about that.

**Dedicated vector databases** (Pinecone, Qdrant, Weaviate) are built ground-up for one purpose: fast, scalable vector search. They offer:
- Better query throughput at high concurrency
- Built-in hybrid search (keyword + semantic in one query)
- More indexing options
- Horizontal sharding for very large datasets

pgvector is an extension bolted onto PostgreSQL. Its HNSW implementation is solid but not as battle-tested at scale as Qdrant or Pinecone.

**So why are we using pgvector?**

1. **We already run PostgreSQL.** Adding pgvector is one `CREATE EXTENSION` command. Running a separate Qdrant or Pinecone instance adds a new service to manage, a new connection pool, a new failure point, a new cost, and a synchronisation problem (what happens if a review is written to PostgreSQL but the vector write to Pinecone fails?).

2. **Our dataset is small.** We have hundreds to low thousands of reviews — not millions. At this scale, pgvector's HNSW is fast enough that the difference between it and a dedicated vector DB is measured in microseconds, not seconds. Optimising for query latency here is premature.

3. **Joins are free.** Our retrieval query joins `review_embeddings` with `reviews` to get metadata (author, rating, sentiment). In a separate vector DB, you'd retrieve IDs, then make a second query to PostgreSQL to fetch the metadata. Two round trips vs one.

4. **Transactional consistency.** When a review is upserted and its embedding is stored, both happen in the same PostgreSQL transaction. With a separate vector DB, you have distributed write consistency to manage.

**When you should switch away from pgvector:**
- You have millions of reviews and query latency becomes measurable
- You need hybrid search (BM25 keyword + vector semantic in one ranked result)
- You need multi-tenant isolation at the vector level
- You need filtering on high-cardinality fields at very high QPS

For this project at this scale: pgvector is the right call. Not because it's the best vector DB — it isn't — but because the operational simplicity of staying in one database outweighs the marginal performance gains of a dedicated system.

---

### HNSW vs IVFFlat — Why HNSW?

pgvector supports two ANN (Approximate Nearest Neighbour) index types:

**IVFFlat (Inverted File Index + Flat)**
- Divides the vector space into `lists` clusters using k-means
- At query time, searches only the nearest `probes` clusters
- Requires a training step (building the clusters before inserting data)
- Lower memory footprint
- Recall degrades if data distribution shifts after training

**HNSW (Hierarchical Navigable Small World)**
- Graph-based index: builds a multi-layer proximity graph over all vectors
- No training step — vectors can be inserted at any time, index stays valid
- Higher memory usage (stores the graph edges)
- Faster queries and better recall than IVFFlat at most dataset sizes
- The current industry default for small-to-medium datasets

We use HNSW because:
1. No training step — we can insert new reviews incrementally without rebuilding
2. Better recall-to-latency ratio at our scale
3. It's the recommended default in pgvector's own documentation

At millions of vectors where memory becomes a constraint, IVFFlat (or IVF-PQ with product quantisation) would be worth reconsidering.

---

### Step 3 — What Re-ranking Is and Why It's Needed

**The fundamental limitation of bi-encoders (what we use for retrieval):**

When we embed a review and store it in pgvector, we're using a *bi-encoder*: the query and the document are encoded *separately* into vectors, and similarity is measured by comparing those independent vectors.

This works well for semantic similarity: "great seafood" and "fresh fish" will have similar vectors. But it breaks down for *relevance to a specific question*.

Consider this query: **"What do customers complain about?"**

The bi-encoder embeds this into a vector. But this vector represents the *semantic meaning* of the question itself — it points toward a region of embedding space near concepts like "complaints", "problems", "negatives". Reviews that use the word "complain" or "issue" will score high. But a review like:

> *"Waited 45 minutes. Staff ignored us completely."*

…might not score high because it doesn't use complaint vocabulary — it just *is* a complaint. The bi-encoder missed it.

**The cross-encoder solves this by reading both together:**

A cross-encoder takes `(query, document)` as a single input — both texts go in at once — and outputs a single relevance score. Because it reads both together, it models the *relationship* between them, not just their independent meanings.

```
Input:  ["What do customers complain about?", "Waited 45 minutes. Staff ignored us."]
Output: 0.91  ← highly relevant, even though vocabulary doesn't overlap
```

The cross-encoder understands that a 45-minute wait and being ignored by staff *are* complaints — even without the word "complaint" appearing.

**Why not just use the cross-encoder for everything?**

Speed. The bi-encoder pre-computes all document vectors at index time. At query time it only computes one vector (the query) and does a fast ANN search. The cross-encoder cannot be pre-computed — it must read the (query, document) pair at query time. For 10,000 reviews, that's 10,000 forward passes through a neural network per query. That takes seconds, not milliseconds.

**Two-stage retrieval is the industry standard pattern for this reason:**

1. **Stage 1 — Recall:** bi-encoder + HNSW, retrieve top-20 fast (milliseconds). Goal: don't miss anything relevant.
2. **Stage 2 — Precision:** cross-encoder re-ranks the 20 candidates (tens of milliseconds). Goal: put the most relevant ones at the top.

Total cost: one vector lookup + 20 cross-encoder forward passes. Manageable.

---

### Honest Problem: Our Cross-Encoder Is English-Only

**`cross-encoder/ms-marco-MiniLM-L-6-v2`** was trained on the MS MARCO dataset — Microsoft Bing search queries, entirely in English. Our reviews are in Vietnamese.

This is a real weakness. The cross-encoder will score English-language reviews much more reliably than Vietnamese ones. For a Vietnamese restaurant where most reviews are in Vietnamese, this matters.

**Better alternatives:**

| Model | Language | Size | Notes |
|-------|----------|------|-------|
| `BAAI/bge-reranker-v2-m3` | Multilingual (100+ languages, incl. Vietnamese) | 568MB | Best open-source multilingual reranker; significantly better for our use case |
| `BAAI/bge-reranker-base` | English-primary | 278MB | Better than ms-marco on benchmarks, still English |
| Cohere Rerank API | Multilingual | API | Paid, excellent quality, no local inference |
| `cross-encoder/ms-marco-MiniLM-L-6-v2` | English | 22MB | What we planned — fast, but wrong language |

**Recommendation:** Switch to `BAAI/bge-reranker-v2-m3` before the first real demo. It's larger (568MB vs 22MB) but handles Vietnamese properly. The ms-marco model was chosen for speed in the initial plan without accounting for the Vietnamese language requirement. That was a mistake worth correcting before building it in.

---

### Summary: Retrieval Decision Log

| Decision | Choice | Honest Reasoning |
|----------|--------|-----------------|
| Vector similarity metric | Cosine | Correct for normalised text embeddings; direction matters, magnitude doesn't |
| Vector database | pgvector | Not the best, but same DB as everything else — operational simplicity wins at this scale |
| ANN index | HNSW | No training step, better recall, standard default for small-to-medium datasets |
| Two-stage retrieval | Yes | Bi-encoder for speed, cross-encoder for precision — industry standard, necessary |
| Cross-encoder model | ~~ms-marco-MiniLM~~ → `BAAI/bge-reranker-v2-m3` | Original choice was English-only; Vietnamese reviews need a multilingual model |

### Step 4 — `ReviewChunk` dataclass

A simple container that carries both the review data and the retrieval scores:

```python
@dataclass
class ReviewChunk:
    review_id: UUID            # UUID — used for citations and source tracking
    content: str               # the review text
    author: str | None         # "Thiago Gandarillas"
    rating: float | None       # 4.0
    sentiment_label: str | None  # "positive"
    platform: str              # "google"
    similarity_score: float    # from pgvector (0–1)
    rerank_score: float = 0.0  # from cross-encoder (can be negative, higher = better)
```

---

## File: `pipelines/rag/context_builder.py` — Explained

Takes the list of `ReviewChunk` objects and formats them into a plain text block that the LLM can read:

```
Review [1] — Google Reviews | ⭐ 4.0 | Positive | Thiago Gandarillas
"The seafood was fresh but the service was quite slow during peak hours."

Review [2] — Google Reviews | ⭐ 2.0 | Negative | Anonymous
"Waited 45 minutes for our food. Staff seemed overwhelmed."

Review [3] — Google Reviews | ⭐ 5.0 | Positive | Linh Nguyen
"Amazing ocean view. Best bánh xèo I've had in Phan Rang."
```

Two important constraints:
1. **Token budget**: LLMs have context limits. We cap the total context at 2000 tokens (default `token_budget=2000`, configurable) so the LLM still has room for the system prompt + its answer.
2. **Citation numbers**: `[1]`, `[2]`, `[3]` so the LLM can reference specific reviews in its answer.

---

## File: `pipelines/rag/answer_generator.py` — Explained

This is a LangChain LCEL (LangChain Expression Language) chain:

```python
chain = prompt | llm | output_parser
```

The system prompt instructs the LLM to:
- Answer ONLY using the provided reviews (no hallucination)
- Cite specific reviews using `[1]`, `[2]` markers
- Say "I don't have enough information" if the reviews don't contain an answer

The chain returns a tuple:
```python
answer: str          # "Customers mainly complain about slow service [1][2] and parking [3]."
used_chunks: list[ReviewChunk]  # only the chunks that fit within the token budget
```

The caller (`run_rag_pipeline`) extracts `source_ids` from `used_chunks` and returns `(answer, source_ids)` to the HTTP layer. The current model is `google/gemini-2.0-flash-001` via OpenRouter.

---

## File: `backend/app/api/routes_chat.py` — Explained

The HTTP endpoint that wires everything together:

```
POST /api/chat
Body: {
  "business_id": "ChIJhTEAbgFB1moRCYXM8lnO3vI",
  "messages": [
    { "role": "user", "content": "What do customers complain about?" }
  ]
}

  1. embed_query(last_message)             → 768-dim vector
  2. retrieve(db, vector, business_id=...) → top-20 ReviewChunks from pgvector
  3. rerank(query, chunks)                 → top-5 re-ranked chunks
  4. build_context(chunks)                 → formatted text block (token_budget=2000)
  5. LangChain LCEL chain                  → grounded answer via OpenRouter
  6. Persist exchange to chat_messages table
  7. Return { "answer": "...", "sources": [...] }
```

---

## LangSmith Observability

LangSmith is wired and active. The SDK now uses `LANGSMITH_*` env vars (renamed from `LANGCHAIN_*` in recent versions):

```
LANGSMITH_TRACING=true
LANGSMITH_ENDPOINT=https://api.smith.langchain.com
LANGSMITH_API_KEY=<your key>
LANGSMITH_PROJECT=customervoice-ai
```

These are set in `.env` and propagated to `os.environ` at startup in `main.py`.

Two `@traceable` decorators provide explicit root spans:
- `@traceable(name="rag_pipeline")` on `run_rag_pipeline` in `rag_service.py` — wraps the full embed → retrieve → rerank → generate path
- `@traceable(name="run_agent")` on `run_agent` in `agents/graph.py` — wraps the full LangGraph invocation

Every `ChatOpenAI` call inside those spans (intent classifier, answer generator, insight node) is automatically nested as a child trace. Visible at smith.langchain.com under project `customervoice-ai`.

---

## Complete RAG Flow Summary

```
POST /api/chat
  { "query": "...", "business_id": "..." }
          │
          ▼
    [retriever.py]
    embed_query()           ← sentence-transformers, `query:` prefix
          │
          ▼
    retrieve()              ← pgvector HNSW cosine search, top-20
          │
          ▼
    rerank()                ← cross-encoder/ms-marco-MiniLM-L-6-v2, top-5 (⚠️ English-only — see multilingual note)
          │
          ▼
    [context_builder.py]
    build_context()         ← format chunks with [1][2][3] citations, token budget
          │
          ▼
    [answer_generator.py]
    LangChain LCEL chain    ← system prompt + context + query → LLM
          │                    traced automatically by LangSmith
          ▼
    {
      "answer": "Customers mostly complain about slow service [1][2].",
      "sources": [{ review_id, content, score }, ...]
    }
```

---

## Implementation Order

1. `pipelines/rag/retriever.py` — embed + retrieve + rerank
2. `pipelines/rag/context_builder.py` — format chunks for LLM
3. `pipelines/rag/answer_generator.py` — LangChain chain
4. `backend/app/config.py` — add LangSmith env vars
5. `backend/app/schemas/chat_schema.py` — request/response types
6. `backend/app/api/routes_chat.py` — wire it all into an endpoint
7. Refactor `sentiment_analysis.py` to use LangChain (adds LangChain to resume)

## Benchmark
### 1. Published Benchmarks (MTEB)
MTEB (Massive Text Embedding Benchmark) is the standard for comparing embedding and reranking models. You can look up scores without running anything:

Go to huggingface.co/spaces/mteb/leaderboard
Filter by task: Reranking
Compare BAAI/bge-reranker-v2-m3 vs cross-encoder/ms-marco-MiniLM-L-6-v2
What MTEB tells you: How models perform on standardised academic datasets across languages.

What it doesn't tell you: How they perform on your Vietnamese restaurant reviews. Academic benchmarks use news articles, Wikipedia, legal documents — not hospitality reviews. A model that scores 0.87 on MTEB may still be worse than a smaller model on your specific domain.

### 2. The Right Approach for This Project — Domain-Specific Evaluation
This feeds directly into the DeepEval plan you already have. The idea is simple:

Step 1: Take 20–30 real reviews from your database.

Step 2: Write 10–15 questions that should be answered by specific reviews you already know:


Question: "What do customers say about parking?"
Expected: review_id = "abc-123" (contains "parking was difficult")

Question: "Ai khen ngợi hải sản?"  (Who praised the seafood?)
Expected: review_id = "def-456" (contains "hải sản tươi ngon")
Step 3: Run both models, measure which one ranks the correct review higher.

Step 4: Calculate standard IR metrics:

Metric	What it measures
Recall@5	Was the correct review in the top 5 results?
MRR@10	Mean Reciprocal Rank — how high was the first correct result?
NDCG@10	Normalised Discounted Cumulative Gain — standard ranking quality metric

### 3. Practically — A Quick Head-to-Head
a lightweight comparison in ~50 lines of Python before committing to either model:

```
from sentence_transformers import CrossEncoder

ms_marco = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
bge_multilingual = CrossEncoder("BAAI/bge-reranker-v2-m3")

query = "Nhà hàng có bãi đỗ xe không?"  # Vietnamese: Does the restaurant have parking?
docs = [
    "Bãi giữ xe rộng rãi, rất tiện lợi.",       # correct: mentions parking
    "Hải sản rất tươi, giá hợp lý.",              # irrelevant: seafood/price
    "Dịch vụ chậm, phục vụ không nhiệt tình.",    # irrelevant: service
]

print("ms-marco scores:", ms_marco.predict([(query, d) for d in docs]))
print("bge-m3 scores:  ", bge_multilingual.predict([(query, d) for d in docs]))
```

If ms-marco gives similar scores to all three but bge-m3 scores the first doc clearly higher — bge-m3 is the right choice for Vietnamese. If they behave the same, ms-marco's smaller size (22MB vs 568MB) becomes a valid reason to keep it.

### 4. The Honest Limitation of Any Benchmark

All benchmarks — MTEB, BEIR, your own golden dataset — measure retrieval quality on labelled data. They answer: "given a question and a document I already know is relevant, does the model rank it highly?"

They don't answer: "does the retrieved context actually produce a better final answer?" For that, you need end-to-end RAG evaluation — which is exactly what `ContextualRecallMetric` and `FaithfulnessMetric` in DeepEval measure. That's the ground truth for whether the retrieval is good for this specific application.

**Recommended order:**
1. Look up MTEB reranking scores (5 minutes, confirms bge-m3 is worth the size cost)
2. Run the quick head-to-head script above on 5–10 Vietnamese queries from your actual data
3. After building the full RAG pipeline, run DeepEval `ContextualRecallMetric` — this is the only benchmark that truly measures whether retrieval quality translates to better answers

---

## Research Notes: External Resources

---

### Resource 1 — AWS: Improve RAG Performance Using Cohere Rerank

**Source:** AWS Machine Learning Blog — Cohere Rerank on SageMaker / Bedrock

**Main point:** Confirms the two-stage retrieval pattern as AWS's recommended production approach for RAG. Cohere Rerank is a managed cross-encoder API that eliminates the need to host a re-ranker model yourself.

**Relevant to this project:**

- **Cohere vs local cross-encoder:** Cohere Rerank is a paid API (~$0.002/query); `BAAI/bge-reranker-v2-m3` runs locally for free. For a low-volume project, local is fine. For production at scale, Cohere's managed endpoint removes operational overhead and is available natively on AWS Bedrock — relevant when we deploy to AWS.
- **AWS Bedrock Rerank API** (available since June 2025): single `boto3` call, no endpoint management, supports `rerank-multilingual-v3.0` — directly applicable to our AWS deployment phase.
- **Models available:** `rerank-english-v3.0`, `rerank-multilingual-v3.0`, `Rerank 3 Nimble` (3-5x faster, same accuracy).

**Decision for this project:**
- Local dev → `BAAI/bge-reranker-v2-m3` (free, multilingual, no API dependency)
- AWS production → Bedrock Rerank API with `rerank-multilingual-v3.0` (swap is one function call with LangChain)

---

### Resource 2 — Anthropic Cookbook: Contextual Embeddings Guide

**Source:** Anthropic Platform Cookbook — Contextual Embeddings

**Main point:** Standard RAG embeds chunks in isolation, which causes poor retrieval because chunks lose their surrounding context. *Contextual embeddings* fix this by using Claude to generate a 1–2 sentence situating description per chunk before embedding. This is a significant, measurable improvement.

**Benchmark results** (9 codebases, 737 chunks, 248 eval queries — Pass@10 metric):

| Approach | Pass@10 | Failure rate |
|----------|---------|--------------|
| Baseline RAG (standard embeddings) | 87.2% | 12.85% |
| + Contextual embeddings | 92.3% | 7.7% |
| + Hybrid BM25 search | 92.3% | 7.7% |
| + Reranking (Cohere) | **95.3%** | **4.74%** |

Reranking alone adds ~3 percentage points on top of contextual embeddings. Combined, the failure rate drops from 12.85% → 4.74% — a **47% reduction in retrieval failures** compared to standard RAG.

**What is Contextual Embeddings?**

Instead of embedding a chunk as-is:
```
"Waited 45 minutes. Staff ignored us completely."
```

You prepend a Claude-generated context sentence first:
```
"This is a negative Google Maps review for Nhà hàng Biển Vĩnh Hảo 2
 discussing service quality and wait time.
 Waited 45 minutes. Staff ignored us completely."
```

Then embed the enriched chunk. The embedding now captures that this is about *service complaints at this specific business* rather than just a sequence of sentences about waiting.

**Why this matters for our reviews specifically:**
Short reviews ("Ngon!") lose almost all context when embedded in isolation. A contextual prefix — "This is a 5-star Vietnamese-language Google Maps review praising food quality at Nhà hàng Biển Vĩnh Hảo 2" — gives the embedding model enough signal to place the vector correctly in semantic space.

**Cost with prompt caching:**
- Without caching: ~$9.20 per ingestion batch (737 chunks)
- With caching (`cache_control: ephemeral`): ~$2.85 (**69% savings**)
- Requires processing chunks from the same document sequentially to maximise cache hits

**Hybrid search (Contextual BM25):**
The guide also covers combining vector search with BM25 keyword search (Elasticsearch) using Reciprocal Rank Fusion (80% semantic weight, 20% BM25). This is useful when exact keyword matches matter — e.g., searching for a reviewer's name or a specific dish name. For review intelligence, this is a nice-to-have, not critical.

---

### What This Changes for Our Implementation

**Priority addition — Contextual Embeddings during ingestion (not yet implemented):**

When a new review is ingested and embedded, instead of embedding the raw review text, first call the LLM to generate a context prefix, then embed `prefix + review`. This happens in `generate_embeddings.py` and would require re-embedding any reviews already in the database.

The context template for a review:
```
This is a {sentiment_label} {platform} review (rating: {rating}/5) for {business_name},
discussing the following topics: {topics}.
{review_content}
```

This is cheaper and simpler than the full Claude-based contextual embedding from the cookbook because we already have structured metadata (sentiment, topics, platform, rating) from the processing pipeline — we don't need an LLM call to generate the context.

**Updated ingestion flow with contextual embedding:**
```
review ingested
    │
    ▼
clean_review_text()
    │
    ▼
analyze_sentiment_and_topics()  ← produces sentiment_label, topics
    │
    ▼
build_contextual_chunk()        ← NEW: prefix metadata + review content
    │
    ▼
generate_embedding(contextual_chunk)  ← embed the enriched text
    │
    ▼
store in pgvector
```

**Impact on re-ranking model choice:**
The Anthropic guide uses Cohere `rerank-english-v3.0`. Our conclusion remains the same — use `BAAI/bge-reranker-v2-m3` locally for Vietnamese support, swap to Cohere `rerank-multilingual-v3.0` via Bedrock when deploying to AWS.

---

### Updated Retrieval Pipeline (incorporating both resources)

```
Standard RAG (what most tutorials show):
  embed(raw_chunk) → pgvector search → top-5 → LLM

Our target pipeline (industry standard):
  embed(context_prefix + raw_chunk)   ← contextual embeddings at ingestion time
       │
       ▼
  pgvector cosine search (HNSW)       ← top-20 candidates
       │
       ▼
  BAAI/bge-reranker-v2-m3             ← re-rank to top-5 (local, multilingual)
       │                                 swap to Cohere rerank-multilingual-v3.0 on AWS
       ▼
  build_context() with citations      ← token-budgeted, [1][2][3]
       │
       ▼
  LangChain LLM chain                 ← grounded answer
```

Expected improvement over standard RAG: **~8 percentage points on Pass@10** (87% → 95%), based on the Anthropic benchmark numbers.