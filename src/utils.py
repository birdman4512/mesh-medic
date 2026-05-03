import re


def _normalize_marker_only_chunks(chunks: list[str], max_len: int) -> list[str]:
    normalized: list[str] = []

    i = 0
    while i < len(chunks):
        chunk = chunks[i].strip()

        if re.fullmatch(r"\d+\.", chunk) and i + 1 < len(chunks):
            next_chunk = chunks[i + 1].lstrip()
            available = max_len - len(chunk) - 1
            if available > 0:
                taken = next_chunk[:available]
                if len(next_chunk) > available:
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
        if len(merged_next) > max_len:
            continue

        normalized[i] = current[:last_space].rstrip()
        normalized[i + 1] = merged_next

    return [chunk for chunk in normalized if chunk]


def chunk_text(text: str, max_len: int, max_chunks: int | None = None) -> list[str]:
    """Split text into chunks, preferring paragraph, line, sentence, then word boundaries."""
    if not text:
        return []
    if len(text) <= max_len:
        return [text]

    prefix_reserve = 0
    if max_chunks and max_chunks > 1:
        prefix_reserve = len(f"[{max_chunks}/{max_chunks}] ")
    effective_max_len = max(1, max_len - prefix_reserve)

    chunks: list[str] = []
    remaining = text.strip()

    while remaining:
        if len(remaining) <= effective_max_len:
            chunks.append(remaining)
            break

        split_at = remaining.rfind("\n\n", 0, effective_max_len)
        if split_at != -1:
            split_at += 2
        else:
            split_at = remaining.rfind("\n", 0, effective_max_len)
            if split_at != -1:
                split_at += 1
            else:
                split_at = remaining.rfind(". ", 0, effective_max_len)
                if split_at != -1:
                    split_at += 1
                else:
                    split_at = remaining.rfind(" ", 0, effective_max_len)

        if split_at <= 0:
            split_at = effective_max_len

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
        tail = tail_source[:effective_max_len].strip()

        if len(tail_source) > effective_max_len:
            last_space = tail.rfind(" ")
            if last_space > 0:
                tail = tail[:last_space].rstrip()

        chunks = head + ([tail] if tail else [])

    return chunks
