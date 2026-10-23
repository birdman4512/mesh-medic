import argparse
import logging
import signal
import sys
import threading

from src.config import load_config
from src.dispatcher import Dispatcher
from src.llm_engine import LLMEngine
from src.rag_engine import RAGEngine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

NO_ANSWER_REPLY = "Sorry, I couldn't produce an answer. Try rephrasing the question."


def build_handler(rag: RAGEngine, llm: LLMEngine, cite_sources: bool = False):
    def handle_message(question: str, sender_id: str, is_dm: bool) -> str:
        logger.info(
            "Question from %s (%d chars, %s)",
            sender_id,
            len(question),
            "DM" if is_dm else "channel",
        )
        logger.debug("Question text from %s: %r", sender_id, question)

        retrieval = rag.retrieve(question)
        if retrieval.context:
            logger.info(
                "Retrieved %d chars of context from %s",
                len(retrieval.context), ", ".join(retrieval.citations),
            )
        else:
            logger.info("No context found — answering from base model knowledge")

        answer = llm.answer(question, retrieval.context) or NO_ANSWER_REPLY
        if cite_sources and retrieval.citations and answer != NO_ANSWER_REPLY:
            answer = f"{answer}\n[{retrieval.citations[0]}]"
        logger.info("Answer prepared (%d chars)", len(answer))
        logger.debug("Answer text: %r", answer)
        return answer

    return handle_message


def create_client(config, on_message):
    # Imported lazily so only the selected backend's library has to be importable.
    if config.radio.type == "meshcore":
        from src.meshcore_client import MeshCoreClient

        return MeshCoreClient(config, on_message=on_message)
    from src.meshtastic_client import MeshtasticClient

    return MeshtasticClient(config, on_message=on_message)


def main():
    parser = argparse.ArgumentParser(description="Mesh Medic offline survival assistant")
    parser.add_argument(
        "--config", default="config.yaml", help="Path to config file (default: config.yaml)"
    )
    args = parser.parse_args()

    config = load_config(args.config)

    logger.info(f"Model: {config.llm.model}")
    logger.info("Initializing RAG engine...")
    rag = RAGEngine(config)
    logger.info(f"Knowledge base: {rag.chunk_count()} chunks from {rag.list_sources()}")

    logger.info("Initializing LLM engine...")
    llm = LLMEngine(config)

    dispatcher = Dispatcher(
        build_handler(rag, llm, cite_sources=config.response.cite_sources), config.limits
    )
    dispatcher.start()

    logger.info(f"Radio backend: {config.radio.type}")
    client = create_client(config, on_message=dispatcher.submit)
    client.connect()

    stop = threading.Event()

    def shutdown(sig, frame):
        logger.info("Shutting down...")
        stop.set()

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    logger.info("Mesh Medic running. Waiting for messages...")
    exit_code = 0
    while not stop.is_set():
        if client.connection_lost.wait(timeout=1):
            # Exit non-zero so systemd (Restart=on-failure) restarts us and reconnects.
            logger.error("Radio connection lost — exiting so the service restarts")
            exit_code = 1
            break

    dispatcher.stop()
    client.disconnect()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
