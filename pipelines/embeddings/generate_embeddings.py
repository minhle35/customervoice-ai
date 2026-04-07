from __future__ import annotations

from sentence_transformers import SentenceTransformer

from app.config import get_settings

# Load once at module level — avoids reloading the model on every call
_model: SentenceTransformer | None = None


def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer(get_settings().embedding_model)
    return _model


def generate_embedding(text: str) -> list[float]:
    """Return a 768-dim embedding vector for the given text.

    multilingual-e5 models require a task prefix:
      - 'passage: ' for documents being indexed (reviews)
      - 'query: '   for search queries at retrieval time
    """
    model = _get_model()
    vector = model.encode(f"passage: {text}", normalize_embeddings=True)
    return vector.tolist()
