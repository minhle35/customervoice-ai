"""RAG pipeline evaluation using RAGAS metrics.

Metrics:
  Faithfulness      — does the answer follow from the retrieved context (no hallucination)?
  AnswerRelevancy   — does the answer actually address the question?
  ContextPrecision  — are the most relevant chunks ranked highest?
  ContextRecall     — did retrieval capture all information needed for the ground truth?

Usage (run from repo root, with Docker DB running):
  cd backend
  python tests/evaluation/eval_rag.py --business-id ChIJhTEAbgFB1moRCYXM8lnO3vI

Optional flags:
  --retrieve-top-k  INT   candidates from pgvector (default: 20)
  --rerank-top-k    INT   chunks after cross-encoder (default: 5)
  --run-name        STR   MLflow run label (default: eval_<business_id>)

TODO (multi-system comparison — not yet implemented):
  - Add --system-type flag: baseline | hybrid | graph | agentic | rag_as_service | multimodal
  - Loop over all system types and log each as a separate MLflow run
  - Add DeepEval metrics: HallucinationMetric, AnswerCorrectnessMetric
  - Add custom metrics: source_diversity, citation_coverage
  - Add --golden-dataset flag to specify a path other than the default
  - Expand golden_dataset.json to 50+ samples covering cross-source queries
"""

