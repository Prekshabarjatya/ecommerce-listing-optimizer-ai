"""CLI: query the Santerra RAG knowledge base.

Usage:
    python scripts/query_knowledge_base.py "is fully biodegradable an approved claim?"
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.rag.retriever import KnowledgeBaseRetriever


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query")
    parser.add_argument("--top-k", type=int, default=3)
    args = parser.parse_args()

    retriever = KnowledgeBaseRetriever()
    results = retriever.retrieve(args.query, top_k=args.top_k)

    if not results:
        print("No matching chunks found.")
        return

    for i, scored in enumerate(results, 1):
        print(f"[{i}] score={scored.score:.3f}  {scored.chunk.source_file} § {scored.chunk.heading}")
        print(scored.chunk.text)
        print()


if __name__ == "__main__":
    main()
