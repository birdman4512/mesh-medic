# Mesh Medic

[![CI](https://github.com/birdman4512/mesh-medic/actions/workflows/ci.yml/badge.svg)](https://github.com/birdman4512/mesh-medic/actions/workflows/ci.yml)
[![Ansible Lint](https://github.com/birdman4512/mesh-medic/actions/workflows/ansible-lint.yml/badge.svg)](https://github.com/birdman4512/mesh-medic/actions/workflows/ansible-lint.yml)

Offline survival assistant for Raspberry Pi. Receives questions via any Meshtastic radio connected over USB, retrieves relevant content from ingested PDFs, and answers using a local LLM — no internet required once deployed.

**Guides:** [Off-grid solar setup](docs/off-grid-setup.md)

## How it works

```
[Meshtastic DM] → [USB LoRa device] → [RAG retrieval] → [Ollama LLM] → [Meshtastic reply]
```

Long answers are automatically split into numbered chunks (`[1/3] …`) to fit Meshtastic's 237-byte packet limit.

---

## Hardware requirements

- Raspberry Pi 4 (4 GB RAM minimum) or Pi 5
- Any Meshtastic-compatible device connected via USB (see [Supported devices](#supported-devices))
- microSD card (16 GB+)

## Software prerequisites (Pi)

- Raspberry Pi OS Lite 64-bit (recommended)
- SSH access enabled
- Internet access **during initial deploy only** — runs fully offline after

---

## Quick start (manual)

```bash
# 1. Clone and install
# On Debian/Ubuntu, ensure venv support is available first:
#   sudo apt install python3-full python3-venv -y
git clone https://github.com/birdman4512/mesh-medic.git
cd mesh-medic
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 2. Ingest your survival PDF(s)
python scripts/ingest_pdf.py /path/to/survival-guide.pdf

# List what has been ingested
python scripts/ingest_pdf.py --list

# 3. Run
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

# Review ansible/group_vars/all.yml — key variables:
#   mesh_medic_repo_url  — your fork URL
#   ollama_model         — phi3:mini (faster) or llama3.2:3b (better quality)
#   meshtastic_device    — /dev/ttyUSB0 or /dev/ttyACM0

# Deploy
ansible-playbook -i ansible/inventory.yml ansible/playbook.yml
```

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

## Switching LLM models

Both models are pulled during Ansible deployment (`ollama_pull_both_models: true`).  
To switch, edit `config.yaml` on the Pi and restart:

```yaml
llm:
  model: phi3:mini      # faster responses (~2.3 GB)
  # model: llama3.2:3b  # better quality (~2.0 GB)
```

```bash
sudo systemctl restart mesh-medic
```

| Model | Size | Speed | Quality |
|---|---|---|---|
| `phi3:mini` | ~2.3 GB | Faster | Good |
| `llama3.2:3b` | ~2.0 GB | Moderate | Better |

---

## PDF ingestion

PDFs must be text-based (not scanned images). Scanned PDFs require OCR pre-processing before ingestion.

```bash
# Ingest a PDF
python scripts/ingest_pdf.py wilderness-survival.pdf

# Ingest multiple
python scripts/ingest_pdf.py first-aid-manual.pdf

# List all ingested sources
python scripts/ingest_pdf.py --list
```

Re-ingesting a PDF safely replaces its previous chunks.

---

## Supported devices

Mesh Medic works with **any device running Meshtastic firmware** connected via USB — it communicates at the firmware protocol level, not the hardware level. The only configuration needed is the correct serial port path.

| Device | USB chip | Typical path |
|---|---|---|
| Heltec WiFi LoRa 32 V3 | CP2102N | `/dev/ttyUSB0` |
| Heltec WiFi LoRa 32 V2 | CP2102 | `/dev/ttyUSB0` |
| LILYGO T-Beam (classic) | CP2104 | `/dev/ttyUSB0` |
| LILYGO T-Beam S3 | Native USB CDC | `/dev/ttyACM0` |
| LILYGO T3-S3 | Native USB CDC | `/dev/ttyACM0` |
| RAK WisBlock (via USB) | CH340 / CP2102 | `/dev/ttyUSB0` |

> **Rule of thumb:** boards with a dedicated USB-UART chip (CP210x, CH340) show up as `/dev/ttyUSB0`; boards that use the ESP32-S3's built-in native USB show up as `/dev/ttyACM0`.

Set the path in `config.yaml`:
```yaml
meshtastic:
  device: /dev/ttyACM0   # adjust to match your board
```

If unsure, plug in the device and run `dmesg | tail -20` — the kernel will log the exact path.

---

## Enabling channel messages

By default Mesh Medic only responds to direct messages (DMs). To also respond on a channel:

```yaml
# config.yaml
meshtastic:
  respond_to_channels: true
  channel_index: 0
```

---

## Troubleshooting

**Device not found**
```bash
# Plug in the device then check what appeared
dmesg | tail -20
ls /dev/tty*
# Update meshtastic.device in config.yaml to match
```

**Permission denied on serial port**
```bash
sudo usermod -aG dialout $USER
# Log out and back in for the group change to take effect
```

**Ollama not responding**
```bash
sudo systemctl status ollama
sudo systemctl start ollama
# Check model is pulled
ollama list
ollama pull phi3:mini
```

**No context retrieved (answer ignores PDF)**
```bash
# Verify PDFs have been ingested
python scripts/ingest_pdf.py --list
# Re-ingest if the list is empty
python scripts/ingest_pdf.py /path/to/guide.pdf
```

**Slow responses on Pi 4**
- Switch to `phi3:mini` — it's meaningfully faster than `llama3.2:3b` on constrained hardware
- Reduce `max_tokens` in `config.yaml` (e.g. 200)

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
│   ├── config.py            # Config dataclasses + YAML loader
│   ├── utils.py             # Shared helpers (text chunking)
│   ├── rag_engine.py        # PDF ingestion + ChromaDB vector retrieval
│   ├── llm_engine.py        # Ollama HTTP client
│   ├── meshtastic_client.py # Meshtastic USB interface, DM handler, reply chunking
│   └── main.py              # Entry point
├── scripts/
│   └── ingest_pdf.py        # CLI: add PDFs to knowledge base
├── tests/
│   ├── test_config.py       # Config loading unit tests
│   └── test_utils.py        # Text chunking unit tests
├── .github/workflows/
│   ├── ci.yml               # Lint + test on push/PR
│   └── ansible-lint.yml     # Ansible lint on playbook changes
├── ansible/
│   ├── playbook.yml
│   ├── inventory.example.yml
│   ├── group_vars/all.yml
│   └── roles/
│       ├── common/          # System dependencies + dialout group
│       ├── ollama/          # Ollama install + model pulls
│       └── mesh-medic/      # App deploy, config template, systemd service
├── config.yaml
├── requirements.txt
├── requirements-dev.txt
└── pyproject.toml           # ruff + pytest config
```
