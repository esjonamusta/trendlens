from __future__ import annotations

from app.core.config import settings
from app.core.logger import get_logger

log = get_logger(__name__)

_MODEL = "text-embedding-3-small"

# Cosine similarity threshold for embedding-based topic matching.
# Empirically, 0.65 catches paraphrases of the same story while rejecting
# unrelated topics. Jaccard uses 0.20 for comparison.
EMBED_MATCH_THRESHOLD = 0.65


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = sum(x * x for x in a) ** 0.5
    mag_b = sum(x * x for x in b) ** 0.5
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


async def _fetch(texts: list[str]) -> list[list[float]] | None:
    if not settings.openai_api_key:
        log.warning("OPENAI_API_KEY not set — falling back to Jaccard matching")
        return None
    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=settings.openai_api_key)
        response = await client.embeddings.create(model=_MODEL, input=texts)
        # API returns items in the order requested; sort by index to be safe
        ordered = sorted(response.data, key=lambda x: x.index)
        return [item.embedding for item in ordered]
    except Exception as exc:
        log.warning(f"Embedding API error — falling back to Jaccard: {exc}")
        return None


async def build_similarity_matrix(
    texts_a: list[str],
    texts_b: list[str],
) -> list[list[float]] | None:
    """Return sim_matrix[i][j] = cosine similarity(texts_a[i], texts_b[j]).

    Returns None if embeddings are unavailable, signalling the caller to use Jaccard.
    Both lists are embedded in a single API call to minimise latency.
    """
    if not texts_a or not texts_b:
        return None

    embeddings = await _fetch(texts_a + texts_b)
    if embeddings is None:
        return None

    emb_a = embeddings[: len(texts_a)]
    emb_b = embeddings[len(texts_a) :]

    return [
        [_cosine(ea, eb) for eb in emb_b]
        for ea in emb_a
    ]
