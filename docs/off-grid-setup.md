# Off-Grid Power Setup

This guide covers how to power Mesh Medic entirely from solar — no mains power required. It walks through calculating your power budget, sizing the solar panel and battery, choosing components, and wiring everything together.

---

## Power budget

Before sizing anything, establish how much power the system consumes.

| Component | Idle | Peak (LLM inference) |
|---|---|---|
| Raspberry Pi 4 (4 GB) | ~3 W | ~8 W |
| Raspberry Pi 5 | ~4 W | ~10 W |
| Meshtastic device (receiving) | ~0.3 W | ~0.8 W (transmitting) |
| **System total** | **~3.5 W** | **~9 W** |

**Daily energy budget** (24-hour operation):

- Average draw (Pi 4, mostly idle with occasional queries): ~5 W
- Daily consumption: **5 W × 24 h = 120 Wh/day**

> Use 120–150 Wh/day as your planning figure. Heavier query loads can push it toward 150 Wh/day.

---

## Solar panel sizing

Peak sun hours vary by location and season — typically 3–6 hours/day in temperate climates, higher in arid regions.

**Formula:**

```
Panel watts required = Daily Wh ÷ Peak sun hours ÷ System efficiency
```

Using 150 Wh/day, 4 peak sun hours, and 80% efficiency:

```
150 ÷ 4 ÷ 0.80 = 47 W minimum
```

| Use case | Recommended panel |
|---|---|
| Sunny climate, occasional use | 50 W |
| Temperate climate, daily use | **80 W** (recommended) |
| Overcast / winter / critical deployment | 100–120 W |

A **80 W monocrystalline panel** is the practical sweet spot for most deployments. Monocrystalline panels outperform polycrystalline in low-light and overcast conditions.

---

## Battery sizing

Size the battery to cover **2–3 days of autonomy** without sun (cloudy weather, winter).

```
Battery capacity (Wh) = Daily consumption × Autonomy days ÷ Usable depth of discharge
```

Using 150 Wh/day, 3 days autonomy, 80% usable capacity (LiFePO4):

```
150 × 3 ÷ 0.80 = 562 Wh → 47 Ah at 12 V
```

| Battery type | Recommended capacity | Notes |
|---|---|---|
| LiFePO4 (lithium iron phosphate) | **50 Ah @ 12 V** | Best choice — deep cycle safe, long lifespan (~2000 cycles), handles temperature well |
| AGM (sealed lead-acid) | 100 Ah @ 12 V | Double the capacity needed because AGM should only be discharged to 50% |
| Flooded lead-acid | Not recommended | Requires maintenance, off-gassing, prone to sulphation |

**LiFePO4 is strongly recommended** for unattended off-grid deployments. It is safer than other lithium chemistries, requires no maintenance, and lasts far longer than lead-acid.

---

## Component list

| Component | Specification | Example |
|---|---|---|
| Solar panel | 80 W monocrystalline, 12 V nominal | Renogy 80W, HQST 80W |
| Charge controller | MPPT, 10 A, 12/24 V | Victron SmartSolar MPPT 75/10, Renogy Wanderer MPPT |
| Battery | 12 V 50 Ah LiFePO4 | Renogy 12V 50Ah, Ampere Time 50Ah |
| DC-DC buck converter | 12 V → 5 V, 5 A rated (25 W) | Drok/DZSM 5A USB step-down, Pololu 5V 5A |
| USB-C cable | 1 m, 5 A rated | For Raspberry Pi 5 power |
| Micro-USB or USB-C cable | For Meshtastic device power | Depends on your board |
| Weatherproof enclosure | IP65 or better | Hammond 1554, Pelican 1150 |
| MC4 connectors | Pre-fitted on most panels | Matched pair |
| Inline fuse — panel to controller | 10 A blade fuse + holder | Between panel positive and controller |
| Inline fuse — battery to controller | 15 A blade fuse + holder | Between battery positive and controller |
| Inline fuse — battery to DC-DC | 5 A blade fuse + holder | Between battery positive and DC-DC input |
| Wire | 4 mm² (12 AWG) for panel/battery runs | Tinned marine-grade recommended |

> **MPPT vs PWM:** Always use an MPPT charge controller. MPPT controllers recover 20–30% more energy from the panel than PWM, which matters most on cloudy days.

---

## Wiring diagram

