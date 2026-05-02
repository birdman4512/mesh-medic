# Troubleshooting

Common issues encountered when deploying and running Mesh Medic, with their root causes and fixes.

---

## Meshtastic device

### "Timed out waiting for connection completion"

```
meshtastic.mesh_interface.MeshInterface.MeshInterfaceError: Timed out waiting for connection completion
```

**Cause:** The device is unresponsive on the serial port. This happens after the service stops and releases `/dev/ttyACM0` — the SEEED_XIAO_S3 enters a bad state until USB is re-enumerated.

**Fix:**
1. Unplug and replug the USB cable.
2. If using VirtualBox, re-attach the device via **Devices → USB → [your device]**.
3. Restart the service: `sudo systemctl restart mesh-medic`

The service will retry the connection up to 10 times (15 s apart) before giving up, so a brief enumeration delay is handled automatically.

---

### "Resource temporarily unavailable" / port locked

```
[Errno 11] Could not exclusively lock port /dev/ttyACM0
```

**Cause:** Another process holds the serial port. You cannot run the `meshtastic` CLI while `mesh-medic.service` is running.

**Fix:** Stop the service first, then run your CLI command:
```bash
sudo systemctl stop mesh-medic
meshtastic --info
sudo systemctl start mesh-medic
```

After stopping the service you may still need to replug the USB before the CLI will connect (see above).

---

### Device shows as `/dev/ttyACM0` not `/dev/ttyUSB0`

Devices using native USB CDC (SEEED XIAO S3, some nRF52 boards) appear as `ttyACM0`. UART-bridged devices (Heltec V3 with CH340/CP2102) appear as `ttyUSB0`. Check with:

```bash
ls /dev/tty{ACM,USB}*
```

Update `group_vars/all.yml`:
```yaml
meshtastic_device: /dev/ttyACM0
```

---

### Cannot send DMs — "Error No Channel"

**Cause:** Meshtastic firmware 2.5+ uses PKC (public-key cryptography) for DMs. The sending node must have your node's public key before it can encrypt a DM to you.

**Fix:** The keys are exchanged automatically when the two nodes are in range and exchange packets. Wait for a node info broadcast, or trigger one by sending a channel message first.

---

## LLM / Ollama

### "Error: LLM unavailable. Check Ollama service."

The service received a message but Ollama returned an error or timed out. Check Ollama directly:

```bash
sudo systemctl status ollama
sudo journalctl -u ollama -n 50 --no-pager
```

#### HTTP 500 after ~2 minutes — out of memory

**Cause:** The configured model is too large for available RAM. `phi3:mini` (3.8B params) needs ~3.8 GB RAM (model weights + KV cache). On a 4 GB host this causes OOM during inference.

**Fix:** Switch to `tinyllama:1.1b` (~638 MB):
```bash
ollama pull tinyllama:1.1b
sudo sed -i 's/model: phi3:mini/model: tinyllama:1.1b/' /opt/mesh-medic/config.yaml
sudo systemctl restart mesh-medic
```

Or update `group_vars/all.yml` and re-run Ansible:
```yaml
ollama_model: tinyllama:1.1b
```

#### Model not found

```
Model 'xyz' not found in Ollama. Run: ollama pull xyz
```

**Fix:**
```bash
ollama pull tinyllama:1.1b   # or whichever model is configured
```

#### Ollama not running

```bash
sudo systemctl start ollama
sudo systemctl enable ollama   # start on boot
```

---

### Replies are too long / packets lost over radio

**Cause:** If `max_tokens` is set too high the LLM generates responses that split into 3+ Meshtastic packets. At 2 s between packets some are lost in transit.

**Fix:** Keep `max_tokens` at 80 (≈320 chars = 1–2 packets) and `chunk_delay` at 5 s in `config.yaml`:

```yaml
llm:
  max_tokens: 80

response:
  chunk_delay: 5
```

---

## Ansible deployment

### Git clone fails — "destination path is not empty"

**Cause:** The install directory (`/opt/mesh-medic`) was pre-created by an earlier task before the git clone ran.

**Fix:** The playbook has `force: true` on the git task. If the directory was manually created and is truly empty, delete it and re-run:
```bash
sudo rm -rf /opt/mesh-medic
ansible-playbook ansible/site.yml -i ansible/inventory.yml
```

---

### "dubious ownership" git error

```
fatal: detected dubious ownership in repository at '/opt/mesh-medic'
```

**Cause:** The install directory is owned by `mesh-medic` but Ansible runs git as root.

**Fix:** The playbook adds `/opt/mesh-medic` to git's global safe directory list before cloning. If you hit this manually:
```bash
sudo git config --global --add safe.directory /opt/mesh-medic
```

---

### Disk full during pip install / model download

```
OSError: [Errno 28] No space left on device
```

**Cause:** Default VM disk is too small. PyTorch (CPU-only build) + Ollama models need ~5–8 GB free.

**Fix — expand an LVM-based VM disk:**
```bash
# 1. Resize the disk in VirtualBox (shut down VM first, then use VBoxManage or GUI)
# 2. Inside the VM:
sudo growpart /dev/sda 3          # expand the partition (adjust number if needed)
sudo pvresize /dev/sda3           # resize the LVM physical volume
sudo lvextend -l +100%FREE /dev/ubuntu-vg/ubuntu-lv
sudo resize2fs /dev/ubuntu-vg/ubuntu-lv
df -h                             # verify free space
```

---

### HuggingFace model download fails — permission denied

**Cause:** The `mesh-medic` system user has no home directory, so the default HF cache path (`~/.cache/huggingface`) doesn't exist.

**Fix:** `HF_HOME` is set to `/opt/mesh-medic/data/models` in the systemd service unit and in the Ansible pre-download task. Verify:
```bash
sudo systemctl cat mesh-medic | grep HF_HOME
# should show: Environment=HF_HOME=/opt/mesh-medic/data/models
```

---

## Service

### Service won't start — check logs

```bash
sudo systemctl status mesh-medic
sudo journalctl -u mesh-medic -n 100 --no-pager
```

### Watch live for incoming messages and replies

```bash
sudo journalctl -u mesh-medic -f
```

A healthy session looks like:
```
Connected. Node: !ae6145e8
Listening for messages...
[DM] Message from !433efbe0 (21 chars)
Question from !433efbe0 (21 chars, DM)
Retrieved 980 chars of context
Answer prepared (143 chars)
Sent part 1/1 to !433efbe0
```

### Service restarts repeatedly

The service is set to `Restart=on-failure` with `RestartSec=15`. If it keeps restarting, the underlying error will appear in the journal. Common causes:

- Meshtastic device not connected / wrong port → fix device
- Ollama not running → `sudo systemctl start ollama`
- `config.yaml` has a syntax error → validate with `python3 -c "import yaml; yaml.safe_load(open('/opt/mesh-medic/config.yaml'))"`

---

## PDF ingestion

### Permission denied reading the PDF

**Cause:** The script runs as the `mesh-medic` user, which can't read files in `/home/dean/`.

**Fix:** Copy the PDF into the data directory first:
```bash
sudo cp ~/yourfile.pdf /opt/mesh-medic/data/pdfs/
sudo chown mesh-medic:mesh-medic /opt/mesh-medic/data/pdfs/yourfile.pdf
cd /opt/mesh-medic
sudo -u mesh-medic venv/bin/python scripts/ingest_pdf.py data/pdfs/yourfile.pdf
```

### Verify the knowledge base loaded

```bash
sudo journalctl -u mesh-medic --no-pager | grep "Knowledge base"
# example output:
# Knowledge base: 2165 chunks from ['SAS.Survival.Handbook.pdf']
```
