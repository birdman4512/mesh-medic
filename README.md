# Mesh Medic

Offline survival assistant for Raspberry Pi. Receives questions via Meshtastic radio (Heltec V3), retrieves relevant content from ingested PDFs, and answers using a local LLM — no internet required once deployed.

## How it works

```
[Meshtastic DM] → [Heltec V3 USB] → [RAG retrieval] → [Ollama LLM] → [Meshtastic reply]
```

Long answers are automatically split into numbered chunks to fit Meshtastic's 237-byte packet limit.

## Hardware

- Raspberry Pi 4 (4 GB RAM minimum) or Pi 5
- Heltec WiFi LoRa 32 V3 connected via USB

## Prerequisites (Pi)

- Raspberry Pi OS (64-bit recommended)
- SSH access for Ansible deployment
- Internet access during initial deploy (to pull models — runs fully offline after)

---

## Quick Start (manual)

```bash
# 1. Clone and install
git clone https://github.com/youruser/mesh-medic.git
cd mesh-medic
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 2. Ingest your survival PDF(s)
python scripts/ingest_pdf.py /path/to/survival-guide.pdf

# List what's been ingested
python scripts/ingest_pdf.py --list

# 3. Run
python -m src.main
```

---

## Deployment (Ansible)

```bash
# Install Ansible on your workstation
pip install ansible

# Copy and edit inventory
cp ansible/inventory.example.yml ansible/inventory.yml
# Edit ansible/inventory.yml — set your Pi's IP and SSH user

# Edit ansible/group_vars/all.yml:
#   - Set mesh_medic_repo_url to your fork
#   - Set ollama_model (phi3:mini or llama3.2:3b)
#   - Set meshtastic_device (/dev/ttyUSB0 or /dev/ttyACM0)

# Deploy
ansible-playbook -i ansible/inventory.yml ansible/playbook.yml

# Then SSH to Pi and ingest PDFs
ssh pi@<pi-ip>
cd /opt/mesh-medic
sudo -u mesh-medic venv/bin/python scripts/ingest_pdf.py /opt/mesh-medic/data/pdfs/my-guide.pdf
```

### Checking the service

```bash
sudo systemctl status mesh-medic
sudo journalctl -u mesh-medic -f
```

---

## Switching models

Edit `config.yaml` (or `ansible/group_vars/all.yml` before deploying):

```yaml
llm:
  model: phi3:mini      # faster
  # model: llama3.2:3b  # better quality
```

Both models are pulled during Ansible deployment when `ollama_pull_both_models: true`.  
After editing `config.yaml` manually on the Pi, restart the service:

```bash
sudo systemctl restart mesh-medic
```

---

## Enabling channel messages

By default Mesh Medic only responds to direct messages (DMs). To also respond to channel messages:

```yaml
meshtastic:
  respond_to_channels: true
  channel_index: 0   # which channel to listen/reply on
```

---

## Finding the Heltec V3 device path

```bash
# Before plugging in, then after — compare the output
ls /dev/tty*

# Or check dmesg after plugging in
dmesg | tail -20
```

Common paths: `/dev/ttyUSB0`, `/dev/ttyACM0`

---

## PDF ingestion tips

- PDFs should be text-based (not scanned images). Scanned PDFs require OCR pre-processing.
- You can ingest multiple PDFs — they're all stored in the same vector database.
- Re-ingesting a PDF replaces its previous chunks (safe to re-run).

```bash
# Ingest
python scripts/ingest_pdf.py wilderness-survival.pdf
python scripts/ingest_pdf.py first-aid-manual.pdf

# Check what's loaded
python scripts/ingest_pdf.py --list
```

---

## Project structure

```
mesh-medic/
├── src/
│   ├── config.py            # Config loading
│   ├── rag_engine.py        # PDF ingestion + vector retrieval (ChromaDB)
│   ├── llm_engine.py        # Ollama LLM interface
│   ├── meshtastic_client.py # Meshtastic USB interface + message chunking
│   └── main.py              # Application entry point
├── scripts/
│   └── ingest_pdf.py        # CLI to add PDFs to knowledge base
├── ansible/
│   ├── playbook.yml
│   ├── inventory.example.yml
│   ├── group_vars/all.yml
│   └── roles/
│       ├── common/          # System dependencies
│       ├── ollama/          # Ollama install + model pull
│       └── mesh-medic/      # App deploy + systemd service
├── config.yaml
└── requirements.txt
```
