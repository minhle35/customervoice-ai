r"""Debug helper — explains WHY a golden question scored the way it did, not just the score.

`eval_rag.py` only reports aggregate scores (e.g. `context_precision: 0.4564` across 20
questions) — a low number with no way to tell whether retrieval is bad, the golden dataset's
ground truth doesn't match the real review corpus, or the generated answer leaked noise from
an irrelevant chunk. This script runs the real retrieval pipeline per question, then drills
into four independent diagnostics, each isolating a different failure mode:

1. **context_precision** (always runs) — re-invokes RAGAS's per-chunk judge prompt directly
   (not the public single-float API) so each of the top-5 reranked chunks gets its own
   USEFUL/not-useful verdict + stated reason. Manually replicates the real metric's
   ensembler-based majority-vote aggregation (not `verdicts[0]`) so the printed verdicts can't
   disagree with their own breakdown.
2. **average-precision breakdown** (always runs) — reimplements the score formula
   position-by-position, showing exactly how much a correctly-retrieved-but-poorly-ranked
   chunk drags the aggregate down (the metric rewards relevant chunks ranked early).
3. **context_entity_recall** (always runs) — extracts named entities from the ground truth and
   from the contexts separately, so a low score shows *which* entities (dish names, staff
   names) are missing from retrieval, rather than one opaque float. This is what would have
   caught, directly, the earlier finding that some ground truths name entities that don't
   exist in the real review corpus.
4. **noise_sensitivity** and **faithfulness_with_hhem** (opt-in via `--diagnostics`, see below)
   — the expensive diagnostics. noise_sensitivity checks whether an irrelevant chunk actually
   corrupted the generated answer (~12 sequential LLM calls/question, ~50-90s); faithfulness_with_hhem
   is a non-LLM-judge cross-check via Vectara's HHEM model (currently fails to load in this
   environment due to a `transformers` version incompatibility — skipped gracefully, not fatal).

Design notes:
- `_log()` prints with elapsed-since-last-step timing and `flush=True` on every call — needed
  because stdout block-buffers (not line-buffers) when piped through `grep`, which can make the
  last visible line lie about where execution actually is. Use this to find genuine bottlenecks
  instead of mistaking a slow-but-working step for a hang.
- Not a pytest test — costs real LLM tokens per chunk per question, excluded from collection via
  `collect_ignore_glob` in `pyproject.toml`.

Run directly:
  cd backend
  DB__HOST=localhost uv run python tests/evaluation/debug_context_precision.py --business-id <ID> --limit 5
  DB__HOST=localhost uv run python tests/evaluation/debug_context_precision.py --business-id <ID> --diagnostics noise_sensitivity faithfulness_hhem

  Optional: filter dependency-version noise from stdout
  grep -v "ResourceTracker\|RLock\|recursion_count\|self\._stop\|Deprecat\|UNEXPECTED\|Loading weights\|^Key\|^---\|^Notes\|LOAD REPORT\|can be ignored"
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[2]
_ROOT = _BACKEND.parent
for _p in (str(_BACKEND), str(_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(_ROOT / ".env", override=False)

from langchain_openai import ChatOpenAI  # noqa: E402
from pydantic import SecretStr  # noqa: E402
from ragas.llms import LangchainLLMWrapper  # noqa: E402
from ragas.metrics import (  # noqa: E402
    ContextEntityRecall,
    ContextPrecision,
    FaithfulnesswithHHEM,
    NoiseSensitivity,
)
from ragas.metrics._context_precision import QAC, Verification  # noqa: E402
from ragas.metrics.base import ensembler  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.database.database import get_session, init_db  # noqa: E402
from pipelines.vector_rag.answer_generator import generate_answer  # noqa: E402
from pipelines.vector_rag.retriever import embed_query, rerank, retrieve  # noqa: E402

GOLDEN_DATASET = Path(__file__).parent / "golden_dataset.json"

_last_log_time = time.monotonic()


def _log(msg: str) -> None:
    """Prints with elapsed-since-last-log timing, flushed immediately.

    flush=True matters here: stdout is fully block-buffered (not line-buffered)
    whenever it isn't a real terminal — e.g. when piped through `grep`, as the
    --limit 5 repro command does. Without flush=True, prints can sit in a pipe
    buffer and never reach the screen until the buffer fills or the process
    exits, making the LAST visible line a lie about where execution actually is.
    """
    global _last_log_time
    now = time.monotonic()
    elapsed = now - _last_log_time
    _last_log_time = now
    print(f"  [+{elapsed:6.2f}s] {msg}", flush=True)


async def debug_one(metric, question, ground_truth, contexts) -> list[Verification]:
    print(f"\n{'=' * 90}")
    print(f"Q: {question}")
    print(f"Ground truth: {ground_truth}")
    print(f"{'-' * 90}")

    # generate_multiple() returns list[Verification] — one per LLM sample. The real
    # metric majority-votes across all samples via ensembler.from_discrete(); taking
    # verdicts[0] alone can disagree with the aggregate score printed below if the
    # judge LLM's samples don't all agree.
    finals: list[Verification] = []
    for i, ctx in enumerate(contexts, 1):
        _log(
            f"context_precision: judging chunk {i}/{len(contexts)} — calling LLM judge..."
        )
        verdicts = await metric.context_precision_prompt.generate_multiple(
            data=QAC(question=question, context=ctx, answer=ground_truth),
            llm=metric.llm,
        )
        _log(f"context_precision: chunk {i}/{len(contexts)} judged")
        if len(verdicts) > 1 and len({v.verdict for v in verdicts}) > 1:
            sample_tags = ", ".join(str(v.verdict) for v in verdicts)
            print(f"      ({len(verdicts)} samples disagreed: [{sample_tags}])")

        responses = [v.model_dump() for v in verdicts]
        agg_answer = ensembler.from_discrete([responses], "verdict")
        final = Verification(**agg_answer[0])
        finals.append(final)

        tag = "USEFUL" if final.verdict == 1 else "not useful"
        print(f"[{i}] {tag:11s} | {ctx[:100]!r}")
        if final.reason:
            print(f"      reason: {final.reason}")

    # NOTE: we deliberately do NOT call metric._ascore(...) here to get the official
    # score — that would re-invoke the LLM judge on every chunk a second time, and
    # since the judge isn't perfectly deterministic even at temperature=0.0, a fresh
    # call can disagree with the verdicts already printed above, producing a score
    # that looks inconsistent with its own breakdown. debug_average_precision_breakdown()
    # computes the identical formula from these same `finals`, so it can't disagree.
    return finals


def debug_average_precision_breakdown(verifications: list[Verification]) -> float:
    """Reimplements LLMContextPrecisionWithReference._calculate_average_precision,
    printing the per-position contribution instead of just the final float.

    Average Precision rewards relevant (verdict=1) chunks ranked EARLY: each
    relevant chunk's contribution is precision@its-own-position, so the same
    chunk scores higher near the top of the ranking than near the bottom —
    this is what makes the metric sensitive to rerank ordering, not just
    "how many of the 5 chunks were relevant."
    """
    verdict_list = [1 if v.verdict else 0 for v in verifications]
    denominator = sum(verdict_list) + 1e-10

    print(
        "\n  Average-precision breakdown (position : verdict : precision@k : contribution):"
    )
    numerator = 0.0
    cumulative_relevant = 0
    for i, verdict in enumerate(verdict_list):
        cumulative_relevant += verdict
        precision_at_k = cumulative_relevant / (i + 1)
        contribution = precision_at_k * verdict
        numerator += contribution
        print(
            f"    [{i + 1}] verdict={verdict}  precision@{i + 1}={precision_at_k:.3f}"
            f"  contribution={contribution:.3f}"
        )

    score = numerator / denominator
    print(
        f"  => sum(contributions)={numerator:.3f} / relevant_count={sum(verdict_list)} = {score:.4f}"
    )
    return score


async def debug_context_entity_recall(
    metric: ContextEntityRecall, ground_truth: str, contexts: list[str]
):
    """Extracts entities from ground_truth and from the retrieved contexts separately,
    so a low score is explained by *which* named entities (dish names, staff names, etc.)
    are missing from retrieval — not just a single opaque float.
    """
    _log("context_entity_recall: extracting entities from ground_truth...")
    gt_entities = await metric.get_entities(ground_truth, callbacks=None)
    _log("context_entity_recall: extracting entities from contexts...")
    ctx_entities = await metric.get_entities("\n".join(contexts), callbacks=None)
    _log("context_entity_recall: done")

    gt_set, ctx_set = set(gt_entities.entities), set(ctx_entities.entities)
    matched = gt_set & ctx_set
    missing = gt_set - ctx_set
    score = metric._compute_score(gt_entities.entities, ctx_entities.entities)

    print(f"\n  context_entity_recall: {score:.4f}")
    print(f"    ground_truth entities: {sorted(gt_set)}")
    print(f"    matched in contexts:   {sorted(matched)}")
    if missing:
        print(
            f"    MISSING from contexts: {sorted(missing)}  <- likely cause of a low score"
        )


async def debug_noise_sensitivity(
    metric: NoiseSensitivity,
    question: str,
    response: str,
    ground_truth: str,
    contexts: list[str],
):
    """Unlike context_precision (is this chunk relevant to the reference?), this asks
    a different question: did an irrelevant/noisy chunk actually leak into and corrupt
    the *generated answer*? Requires the real generated answer, not just retrieval output.
    """
    _log(
        "noise_sensitivity: scoring (decomposes response + reference into statements, "
        "checks each against every context — multiple LLM calls)..."
    )
    score = await metric._ascore(
        {
            "user_input": question,
            "response": response,
            "reference": ground_truth,
            "retrieved_contexts": contexts,
        },
        None,
    )
    _log("noise_sensitivity: done")
    print(f"\n  noise_sensitivity ({metric.mode}): {score:.4f}")
    print(
        "    (fraction of incorrect-answer claims traceable to noisy/irrelevant retrieved chunks)"
    )


async def debug_faithfulness_hhem(
    metric: FaithfulnesswithHHEM, question: str, response: str, contexts: list[str]
):
    """Faithfulness via a dedicated hallucination-detection model (Vectara HHEM) instead
    of an LLM judge — a cheaper, non-LLM cross-check against RAGAS's default LLM-judged
    Faithfulness, useful when you suspect the judge LLM itself may be unreliable.
    """
    _log("faithfulness_with_hhem: scoring...")
    score = await metric._ascore(
        {"user_input": question, "response": response, "retrieved_contexts": contexts},
        None,
    )
    _log("faithfulness_with_hhem: done")
    print(
        f"\n  faithfulness_with_hhem: {score:.4f}  (non-LLM cross-check against judge-based Faithfulness)"
    )


async def run_all(args, golden, settings):
    init_db()

    llm = ChatOpenAI(
        api_key=SecretStr(settings.openrouter_api_key),
        base_url=settings.openrouter_base_url,
        model=settings.openrouter_chat_model,
        temperature=0.0,
        max_tokens=1500,
    )
    wrapped_llm = LangchainLLMWrapper(llm)
    context_precision_metric = ContextPrecision(llm=wrapped_llm)
    entity_recall_metric = ContextEntityRecall(llm=wrapped_llm)

    noise_sensitivity_metric = None
    if "noise_sensitivity" in args.diagnostics:
        noise_sensitivity_metric = NoiseSensitivity(llm=wrapped_llm)

    faithfulness_hhem_metric = None
    if "faithfulness_hhem" in args.diagnostics:
        # __post_init__ downloads vectara/hallucination_evaluation_model from HF on
        # first run. Its remote modeling code can be incompatible with newer
        # `transformers` releases — skip this one diagnostic rather than crash if so.
        try:
            faithfulness_hhem_metric = FaithfulnesswithHHEM(llm=wrapped_llm)
        except Exception as exc:  # noqa: BLE001
            print(
                f"[skip] faithfulness_with_hhem unavailable in this environment: {exc}"
            )

    with get_session() as db:
        for qi, item in enumerate(golden, 1):
            question = item["question"]
            ground_truth = item["ground_truth"]
            print(f"\n### Question {qi}/{len(golden)} ###")
            print("Question: ", question)
            print("Ground truth: ", ground_truth)

            _log("embed_query: encoding question...")
            query_vec = embed_query(question)
            _log("embed_query: done")

            _log("retrieve: pgvector HNSW search...")
            candidates = retrieve(db, query_vec, args.business_id, top_k=20)
            _log(f"retrieve: done ({len(candidates)} candidates)")
            if not candidates:
                print(f"\nQ: {question}\n  SKIP — no candidates retrieved")
                continue

            _log("rerank: cross-encoder scoring...")
            reranked = rerank(question, candidates, final_top_k=5)
            _log("rerank: done")
            contexts = [chunk.content for chunk in reranked]

            _log(
                "generate_answer: calling LLM (blocking, sync call inside async loop)..."
            )
            answer, _used_chunks = generate_answer(
                question=question,
                chunks=reranked,
                api_key=settings.openrouter_api_key,
                base_url=settings.openrouter_base_url,
                model=settings.openrouter_chat_model,
                token_budget=2000,
            )
            _log("generate_answer: done")

            finals = await debug_one(
                context_precision_metric, question, ground_truth, contexts
            )
            debug_average_precision_breakdown(finals)
            await debug_context_entity_recall(
                entity_recall_metric, ground_truth, contexts
            )
            if noise_sensitivity_metric is not None:
                await debug_noise_sensitivity(
                    noise_sensitivity_metric, question, answer, ground_truth, contexts
                )
            if faithfulness_hhem_metric is not None:
                await debug_faithfulness_hhem(
                    faithfulness_hhem_metric, question, answer, contexts
                )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--business-id", required=True)
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument(
        "--diagnostics",
        nargs="+",
        choices=["noise_sensitivity", "faithfulness_hhem"],
        default=[],
        help=(
            "Opt-in slow diagnostics. context_precision + entity_recall always run "
            "(fast). noise_sensitivity adds ~12 sequential LLM calls per question "
            "(~50-90s); faithfulness_hhem downloads a HF model on first use. "
            "Example: --diagnostics noise_sensitivity"
        ),
    )
    args = parser.parse_args()

    settings = get_settings()
    golden = json.loads(GOLDEN_DATASET.read_text())[: args.limit]

    asyncio.run(run_all(args, golden, settings))


if __name__ == "__main__":
    main()
