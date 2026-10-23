from src.utils import chunk_document, chunk_text, utf8_len


def test_short_text_returned_as_single_chunk():
    assert chunk_text("Hello world", 200) == ["Hello world"]


def test_exact_length_is_single_chunk():
    text = "a" * 200
    assert chunk_text(text, 200) == [text]


def test_splits_at_sentence_boundary():
    text = "First sentence. Second sentence that pushes over the limit."
    chunks = chunk_text(text, 20)
    assert chunks[0] == "First sentence."
    assert "Second sentence" in chunks[1]


def test_splits_at_word_boundary_when_no_sentence():
    text = "one two three four five six seven eight nine ten"
    chunks = chunk_text(text, 20)
    for chunk in chunks:
        assert len(chunk) <= 20


def test_hard_cuts_word_with_no_spaces():
    text = "a" * 50
    chunks = chunk_text(text, 20)
    assert all(len(c) <= 20 for c in chunks)


def test_empty_string():
    assert chunk_text("", 200) == []


def test_multiple_chunks_cover_all_content():
    text = "Word " * 100
    chunks = chunk_text(text.strip(), 50)
    reconstructed = " ".join(chunks)
    # All words should be present across the chunks
    assert len(reconstructed) >= len(text.strip()) - len(chunks)


def test_chunk_prefix_format():
    """Verify that multi-chunk messages get the [N/M] prefix applied by the caller."""
    text = "Short."
    chunks = chunk_text(text, 200)
    assert len(chunks) == 1
    # Prefix logic lives in MeshtasticClient._send_reply, not chunk_text
    assert "[" not in chunks[0]


def test_chunk_limit_caps_number_of_parts():
    text = " ".join(f"word{i}" for i in range(100))
    chunks = chunk_text(text, 20, max_chunks=5)
    assert len(chunks) == 5
    assert all(len(chunk) <= 20 for chunk in chunks)


def test_chunk_limit_reserves_space_for_part_prefixes():
    text = "a" * 200
    chunks = chunk_text(text, 20, max_chunks=5)
    prefix = len("[5/5] ")
    assert len(chunks) == 5
    assert all(len(chunk) <= 20 - prefix for chunk in chunks)


def test_prefers_newline_boundaries_for_numbered_lists():
    text = (
        "To find water, you can do the following:\n\n"
        "1. Dig a hole in your yard or garden to collect water.\n"
        "2. Use a plastic sheet or concrete block to line the hole.\n"
        "3. Check whether your local water table is accessible."
    )
    chunks = chunk_text(text, 80, max_chunks=5)
    assert len(chunks) >= 2
    assert all(not chunk.endswith("\n2.") for chunk in chunks[:-1])
    assert any(chunk.startswith("2. ") for chunk in chunks[1:])


def test_does_not_emit_marker_only_chunk():
    text = "1. First item is long enough to wrap.\n2. Second item starts here.\n3. Third item."
    chunks = chunk_text(text, 20, max_chunks=10)
    assert all(chunk.strip() not in {"1.", "2.", "3."} for chunk in chunks)


def test_chunks_respect_utf8_byte_limit():
    # "–" and "°" are 3 and 2 bytes; a character count would overflow the packet.
    text = "Boil water – 1 min at sea level, 3 min above 2000 m° " * 10
    chunks = chunk_text(text.strip(), 60, max_chunks=10)
    prefix = len("[10/10] ")
    assert all(len(c.encode("utf-8")) <= 60 - prefix for c in chunks)


def test_multibyte_text_within_byte_limit_is_single_chunk():
    assert chunk_text("Keep warm – 37°C", 200) == ["Keep warm – 37°C"]


def test_short_char_count_but_long_in_bytes_is_split():
    text = "é" * 30  # 30 chars, 60 bytes
    chunks = chunk_text(text, 40)
    assert len(chunks) == 2
    assert all(len(c.encode("utf-8")) <= 40 for c in chunks)
    assert "".join(chunks) == text


def test_utf8_len():
    assert utf8_len("abc") == 3
    assert utf8_len("–") == 3


def test_chunk_document_splits_at_sentences_and_tracks_pages():
    pages = [
        (1, "Find shelter first. Stay dry and out of the wind."),
        (2, "Water comes next. Boil it for one minute. Filter through cloth."),
    ]
    chunks = chunk_document(pages, size=60, overlap=0)
    texts = [t for t, _ in chunks]
    assert all(len(t) <= 60 for t in texts)
    assert all(t.endswith(".") for t in texts)  # never cut mid-sentence
    assert chunks[0][1] == 1
    assert any(page == 2 and t.startswith("Water") for t, page in chunks)


def test_chunk_document_overlap_carries_whole_sentences():
    pages = [(1, "One two. Three four. Five six. Seven eight.")]
    chunks = chunk_document(pages, size=22, overlap=11)
    assert [t for t, _ in chunks] == ["One two. Three four.", "Three four. Five six.", "Five six. Seven eight."]


def test_chunk_document_rejoins_hyphenated_words_and_lines():
    chunks = chunk_document([(3, "Apply pres-\nsure to the\nwound.")], size=100, overlap=0)
    assert chunks == [("Apply pressure to the wound.", 3)]


def test_chunk_document_splits_overlong_sentence():
    chunks = chunk_document([(1, "word " * 50)], size=30, overlap=5)
    assert chunks
    assert all(len(t) <= 30 for t, _ in chunks)


def test_chunk_document_rejects_overlap_not_smaller_than_size():
    import pytest

    with pytest.raises(ValueError):
        chunk_document([(1, "text")], size=10, overlap=10)
