# CustomerVoice AI — Feature Checklist
**Created:** March 24, 2026
**Goal:** Build an industry-standard AI engineering portfolio project for Australian AI Engineer roles

---

## Architecture Overview (Target State)

```
User (Natural Language Query)
        │
        ▼
Next.js Dashboard ──────────────────────────────────────────────────────────┐
        │                                                                    │
        ▼                                                                    │
FastAPI (Backend)                                                            │
        │                                                                    │
   LangGraph Orchestrator                                                    │
   ┌────┴─────────────────────────────┐                                     │
   │                                  │                                     │
Intent Agent              Ingestion Agent                                    │
(parse query,             (SerpAPI tool,                                     │
 confirm context)          resolve data_id,                                  │
        │                  trigger Celery)                                   │
        ▼                                                                    │
Analysis Agent ──► RAG Retrieval ──► pgvector (HNSW) ──► LLM Answer         │
        │                  │                                                 │
        │            Langfuse/LangSmith (trace every call)                  │
        │                                                                    │
        ▼                                                                    │
Insight Agent (summarise, compare, generate SOPs)                           │
        │                                                                    │
        ▼                                                                    │
DeepEval (evaluate faithfulness, relevance, recall) ◄───────────────────────┘
        │
        ▼
MLflow (log eval scores, prompt versions, model experiments)
        │
        ▼
AWS Bedrock / OpenRouter (LLM backend, swap-able)
AWS SageMaker (fine-tuning embedding model)
```

---

## Phase 1 — Complete RAG Architecture
**Estimated time:** 1–2 weeks
**Resume signal:** "Production RAG pipeline" — the #1 required skill in AU GenAI roles

### What's already done ✅
- [x] pgvector + HNSW index on `review_embeddings`
- [x] `generate_embedding()` with `intfloat/multilingual-e5-base` (768 dims)
- [x] `EmbeddingService.upsert_embedding()` stores embeddings after ingestion
- [x] Reviews stored with sentiment label + topics

### What's missing — build this ❌

#### 1.1 Query Embedding + Semantic Retrieval
- [ ] Create `pipelines/rag/retriever.py`
  - `embed_query(text) → list[float]` — use `query:` prefix (multilingual-e5 convention)
  - `retrieve(query_embedding, business_id, top_k=5) → list[ReviewChunk]`
  - SQL: `ORDER BY embedding <=> query_vec LIMIT k` (cosine distance on HNSW index)
  - Filter by `business_id` and optionally `platform`, `sentiment_label`, date range
- [ ] Add `ReviewChunk` dataclass: `{review_id, content, author, rating, sentiment_label, score}`

#### 1.2 Context Builder
- [ ] Create `pipelines/rag/context_builder.py`
  - `build_context(chunks: list[ReviewChunk]) → str`
  - Format: numbered list with metadata — "Review 1 (Google, ⭐4, Positive): ..."
  - Respect token budget: max ~3000 tokens of context (leave room for system prompt + answer)
  - Include citation markers `[1]`, `[2]` for source attribution in the answer

#### 1.3 Re-ranking (industry standard — most tutorials skip this)
- [ ] Add a cross-encoder re-ranker after initial retrieval
  - Use `cross-encoder/ms-marco-MiniLM-L-6-v2` locally (lightweight, free)
  - Retrieve top-20 → re-rank → keep top-5
  - Why: initial HNSW retrieval is approximate; re-ranking improves precision significantly
  - Add to `retriever.py` as optional step: `rerank(query, chunks) → list[ReviewChunk]`

#### 1.4 RAG Answer Generation
- [ ] Create `pipelines/rag/answer_generator.py`
  - System prompt: *"You are a customer insight analyst. Answer using ONLY the provided reviews. Cite sources as [1], [2]."*
  - Return: `{answer: str, sources: list[ReviewChunk], model: str, latency_ms: int}`
  - Handle no-context case: "I don't have enough reviews to answer this question."

#### 1.5 RAG API Endpoint
- [ ] Implement `POST /api/chat` in `backend/app/api/routes_chat.py`
  - Request: `{query: str, business_id: str, top_k: int = 5}`
  - Response: `{answer: str, sources: [{review_id, content, score}], session_id: str}`
  - Stream response via Server-Sent Events (SSE) for better UX — use FastAPI `StreamingResponse`

