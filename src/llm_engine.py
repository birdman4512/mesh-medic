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
                "num_ctx": 1024,  # cap KV cache to ~1 GB; prevents OOM on low-RAM hosts
            },
        }

        try:
            resp = requests.post(
                f"{self.cfg.base_url}/api/generate",
                json=payload,
                timeout=180,
            )
            resp.raise_for_status()
            raw = resp.json()["response"].strip()
            return self._clean(raw)
        except requests.RequestException as e:
            logger.error(f"LLM request failed: {e}")
            return "Error: LLM unavailable. Check Ollama service."

    # Max characters to send over radio regardless of model output length.
    # 195 chars fits in a single 200-char Meshtastic packet — multi-packet
    # sends are unreliable over LoRa so we guarantee single-packet delivery.
    _MAX_CHARS = 195

    def _clean(self, text: str) -> str:
        """Remove prompt echo artifacts and hard-cap length."""
        # TinyLlama sometimes echoes the prompt format back into the response.
        # If it starts with "Question:" or "Reference material:", the model
        # repeated the prompt instead of just answering — skip to the answer.
        for prefix in ("Reference material:", "Question:"):
            if text.startswith(prefix):
                # Try to find "Answer:" or just take everything after a blank line
                for marker in ("Answer:", "\n\n"):
                    idx = text.find(marker)
                    if idx != -1:
                        text = text[idx + len(marker):].strip()
                        break
                else:
                    text = ""
                break

        # Hard cap at _MAX_CHARS — truncate at last sentence boundary if possible
        if len(text) > self._MAX_CHARS:
            truncated = text[: self._MAX_CHARS]
            last_stop = max(
                truncated.rfind(". "),
                truncated.rfind("! "),
                truncated.rfind("? "),
            )
            text = truncated[: last_stop + 1] if last_stop > 50 else truncated

        return text

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
