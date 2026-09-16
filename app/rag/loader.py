"""Load knowledge_base/*.md into section-level chunks for retrieval.

Splitting on "## " headings keeps each chunk topically narrow (a handful of
sentences to a short table) so retrieval returns focused evidence rather
than a whole multi-topic document.
"""

from __future__ import annotations

import glob
import re
from pathlib import Path

from pydantic import BaseModel

KNOWLEDGE_BASE_DIR = Path(__file__).resolve().parent.parent.parent / "knowledge_base"

_H1_RE = re.compile(r"^# (.+)$", re.MULTILINE)
_H2_SPLIT_RE = re.compile(r"^## (.+)$", re.MULTILINE)


class Chunk(BaseModel):
    source_file: str
    heading: str
    text: str


def _chunk_document(path: Path) -> list[Chunk]:
    content = path.read_text(encoding="utf-8")
    source_file = path.name

    h1_match = _H1_RE.search(content)
    title = h1_match.group(1).strip() if h1_match else source_file

    parts = _H2_SPLIT_RE.split(content)
    # re.split with a capturing group interleaves: [preamble, heading1, body1, heading2, body2, ...]
    preamble = parts[0]
    chunks: list[Chunk] = []

    if preamble.strip():
        chunks.append(Chunk(source_file=source_file, heading=title, text=preamble.strip()))

    for i in range(1, len(parts), 2):
        heading = parts[i].strip()
        body = parts[i + 1].strip() if i + 1 < len(parts) else ""
        text = f"## {heading}\n\n{body}" if body else f"## {heading}"
        chunks.append(Chunk(source_file=source_file, heading=heading, text=text))

    return chunks


def load_chunks(knowledge_base_dir: str | Path = KNOWLEDGE_BASE_DIR) -> list[Chunk]:
    chunks: list[Chunk] = []
    for path in sorted(glob.glob(str(Path(knowledge_base_dir) / "*.md"))):
        chunks.extend(_chunk_document(Path(path)))
    return chunks
