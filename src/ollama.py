import logging

import requests

logger = logging.getLogger(__name__)


def model_matches(wanted: str, available: str) -> bool:
    """True if an installed Ollama model name satisfies the configured one.

    A configured name without a tag ("all-minilm") matches any tag of that model.
    """
    if available == wanted:
        return True
    return ":" not in wanted and available.split(":", 1)[0] == wanted


def check_model(base_url: str, model: str) -> bool:
    """Log whether Ollama is reachable and has `model` pulled. Returns True if it is ready."""
    try:
        resp = requests.get(f"{base_url}/api/tags", timeout=5)
        resp.raise_for_status()
        models = [m["name"] for m in resp.json().get("models", [])]
    except requests.RequestException as e:
        logger.error(f"Cannot reach Ollama at {base_url}: {e}")
        return False

    if any(model_matches(model, m) for m in models):
        logger.info(f"Model '{model}' ready.")
        return True
    logger.warning(
        f"Model '{model}' not found in Ollama. Available: {models}. Run: ollama pull {model}"
    )
    return False


def embed(base_url: str, model: str, texts: list[str], timeout: float = 120) -> list[list[float]]:
    resp = requests.post(
        f"{base_url}/api/embed",
        json={"model": model, "input": texts},
        timeout=timeout,
    )
    resp.raise_for_status()
    embeddings = resp.json()["embeddings"]
    if len(embeddings) != len(texts):
        raise RuntimeError(f"Ollama returned {len(embeddings)} embeddings for {len(texts)} texts")
    return embeddings
