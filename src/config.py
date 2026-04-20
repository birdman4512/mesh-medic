import yaml
from dataclasses import dataclass
from pathlib import Path


@dataclass
class MeshtasticConfig:
    device: str
    respond_to_channels: bool
    channel_index: int


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


@dataclass
class Config:
    meshtastic: MeshtasticConfig
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

    return Config(
        meshtastic=MeshtasticConfig(**raw["meshtastic"]),
        llm=LLMConfig(**raw["llm"]),
        rag=RAGConfig(**raw["rag"]),
        data=DataConfig(**raw["data"]),
        response=ResponseConfig(**raw["response"]),
    )
