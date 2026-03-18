from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Optional

from openai import OpenAI
from app.models.review import SentimentLabel

from app.config import settings


@dataclass
class SentimentResult:
    sentiment_score: float
    sentiment_label: Optional[SentimentLabel]
    topics: Optional[list[str]] = None


def _client() -> OpenAI:
    return OpenAI(
        api_key=settings.openrouter_api_key,
        base_url=settings.openrouter_base_url,
    )


def _extract_json(text: str) -> dict:
    """Extract first JSON object from model output, handling markdown code blocks."""
    # Strip ```json ... ``` fences if present
    text = re.sub(r"```(?:json)?\s*", "", text).strip().rstrip("`").strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return {}


def analyze_sentiment_and_topics(text: str, max_topics: int = 5) -> SentimentResult:
    """Return sentiment score + label + topics in one call."""
    if not text.strip():
        return SentimentResult(
            sentiment_score=0.0, sentiment_label=SentimentLabel.neutral, topics=[]
        )

    prompt = (
        "You analyze a customer review. "
        "Respond with ONLY a JSON object — no explanation, no markdown — with these keys:\n"
        "  sentiment_score: float from -1.0 (very negative) to 1.0 (very positive)\n"
        "  sentiment_label: one of positive, negative, neutral\n"
        f"  topics: array of up to {max_topics} short noun phrases describing what the review is about\n"
        'Example: {"sentiment_score": 0.8, "sentiment_label": "positive", "topics": ["food quality", "service"]}'
    )
    resp = _client().chat.completions.create(
        model=settings.openrouter_chat_model,
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": text},
        ],
        temperature=0.2,
    )
    content = resp.choices[0].message.content or "{}"
    data = _extract_json(content)

    topics = data.get("topics") or []
    if not isinstance(topics, list):
        topics = []
    topics = [str(t).strip() for t in topics if str(t).strip()][:max_topics]

    raw_label = data.get("sentiment_label", "neutral")
    try:
        sentiment_label = SentimentLabel(raw_label)
    except ValueError:
        sentiment_label = SentimentLabel.neutral

    return SentimentResult(
        sentiment_score=float(data.get("sentiment_score", 0.0)),
        sentiment_label=sentiment_label,
        topics=topics,
    )
