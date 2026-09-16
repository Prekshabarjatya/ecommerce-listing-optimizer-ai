"""TF-IDF + cosine similarity retrieval over knowledge_base chunks.

Same lightweight approach as the sibling ai-logistics-workforce project's
tools/rag_tool.py — no embeddings API call, no vector DB. Good enough for a
knowledge base this size (a few dozen chunks) and keeps this stage runnable
without any API key or external service.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass

import numpy as np

from app.rag.loader import Chunk, load_chunks


def _tokenize(text: str) -> list[str]:
    return [t.lower() for t in text.split() if t.isalpha()]


@dataclass
class ScoredChunk:
    chunk: Chunk
    score: float


class KnowledgeBaseRetriever:
    """Builds a TF-IDF index over the given chunks at construction time."""

    def __init__(self, chunks: list[Chunk] | None = None):
        self.chunks = chunks if chunks is not None else load_chunks()
        self._vectors, self._vocab, self._idf = self._build_index(
            [c.text for c in self.chunks]
        )

    @staticmethod
    def _build_index(texts: list[str]) -> tuple[list[np.ndarray], list[str], dict[str, float]]:
        tokenized = [_tokenize(t) for t in texts]
        vocab = sorted({term for tokens in tokenized for term in tokens})

        doc_freq: Counter = Counter()
        for tokens in tokenized:
            for term in set(tokens):
                doc_freq[term] += 1

        num_docs = len(texts)
        idf = {
            term: math.log((1 + num_docs) / (1 + doc_freq[term])) + 1 for term in vocab
        }

        vectors = []
        for tokens in tokenized:
            term_freq = Counter(tokens)
            vectors.append(np.array([term_freq[term] * idf[term] for term in vocab]))

        return vectors, vocab, idf

    @staticmethod
    def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
        denom = np.linalg.norm(a) * np.linalg.norm(b)
        return float(np.dot(a, b) / denom) if denom else 0.0

    def retrieve(self, query: str, top_k: int = 3) -> list[ScoredChunk]:
        if not self.chunks:
            return []

        query_term_freq = Counter(_tokenize(query))
        query_vector = np.array(
            [query_term_freq[term] * self._idf.get(term, 0) for term in self._vocab]
        )

        scored = [
            ScoredChunk(chunk=chunk, score=self._cosine_similarity(query_vector, vec))
            for chunk, vec in zip(self.chunks, self._vectors)
        ]
        scored.sort(key=lambda sc: sc.score, reverse=True)
        return [sc for sc in scored[:top_k] if sc.score > 0]