```
                    ┌─────────────┐
   Solar Panel      │    MPPT     │
   (+) ──[F1]──────▶│ PV+    BAT+ │──[F2]──┬──────────────────────┐
   (-) ─────────────▶│ PV-    BAT- │────────┤                      │
                    │             │        │                      │
                    │        LOAD+│──[F3]──┤  (optional load out) │
                    │        LOAD-│────────┘                      │
                    └─────────────┘                               │
                                                                  │
                                            ┌─────────────────────┤
                                            │     12 V Battery    │
                                            │   (LiFePO4 50 Ah)   │
                                            └──────┬──────────────┘
                                                   │
                                              [F4] │ 12 V
                                                   ▼
                                       ┌───────────────────────┐
                                       │  DC-DC Buck Converter │
                                       │    12 V in → 5 V out  │
                                       └───────┬───────────────┘
                                               │ 5 V / 5 A
                                    ┌──────────┴──────────┐
                                    │                     │
                                    ▼                     ▼
                           Raspberry Pi            Meshtastic device
                           (USB-C 5V/3A)           (USB 5V)

Fuse ratings:
  F1 — 10 A  (panel to controller)
  F2 — 15 A  (controller to battery)
  F3 — 10 A  (controller load output, if used)
  F4 —  5 A  (battery to DC-DC converter)
```

**Wiring order — always connect in this sequence to avoid sparks:**

1. Connect battery to charge controller
2. Connect solar panel to charge controller
3. Connect DC-DC converter to battery (via fuse)
4. Connect Raspberry Pi and Meshtastic device to DC-DC converter
5. Verify voltages before powering on

**Disconnect in reverse order.**

---

## Enclosure and weatherproofing

| Item | Recommendation |
|---|---|
| Enclosure rating | IP65 minimum (dust-tight, water jet resistant) |
| Panel mounting | Tilted toward equator at your latitude angle for best year-round output |
| Cable entry | Use IP68 cable glands for all wire penetrations |
| Ventilation | Add a Gore-Tex vent plug to prevent condensation without allowing water ingress |
| Thermal management | Avoid sealing the Pi in an unventilated box — it will throttle under LLM load |

**Enclosure layout tips:**

- Mount the charge controller inside the enclosure — it generates a little heat but handles it better indoors
- Keep battery outside or in a vented compartment if using LiFePO4 (safe chemistry, but best practice)
- Run panel cables along the mount structure to protect them from UV and abrasion
- Use a drip loop on all external cable runs to stop water tracking along the wire into the enclosure

---

## Reducing power consumption

Every watt saved extends battery life or lets you use a smaller panel.

| Action | Saving |
|---|---|
| Disable HDMI output | ~25 mW |
| Disable Bluetooth | ~50 mW |
| Disable WiFi (if using Ethernet or not needed) | ~100 mW |
| Use Pi 4 instead of Pi 5 | ~1–2 W at idle |
| Set CPU governor to `powersave` | ~0.5–1 W |
| Reduce LLM `max_tokens` in `config.yaml` | Shorter inference = less active time |

**Disable HDMI and Bluetooth on boot** — add to `/boot/config.txt` on the Pi:

```ini
# Disable HDMI
hdmi_blanking=2

# Disable Bluetooth
dtoverlay=disable-bt
```

**Set CPU governor to powersave:**

```bash
echo powersave | sudo tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor
```

To make it persistent, add to `/etc/rc.local` before `exit 0`.

---

## Monitoring battery state

The MPPT charge controller's load output (if available) or a simple voltage monitor lets you shut the Pi down gracefully before the battery is exhausted.

**Victron SmartSolar** controllers support Bluetooth monitoring via the Victron Connect app — useful during initial setup to verify charging behaviour.

For automated low-battery shutdown on the Pi, a cheap INA219 or voltage divider on a GPIO pin can trigger a `sudo shutdown -h now` before the battery hits its protection cutoff.

---

## Quick-reference: recommended build

For a reliable, no-fuss off-grid deployment in a temperate climate:

| Item | Choice |
|---|---|
| Panel | 80 W monocrystalline |
| Charge controller | Victron SmartSolar MPPT 75/10 |
| Battery | 12 V 50 Ah LiFePO4 |
| DC-DC converter | 12 V → 5 V 5 A buck module |
| Enclosure | IP65 ABS box (200 × 150 × 100 mm minimum) |
| Compute | Raspberry Pi 4 4 GB |
| Radio | Any Meshtastic USB device (see [supported devices](../README.md#supported-devices)) |

Estimated total cost (excluding Pi and radio): **£80–£150 / $100–$180 USD** depending on battery brand.