#### 1.6 LangChain Integration (adds framework name to resume)
- [ ] Refactor `sentiment_analysis.py` to use `langchain_openai.ChatOpenAI`
- [ ] Build the RAG chain using `LangChain LCEL` (LangChain Expression Language):
  ```python
  chain = retriever | context_builder | prompt | llm | output_parser
  ```
- [ ] Use `LangChain` document schema for review chunks
- [ ] Why LangChain: easy swap between OpenRouter → AWS Bedrock later; LCEL is the modern standard

#### 1.7 Install dependencies
```bash
uv add langchain langchain-openai langchain-community llama-index langgraph
uv add sentence-transformers  # already have
```

---

## Phase 2 — LLM Observability (LangSmith)
**Estimated time:** 3–5 days
**Resume signal:** Rarest skill in AU market — almost no candidate can demo this in interviews

> **LangSmith vs Langfuse:**
> - **LangSmith** = LangChain's native tracing platform, cloud-hosted, free tier available, integrates automatically when you use LangChain (just set `LANGCHAIN_TRACING_V2=true`)
> - **Langfuse** = open-source alternative, self-hostable (good for data sovereignty demo on AWS)
> - **Recommendation:** Use LangSmith first (zero config with LangChain) → add Langfuse when deploying to AWS to show self-hosted observability

### LangSmith Setup
- [ ] Create account at smith.langchain.com
- [ ] Add env vars:
  ```
  LANGCHAIN_TRACING_V2=true
  LANGCHAIN_API_KEY=...
  LANGCHAIN_PROJECT=customervoice-ai
  ```
- [ ] Every LangChain call is now automatically traced — zero code changes needed
- [ ] Add custom metadata to traces: `{business_id, user_query, retrieved_chunks_count}`

### What to track in every trace
- [ ] Query → embedding latency
- [ ] Retrieval → top-K scores (to identify poor retrieval)
- [ ] LLM prompt tokens + completion tokens (cost tracking)
- [ ] End-to-end response latency (p50/p95)
- [ ] User feedback signal (thumbs up/down on chat response → log to LangSmith)

### Langfuse (AWS phase — self-hosted)
- [ ] Add Langfuse Docker service to `docker-compose.yml`
- [ ] Add `langfuse` SDK alongside LangSmith — same trace, two destinations
- [ ] Deploy Langfuse on AWS ECS when deploying (shows data sovereignty awareness)

---

## Phase 3 — LangGraph Multi-Agent System
**Estimated time:** 2–3 weeks
**Resume signal:** "Agentic AI workflow design" — fastest-growing senior-level differentiator

### Agent Architecture

```
User Query
    │
    ▼
┌─────────────────────────────────────────────┐
│           LangGraph Orchestrator             │
│                                             │
│  ┌──────────────┐    ┌──────────────────┐   │
│  │ Intent Agent │───►│ Clarification    │   │
│  │              │    │ Agent            │   │
│  │ - parse NL   │    │                  │   │
│  │ - extract    │    │ - ask follow-up  │   │
│  │   entities   │    │   if ambiguous   │   │
│  │ - route to   │    │ - confirm biz    │   │
│  │   right flow │    │   before action  │   │
│  └──────┬───────┘    └──────────────────┘   │
│         │                                   │
│    ┌────┴──────────────────────┐            │
│    │                           │            │
│    ▼                           ▼            │
│ ┌──────────────┐    ┌──────────────────┐   │
│ │ Ingestion    │    │ Analysis Agent   │   │
│ │ Agent        │    │                  │   │
│ │              │    │ - RAG retrieval  │   │
│ │ - SerpAPI    │    │ - sentiment      │   │
│ │   tool call  │    │   summary        │   │
│ │ - resolve    │    │ - topic compare  │   │
│ │   data_id    │    │ - trend detect   │   │
│ │ - trigger    │    │                  │   │
│ │   Celery     │    └────────┬─────────┘   │
│ └──────────────┘             │             │
│                              ▼             │
│                   ┌──────────────────┐     │
│                   │  Insight Agent   │     │
│                   │                  │     │
│                   │ - generate SOP   │     │
│                   │ - write report   │     │
│                   │ - stream answer  │     │
│                   └──────────────────┘     │
└─────────────────────────────────────────────┘
```

