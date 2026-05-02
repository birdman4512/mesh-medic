"""One-shot script: set MeshCore node name and radio frequency, then reboot."""
import asyncio
import sys

from meshcore import MeshCore


async def main(device, name, freq, bw, sf, cr, repeat=None):
    print(f"Connecting to {device}...")
    mc = await MeshCore.create_serial(device, 115200)

    print(f"  name  -> {name!r}")
    r = await mc.commands.set_name(name)
    if r.type.name == "ERROR":
        print(f"  ERROR setting name: {r.payload}", file=sys.stderr)
        sys.exit(1)

    repeat_label = f", repeat {repeat}" if repeat is not None else ""
    print(f"  radio -> {freq} MHz, BW {bw} kHz, SF {sf}, CR {cr}{repeat_label}")
    r = await mc.commands.set_radio(freq, bw, sf, cr, repeat)
    if r.type.name == "ERROR":
        print(f"  ERROR setting radio: {r.payload}", file=sys.stderr)
        sys.exit(1)

    print("  rebooting device...")
    await mc.commands.reboot()
    print("Done.")


if __name__ == "__main__":
    device = sys.argv[1]
    name   = sys.argv[2]
    freq   = float(sys.argv[3])
    bw     = float(sys.argv[4])
    sf     = int(sys.argv[5])
    cr     = int(sys.argv[6])
    repeat = int(sys.argv[7]) if len(sys.argv) > 7 else None
    asyncio.run(main(device, name, freq, bw, sf, cr, repeat))
