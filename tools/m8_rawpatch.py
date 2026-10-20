#!/usr/bin/env python3
"""
Leica M8 firmware 2.014 / 2.024 -- "persistent RAW" patch.

Status:
  2.014, P1+P2+P3   tested on hardware (2026-10-19) and in tools/m8_emutest.py.
  2.014 --no-menu   emulator-tested only.
  2.024             untested on hardware (same code; static analysis only).
Flashing modified firmware can brick the camera. Rollback = flash the stock file.

Patches the PXA (Intel XScale / ARM, load base 0x20000) section of m8-2_014.upd or m8-2_024.upd
(identical code at identical addresses in both versions):

  P1 0x2191C  beq 0x21944 -> nop
      Settings-load-from-EEPROM routine: if compression == 5 (JPG fine+RAW)
      it unconditionally rewrites it to 1 (JPG fine) at every boot/wake.
  P2 0x4F0C8  beq 0x4EFC8 -> b 0x4EFC8
      SET-menu loader: if compression == 5 and service mode is NOT active,
      it rewrites the profile to 1 (JPG fine). Make it always accept 5.
  P3 0x4EED4  movne r3,#5 -> movne r3,#6
      SET-menu Compression item shows 5 entries normally, 6 in service mode.
      Make it always show 6, so "JPG fine+RAW" is selectable without the
      button dance.  (Optional: use --no-menu to apply only P1+P2, which keeps
      the dance as the way to *select* RAW but makes the choice persist.)

Usage: python3 m8_rawpatch.py m8-2_0xx.upd out.upd [--no-menu]
"""
import hashlib, struct, sys

KNOWN_INPUTS = {  # stock Leica files this patch was verified against
    "95dbb319ba6b2d675437853402a8bbabe8e96796b74a52ed325fa5c8b3f68acb": "2.024",
    "99f5254847a92c68086f37b1a4140c359379801b479df12052136abb73f09ed0": "2.014",
}
KNOWN_OUTPUTS = {  # full-patch outputs (see FINDINGS)
    "f6589c41a583d1a44fbce77c4acda707640d255acec97a0d2e1ac829c2e70396": "2.014, tested on hardware",
    "6c411873891a965d03ad83f1bcb9b2030329595a4d00848cf369eaec45a9c94e": "2.024, untested on hardware",
}
PXA_BASE = 0x20000

PATCHES = [
    # (name, vaddr, original bytes, new bytes)
    ("P1 keep RAW at boot", 0x2191C, bytes.fromhex("0800000a"), bytes.fromhex("0000a0e1")),
    ("P2 keep RAW in menu", 0x4F0C8, bytes.fromhex("beffff0a"), bytes.fromhex("beffffea")),
    ("P3 show RAW in menu", 0x4EED4, bytes.fromhex("0530a013"), bytes.fromhex("0630a013")),
]


def find_lump(buf, want):
    assert buf[:4] == b"PWAD", "not a PWAD/M8 update file"
    n, ofs = struct.unpack_from("<II", buf, 4)
    for i in range(n):
        pos, size, name = struct.unpack_from("<II8s", buf, ofs + i * 16)
        if name.split(b"\0")[0] == want:
            return pos, size
    raise SystemExit(f"lump {want!r} not found")


def main():
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    src, dst = sys.argv[1], sys.argv[2]
    no_menu = "--no-menu" in sys.argv
    data = bytearray(open(src, "rb").read())
    ver = KNOWN_INPUTS.get(hashlib.sha256(data).hexdigest())
    if not ver:
        raise SystemExit("input is not a stock m8-2_014.upd or m8-2_024.upd this patch was made for")
    print("input: stock firmware", ver)
    pxa_pos, pxa_size = find_lump(data, b"PXA")
    for name, va, old, new in PATCHES:
        if no_menu and name.startswith("P3"):
            continue
        off = pxa_pos + (va - PXA_BASE)
        assert va - PXA_BASE + 4 <= pxa_size
        cur = bytes(data[off:off + 4])
        if cur != old:
            raise SystemExit(f"{name}: unexpected bytes {cur.hex()} at file 0x{off:X}")
        data[off:off + 4] = new
        print(f"{name}: file offset 0x{off:06X}  {old.hex()} -> {new.hex()}")
    open(dst, "wb").write(data)
    sha = hashlib.sha256(data).hexdigest()
    print("wrote", dst, "sha256", sha)
    print("matches known build:", KNOWN_OUTPUTS.get(sha, "no (untested variant)"))


if __name__ == "__main__":
    main()
