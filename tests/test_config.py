import textwrap

import pytest

from src.config import load_config

MINIMAL_CONFIG = textwrap.dedent("""
    meshtastic:
      device: /dev/ttyUSB0
      respond_to_channels: false
      channel_index: 0

    llm:
      model: phi3:mini
      base_url: http://localhost:11434
      max_tokens: 400
      temperature: 0.7
      system_prompt: "You are a survival assistant."

    rag:
      chunk_size: 512
      chunk_overlap: 64
      top_k: 3
      collection_name: survival_docs

    data:
      pdf_dir: /tmp/pdfs
      vectordb_dir: /tmp/vectordb

    response:
      max_chunk_size: 200
      chunk_delay: 2
      max_chunks: 15
""")


@pytest.fixture
def config_file(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(MINIMAL_CONFIG)
    return str(path)


def test_load_config_returns_all_sections(config_file):
    cfg = load_config(config_file)
    assert cfg.meshtastic is not None
    assert cfg.llm is not None
    assert cfg.rag is not None
    assert cfg.data is not None
    assert cfg.response is not None


def test_meshtastic_config_values(config_file):
    cfg = load_config(config_file)
    assert cfg.meshtastic.device == "/dev/ttyUSB0"
    assert cfg.meshtastic.respond_to_channels is False
    assert cfg.meshtastic.channel_index == 0


def test_llm_config_values(config_file):
    cfg = load_config(config_file)
    assert cfg.llm.model == "phi3:mini"
    assert cfg.llm.max_tokens == 400
    assert cfg.llm.temperature == pytest.approx(0.7)


def test_rag_config_values(config_file):
    cfg = load_config(config_file)
    assert cfg.rag.chunk_size == 512
    assert cfg.rag.top_k == 3
    assert cfg.rag.collection_name == "survival_docs"


def test_response_config_values(config_file):
    cfg = load_config(config_file)
    assert cfg.response.max_chunk_size == 200
    assert cfg.response.chunk_delay == pytest.approx(2.0)
    assert cfg.response.max_chunks == 15


def test_response_config_defaults_max_chunks_when_missing(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(MINIMAL_CONFIG.replace("      max_chunks: 15\n", ""))
    cfg = load_config(str(path))
    assert cfg.response.max_chunks == 15


def test_missing_config_file_raises():
    with pytest.raises(FileNotFoundError):
        load_config("/nonexistent/config.yaml")


def test_new_settings_have_defaults(config_file):
    cfg = load_config(config_file)
    assert cfg.radio.type == "meshtastic"
    assert cfg.llm.num_ctx == 1024
    assert cfg.rag.embedding_model == "all-minilm"
    assert cfg.response.ack_timeout == pytest.approx(30.0)
    assert cfg.response.cite_sources is False
    assert cfg.limits.max_queue == 5
    assert cfg.meshcore.room_trigger == "?"


@pytest.mark.parametrize(
    "old,new,message",
    [
        ("chunk_overlap: 64", "chunk_overlap: 512", "chunk_overlap"),
        ("top_k: 3", "top_k: 0", "top_k"),
        ("max_chunk_size: 200", "max_chunk_size: 10", "max_chunk_size"),
        ("max_tokens: 400", "max_tokens: 4000", "num_ctx"),
    ],
)
def test_invalid_values_rejected(tmp_path, old, new, message):
    path = tmp_path / "config.yaml"
    path.write_text(MINIMAL_CONFIG.replace(old, new))
    with pytest.raises(ValueError, match=message):
        load_config(str(path))


def test_unknown_radio_type_rejected(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("radio:\n  type: lorawan\n" + MINIMAL_CONFIG)
    with pytest.raises(ValueError, match="radio.type"):
        load_config(str(path))


def test_typo_in_key_rejected(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(MINIMAL_CONFIG.replace("top_k: 3", "topk: 3"))
    with pytest.raises(ValueError, match="rag"):
        load_config(str(path))


def test_repo_config_is_valid():
    cfg = load_config("config.yaml")
    assert cfg.limits.sender_cooldown == 30
