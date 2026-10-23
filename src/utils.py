import re


def utf8_len(text: str) -> int:
    return len(text.encode("utf-8"))


def _fit_chars(text: str, max_bytes: int) -> int:
    """Return how many leading characters of text fit in max_bytes of UTF-8."""
    total = 0
    for i, ch in enumerate(text):
        total += utf8_len(ch)
        if total > max_bytes:
            return i
    return len(text)


def _normalize_marker_only_chunks(chunks: list[str], max_len: int) -> list[str]:
    normalized: list[str] = []

    i = 0
    while i < len(chunks):
        chunk = chunks[i].strip()

        if re.fullmatch(r"\d+\.", chunk) and i + 1 < len(chunks):
            next_chunk = chunks[i + 1].lstrip()
            available = max_len - utf8_len(chunk) - 1
            if available > 0:
                taken = next_chunk[: _fit_chars(next_chunk, available)]
                if utf8_len(next_chunk) > available:
                    last_space = taken.rfind(" ")
                    if last_space > 0:
                        taken = taken[:last_space]
                taken = taken.rstrip()
                if taken:
                    normalized.append(f"{chunk} {taken}".strip())
                    remainder = next_chunk[len(taken) :].lstrip()
                    if remainder:
                        normalized.append(remainder)
                    i += 2
                    continue

        normalized.append(chunk)
        i += 1

    return normalized


def _normalize_split_words(chunks: list[str], max_len: int) -> list[str]:
    normalized = chunks[:]

    for i in range(len(normalized) - 1):
        current = normalized[i].rstrip()
        nxt = normalized[i + 1].lstrip()

        if not current or not nxt:
            continue
        if not (current[-1].isalnum() and nxt[0].isalnum()):
            continue

        last_space = current.rfind(" ")
        if last_space <= 0:
            continue
        if re.fullmatch(r"\d+\.\s+\w+", current):
            continue

        trailing = current[last_space + 1 :].strip()
        if not trailing:
            continue

        merged_next = f"{trailing}{nxt}"
        if utf8_len(merged_next) > max_len:
            continue

        normalized[i] = current[:last_space].rstrip()
        normalized[i + 1] = merged_next

    return [chunk for chunk in normalized if chunk]


def chunk_text(text: str, max_len: int, max_chunks: int | None = None) -> list[str]:
    """Split text into chunks, preferring paragraph, line, sentence, then word boundaries.

    Lengths are measured in UTF-8 bytes, because that is what radio packet limits count.
    When max_chunks > 1, room is reserved in each chunk for the caller's "[n/m] " prefix.
    """
    if not text:
        return []
    if utf8_len(text) <= max_len:
        return [text]

    prefix_reserve = 0
    if max_chunks and max_chunks > 1:
        prefix_reserve = len(f"[{max_chunks}/{max_chunks}] ")
    effective_max_len = max(1, max_len - prefix_reserve)

    chunks: list[str] = []
    remaining = text.strip()

    while remaining:
        if utf8_len(remaining) <= effective_max_len:
            chunks.append(remaining)
            break

        window = max(1, _fit_chars(remaining, effective_max_len))
        split_at = remaining.rfind("\n\n", 0, window)
        if split_at != -1:
            split_at += 2
        else:
            split_at = remaining.rfind("\n", 0, window)
            if split_at != -1:
                split_at += 1
            else:
                split_at = remaining.rfind(". ", 0, window)
                if split_at != -1:
                    split_at += 1
                else:
                    split_at = remaining.rfind(" ", 0, window)

        if split_at <= 0:
            split_at = window

        if (
            0 < split_at < len(remaining)
            and remaining[split_at - 1].isalnum()
            and remaining[split_at].isalnum()
        ):
            backtrack = split_at
            while backtrack > 0 and remaining[backtrack - 1].isalnum():
                backtrack -= 1
            if backtrack > 0:
                split_at = backtrack

        chunk = remaining[:split_at].strip()
        if chunk:
            chunks.append(chunk)
        remaining = remaining[split_at:].strip()

    chunks = _normalize_marker_only_chunks(chunks, effective_max_len)
    chunks = _normalize_split_words(chunks, effective_max_len)

    if max_chunks and len(chunks) > max_chunks:
        head = chunks[: max_chunks - 1]
        tail_source = " ".join(chunks[max_chunks - 1 :]).strip()
        tail = tail_source[: _fit_chars(tail_source, effective_max_len)].strip()

        if utf8_len(tail_source) > effective_max_len:
            last_space = tail.rfind(" ")
            if last_space > 0:
                tail = tail[:last_space].rstrip()

        chunks = head + ([tail] if tail else [])

    return chunks


_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def _document_units(text: str, max_len: int) -> list[str]:
    """Break page text into sentences, splitting any sentence longer than max_len at spaces."""
    text = re.sub(r"(\w)-\n(?=[a-z])", r"\1", text)  # re-join words hyphenated across lines
    units: list[str] = []
    for paragraph in re.split(r"\n\s*\n", text):
        paragraph = re.sub(r"\s+", " ", paragraph).strip()
        for sentence in _SENTENCE_END.split(paragraph):
            sentence = sentence.strip()
            while len(sentence) > max_len:
                cut = sentence.rfind(" ", 0, max_len + 1)
                if cut <= 0:
                    cut = max_len
                units.append(sentence[:cut].strip())
                sentence = sentence[cut:].strip()
            if sentence:
                units.append(sentence)
    return units


def chunk_document(
    pages: list[tuple[int, str]], size: int, overlap: int
) -> list[tuple[str, int]]:
    """Pack page text into retrieval chunks of up to `size` characters at sentence boundaries.

    Each chunk starts with up to `overlap` characters of whole sentences from the end of the
    previous chunk. Returns (chunk_text, page_number) pairs, where the page is the one the
    chunk's first new sentence came from.
    """
    if not 0 <= overlap < size:
        raise ValueError("overlap must be >= 0 and smaller than size")

    units = [(unit, page) for page, text in pages for unit in _document_units(text, size)]
    chunks: list[tuple[str, int]] = []
    current: list[str] = []
    current_len = 0
    current_page = None

    for unit, page in units:
        added = len(unit) + (1 if current else 0)
        if current and current_len + added > size:
            chunks.append((" ".join(current), current_page))
            carried: list[str] = []
            carried_len = 0
            for prev in reversed(current):
                extra = len(prev) + (1 if carried else 0)
                if carried_len + extra > overlap:
                    break
                carried.insert(0, prev)
                carried_len += extra
            if carried and carried_len + 1 + len(unit) > size:
                carried, carried_len = [], 0
            current, current_len, current_page = carried, carried_len, None
            added = len(unit) + (1 if current else 0)
        if current_page is None:
            current_page = page
        current.append(unit)
        current_len += added

    if current:
        chunks.append((" ".join(current), current_page))
    return chunks
