from dataclasses import dataclass, field
from pathlib import Path

import yaml

RADIO_TYPES = ("meshtastic", "meshcore")


@dataclass
class RadioConfig:
    type: str = "meshtastic"  # "meshtastic" or "meshcore"


@dataclass
class MeshtasticConfig:
    device: str = "/dev/ttyACM0"
    respond_to_channels: bool = False
    channel_index: int = 0


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
    num_ctx: int = 1024  # Ollama context window; prompt + reply must fit inside it


@dataclass
class RAGConfig:
    chunk_size: int
    chunk_overlap: int
    top_k: int
    collection_name: str
    embedding_model: str = "all-minilm"  # Ollama embedding model (all-MiniLM-L6-v2)


@dataclass
class DataConfig:
    pdf_dir: str
    vectordb_dir: str


@dataclass
class ResponseConfig:
    max_chunk_size: int          # max UTF-8 bytes per packet, including the [n/m] prefix
    chunk_delay: float           # pause between parts when there is no ACK to wait for
    max_chunks: int = 15
    ack_timeout: float = 30.0    # DMs: max seconds to wait for each part's ACK
    cite_sources: bool = False   # append "[file p.N]" of the best-matching passage


@dataclass
class LimitsConfig:
    max_queue: int = 5            # questions waiting or in progress before "busy" replies
    sender_cooldown: float = 30.0 # min seconds between accepted questions from one sender
    queue_notice: bool = True     # tell senders their place in line when others are ahead


@dataclass
class Config:
    radio: RadioConfig
    meshtastic: MeshtasticConfig
    meshcore: MeshCoreConfig
    llm: LLMConfig
    rag: RAGConfig
    data: DataConfig
    response: ResponseConfig
    limits: LimitsConfig = field(default_factory=LimitsConfig)


def _section(cls, raw: dict, name: str, required: bool = False):
    values = raw.get(name)
    if values is None:
        if required:
            raise ValueError(f"Missing required config section: {name}")
        values = {}
    try:
        return cls(**values)
    except TypeError as e:
        raise ValueError(f"Invalid '{name}' config section: {e}") from e


def validate(config: Config) -> None:
    errors = []
    if config.radio.type not in RADIO_TYPES:
        errors.append(f"radio.type must be one of {RADIO_TYPES}, got {config.radio.type!r}")

    rag = config.rag
    if rag.chunk_size <= 0:
        errors.append("rag.chunk_size must be positive")
    if not 0 <= rag.chunk_overlap < rag.chunk_size:
        errors.append("rag.chunk_overlap must be >= 0 and smaller than rag.chunk_size")
    if rag.top_k < 1:
        errors.append("rag.top_k must be at least 1")

    resp = config.response
    if resp.max_chunks < 1:
        errors.append("response.max_chunks must be at least 1")
    prefix_len = len(f"[{resp.max_chunks}/{resp.max_chunks}] ")
    if resp.max_chunk_size < prefix_len + 20:
        errors.append(f"response.max_chunk_size must be at least {prefix_len + 20}")
    if resp.chunk_delay < 0:
        errors.append("response.chunk_delay must be >= 0")
    if resp.ack_timeout <= 0:
        errors.append("response.ack_timeout must be positive")

    if config.llm.num_ctx <= config.llm.max_tokens:
        errors.append("llm.num_ctx must be larger than llm.max_tokens")

    if config.limits.max_queue < 1:
        errors.append("limits.max_queue must be at least 1")
    if config.limits.sender_cooldown < 0:
        errors.append("limits.sender_cooldown must be >= 0")

    if errors:
        raise ValueError("Invalid config:\n  " + "\n  ".join(errors))


def load_config(path: str = "config.yaml") -> Config:
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with open(config_path) as f:
        raw = yaml.safe_load(f) or {}

    config = Config(
        radio=_section(RadioConfig, raw, "radio"),
        meshtastic=_section(MeshtasticConfig, raw, "meshtastic"),
        meshcore=_section(MeshCoreConfig, raw, "meshcore"),
        llm=_section(LLMConfig, raw, "llm", required=True),
        rag=_section(RAGConfig, raw, "rag", required=True),
        data=_section(DataConfig, raw, "data", required=True),
        response=_section(ResponseConfig, raw, "response", required=True),
        limits=_section(LimitsConfig, raw, "limits"),
    )
    validate(config)
    return config
