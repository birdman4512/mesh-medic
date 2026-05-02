def chunk_text(text: str, max_len: int, max_chunks: int | None = None) -> list[str]:
    """Split text into chunks no longer than max_len, preferring sentence then word boundaries."""
    if not text:
        return []
    if len(text) <= max_len:
        return [text]

    prefix_reserve = 0
    if max_chunks and max_chunks > 1:
        prefix_reserve = len(f"[{max_chunks}/{max_chunks}] ")
    effective_max_len = max(1, max_len - prefix_reserve)

    chunks = []
    while text:
        if len(text) <= effective_max_len:
            chunks.append(text)
            break

        split_at = text.rfind(". ", 0, effective_max_len)
        if split_at != -1:
            split_at += 1  # keep the period
        else:
            split_at = text.rfind(" ", 0, effective_max_len)
        if split_at <= 0:
            split_at = effective_max_len

        chunks.append(text[:split_at].strip())
        text = text[split_at:].strip()

    if max_chunks and len(chunks) > max_chunks:
        limited = chunks[: max_chunks - 1]
        remaining_text = " ".join(chunks[max_chunks - 1 :]).strip()
        tail = (
            chunk_text(remaining_text, max_len, max_chunks=1)[0]
            if remaining_text
            else ""
        )
        chunks = limited + [tail]

    return chunks
