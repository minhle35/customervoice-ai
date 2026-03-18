from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Optional

from bs4 import BeautifulSoup
from langdetect import detect, LangDetectException


_WHITESPACE_RE = re.compile(r"\s+")


@dataclass
class CleanResult:
    cleaned_text: str
    language: str


def strip_html(text: str) -> str:
    if "<" not in text:
        return text
    soup = BeautifulSoup(text, "html.parser")
    return soup.get_text(" ", strip=True)


def normalize_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text)
    normalized = _WHITESPACE_RE.sub(" ", normalized)
    return normalized.strip()


def truncate_to_max_tokens(text: str, max_tokens: int = 2000, chars_per_token: int = 4) -> str:
    max_chars = max_tokens * chars_per_token
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip()


def detect_language(text: str, fallback: str = "unknown") -> str:
    try:
        return detect(text)
    except LangDetectException:
        return fallback


def clean_review_text(text: str, max_tokens: int = 2000) -> CleanResult:
    stripped = strip_html(text)
    normalized = normalize_text(stripped)
    truncated = truncate_to_max_tokens(normalized, max_tokens=max_tokens)
    language = detect_language(truncated)
    return CleanResult(cleaned_text=truncated, language=language)