# ---------------------------------------------------------------------------
# stdlib — sys.path must be patched before any local imports
# ---------------------------------------------------------------------------
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[2]  # .../backend/
_ROOT = _BACKEND.parent  # project root (pipelines/, agents/)
for _p in (str(_BACKEND), str(_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# Load .env from the project root so API keys are available regardless of CWD.
# Must happen before any pydantic-settings ServerSettings instantiation.
from dotenv import load_dotenv  # noqa: E402

load_dotenv(_ROOT / ".env", override=False)

# ---------------------------------------------------------------------------
# third-party  (noqa: E402 — must come after sys.path patch above)
# ---------------------------------------------------------------------------
import mlflow  # noqa: E402
from langchain_openai import ChatOpenAI  # noqa: E402
from pydantic import SecretStr  # noqa: E402
from ragas import EvaluationDataset, SingleTurnSample, evaluate  # noqa: E402
from ragas.dataset_schema import EvaluationResult  # noqa: E402
from ragas.executor import Executor  # noqa: E402
from langchain_community.embeddings import (  # noqa: E402
    HuggingFaceEmbeddings as LangchainHuggingFaceEmbeddings,
)
from ragas.embeddings import LangchainEmbeddingsWrapper  # noqa: E402
from ragas.llms import LangchainLLMWrapper  # noqa: E402

# Legacy metrics — required because evaluate() only accepts BaseRagasLLM-backed
# metrics; ragas.metrics.collections uses a separate, evaluate()-incompatible
# per-sample scoring API (.score()/.ascore()), not the dataset-level evaluate().
from ragas.metrics import (  # noqa: E402
    AnswerRelevancy,
    ContextPrecision,
    ContextRecall,
    Faithfulness,
)

# ---------------------------------------------------------------------------
# local
# ---------------------------------------------------------------------------
from app.config import get_settings  # noqa: E402
from app.database.database import get_session, init_db  # noqa: E402
from pipelines.rag.answer_generator import generate_answer  # noqa: E402
from pipelines.rag.retriever import embed_query, rerank, retrieve  # noqa: E402

GOLDEN_DATASET = Path(__file__).parent / "golden_dataset.json"


def _build_ragas_llm(settings):
    llm = ChatOpenAI(
        api_key=SecretStr(settings.openrouter_api_key),
        base_url=settings.openrouter_base_url,
        model=settings.openrouter_chat_model,
        temperature=0.0,
        max_tokens=1500,
    )
    return LangchainLLMWrapper(llm)


def _build_ragas_embeddings(settings):
    return LangchainEmbeddingsWrapper(
        LangchainHuggingFaceEmbeddings(model_name=settings.embedding_model)
    )


def _run_pipeline(
    db,
    question: str,
    business_id: str,
    retrieve_top_k: int,
    rerank_top_k: int,
    settings,
):
    """Run retrieval + rerank + generate for one question. Returns (answer, contexts)."""
    query_vec = embed_query(question)
    candidates = retrieve(db, query_vec, business_id, top_k=retrieve_top_k)

    if not candidates:
        return None, []

    reranked = rerank(question, candidates, final_top_k=rerank_top_k)
    contexts = [chunk.content for chunk in reranked]

    answer, _ = generate_answer(
        question=question,
        chunks=reranked,
        api_key=settings.openrouter_api_key,
        base_url=settings.openrouter_base_url,
        model=settings.openrouter_chat_model,
        token_budget=2000,
    )
    return answer, contexts


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--business-id", required=True)
    parser.add_argument("--retrieve-top-k", type=int, default=20)
    parser.add_argument("--rerank-top-k", type=int, default=5)
    parser.add_argument("--run-name", default=None)
    parser.add_argument(
        "--limit", type=int, default=None, help="Only run the first N golden questions"
    )
    # TODO: add --system-type once multi-system support is implemented
    args = parser.parse_args()

    settings = get_settings()
    run_name = args.run_name or f"eval_{args.business_id[:8]}"

    golden = json.loads(GOLDEN_DATASET.read_text())
    if args.limit:
        golden = golden[: args.limit]
    print(f"Loaded {len(golden)} golden questions")

    init_db()

    samples = []
    skipped = 0

    with get_session() as db:
        for item in golden:
            question = item["question"]
            ground_truth = item["ground_truth"]

            print(f"  Running: {question[:70]}...")
            answer, contexts = _run_pipeline(
                db,
                question,
                args.business_id,
                args.retrieve_top_k,
                args.rerank_top_k,
                settings,
            )

            if answer is None:
                print("    SKIP — no reviews found for business")
                skipped += 1
                continue

            samples.append(
                SingleTurnSample(
                    user_input=question,
                    response=answer,
                    retrieved_contexts=contexts,
                    reference=ground_truth,
                )
            )

    if not samples:
        print("No samples collected — check business_id and that reviews are ingested.")
        return

    print(
        f"\nCollected {len(samples)} samples ({skipped} skipped). Running RAGAS evaluation..."
    )

    ragas_llm = _build_ragas_llm(settings)
    ragas_embeddings = _build_ragas_embeddings(settings)
    metrics = [
        Faithfulness(llm=ragas_llm),
        AnswerRelevancy(llm=ragas_llm, embeddings=ragas_embeddings),
        ContextPrecision(llm=ragas_llm),
        ContextRecall(llm=ragas_llm),
    ]

    dataset = EvaluationDataset(samples=samples)
    results = evaluate(dataset=dataset, metrics=metrics)

    print("\n=== RAG Evaluation Results ===")
    print(results)

    # evaluate() returns EvaluationResult normally; Executor when return_executor=True
    scores: dict[str, float] = {}
    if isinstance(results, EvaluationResult):
        eval_result: EvaluationResult = results
    elif isinstance(results, Executor):
        eval_result = results.results()
    else:
        raise TypeError(f"Unexpected evaluate() return type: {type(results)}")
    scores = {
        str(k): float(v)
        for k, v in eval_result.to_pandas().mean(numeric_only=True).items()
    }

    with mlflow.start_run(run_name=run_name):
        mlflow.log_params(
            {
                "business_id": args.business_id,
                "retrieve_top_k": args.retrieve_top_k,
                "rerank_top_k": args.rerank_top_k,
                "model": settings.openrouter_chat_model,
                "embedding_model": settings.embedding_model,
                "num_questions": len(samples),
            }
        )
        for metric_name, value in scores.items():
            mlflow.log_metric(str(metric_name), round(value, 4))
            print(f"  {metric_name}: {value:.4f}")

    print(f"\nResults logged to MLflow run: {run_name}")
    print("View with: mlflow ui  (then open http://localhost:5000)")

    THRESHOLDS = {
        "faithfulness": 0.70,
        "answer_relevancy": 0.75,
        "context_precision": 0.60,
        "context_recall": 0.55,
    }
    failed = [k for k, v in scores.items() if v < THRESHOLDS.get(k, 0.0)]
    if failed:
        print(f"\nFAILED quality thresholds: {failed}")
        sys.exit(1)


if __name__ == "__main__":
    main()
