import logging
import signal
import sys
import time

from src.config import load_config
from src.llm_engine import LLMEngine
from src.meshcore_client import MeshCoreClient
from src.meshtastic_client import MeshtasticClient
from src.rag_engine import RAGEngine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def build_handler(rag: RAGEngine, llm: LLMEngine):
    def handle_message(question: str, sender_id: str, is_dm: bool) -> str:
        logger.info(
            "Question from %s (%d chars, %s)",
            sender_id,
            len(question),
            "DM" if is_dm else "channel",
        )
        logger.debug("Question text from %s: %r", sender_id, question)

        context = rag.retrieve(question)
        if context:
            logger.info(f"Retrieved {len(context)} chars of context")
        else:
            logger.info("No context found — answering from base model knowledge")

        answer = llm.answer(question, context)
        logger.info("Answer prepared (%d chars)", len(answer))
        logger.debug("Answer text: %r", answer)
        return answer

    return handle_message


def main():
    config = load_config()

    logger.info(f"Model: {config.llm.model}")
    logger.info("Initializing RAG engine...")
    rag = RAGEngine(config)
    logger.info(f"Knowledge base: {rag.chunk_count()} chunks from {rag.list_sources()}")

    logger.info("Initializing LLM engine...")
    llm = LLMEngine(config)

    handler = build_handler(rag, llm)

    radio_type = config.radio.type
    logger.info(f"Radio backend: {radio_type}")
    if radio_type == "meshcore":
        client = MeshCoreClient(config, on_message=handler)
    else:
        client = MeshtasticClient(config, on_message=handler)
    client.connect()

    def shutdown(sig, frame):
        logger.info("Shutting down...")
        client.disconnect()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    logger.info("Mesh Medic running. Waiting for messages...")
    while True:
        time.sleep(1)


if __name__ == "__main__":
    main()
