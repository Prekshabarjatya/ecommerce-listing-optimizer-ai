from app.rag.loader import Chunk, load_chunks
from app.rag.retriever import KnowledgeBaseRetriever


def _fixture_chunks() -> list[Chunk]:
    return [
        Chunk(
            source_file="sustainability_and_claims.md",
            heading="Environmental Claims Policy",
            text=(
                "## Environmental Claims Policy\n\n"
                "Approved: biodegradable materials, responsibly sourced paper. "
                "Claims requiring verification: fully biodegradable, compostable, "
                "carbon neutral, zero waste, plastic-free, 100% sustainable."
            ),
        ),
        Chunk(
            source_file="marketing_and_channels.md",
            heading="E-Commerce Marketplaces",
            text=(
                "## E-Commerce Marketplaces\n\n"
                "Amazon India, Flipkart, Meesho are the primary marketplaces."
            ),
        ),
        Chunk(
            source_file="company_and_brand.md",
            heading="Brand Tagline",
            text='## Brand Tagline\n\n"Hygiene for Everyone"',
        ),
    ]


def test_load_chunks_from_real_knowledge_base_dir():
    chunks = load_chunks()
    assert len(chunks) > 5
    assert any(c.source_file == "sustainability_and_claims.md" for c in chunks)


def test_retrieve_ranks_most_relevant_chunk_first():
    retriever = KnowledgeBaseRetriever(chunks=_fixture_chunks())

    results = retriever.retrieve("is fully biodegradable an approved claim", top_k=1)

    assert len(results) == 1
    assert results[0].chunk.heading == "Environmental Claims Policy"
    assert results[0].score > 0


def test_retrieve_returns_source_for_citation():
    retriever = KnowledgeBaseRetriever(chunks=_fixture_chunks())

    results = retriever.retrieve("which marketplaces does Santerra sell on", top_k=1)

    assert results[0].chunk.source_file == "marketing_and_channels.md"


def test_retrieve_on_empty_index_returns_nothing():
    retriever = KnowledgeBaseRetriever(chunks=[])
    assert retriever.retrieve("anything") == []


def test_retrieve_with_no_matching_terms_returns_nothing():
    retriever = KnowledgeBaseRetriever(chunks=_fixture_chunks())
    results = retriever.retrieve("zzz nonexistent qqq")
    assert results == []
