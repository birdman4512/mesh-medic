from types import SimpleNamespace

import pytest

from src.config import LimitsConfig, ResponseConfig


@pytest.fixture
def make_config():
    """Build a lightweight config object with only the sections a test needs."""

    def _make(radio_type="meshtastic", **response_overrides):
        response = dict(max_chunk_size=200, chunk_delay=0, max_chunks=5, ack_timeout=0.5)
        response.update(response_overrides)
        return SimpleNamespace(
            radio=SimpleNamespace(type=radio_type),
            response=ResponseConfig(**response),
            limits=LimitsConfig(),
            meshtastic=SimpleNamespace(
                device="/dev/null", respond_to_channels=False, channel_index=0
            ),
            meshcore=SimpleNamespace(
                device="/dev/null",
                respond_to_channels=False,
                channel_index=0,
                room_server="",
                room_password="hello",
                room_trigger="?",
            ),
            llm=SimpleNamespace(
                model="m",
                base_url="http://ollama",
                max_tokens=220,
                temperature=0.7,
                num_ctx=1024,
                system_prompt="You are a survival expert.",
            ),
        )

    return _make
