import logging
from pathlib import Path
from typing import List

import chromadb
import pdfplumber
from chromadb.config import Settings
from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)


class RAGEngine:
    def __init__(self, config):
        self.rag_cfg = config.rag
        self.data_cfg = config.data
        self._init_db()
        self._init_embedder()

    def _init_db(self):
        Path(self.data_cfg.vectordb_dir).mkdir(parents=True, exist_ok=True)
        self.client = chromadb.PersistentClient(
            path=self.data_cfg.vectordb_dir,
            settings=Settings(anonymized_telemetry=False),
        )
        self.collection = self.client.get_or_create_collection(
            name=self.rag_cfg.collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    def _init_embedder(self):
        logger.info("Loading embedding model (all-MiniLM-L6-v2)...")
        self.embedder = SentenceTransformer("all-MiniLM-L6-v2")
        logger.info("Embedding model ready.")

    def ingest_pdf(self, pdf_path: str) -> int:
        path = Path(pdf_path)
        logger.info(f"Ingesting: {path.name}")

        chunks = self._extract_chunks(path)
        if not chunks:
            logger.warning(f"No text extracted from {path.name}")
            return 0

        # Remove existing chunks for this file so re-ingestion is safe
        existing = self.collection.get(where={"source": path.name})
        if existing["ids"]:
            self.collection.delete(ids=existing["ids"])
            logger.info(f"Removed {len(existing['ids'])} existing chunks for {path.name}")

        embeddings = self.embedder.encode(chunks, show_progress_bar=True).tolist()
        ids = [f"{path.stem}_{i}" for i in range(len(chunks))]
        metadatas = [{"source": path.name, "chunk_index": i} for i in range(len(chunks))]

        self.collection.add(
            documents=chunks,
            embeddings=embeddings,
            ids=ids,
            metadatas=metadatas,
        )
        logger.info(f"Ingested {len(chunks)} chunks from {path.name}")
        return len(chunks)

    def _extract_chunks(self, path: Path) -> List[str]:
        text_parts = []
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(page_text)

        full_text = "\n".join(text_parts)
        if not full_text.strip():
            return []

        size = self.rag_cfg.chunk_size
        overlap = self.rag_cfg.chunk_overlap
        chunks = []
        start = 0

        while start < len(full_text):
            end = start + size
            chunk = full_text[start:end].strip()
            if chunk:
                chunks.append(chunk)
            start = end - overlap

        return chunks

    def retrieve(self, query: str) -> str:
        count = self.collection.count()
        if count == 0:
            return ""

        embedding = self.embedder.encode([query]).tolist()
        results = self.collection.query(
            query_embeddings=embedding,
            n_results=min(self.rag_cfg.top_k, count),
        )

        docs = results["documents"][0]
        return "\n\n---\n\n".join(docs) if docs else ""

    def list_sources(self) -> List[str]:
        if self.collection.count() == 0:
            return []
        all_items = self.collection.get()
        sources = {m["source"] for m in all_items["metadatas"]}
        return sorted(sources)

    def chunk_count(self) -> int:
        return self.collection.count()
