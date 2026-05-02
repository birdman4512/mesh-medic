"""Query MeshCore device info and custom vars — for diagnostics."""
import asyncio
from meshcore import MeshCore


async def main():
    mc = await MeshCore.create_serial("/dev/ttyUSB0", 115200)

    print("=== device info ===")
    r = await mc.commands.send_appstart()
    print(r.payload)

    print("\n=== custom vars ===")
    r = await mc.commands.get_custom_vars()
    print(r.payload)

    print("\n=== allowed repeat freqs ===")
    r = await mc.commands.get_allowed_repeat_freq()
    print(r.payload)

    print("\n=== testing radio params (no repeat) ===")
    r = await mc.commands.set_radio(923.125, 62.5, 8, 6)
    print(r.type, r.payload)


asyncio.run(main())
