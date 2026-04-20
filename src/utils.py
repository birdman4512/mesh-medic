def chunk_text(text: str, max_len: int) -> list[str]:
    """Split text into chunks no longer than max_len, preferring sentence then word boundaries."""
    if not text:
        return []
    if len(text) <= max_len:
        return [text]

    chunks = []
    while text:
        if len(text) <= max_len:
            chunks.append(text)
            break

        split_at = text.rfind(". ", 0, max_len)
        if split_at != -1:
            split_at += 1  # keep the period
        else:
            split_at = text.rfind(" ", 0, max_len)
        if split_at <= 0:
            split_at = max_len

        chunks.append(text[:split_at].strip())
        text = text[split_at:].strip()

    return chunks
