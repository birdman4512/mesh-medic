# Mesh Medic

[![CI](https://github.com/birdman4512/mesh-medic/actions/workflows/ci.yml/badge.svg)](https://github.com/birdman4512/mesh-medic/actions/workflows/ci.yml)
[![Ansible Lint](https://github.com/birdman4512/mesh-medic/actions/workflows/ansible-lint.yml/badge.svg)](https://github.com/birdman4512/mesh-medic/actions/workflows/ansible-lint.yml)

Offline AI survival assistant for Raspberry Pi. Send a question over LoRa radio and get an answer back — no internet, no cloud, no infrastructure.

**Guides:** [Off-grid solar setup](docs/off-grid-setup.md) · [Troubleshooting](docs/troubleshooting.md)

---

## What it does

Mesh Medic turns a Raspberry Pi into an AI assistant that lives entirely on the mesh. You send it a direct message from any node in the network, and it replies with an answer drawn from your ingested PDF knowledge base (survival guides, first aid manuals, field references) and supplemented by a local LLM.

Everything runs offline after the initial deployment:

- **Radio interface** — receives DMs (and optionally channel messages) via a USB-connected LoRa device running Meshtastic or MeshCore firmware
- **Retrieval-Augmented Generation (RAG)** — finds the most relevant passages from your ingested PDFs using vector embeddings (ChromaDB + `all-MiniLM-L6-v2`)
- **Local LLM** — generates a concise answer via [Ollama](https://ollama.com), running on the Pi itself
- **Reply chunking** — long answers are automatically split into numbered packets (`[1/3] …`) to fit the radio's packet size limit

```
[LoRa DM]  →  [USB device]  →  [RAG retrieval]  →  [Ollama LLM]  →  [LoRa reply]
```

---

## Hardware requirements

- Raspberry Pi 4 (4 GB RAM minimum) or Pi 5
- A LoRa device connected via USB running [Meshtastic](https://meshtastic.org) or [MeshCore](https://meshcore.co.uk) firmware
- microSD card (16 GB+)

## Software prerequisites (Pi)

- Raspberry Pi OS Lite 64-bit (recommended)
- SSH access enabled
- Internet access **during initial deploy only** — runs fully offline after

---

## Quick start (manual)

```bash
# On Debian/Ubuntu, ensure venv support is available first:
#   sudo apt install python3-full python3-venv -y
git clone https://github.com/birdman4512/mesh-medic.git
cd mesh-medic
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Ingest your survival PDF(s)
python scripts/ingest_pdf.py /path/to/survival-guide.pdf

# List what has been ingested
python scripts/ingest_pdf.py --list

# Run
python -m src.main
```

---

## Deployment (Ansible)

Ansible handles everything: system packages, Ollama, model downloads, app install, and the systemd service.

```bash
# On your workstation
pip install ansible

# Copy and edit the inventory
cp ansible/inventory.example.yml ansible/inventory.yml
# Set your Pi's IP address and SSH user

# Review ansible/group_vars/all.yml — key variables described below

# Deploy
ansible-playbook -i ansible/inventory.yml ansible/playbook.yml
```

`ansible/inventory.yml` is ignored by git. Keep real credentials there or, better, use SSH keys and/or Ansible Vault.

After deployment, ingest PDFs on the Pi:

```bash
ssh pi@<pi-ip>
sudo -u mesh-medic /opt/mesh-medic/venv/bin/python \
  scripts/ingest_pdf.py /opt/mesh-medic/data/pdfs/survival-guide.pdf
```

### Service management

```bash
sudo systemctl status mesh-medic
sudo journalctl -u mesh-medic -f      # live logs
sudo systemctl restart mesh-medic
```

---

## Radio backends

Mesh Medic supports two radio firmware ecosystems. Set `radio_type` in `ansible/group_vars/all.yml` before deploying, or edit `radio.type` in `config.yaml` on the Pi and restart the service.

### Meshtastic (default)

Uses the [`meshtastic`](https://github.com/meshtastic/python) Python library. Connects to any device running [Meshtastic firmware](https://meshtastic.org) via USB serial.

```yaml
# ansible/group_vars/all.yml
radio_type: meshtastic
meshtastic_device: /dev/ttyACM0   # adjust to match your board
```

```yaml
# config.yaml (set by Ansible, or edit manually)
radio:
  type: meshtastic

meshtastic:
  device: /dev/ttyACM0
  respond_to_channels: false  # true = also answer channel messages
  channel_index: 0
```

Packet limit: 237 bytes. Replies are chunked to 200 characters.

### MeshCore

Uses the [`meshcore`](https://github.com/meshcore-dev/meshcore_py) Python library. Connects to any device running [MeshCore firmware](https://meshcore.co.uk) via USB serial (115200 baud).

```yaml
# ansible/group_vars/all.yml
radio_type: meshcore
meshcore_device: /dev/ttyACM0
```

```yaml
# config.yaml
radio:
  type: meshcore

meshcore:
  device: /dev/ttyACM0
  respond_to_channels: false
  channel_index: 0
  room_server: ""       # pubkey prefix of a room server to join (leave empty to disable)
  room_password: hello  # password to log in to the room server
  room_trigger: "?"     # prefix that directs a room message at mesh-medic
```

Packet limit: 184 bytes. Replies are chunked to 160 characters regardless of `max_chunk_size`.

> MeshCore uses an async Python library. Mesh Medic runs it in a background thread so the rest of the app stays synchronous.

#### MeshCore room server (optional)

A MeshCore [room server](https://meshcore.co.uk) is a dedicated node that acts as a group chat hub — all logged-in members share the same message stream. Mesh Medic can join a room and answer questions posted there, making it a shared resource for everyone in the room rather than a 1:1 DM service.

**How it works:**

1. On startup, Mesh Medic logs in to the configured room server using the provided password.
2. All messages relayed by the room server arrive as `"SenderName: message text"`. Mesh Medic strips the sender label and checks for the trigger prefix.
3. Any message matching `room_trigger` (default `?`) is treated as a question — e.g. `? how do I purify water?`
4. The answer is sent back to the room server, which relays it to all logged-in members.

**Setup:**

1. Find the pubkey prefix of your room server node (visible in the MeshCore app or CLI).
2. Set the variables in `ansible/group_vars/all.yml` and redeploy:

```yaml
radio_type: meshcore
meshcore_device: /dev/ttyACM0
meshcore_room_server: "a1b2c3d4"  # pubkey prefix of your room server
meshcore_room_password: hello      # default guest password; change if yours differs
meshcore_room_trigger: "?"         # users prefix questions with this character
```

Or edit `config.yaml` directly on the Pi and restart:

```yaml
meshcore:
  room_server: "a1b2c3d4"
  room_password: hello
  room_trigger: "?"
```

```bash
sudo systemctl restart mesh-medic
```

3. In the room, members ask questions like:
   ```
   ? how do I treat a blister?
   ? best way to find water in the bush?
   ```
   Messages without the trigger prefix are ignored.

> Room server and DM modes are **independent** — both are active at the same time. A DM always gets a reply; a room message only gets a reply if it starts with the trigger prefix.

---

## Supported devices

### Meshtastic devices

Mesh Medic works with **any device running Meshtastic firmware** connected via USB. The only configuration needed is the correct serial port path.

| Device | USB chip | Typical path |
|---|---|---|
| Heltec WiFi LoRa 32 V3 | CP2102N | `/dev/ttyUSB0` |
| Heltec WiFi LoRa 32 V2 | CP2102 | `/dev/ttyUSB0` |
| LILYGO T-Beam (classic) | CP2104 | `/dev/ttyUSB0` |
| LILYGO T-Beam S3 | Native USB CDC | `/dev/ttyACM0` |
| LILYGO T3-S3 | Native USB CDC | `/dev/ttyACM0` |
| SEEED XIAO S3 | Native USB CDC | `/dev/ttyACM0` |
| RAK WisBlock (via USB) | CH340 / CP2102 | `/dev/ttyUSB0` |

### MeshCore devices

Any device flashed with [MeshCore firmware](https://flasher.meshcore.co.uk) and connected via USB serial.

> **Rule of thumb:** boards with a dedicated USB-UART chip (CP210x, CH340) show up as `/dev/ttyUSB0`; boards using an ESP32-S3's built-in native USB show up as `/dev/ttyACM0`.

If unsure, plug in the device and run `dmesg | tail -20` — the kernel will log the exact path.

---

## LLM models

| Model | Size | Min RAM | Notes |
|---|---|---|---|
| `tinyllama:1.1b` | ~638 MB | 2 GB | Default — fits comfortably on Pi 4 4 GB |
| `phi3:mini` | ~2.3 GB | 4 GB | Better quality, noticeably slower on Pi 4 |
| `llama3.2:3b` | ~2.0 GB | 4 GB | Similar to phi3:mini |

To switch model, edit `config.yaml` on the Pi and restart:

```yaml
llm:
  model: phi3:mini
```

```bash
sudo systemctl restart mesh-medic
```

Set `ollama_model` in `group_vars/all.yml` to make it permanent across deploys.

---

## PDF ingestion

PDFs must be text-based (not scanned images). Scanned PDFs require OCR pre-processing before ingestion.

```bash
# Ingest a PDF
python scripts/ingest_pdf.py wilderness-survival.pdf

# Ingest multiple
python scripts/ingest_pdf.py first-aid-manual.pdf field-medicine.pdf

# List all ingested sources
python scripts/ingest_pdf.py --list
```

Re-ingesting a PDF safely replaces its previous chunks.

---

## Configuration reference

All settings live in `config.yaml` (managed by Ansible via `group_vars/all.yml`).

```yaml
radio:
  type: meshtastic         # meshtastic | meshcore

meshtastic:
  device: /dev/ttyACM0
  respond_to_channels: false
  channel_index: 0

meshcore:
  device: /dev/ttyACM0
  respond_to_channels: false
  channel_index: 0
  room_server: ""          # pubkey prefix of room server (empty = disabled)
  room_password: hello     # password to log in to the room server
  room_trigger: "?"        # message prefix that directs a question at mesh-medic

llm:
  model: tinyllama:1.1b
  base_url: http://localhost:11434
  max_tokens: 140          # allows longer multi-packet replies
  temperature: 0.7
  system_prompt: |
    You are a survival expert. Give clear, practical answers using the reference material when relevant.
    Prefer 3-6 concise sentences when needed. Keep replies compact for radio delivery, but include useful detail.
    No greetings or filler. If the reference material is not relevant, give brief general advice.

rag:
  chunk_size: 512
  chunk_overlap: 64
  top_k: 2                 # number of PDF passages to retrieve per question
  collection_name: survival_docs

response:
  max_chunk_size: 200      # max chars per packet (MeshCore hard-caps at 160 regardless)
  chunk_delay: 5           # seconds between multi-part message chunks
  max_chunks: 5           # maximum number of reply packets
```

### Ansible group vars

The key variables in `ansible/group_vars/all.yml`:

| Variable | Default | Description |
|---|---|---|
| `radio_type` | `meshtastic` | Radio backend: `meshtastic` or `meshcore` |
| `meshtastic_device` | `/dev/ttyACM0` | Serial port for Meshtastic device |
| `meshcore_device` | `/dev/ttyACM0` | Serial port for MeshCore device |
| `meshcore_room_server` | `""` | Pubkey prefix of room server to join (empty = disabled) |
| `meshcore_room_password` | `hello` | Password to log in to the room server |
| `meshcore_room_trigger` | `?` | Message prefix that triggers a response in the room |
| `ollama_model` | `tinyllama:1.1b` | LLM model to pull and use |
| `ollama_version` | `0.21.0` | Pinned Ollama version to install |
| `ollama_pull_both_models` | `false` | Pull both tinyllama and phi3:mini |
| `llm_max_tokens` | `140` | Token cap for LLM responses |
| `response_max_chunk_size` | `200` | Max chars per radio packet |
| `response_chunk_delay` | `5` | Seconds between reply chunks |
| `response_max_chunks` | `5` | Maximum number of reply packets |
| `rag_chunk_size` | `512` | PDF chunk size for ingestion |
| `rag_top_k` | `2` | Retrieved passages per question |

---

## Troubleshooting

See [docs/troubleshooting.md](docs/troubleshooting.md) for detailed fixes. Quick reference:

**Device not found**
```bash
dmesg | tail -20          # shows the exact port after plugging in
ls /dev/tty{ACM,USB}*
# Update the device path in config.yaml to match
```

**Permission denied on serial port**
```bash
sudo usermod -aG dialout $USER
# Log out and back in for the group change to take effect
```

**Ollama not responding**
```bash
sudo systemctl status ollama
ollama list               # verify model is pulled
ollama pull tinyllama:1.1b
```

**Out of memory (Ollama HTTP 500)**  
Switch to `tinyllama:1.1b` — `phi3:mini` needs ~3.8 GB and will OOM on a 4 GB Pi 4.

**No context retrieved (answer ignores PDF)**
```bash
python scripts/ingest_pdf.py --list   # verify PDFs are ingested
```

**MeshCore device not connecting**  
MeshCore devices connect at 115200 baud. Ensure the device is flashed with MeshCore firmware (not Meshtastic) and the serial port is correct. The service retries up to 10 times with 15 s between attempts.

---

## Development

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements-dev.txt

# Lint
ruff check src/ scripts/ tests/

# Tests
pytest tests/ -v
```

### CI/CD

| Workflow | Trigger | Checks |
|---|---|---|
| [CI](https://github.com/birdman4512/mesh-medic/actions/workflows/ci.yml) | Push / PR to `main` | ruff lint, pytest unit tests |
| [Ansible Lint](https://github.com/birdman4512/mesh-medic/actions/workflows/ansible-lint.yml) | Changes to `ansible/` | ansible-lint |

---

## Project structure

```
mesh-medic/
├── src/
│   ├── config.py             # Config dataclasses + YAML loader
│   ├── utils.py              # Shared helpers (text chunking)
│   ├── rag_engine.py         # PDF ingestion + ChromaDB vector retrieval
│   ├── llm_engine.py         # Ollama HTTP client
│   ├── meshtastic_client.py  # Meshtastic USB interface, DM handler, reply chunking
│   ├── meshcore_client.py    # MeshCore USB interface (async, bridged to sync)
│   └── main.py               # Entry point — selects radio backend from config
├── scripts/
│   └── ingest_pdf.py         # CLI: add PDFs to knowledge base
├── tests/
│   ├── test_config.py
│   └── test_utils.py
├── docs/
│   ├── off-grid-setup.md     # Solar + battery deployment guide
│   └── troubleshooting.md    # Detailed error reference
├── .github/workflows/
│   ├── ci.yml
│   └── ansible-lint.yml
├── ansible/
│   ├── playbook.yml
│   ├── inventory.example.yml
│   ├── group_vars/all.yml    # All deployment variables
│   └── roles/
│       ├── common/           # System dependencies + dialout group
│       ├── ollama/           # Ollama install + model pulls
│       └── mesh-medic/       # App deploy, config template, systemd service
├── config.yaml
├── requirements.txt
├── requirements-dev.txt
└── pyproject.toml            # ruff + pytest config
```
