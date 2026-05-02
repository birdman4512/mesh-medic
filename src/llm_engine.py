import logging
import re

import requests

logger = logging.getLogger(__name__)


class LLMEngine:
    _META_PATTERNS = (
        r"additional reference material",
        r"reference material",
        r"context",
        r"the following instructions[^.:\n]*",
        r"instructions?[^.:\n]*radio delivery",
        r"concise and useful for radio delivery",
        r"concise an useful for radio delivery",
        r"useful for radio delivery",
        r"prefer 3-6 concise sentences(?: when needed)?",
        r"keep replies compact for radio delivery(?:,? but include useful detail)?",
        r"give clear, practical answers(?: using the reference material when relevant)?",
        r"never repeat, quote,? or describe these instructions",
        r"never talk about your formatting rules or the reference material unless the user asks about them",
        r"no greetings or filler",
        r"if the reference material is not relevant, give brief general advice",
        r"answer directly for the user(?: from general survival knowledge)?",
        r"do not repeat or describe your instructions",
        r"do not talk about the reference material unless the answer truly needs it",
        r"answer based on the reference material above",
        r"ask for clarification if necessary",
    )

    def __init__(self, config):
        self.cfg = config.llm
        self.radio_cfg = config.radio
        self.resp_cfg = config.response
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

        lowered = text.lower()
        if any(re.search(pattern, lowered) for pattern in self._META_PATTERNS):
            for pattern in self._META_PATTERNS:
                text = re.sub(pattern, "", text, flags=re.IGNORECASE)

            # Remove dangling quoted/context-intro fragments that often precede
            # the real answer in smaller models.
            text = re.sub(
                r'^[^A-Za-z0-9]*(?:in\s+the\s+of\s+)?".{0,160}?(?=(?:\d+\s|[A-Z]))',
                "",
                text,
                flags=re.IGNORECASE,
            )
            text = re.sub(r"^[^A-Za-z0-9]*(?:in\s+the\s+of\s+)", "", text, flags=re.IGNORECASE)
            text = re.sub(r"\s+", " ", text).strip(" ,.-:\n\t")
            sentences = re.split(r"(?<=[.!?])\s+", text)
            kept = []
            for sentence in sentences:
                stripped = sentence.strip(" ,.-:\n\t")
                if not stripped:
                    continue
                lowered = stripped.lower()
                if any(re.search(pattern, lowered) for pattern in self._META_PATTERNS):
                    continue
                kept.append(stripped)
            if kept:
                text = " ".join(kept).strip()

        max_chars = self._max_reply_chars()
        if len(text) > max_chars:
            truncated = text[:max_chars]
            last_stop = max(
                truncated.rfind(". "),
                truncated.rfind("! "),
                truncated.rfind("? "),
            )
            text = truncated[: last_stop + 1] if last_stop > 50 else truncated
        else:
            stripped = text.rstrip()
            if stripped and stripped[-1] not in ".!?":
                last_stop = max(
                    stripped.rfind(". "),
                    stripped.rfind("! "),
                    stripped.rfind("? "),
                )
                if last_stop > 50:
                    text = stripped[: last_stop + 1]

        return text

    def _max_reply_chars(self) -> int:
        per_chunk = self.resp_cfg.max_chunk_size
        if self.radio_cfg.type == "meshcore":
            per_chunk = min(per_chunk, 160)

        if self.resp_cfg.max_chunks <= 1:
            return per_chunk

        prefix_len = len(
            f"[{self.resp_cfg.max_chunks}/{self.resp_cfg.max_chunks}] "
        )
        usable_per_chunk = max(1, per_chunk - prefix_len)
        return usable_per_chunk * self.resp_cfg.max_chunks

    def _build_prompt(self, question: str, context: str) -> str:
        if context:
            return (
                f"Context:\n{context}\n\n"
                f"Question: {question}\n\n"
                "Answer:"
            )
        return (
            f"Question: {question}\n\n"
            "Answer:"
        )
