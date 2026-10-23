import logging
import re

import requests

from src.ollama import check_model

logger = logging.getLogger(__name__)

# Rough chars-per-token ratio used to budget the prompt against num_ctx. Deliberately low
# (English averages ~4) so the estimate errs towards leaving room for the reply.
CHARS_PER_TOKEN = 3


class LLMEngine:
    # Echoed prompt sections that small models sometimes start their reply with.
    _ECHO_PREFIXES = ("Context:", "Reference material:", "Question:")

    # "Based on the context, boil water..." -> "Boil water..."
    _LEAD_IN = re.compile(
        r"^(?:according to|based on|using|from)\s+the\s+(?:provided\s+|given\s+|above\s+)?"
        r"(?:context|reference material|references?|information)"
        r"(?:\s+(?:provided|given|above))?\s*[,:]\s*",
        re.IGNORECASE,
    )

    # Sentences that only repeat the system prompt or talk about the prompt itself.
    # Matched against a whole sentence, which is then dropped; anything else is kept verbatim.
    _INSTRUCTION_ECHO = tuple(
        re.compile(p, re.IGNORECASE)
        for p in (
            r"\b(?:these|my|the following|your|the above) instructions\b",
            r"\bradio delivery\b",
            r"\bevery character costs airtime\b",
            r"\bformatting rules\b",
            r"\bno (?:greetings|preamble)\b",
            r"\bnumbered lists?\b",
            r"\b(?:aim for|keep it|keep replies) under \d+ characters\b",
            r"\bnever exceed \d+\b",
            r"\byou are a survival (?:expert|assistant)\b",
            r"\b(?:the )?(?:provided |given )?(?:context|reference material) "
            r"(?:does not|doesn't|did not|didn't|is not|isn't)\b",
            r"^answer:?$",
        )
    )

    _SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")

    def __init__(self, config):
        self.cfg = config.llm
        self.radio_cfg = config.radio
        self.resp_cfg = config.response
        check_model(self.cfg.base_url, self.cfg.model)

    def answer(self, question: str, context: str) -> str:
        context = self._fit_context(question, context)
        payload = {
            "model": self.cfg.model,
            "prompt": self._build_prompt(question, context),
            "system": self.cfg.system_prompt,
            "stream": False,
            "options": {
                "temperature": self.cfg.temperature,
                "num_predict": self.cfg.max_tokens,
                "num_ctx": self.cfg.num_ctx,
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

    def _fit_context(self, question: str, context: str) -> str:
        """Trim retrieved context so system prompt + prompt + reply fit in num_ctx.

        Ollama silently drops the start of an over-long prompt, so trim here instead,
        keeping the highest-ranked passages (which come first).
        """
        if not context:
            return context
        overhead = len(self.cfg.system_prompt) + len(self._build_prompt(question, ""))
        budget_tokens = self.cfg.num_ctx - self.cfg.max_tokens - 32
        budget_chars = budget_tokens * CHARS_PER_TOKEN - overhead - len("Context:\n\n\n")
        if len(context) <= budget_chars:
            return context
        if budget_chars <= 0:
            logger.warning(
                "No room for reference material: raise llm.num_ctx or lower llm.max_tokens"
            )
            return ""
        logger.warning(
            "Context trimmed from %d to %d chars to fit num_ctx=%d "
            "(raise llm.num_ctx or lower rag.top_k / rag.chunk_size)",
            len(context), budget_chars, self.cfg.num_ctx,
        )
        return context[:budget_chars].rstrip()

    def _clean(self, text: str) -> str:
        """Remove prompt echo artifacts and hard-cap length.

        Only whole echoed sections and sentences are removed; the remaining answer keeps its
        wording, punctuation and line breaks.
        """
        text = self._strip_prompt_echo(text.strip())

        lines = []
        for line in text.split("\n"):
            kept = []
            for sentence in self._SENTENCE_SPLIT.split(line.strip()):
                if not sentence:
                    continue
                if any(p.search(sentence) for p in self._INSTRUCTION_ECHO):
                    continue
                stripped = self._LEAD_IN.sub("", sentence)
                if stripped != sentence:
                    if not stripped:
                        continue
                    sentence = stripped[0].upper() + stripped[1:]
                kept.append(sentence)
            lines.append(" ".join(kept))
        text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()

        return self._cap_length(text)

    def _strip_prompt_echo(self, text: str) -> str:
        # Small models sometimes repeat the prompt format before answering. If the reply
        # starts with an echoed section, skip to the answer (or the first blank line).
        if text.startswith(self._ECHO_PREFIXES):
            for marker in ("Answer:", "\n\n"):
                idx = text.find(marker)
                if idx != -1:
                    return text[idx + len(marker):].strip()
            return ""
        if text.startswith("Answer:"):
            return text[len("Answer:"):].strip()
        return text

    @staticmethod
    def _last_sentence_end(text: str) -> int:
        """Index just past the last sentence end that is followed by whitespace, or -1."""
        ends = [m.start() + 1 for m in re.finditer(r"[.!?](?=\s)", text)]
        return ends[-1] if ends else -1

    def _cap_length(self, text: str) -> str:
        max_chars = self._max_reply_chars()
        if len(text) > max_chars:
            truncated = text[:max_chars]
            end = self._last_sentence_end(truncated + " ")
            return truncated[:end].rstrip() if end > 50 else truncated.rstrip()

        # Drop a trailing half-sentence left when the model hit its token limit.
        if text and text[-1] not in ".!?":
            end = self._last_sentence_end(text)
            if end > 50:
                return text[:end]
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
