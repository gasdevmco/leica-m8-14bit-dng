# leica-m8-firmware

Private tools and notes for modifying Leica M8 firmware.

- **Persistent RAW patch:** makes the service-mode "JPG fine+RAW" (14-bit) setting selectable in
  SET and keeps it across power cycles. **2.014: tested on hardware** (2026-10-19) and in the
  emulator. 2.024: same code, untested on hardware.
- **In-camera 14-bit DNG (in progress):** the desktop prototype produces DNGs that Lightroom opens
  natively, with per-shot exposure, ISO and date. Firmware phase started: staged builds and an emulated save path; stage 1 (canary) built. Plan:
  [`docs/DNG_PLAN.md`](docs/DNG_PLAN.md).
- All addresses, hashes and conclusions: [`docs/FINDINGS.md`](docs/FINDINGS.md).

No Leica firmware is included. Put your own stock `.upd` files in `firmware/stock/`; the scripts
check their SHA-256 hashes.

## Setup

```sh
python3 -m venv work/venv && work/venv/bin/pip install -r requirements.txt
python3 tools/split_upd.py firmware/stock/m8-2_014.upd work/split-2.014
```

## Tools

| Script | Purpose |
|---|---|
| `tools/m8_rawpatch.py` | Build the persistent-RAW firmware: `python3 tools/m8_rawpatch.py firmware/stock/m8-2_014.upd firmware/patched/m8-2_014.upd` |
| `tools/m8_emutest.py` | Unicorn emulator tests of the patch (stock vs patched): `work/venv/bin/python tools/m8_emutest.py` |
| `tools/m8_dngpatch.py` | Staged in-camera DNG builds (`--stage N`), with a declared-regions check against the flashed build |
| `tools/m8_savetest.py` | Emulated RAW save path: a simulated shot through the real firmware, compared with camera files |
| `tools/m8_wrapdng.py` | Desktop prototype of the in-camera RAW→DNG wrap: `python3 tools/m8_wrapdng.py sampleraws/X.RAW` |
| `tools/m8_reclaim.py` | Rank debug-command handlers as reclaimable code space |
| `tools/armtools.py` | Capstone disassembly and cross-reference helpers |
| `tools/split_upd.py` | Split a `.upd` (PWAD) file into its parts |
| `tools/ghidra/` | Headless Ghidra scripts for a second opinion on references |

Flashing modified firmware is at your own risk. Keep the stock file to roll back.
