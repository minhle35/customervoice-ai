"""LangChain LCEL chain for grounded answer generation with citation support."""

from __future__ import annotations

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from pipelines.vector_rag.context_builder import build_context
from pipelines.vector_rag.retriever import ReviewChunk

_SYSTEM_PROMPT = """\
You are a customer feedback analyst. Your job is to answer questions about a \
business based solely on real customer reviews provided below.

Rules:
- Answer using ONLY the review excerpts in the context. Do not invent facts.
- Cite specific reviews with their bracketed number, e.g. [1], [2], when referencing them.
- If the reviews don't contain enough information, say so honestly.
- Be concise and actionable — business owners read your answers to make decisions.

--- CUSTOMER REVIEWS ---
{context}
--- END REVIEWS ---"""


def _build_chain(api_key: str, base_url: str, model: str):
    llm = ChatOpenAI(
        api_key=SecretStr(api_key),
        base_url=base_url,
        model=model,
        temperature=0.2,
        max_tokens=1500,
    )
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", _SYSTEM_PROMPT),
            ("human", "{question}"),
        ]
    )
    return prompt | llm | StrOutputParser()


def generate_answer(
    question: str,
    chunks: list[ReviewChunk],
    *,
    api_key: str,
    base_url: str,
    model: str,
    token_budget: int = 2000,
) -> tuple[str, list[ReviewChunk]]:
    """Generate a grounded answer from re-ranked review chunks.

    Args:
        question:     The user's natural language question.
        chunks:       Re-ranked ReviewChunks (highest relevance first).
        api_key:      LLM provider API key.
        base_url:     LLM provider base URL (OpenAI-compatible).
        model:        Model identifier string.
        token_budget: Maximum tokens to allocate for the review context.

    Returns:
        answer:       LLM-generated answer with [N] citation markers.
        used_chunks:  The chunks that were included in the context window.
    """
    context, used_chunks = build_context(chunks, token_budget=token_budget)

    if not used_chunks:
        return (
            "I couldn't find any relevant reviews to answer your question.",
            [],
        )

    chain = _build_chain(api_key=api_key, base_url=base_url, model=model)
    answer: str = chain.invoke({"context": context, "question": question})

    return answer, used_chunks
