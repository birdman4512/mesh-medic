import pytest
import textwrap
from pathlib import Path

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


def test_missing_config_file_raises():
    with pytest.raises(FileNotFoundError):
        load_config("/nonexistent/config.yaml")