### 3.1 Define Tools (what agents can call)
- [ ] `search_reviews(query, business_id, top_k)` → calls pgvector retrieval
- [ ] `get_sentiment_summary(business_id, date_range)` → aggregates from DB
- [ ] `get_top_topics(business_id, limit)` → groups topics by frequency
- [ ] `resolve_business(name, location)` → calls SerpAPI google_maps engine
- [ ] `trigger_ingestion(business_id, data_id)` → queues Celery task
- [ ] `compare_periods(business_id, period_a, period_b)` → sentiment delta

### 3.2 Intent Agent
- [ ] Parse natural language query into structured intent:
  ```python
  {
    "intent": "analysis" | "ingestion" | "comparison" | "insight_generation",
    "business_id": str | None,
    "topic": str | None,
    "time_range": str | None,
    "confidence": float
  }
  ```
- [ ] If `confidence < 0.7` → route to Clarification Agent
- [ ] If `intent == "ingestion"` → route to Ingestion Agent
- [ ] If `intent == "analysis"` → route to Analysis Agent

### 3.3 Clarification Agent (Human-in-the-loop)
- [ ] When intent is ambiguous, ask one clarifying question
- [ ] Stream question to frontend via SSE
- [ ] Wait for user response (LangGraph interrupt + resume pattern)
- [ ] Example: *"I found 3 businesses matching 'Biển Vĩnh Hảo'. Which one did you mean? [1] Nhà hàng Biển Vĩnh Hảo 2 — Phan Rang [2] Biển Vĩnh Hảo — Nha Trang"*

### 3.4 Ingestion Agent
- [ ] Tool 1: `resolve_business(name, location)` → SerpAPI google_maps → returns data_id candidates
- [ ] Tool 2: present candidates to user for confirmation (human-in-the-loop)
- [ ] Tool 3: `trigger_ingestion(business_id, data_id)` → Celery task
- [ ] Return: `{status: "queued", task_id, estimated_reviews: int}`

### 3.5 Analysis Agent
- [ ] Tool 1: `search_reviews` → RAG retrieval
- [ ] Tool 2: `get_sentiment_summary`
- [ ] Tool 3: `get_top_topics`
- [ ] Synthesise into a grounded answer with citations
- [ ] Stream response tokens to frontend

### 3.6 Insight Agent
- [ ] Input: full analysis from Analysis Agent
- [ ] Generate: structured business insight report
  - What's working well (top positive topics)
  - What needs fixing (recurring negative themes)
  - Draft 3 operational recommendations
- [ ] Output: markdown report + JSON structured data for dashboard

### 3.7 LangGraph State Machine
- [ ] Define `AgentState` TypedDict:
  ```python
  class AgentState(TypedDict):
      messages: list[BaseMessage]
      intent: str
      business_id: str
      retrieved_chunks: list
      final_answer: str
      needs_clarification: bool
  ```
- [ ] Define graph edges (conditional routing based on intent + confidence)
- [ ] Add persistence: `SqliteSaver` or `PostgresSaver` for conversation memory

---

## Phase 4 — Evaluation with DeepEval
**Estimated time:** 1 week
**Resume signal:** Rarest portfolio skill — 97% of candidates don't have this

