import hashlib
from types import SimpleNamespace

import pytest

from src import rag_engine
from src.config import DataConfig, RAGConfig
from src.rag_engine import RAGEngine


def fake_embed(base_url, model, texts):
    # Deterministic bag-of-words vectors: texts sharing words point the same way.
    vectors = []
    for text in texts:
        v = [0.0] * 32
        for word in text.lower().split():
            v[int(hashlib.md5(word.strip(".,?").encode()).hexdigest(), 16) % 32] += 1.0
        vectors.append(v)
    return vectors


@pytest.fixture
def engine(tmp_path, mocker):
    mocker.patch("src.rag_engine.check_model")
    mocker.patch("src.rag_engine.embed", side_effect=fake_embed)
    config = SimpleNamespace(
        rag=RAGConfig(chunk_size=200, chunk_overlap=20, top_k=2, collection_name="test_docs"),
        data=DataConfig(pdf_dir=str(tmp_path / "pdfs"), vectordb_dir=str(tmp_path / "db")),
        llm=SimpleNamespace(base_url="http://ollama"),
    )
    return RAGEngine(config)


def chunks(n, prefix):
    return [(f"{prefix} passage {i} about boiling water.", i // 10 + 1) for i in range(n)]


def test_ingest_in_batches_and_reingest_replaces(engine, mocker, tmp_path):
    mocker.patch.object(rag_engine, "ADD_BATCH", 7)
    mocker.patch.object(engine, "_extract_chunks", return_value=chunks(25, "first"))
    pdf = tmp_path / "guide.pdf"
    assert engine.ingest_pdf(str(pdf)) == 25
    assert engine.chunk_count() == 25

    engine._extract_chunks.return_value = chunks(5, "second")
    assert engine.ingest_pdf(str(pdf)) == 5
    assert engine.chunk_count() == 5
    assert engine.list_sources() == ["guide.pdf"]


def test_retrieve_returns_context_and_page_citations(engine, mocker, tmp_path):
    mocker.patch.object(
        engine,
        "_extract_chunks",
        return_value=[
            ("Boil water for one minute to purify it.", 4),
            ("Build a shelter out of the wind.", 9),
        ],
    )
    engine.ingest_pdf(str(tmp_path / "survival.pdf"))
    result = engine.retrieve("how long to boil water")
    assert result.context.startswith("Boil water")
    assert result.citations[0] == "survival.pdf p.4"


def test_retrieve_on_empty_collection(engine):
    result = engine.retrieve("anything")
    assert result.context == ""
    assert result.citations == []


def test_failed_embedding_keeps_existing_chunks(engine, mocker, tmp_path):
    mocker.patch.object(engine, "_extract_chunks", return_value=chunks(3, "kept"))
    pdf = tmp_path / "guide.pdf"
    engine.ingest_pdf(str(pdf))
    mocker.patch("src.rag_engine.embed", side_effect=RuntimeError("ollama down"))
    with pytest.raises(RuntimeError):
        engine.ingest_pdf(str(pdf))
    assert engine.chunk_count() == 3
