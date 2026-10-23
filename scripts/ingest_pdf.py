#!/usr/bin/env python3
"""Ingest PDFs into the Mesh Medic knowledge base."""
import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import load_config
from src.rag_engine import RAGEngine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)


def main():
    parser = argparse.ArgumentParser(
        description="Ingest PDFs into the Mesh Medic knowledge base"
    )
    parser.add_argument("pdfs", nargs="*", metavar="pdf", help="Path(s) to PDF file(s) to ingest")
    parser.add_argument("--list", action="store_true", help="List all ingested sources")
    parser.add_argument(
        "--config", default="config.yaml", help="Path to config file (default: config.yaml)"
    )
    args = parser.parse_args()

    if not args.list and not args.pdfs:
        parser.print_help()
        sys.exit(1)

    pdf_paths = [Path(p) for p in args.pdfs]
    for pdf_path in pdf_paths:
        if not pdf_path.exists():
            print(f"Error: File not found: {pdf_path}", file=sys.stderr)
            sys.exit(1)
        if pdf_path.suffix.lower() != ".pdf":
            print(f"Error: Expected a .pdf file, got: {pdf_path.name}", file=sys.stderr)
            sys.exit(1)

    config = load_config(args.config)
    rag = RAGEngine(config)

    if args.list:
        sources = rag.list_sources()
        if sources:
            print(f"Ingested sources ({rag.chunk_count()} total chunks):")
            for s in sources:
                print(f"  {s}")
        else:
            print("No sources ingested yet.")
        if not pdf_paths:
            return

    failed = []
    for pdf_path in pdf_paths:
        count = rag.ingest_pdf(str(pdf_path))
        if count > 0:
            print(f"Done. Ingested {count} chunks from {pdf_path.name}")
        else:
            print(f"Warning: No text extracted from {pdf_path.name}", file=sys.stderr)
            failed.append(pdf_path.name)

    print(f"Total knowledge base: {rag.chunk_count()} chunks across {len(rag.list_sources())} source(s)")
    print("If the mesh-medic service is running, restart it to pick up the new content:")
    print("  sudo systemctl restart mesh-medic")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