> **DeepEval vs RAGAS:**
> - **DeepEval** = more comprehensive, integrates with pytest naturally, has LLM-as-judge metrics
> - **RAGAS** = lighter, more focused on RAG-specific metrics
> - **Recommendation:** Use DeepEval as primary (it's a pytest plugin, fits your existing test setup)

### 4.1 Build Golden Dataset
- [ ] Create `backend/tests/evaluation/golden_dataset.json`
  - 30 question-answer pairs about Nhà hàng Biển Vĩnh Hảo 2 reviews
  - Include: the question, expected answer, relevant review IDs as ground truth context
  - Example:
    ```json
    {
      "input": "What do customers say about the seafood quality?",
      "expected_output": "Customers consistently praise the fresh seafood...",
      "context": ["review_id_1", "review_id_2", "review_id_3"]
    }
    ```

### 4.2 DeepEval Metrics to Implement
- [ ] `AnswerRelevancyMetric` — does the answer actually address the question?
- [ ] `FaithfulnessMetric` — is the answer grounded in the retrieved reviews? (no hallucination)
- [ ] `ContextualRecallMetric` — did retrieval find the right reviews?
- [ ] `ContextualPrecisionMetric` — are the retrieved reviews actually relevant?
- [ ] `HallucinationMetric` — did the LLM invent facts not in the context?
- [ ] `ToxicityMetric` — safety check on LLM outputs

### 4.3 Integration
- [ ] `backend/tests/evaluation/test_rag_pipeline.py`
  ```python
  @pytest.mark.evaluation
  def test_rag_faithfulness():
      # run RAG pipeline on golden dataset
      # assert faithfulness_score > 0.8
  ```
- [ ] Run with `uv run pytest -m evaluation`
- [ ] Log scores to MLflow: track score over time as you improve prompts
- [ ] Set thresholds: fail CI if `faithfulness < 0.75` or `answer_relevancy < 0.70`

### 4.4 Prompt Iteration Workflow
- [ ] Change system prompt → re-run evaluation → compare scores in MLflow
- [ ] Document: "Prompt v1 → faithfulness 0.71 → Prompt v2 (added citation instruction) → 0.89"
- [ ] This is what senior AI engineers actually do — and almost no portfolio project shows it

---

## Phase 5 — AWS Deployment ← Deploy Here
**Estimated time:** 1 week
**Trigger:** After Phase 1–4 complete. Deploy, record video, optionally keep running.

### AWS Services to Use (AI-relevant for resume)

| Service | Role | Why It's Resume-Relevant |
|---------|------|--------------------------|
| **Amazon Bedrock** | Replace OpenRouter with managed LLM API (Claude 3 Haiku, Llama 3) | Most AU employers use Bedrock; shows AWS-native AI |
| **Amazon ECS Fargate** | Run FastAPI + Celery worker | Standard for containerised AI microservices |
| **Amazon RDS PostgreSQL** | pgvector storage | Managed vector DB — shows production thinking |
| **Amazon ElastiCache Redis** | Celery broker + rate limit counters | Standard async ML pipeline component |
| **Amazon S3** | Store evaluation datasets, model artifacts, golden test sets | MLOps data management |
| **Amazon ECR** | Docker image registry | Standard CI/CD for containerised ML |
| **AWS Secrets Manager** | All API keys, DB passwords | Security requirement for all AU enterprise roles |
| **Amazon CloudWatch** | Logs, metrics, LLM cost alarms | MLOps observability |
| **AWS WAF + CloudFront + ALB** | Rate limiting, DDoS protection | Production security |
| **Amazon SageMaker** | Fine-tuning in Phase 6 | The #1 MLOps tool in AU job postings |

### Bedrock Integration (swap OpenRouter → Bedrock)
- [ ] Add `langchain-aws` (`uv add langchain-aws`)
- [ ] Replace `ChatOpenAI(base_url=openrouter_url)` with `ChatBedrock(model_id="anthropic.claude-3-haiku-20240307-v1:0")`
- [ ] Enable Bedrock model access in AWS console (Claude 3 Haiku is free to try)
- [ ] LangChain makes this a 2-line change — this is why we integrated LangChain in Phase 1

### Terraform (Infrastructure as Code)
- [ ] `infrastructure/terraform/`
  - `main.tf` — VPC, subnets, security groups
  - `ecs.tf` — ECS cluster, task definitions, services
  - `rds.tf` — RDS PostgreSQL with pgvector
  - `elasticache.tf` — Redis cluster
  - `alb.tf` — Application Load Balancer + target groups
  - `waf.tf` — WAF with rate-based rules
  - `cloudfront.tf` — CDN + WAF association
  - `secrets.tf` — Secrets Manager for all env vars
  - `cloudwatch.tf` — Log groups, alarms, dashboards
  - `bedrock.tf` — IAM role for ECS → Bedrock access
- [ ] `terraform apply` → full stack up in ~10 minutes
- [ ] `terraform destroy` → full teardown after video

### What to show in the demo video
1. Live dashboard with real review metrics
2. AI chat: type query → LangGraph agents → RAG answer with citations
3. LangSmith/Langfuse: show the full trace (retrieval scores, LLM latency, token cost)
4. DeepEval: show evaluation scores (faithfulness, relevancy)
5. AWS console: ECS tasks running, RDS, CloudWatch log streams
6. Bedrock: show model invocations in Bedrock console

---

## Phase 6 — MLOps with MLflow + SageMaker
**Estimated time:** 1–2 weeks
**What MLOps means for this project:**

MLOps here is NOT about training a neural network from scratch. It's about:
1. Tracking experiments (prompt versions, retrieval configs, eval scores)
2. Managing model artifacts (embedding model versions, fine-tuned models)
3. Automating evaluation in CI

### 6.1 MLflow Experiment Tracking
- [ ] Add MLflow to Docker Compose (lightweight, runs locally)
- [ ] Track every eval run:
  ```python
  with mlflow.start_run(run_name="rag-eval-v3"):
      mlflow.log_param("top_k", 5)
      mlflow.log_param("reranker", "cross-encoder/ms-marco-MiniLM-L-6-v2")
      mlflow.log_param("llm_model", "claude-3-haiku")
      mlflow.log_metric("faithfulness", 0.89)
      mlflow.log_metric("answer_relevancy", 0.84)
      mlflow.log_metric("latency_p95_ms", 1240)
  ```
- [ ] Use MLflow UI to compare runs: prompt v1 vs v2 vs v3
- [ ] Log golden dataset as MLflow artifact

### 6.2 SageMaker (AWS phase)
- [ ] Register the `intfloat/multilingual-e5-base` model in SageMaker Model Registry
- [ ] Create a SageMaker inference endpoint for the embedding model (replaces local sentence-transformers in production)
- [ ] Why: shows you understand managed ML inference vs local inference tradeoffs

---

## Phase 7 — Fine-tuning with LoRA/PEFT
**Estimated time:** 2–3 weeks
**What to fine-tune and why:**

> Fine-tuning is not always the right choice. For this project, fine-tuning makes sense for the **embedding model** on Vietnamese restaurant review text — improving retrieval quality for the specific domain.

### Option A — Fine-tune the Embedding Model (High impact, moderate effort)
- [ ] Collect training pairs from your review corpus:
  - Positive pairs: `(query, relevant_review)` — same topic
  - Negative pairs: `(query, irrelevant_review)` — different topic
- [ ] Fine-tune `intfloat/multilingual-e5-base` using sentence-transformers `MultipleNegativesRankingLoss`
- [ ] Compare retrieval quality before/after: measure `ContextualRecallMetric` in DeepEval
- [ ] Tools: `sentence-transformers` training API + SageMaker training job
- [ ] Expected outcome: better Vietnamese hospitality domain retrieval

### Option B — Fine-tune a Small LLM for Sentiment (Lower priority)
- [ ] Fine-tune `Llama 3.2 3B` (small, trainable on SageMaker ml.g5.xlarge) for Vietnamese sentiment classification
- [ ] Dataset: your labelled reviews (sentiment_label from the pipeline = training labels)
- [ ] Method: LoRA (Low-Rank Adaptation) + PEFT library — trains fast, uses less GPU memory
- [ ] Compare: fine-tuned 3B vs GPT-4o-mini for sentiment accuracy on held-out set
- [ ] Tools: `peft`, `trl`, `unsloth` (faster LoRA), SageMaker training job
- [ ] Expected outcome: cheaper, faster sentiment inference at equivalent quality

### Fine-tuning Resume Bullet
> *"Fine-tuned intfloat/multilingual-e5-base embedding model on Vietnamese restaurant review corpus using sentence-transformers contrastive learning; improved ContextualRecall from 0.71 to 0.85 on domain-specific evaluation set, deployed as SageMaker inference endpoint"*

---

## Phase 8 — Multi-Agent + Semantic Kernel
**Estimated time:** 1–2 weeks

### Semantic Kernel (relevant for DXC/Accenture/Deloitte roles)
Semantic Kernel is Microsoft's AI orchestration framework — DXC and Accenture run Azure-first stacks and specifically look for it.

- [ ] Add `semantic-kernel` (`pip install semantic-kernel`)
- [ ] Implement the insight generation workflow as a Semantic Kernel `KernelFunction`:
  ```python
  @kernel_function(description="Analyse customer reviews for a business")
  async def analyse_reviews(self, business_id: str, query: str) -> str:
      ...
  ```
- [ ] Register the RAG retriever as a Semantic Kernel `Plugin`
- [ ] Use Semantic Kernel `Planner` to orchestrate multi-step insight generation
- [ ] Why: shows you can work with both LangChain (standard) and Semantic Kernel (Microsoft enterprise stack)

### Enhanced Multi-Agent System
Building on Phase 3, add:
- [ ] **Memory Agent** — stores conversation history in PostgreSQL, retrieves relevant past queries
- [ ] **Monitoring Agent** — watches for sudden sentiment drops, triggers alerts (email/Slack via AWS SNS)
- [ ] **Report Agent** — runs nightly, generates weekly insight digest, emails to business owner

---

## Summary — Phase Sequence and Timeline

```
Week 1–2:   Phase 1 — Complete RAG (retriever, re-ranker, answer gen, LangChain)
Week 2–3:   Phase 2 — LangSmith observability (automatic with LangChain)
Week 3–5:   Phase 3 — LangGraph agents (Intent, Clarification, Ingestion, Analysis)
Week 5–6:   Phase 4 — DeepEval evaluation + MLflow tracking
            ↑
            ── DEPLOY TO AWS HERE (Phase 5) ──
            ↓
Week 7:     Phase 5 — Terraform + ECS + Bedrock + record demo video
Week 8–9:   Phase 6 — MLflow + SageMaker embedding endpoint
Week 10–12: Phase 7 — Fine-tuning (embedding model with LoRA)
Week 13–14: Phase 8 — Semantic Kernel + enhanced multi-agent
```

---

## Skills Checklist — After All Phases Complete

| Skill | AU Market Demand | Status After Phases |
|-------|-----------------|---------------------|
| RAG architecture (pgvector + HNSW + re-ranking) | 90% GenAI roles | Phase 1 ✅ |
| LangChain (LCEL chains) | 70% GenAI roles | Phase 1 ✅ |
| LlamaIndex | 50% GenAI roles | Phase 1 ✅ |
| LLM Observability (LangSmith) | High demand, rare supply | Phase 2 ✅ |
| LangGraph agentic workflows | Fastest growing senior signal | Phase 3 ✅ |
| Human-in-the-loop AI | Senior differentiator | Phase 3 ✅ |
| DeepEval evaluation framework | Rarest skill, huge gap | Phase 4 ✅ |
| MLflow experiment tracking | 30% postings | Phase 6 ✅ |
| AWS Bedrock | 33% postings | Phase 5 ✅ |
| Amazon SageMaker | 25% postings | Phase 6 ✅ |
| Fine-tuning (LoRA/PEFT) | 25% postings | Phase 7 ✅ |
| Semantic Kernel | DXC/Accenture/Deloitte specific | Phase 8 ✅ |
| Multi-agent systems (LangGraph) | 20%, growing fast | Phase 3+8 ✅ |
| Docker + ECS Fargate | 60% postings | Phase 5 ✅ |
| Terraform (IaC) | 30% postings | Phase 5 ✅ |
| Python + FastAPI | 71% (baseline) | Already ✅ |
| pgvector + PostgreSQL | 40% GenAI roles | Already ✅ |
| Next.js full-stack | 40% full-stack AI | Already ✅ |

---

## Start Now — Phase 1 First Task

```bash
uv add langchain langchain-openai langchain-community langgraph deepeval mlflow langfuse
```

Then implement `pipelines/rag/retriever.py` — the query embedding + cosine similarity search against pgvector.

This single file transforms the project from "stores embeddings" to "retrieves with embeddings" — the core of RAG.
