"""Shared LangChain LCEL chain for grounded answer generation.

Used identically by both VectorRAG and GraphRAG — per the README's stated
design, the prompt only needs a question and a budget-limited citation-text
block; it doesn't care whether that text came from review chunks
(pipelines/vector_rag/context_builder.py) or serialized graph relationships
(pipelines/graph_rag/context_builder.py). This function takes the
already-built context string, not a system-specific evidence type, so it
has no knowledge of ReviewChunk or GraphFact.

Originally lived in pipelines/vector_rag/answer_generator.py tied to
ReviewChunk; moved here per the README's "Answer generation" tradeoff
("a small refactor of already-working VectorRAG code was required up front,
before any GraphRAG-specific code existed").
"""

from __future__ import annotations

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

_SYSTEM_PROMPT = """\
You are a customer feedback analyst. Your job is to answer questions about a \
business based solely on the evidence provided below.

Rules:
- Answer using ONLY the evidence in the context. Do not invent facts.
- Cite specific evidence with its bracketed number, e.g. [1], [2], when referencing it.
- If the evidence doesn't contain enough information, say so honestly.
- Be concise and actionable — business owners read your answers to make decisions.

--- EVIDENCE ---
{context}
--- END EVIDENCE ---"""


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
    context: str,
    *,
    api_key: str,
    base_url: str,
    model: str,
) -> str:
    """Generate a grounded answer from an already-built, token-budgeted context string.

    Args:
        question: The user's natural language question.
        context:  Pre-formatted, citation-numbered evidence text — the
                  output of a system's own build_context(). Callers are
                  responsible for the empty-candidates case (e.g. "no
                  reviews ingested yet") before reaching this function;
                  an empty/blank context here means candidates existed but
                  none fit the token budget.
        api_key:  LLM provider API key.
        base_url: LLM provider base URL (OpenAI-compatible).
        model:    Model identifier string.

    Returns:
        LLM-generated answer with [N] citation markers.
    """
    if not context.strip():
        return "I couldn't find any relevant evidence to answer your question."

    chain = _build_chain(api_key=api_key, base_url=base_url, model=model)
    return chain.invoke({"context": context, "question": question})
