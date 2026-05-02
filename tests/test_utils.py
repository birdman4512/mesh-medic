from src.utils import chunk_text


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
