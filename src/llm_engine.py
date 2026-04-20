import logging

import requests

logger = logging.getLogger(__name__)


class LLMEngine:
    def __init__(self, config):
        self.cfg = config.llm
        self._verify_connection()

    def _verify_connection(self):
        try:
            resp = requests.get(f"{self.cfg.base_url}/api/tags", timeout=5)
            resp.raise_for_status()
            models = [m["name"] for m in resp.json().get("models", [])]
            if not any(self.cfg.model in m for m in models):
                logger.warning(
                    f"Model '{self.cfg.model}' not found in Ollama. "
                    f"Available: {models}. Run: ollama pull {self.cfg.model}"
                )
            else:
                logger.info(f"Model '{self.cfg.model}' ready.")
        except requests.RequestException as e:
            logger.error(f"Cannot reach Ollama at {self.cfg.base_url}: {e}")

    def answer(self, question: str, context: str) -> str:
        payload = {
            "model": self.cfg.model,
            "prompt": self._build_prompt(question, context),
            "system": self.cfg.system_prompt,
            "stream": False,
            "options": {
                "temperature": self.cfg.temperature,
                "num_predict": self.cfg.max_tokens,
            },
        }

        try:
            resp = requests.post(
                f"{self.cfg.base_url}/api/generate",
                json=payload,
                timeout=120,
            )
            resp.raise_for_status()
            return resp.json()["response"].strip()
        except requests.RequestException as e:
            logger.error(f"LLM request failed: {e}")
            return "Error: LLM unavailable. Check Ollama service."

    def _build_prompt(self, question: str, context: str) -> str:
        if context:
            return (
                f"Reference material:\n{context}\n\n"
                f"Question: {question}\n\n"
                f"Answer based on the reference material above:"
            )
        return (
            f"Question: {question}\n\n"
            f"Note: No matching reference material found. "
            f"Answer from general survival knowledge:"
        )
