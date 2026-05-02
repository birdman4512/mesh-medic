from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass
class RadioConfig:
    type: str = "meshtastic"  # "meshtastic" or "meshcore"


@dataclass
class MeshtasticConfig:
    device: str
    respond_to_channels: bool
    channel_index: int


@dataclass
class MeshCoreConfig:
    device: str = "/dev/ttyACM0"
    respond_to_channels: bool = False
    channel_index: int = 0
    room_server: str = ""        # pubkey prefix of room server (empty = disabled)
    room_password: str = "hello" # password used to log in to the room server
    room_trigger: str = "?"      # message prefix that directs a question at mesh-medic


@dataclass
class LLMConfig:
    model: str
    base_url: str
    max_tokens: int
    temperature: float
    system_prompt: str


@dataclass
class RAGConfig:
    chunk_size: int
    chunk_overlap: int
    top_k: int
    collection_name: str


@dataclass
class DataConfig:
    pdf_dir: str
    vectordb_dir: str


@dataclass
class ResponseConfig:
    max_chunk_size: int
    chunk_delay: float
    max_chunks: int = 15


@dataclass
class Config:
    radio: RadioConfig
    meshtastic: MeshtasticConfig
    meshcore: MeshCoreConfig
    llm: LLMConfig
    rag: RAGConfig
    data: DataConfig
    response: ResponseConfig


def load_config(path: str = "config.yaml") -> Config:
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with open(config_path) as f:
        raw = yaml.safe_load(f)

    radio_raw = raw.get("radio", {})
    mc_raw = raw.get("meshcore", {})

    return Config(
        radio=RadioConfig(type=radio_raw.get("type", "meshtastic")),
        meshtastic=MeshtasticConfig(**raw["meshtastic"]),
        meshcore=MeshCoreConfig(
            device=mc_raw.get("device", "/dev/ttyACM0"),
            respond_to_channels=mc_raw.get("respond_to_channels", False),
            channel_index=mc_raw.get("channel_index", 0),
            room_server=mc_raw.get("room_server", ""),
            room_password=mc_raw.get("room_password", "hello"),
            room_trigger=mc_raw.get("room_trigger", "?"),
        ),
        llm=LLMConfig(**raw["llm"]),
        rag=RAGConfig(**raw["rag"]),
        data=DataConfig(**raw["data"]),
        response=ResponseConfig(
            max_chunk_size=raw["response"]["max_chunk_size"],
            chunk_delay=raw["response"]["chunk_delay"],
            max_chunks=raw["response"].get("max_chunks", 15),
        ),
    )
