# leica-m8-14bit-dng

Tools for patching the firmware of the **Leica M8** so it can:

1. **Keep "JPG fine+RAW" selected.** This hidden service-mode setting saves the sensor's full 14-bit
   data. Stock firmware hides it and resets it at every power-on; the patch makes it a normal SET menu
   choice that stays selected.
2. **Write a 14-bit DNG in the camera.** In JPG fine+RAW mode, the camera saves a JPG plus a 14-bit
   DNG that Lightroom opens directly, with exposure time, ISO and capture date filled in. The
   camera's own DNG mode is 8-bit (companded); this keeps the full sensor data and needs no
   conversion step.

> **Status: tested on one camera.** Both patches run on the author's M8 with firmware 2.014. They are
> experimental, not affiliated with or endorsed by Leica, and flashing modified firmware is at your
> own risk. Read [Safety and recovery](#safety-and-recovery) before flashing anything.

**No Leica firmware is included in this repository**, and none should ever be added: the firmware is
Leica's copyright. You supply your own copy of the stock update file; every script checks its SHA-256
and refuses anything else.

## Contents

- [What you get](#what-you-get)
- [Requirements](#requirements)
- [Build a firmware file](#build-a-firmware-file)
- [Flash it](#flash-it)
- [Safety and recovery](#safety-and-recovery)
- [Known limitations](#known-limitations)
- [How it works](#how-it-works)
- [Testing without a camera](#testing-without-a-camera)
- [Repository layout](#repository-layout)
- [Credits](#credits)
- [License](#license)

## What you get

| Build | Script | What it changes | Tested on hardware |
|---|---|---|---|
| **Persistent RAW** | `tools/m8_rawpatch.py` | 5 bytes: "JPG fine+RAW" listed in SET → Compression and kept across power cycles | 2.014: yes. 2.024: same code, not tested |
| **In-camera DNG** (stage 4) | `tools/m8_dngpatch.py --stage 4` | The RAW patch plus 1,634 bytes: TIFF header, DNG tag block, small routine in unused debug-command space | 2.014 only: yes |

With the DNG build, each JPG fine+RAW shot produces:

- `L10xxxxx.JPG`: the camera's normal JPG, used by in-camera review.
- `L10xxxxx.RAW`: 21,049,052 bytes. Its contents are a complete 14-bit DNG (uncompressed CFA, M8
  colour matrices, white level 16383, black level 92), plus exposure time, exposure program, ISO,
  shutter value, exposure bias, max aperture, focal length and date from the shot. Lightroom opens
  the `.RAW` file as is. For other software, rename the extension to `.DNG`.

The other Compression modes (JPG fine, JPG basic, DNG, DNG+JPG) are unchanged stock code. Switching
to one of them turns the new code off completely.

## Requirements

- A Leica M8 running firmware **2.014**. The DNG build only exists for 2.014.
- The stock update file `m8-2_014.upd`, SHA-256
  `99f5254847a92c68086f37b1a4140c359379801b479df12052136abb73f09ed0`. For the RAW patch on 2.024:
  `m8-2_024.upd`, SHA-256 `95dbb319ba6b2d675437853402a8bbabe8e96796b74a52ed325fa5c8b3f68acb`.
- Python 3 (developed on macOS). The patch scripts need only the standard library and Capstone; the
  emulator tests need Unicorn.
- Optional, only to change the assembly: an ARM-capable clang (Apple clang works).

```sh
python3 -m venv work/venv
work/venv/bin/pip install -r requirements.txt
```

## Build a firmware file

Put the stock file at `firmware/stock/m8-2_014.upd`, then run one of the following.

```sh
# Persistent RAW only
python3 tools/m8_rawpatch.py firmware/stock/m8-2_014.upd firmware/patched/m8-2_014.upd

# In-camera DNG (includes the RAW patch)
work/venv/bin/python tools/m8_dngpatch.py firmware/stock/m8-2_014.upd \
    firmware/patched/m8-2_014-stage4.upd --stage 4
```

Each script prints every changed instruction, checks that nothing outside the declared regions
changed, and prints the output's SHA-256. Compare it with the expected builds:

| Build | SHA-256 |
|---|---|
| Persistent RAW, 2.014 | `f6589c41a583d1a44fbce77c4acda707640d255acec97a0d2e1ac829c2e70396` |
| Persistent RAW, 2.024 (untested on hardware) | `6c411873891a965d03ad83f1bcb9b2030329595a4d00848cf369eaec45a9c94e` |
| In-camera DNG, stage 4, 2.014 | `59aff4a35f5c8fea4ca1fc8ab962ac3e0ac171131bd82410cf67c9231665273c` |

If your hash differs, don't flash the file.

## Flash it

1. **Fully charged battery.**
2. Keep a **second card holding only the stock `m8-2_014.upd`**, ready to roll back.
3. Format a card in the camera. Copy the built file to it as **`M8-2_014.UPD`**: the updater looks
   for `M8.UPD` or `M8-x_yyy.UPD`.
4. Run the camera's normal firmware update, the same as for Leica's own file. The progress bar
   usually pauses around 60% before completing. **Don't touch the battery or card while it runs.**
5. After the restart: SET → Compression → **JPG fine+RAW**. Take a test shot and check it on the
   computer.

## Safety and recovery

**What the patches don't touch.** Both builds leave the bootloader (RedBoot, not in the update file at
all), the SD-card updater, startup code, settings load/save, and every other part of the update file
(DSP, FPGA, body controller, fonts, lens table) byte-identical. The patch scripts check this
automatically on every build. The new DNG code runs only while a JPG fine+RAW shot is being saved,
never at startup or during an update. It writes only into the unused last sensor row of the image
buffer, and it range-checks every write.

**Rolling back.** The updater accepts the same or an older version, so flashing the stock
`m8-2_014.upd` from the card always returns the camera to stock. The author has done
patched → stock → patched on hardware. Before sending the camera to Leica for service, reflash stock.

**If something looks wrong while shooting** (freeze, error, odd behaviour):

1. **Pull the battery first.** Not the power switch, and don't remove the card. Power-state changes
   and card insert/remove make the camera save its settings; a battery pull saves nothing.
2. Power on, set Compression to **JPG fine** (the new code never runs then), and reflash stock or the
   RAW-only build.

## Known limitations

- **Tested on one camera.** Single shots, power cycles, and continuous shooting until the buffer
  fills (on the RAW-only build) are tested; the DNG build hasn't had the full burst test yet.
- **Files are named `.RAW`, not `.DNG`.** A build that names them `.DNG` exists (stage 5), but on the
  camera, review of a JPG + `.DNG` pair then shows only the DNG's file name and can't reach the JPG,
  because these DNGs have no embedded preview. Stage 4 keeps in-camera review working normally.
- **White balance:** Lightroom starts from a fixed daylight balance (Auto and the presets work
  normally); the camera's WB setting isn't carried over yet.
- **Black level:** a constant 92 at every ISO. A per-ISO table from dark frames is planned.
- **Not included yet:** lens name, body serial, the Leica MakerNote, and an embedded preview.
- **`.BIA` dark frames** (written for long exposures) also get the TIFF header bytes, but no DNG tags.
  Converters that skip the header, such as m8raw2dng2, aren't affected.
- The **RAW-only patch on 2.024** uses the same code at the same addresses but is untested on
  hardware. Some bodies are reported to stop saving images on 2.024 regardless; 2.014 is recommended.

## How it works

The M8's update file is an uncompressed container ("PWAD") with no overall checksum. Its `PXA` part is
the main ARM program (Intel XScale, ARMv5TE, loaded at `0x20000`). Everything was found by static
analysis with Capstone and Ghidra, then checked in an emulator and on the camera.

- **Persistent RAW:** two branches that reset Compression 5 (JPG fine+RAW) to 1 are removed, at boot
  and when the SET menu opens. One constant makes the menu list six entries instead of five.
- **In-camera DNG:** the RAW file is already uncompressed 14-bit data with a 108-byte header,
  2,646 rows × 3,976 samples, and one unused trailing row. TIFF lets the tag directory sit anywhere,
  so the build:
  1. rewrites the header code so the first 8 bytes become a TIFF header pointing at the trailing row
     (same number of instructions, in place);
  2. adds a `bl` in the RAW writer's last-block branch to a small routine. The routine sits where the
     `ldimg` debug command used to be; that command is now a stub that returns.
  3. The routine copies a 902-byte DNG tag block into the trailing row and fills the per-shot values
     from the shot's metadata, which the camera already holds for the JPG.

  The pixels are never touched or copied, and the file size, timing and write path stay as in stock
  RAW mode.

Every address, offset and decision, with the evidence for it, is in
[`docs/FINDINGS.md`](docs/FINDINGS.md). The design, staging and risk assessment are in
[`docs/DNG_PLAN.md`](docs/DNG_PLAN.md).

## Testing without a camera

Two Unicorn-based emulator suites run the real firmware code from the stock file:

```sh
work/venv/bin/python tools/m8_emutest.py     # settings loader + SET menu, stock vs RAW patch
work/venv/bin/python tools/m8_savetest.py    # a simulated shot through the real save path (~6 min)
```

`m8_savetest.py` runs the real store routine, DMA handler, ring buffer and RAW writer. It models the
DMA controller and the card-writer task. For each build it compares the file that reaches the "card"
byte for byte with an independently computed expectation, logs every write the new code makes, and
checks that boot and update code are untouched. The stock build reproduces real camera files exactly.

The save-path test needs camera files, which aren't in the repository: `sampleraws/L1031902.RAW` +
`L1031902.JPG` (a JPG fine+RAW pair) and `sampleraws/L1031901.RAW`. Use your own files under those
names. `m8_emutest.py` needs the RAW-patch build at `firmware/patched/m8-2_014.upd`.

## Repository layout

| Path | Contents |
|---|---|
| `tools/m8_rawpatch.py` | Persistent-RAW patch (2.014 / 2.024) |
| `tools/m8_dngpatch.py` | In-camera DNG builds (`--stage 1…5`), with region and hash checks |
| `tools/asm/` | Assembly source of the new code (`m8_header.s`, `m8_dnghook.s`) |
| `tools/m8_asm.py` | Assembles one source with clang and checks it against the frozen bytes |
| `tools/m8_wrapdng.py` | Desktop RAW → DNG wrapper; the reference for the in-camera file and its tag template |
| `tools/m8_emutest.py`, `tools/m8_savetest.py` | Emulator tests |
| `tools/m8_reclaim.py` | Ranks unused debug commands as space for new code |
| `tools/armtools.py`, `tools/split_upd.py`, `tools/ghidra/` | Analysis helpers |
| `docs/FINDINGS.md` | Reverse-engineering notes: addresses, formats, hardware test log |
| `docs/DNG_PLAN.md` | Design and staged plan for the in-camera DNG |
| `firmware/`, `sampleraws/`, `work/` | Local only (git-ignored): firmware files, camera samples, scratch |

The staged builds that led to stage 4 are kept for diagnosis: 1 = header canary, 2 = new code present
but not hooked in, 3 = metadata dump, 5 = `.DNG` names.

## Credits

- **Arvid Kuehl** — the original m8raw2dng (m8raw2dng.de), who discovered how to unlock the M8's
  uncompressed RAW mode and turn its dumps into DNGs.
- **romanvail** — first surfaced the uncompressed-RAW mode on the Leica User Forum.
- **botrx555** — [m8raw2dng2](https://github.com/botrx555/m8raw2dng2), whose documentation of the RAW
  format and converter settings this work builds on.
- **Alex Hude** — "How to Hack an Expensive Camera…", the write-up on Leica's update-file format.

Leica and M8 are trademarks of Leica Camera AG. This project isn't affiliated with Leica Camera AG.

## License

The scripts, assembly sources and documentation in this repository are released under the
[MIT License](LICENSE). The license covers only this project's own work, not Leica's firmware, which
is not included and must not be added.
