import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

import chromadb
import pdfplumber
from chromadb.config import Settings

from src.ollama import check_model, embed
from src.utils import chunk_document

logger = logging.getLogger(__name__)

# Texts per Ollama embedding request during ingestion.
EMBED_BATCH = 64
# Upper bound on chunks per Chroma add() call; Chroma also enforces its own maximum.
ADD_BATCH = 1000


@dataclass
class Retrieval:
    context: str = ""
    citations: List[str] = field(default_factory=list)  # "file.pdf p.12", best match first


class RAGEngine:
    def __init__(self, config):
        self.rag_cfg = config.rag
        self.data_cfg = config.data
        self.base_url = config.llm.base_url
        self._init_db()
        check_model(self.base_url, self.rag_cfg.embedding_model)

    def _init_db(self):
        Path(self.data_cfg.vectordb_dir).mkdir(parents=True, exist_ok=True)
        self.client = chromadb.PersistentClient(
            path=self.data_cfg.vectordb_dir,
            settings=Settings(anonymized_telemetry=False),
        )
        self.collection = self.client.get_or_create_collection(
            name=self.rag_cfg.collection_name,
            metadata={"hnsw:space": "cosine", "embedding_model": self.rag_cfg.embedding_model},
        )
        stored = (self.collection.metadata or {}).get("embedding_model")
        if stored and stored != self.rag_cfg.embedding_model and self.collection.count():
            logger.warning(
                "Knowledge base was built with embedding model %r but %r is configured. "
                "Re-ingest your PDFs or retrieval will return poor matches.",
                stored, self.rag_cfg.embedding_model,
            )

    def _embed(self, texts: List[str]) -> List[List[float]]:
        return embed(self.base_url, self.rag_cfg.embedding_model, texts)

    def ingest_pdf(self, pdf_path: str) -> int:
        path = Path(pdf_path)
        logger.info(f"Ingesting: {path.name}")

        chunks = self._extract_chunks(path)
        if not chunks:
            logger.warning(f"No text extracted from {path.name}")
            return 0

        texts = [text for text, _ in chunks]
        embeddings: List[List[float]] = []
        for start in range(0, len(texts), EMBED_BATCH):
            embeddings.extend(self._embed(texts[start:start + EMBED_BATCH]))
            logger.info(f"Embedded {len(embeddings)}/{len(texts)} chunks")

        # Remove existing chunks for this file so re-ingestion is safe
        existing = self.collection.get(where={"source": path.name}, include=[])
        if existing["ids"]:
            self.collection.delete(ids=existing["ids"])
            logger.info(f"Removed {len(existing['ids'])} existing chunks for {path.name}")

        ids = [f"{path.name}:{i}" for i in range(len(chunks))]
        metadatas = [
            {"source": path.name, "chunk_index": i, "page": page}
            for i, (_, page) in enumerate(chunks)
        ]

        batch = min(ADD_BATCH, self.client.get_max_batch_size())
        for start in range(0, len(chunks), batch):
            end = start + batch
            self.collection.add(
                documents=texts[start:end],
                embeddings=embeddings[start:end],
                ids=ids[start:end],
                metadatas=metadatas[start:end],
            )
        logger.info(f"Ingested {len(chunks)} chunks from {path.name}")
        return len(chunks)

    def _extract_chunks(self, path: Path) -> List[tuple[str, int]]:
        pages = []
        with pdfplumber.open(path) as pdf:
            for number, page in enumerate(pdf.pages, start=1):
                page_text = page.extract_text()
                if page_text and page_text.strip():
                    pages.append((number, page_text))

        return chunk_document(pages, self.rag_cfg.chunk_size, self.rag_cfg.chunk_overlap)

    def retrieve(self, query: str) -> Retrieval:
        count = self.collection.count()
        if count == 0:
            return Retrieval()

        results = self.collection.query(
            query_embeddings=self._embed([query]),
            n_results=min(self.rag_cfg.top_k, count),
            include=["documents", "metadatas"],
        )

        docs = results["documents"][0]
        metas = results["metadatas"][0]
        citations = []
        for meta in metas:
            page = meta.get("page")
            citations.append(f"{meta['source']} p.{page}" if page else meta["source"])
        return Retrieval(context="\n\n---\n\n".join(docs), citations=citations)

    def list_sources(self) -> List[str]:
        if self.collection.count() == 0:
            return []
        all_items = self.collection.get(include=["metadatas"])
        sources = {m["source"] for m in all_items["metadatas"]}
        return sorted(sources)

    def chunk_count(self) -> int:
        return self.collection.count()
