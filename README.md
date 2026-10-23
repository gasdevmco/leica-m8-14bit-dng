# leica-m8-14bit-dng

Tools for patching the firmware of the **Leica M8** so it can:

1. **Keep "JPG fine+RAW" selected.** This hidden service-mode setting saves the sensor's full 14-bit
   data. Stock firmware hides it and resets it at every power-on; the patch makes it a normal SET menu
   choice that stays selected.
2. **Write a 14-bit DNG in the camera.** In JPG fine+RAW mode, the camera saves a JPG plus a 14-bit
   DNG that Lightroom opens directly, with exposure time, ISO and capture date filled in. The
   camera's own DNG mode is 8-bit (companded); this keeps the full sensor data and needs no
   conversion step.

Optional add-on for either option: **INFO shows Camera stats.** In shooting mode the INFO button
shows the shutter count, battery, temperature and lens code (experimental).

> **Status: tested on one camera.** Both patches and the `--info` add-on run on the author's M8 with firmware 2.014. They are
> experimental, not affiliated with or endorsed by Leica, and flashing modified firmware is at your
> own risk. Read [Safety and recovery](#safety-and-recovery) before flashing anything.

**No Leica firmware is included in this repository**, and none should ever be added: the firmware is
Leica's copyright. You supply your own copy of the stock update file; every script checks its SHA-256
and refuses anything else.

## Contents

- [Why 14-bit?](#why-14-bit)
- [Choose an option](#choose-an-option)
- [Requirements](#requirements)
- [Build your firmware file](#build-your-firmware-file)
- [Flash it](#flash-it)
- [Safety and recovery](#safety-and-recovery)
- [Known limitations](#known-limitations)
- [How it works](#how-it-works)
- [For developers](#for-developers)
- [Testing without a camera](#testing-without-a-camera)
- [Repository layout](#repository-layout)
- [Credits](#credits)
- [License](#license)

## Why 14-bit?

The M8's own DNG mode doesn't store what the sensor recorded. Analysis of its files (details in
[`docs/FINDINGS.md`](docs/FINDINGS.md), "Camera's own 8-bit DNG") shows that before saving, the camera:

- **subtracts the black level and clips everything below it to zero.** In a test frame, about 6% of
  all pixels were exactly 0. The faint noise and detail just above and below black are thrown away.
- **compresses the remaining range to 8 bits (256 levels)** with a square-root curve.

Apart from that it's still raw data: no noise reduction, sharpening or demosaicing.

The 14-bit file keeps every sensor value: 16,384 levels, with black recorded as metadata instead of
cut off. In practice that means:

- **Better shadow recovery.** When you lift dark areas, the 14-bit file has real tonal data and
  natural noise there, instead of clipped, blotchy blacks.
- **Smoother gradients under heavy edits.** The 8-bit file's steps are about as large as the sensor
  noise at base ISO, which hides them in normal use. Strong curves or large exposure pushes can turn
  them into banding in skies and smooth surfaces; the 14-bit file has 64× finer steps.
- **More room for later processing.** Lightroom's denoise and black-level adjustments, or tools like
  m8raw2dng2's dark-frame corrections, work from the untouched data.

At normal exposure with moderate edits, the two look very similar: the difference shows when you
push a file. The cost is size. A 14-bit raw is about 21 MB, twice the camera's DNG, so cards fill
faster and each shot takes longer to save.

## Choose an option

| | Option 1: `raw-menu` | Option 2: `dng` |
|---|---|---|
| What it does | "JPG fine+RAW" appears in SET → Compression and stays selected after power-off | Option 1, plus the camera writes the raw file as a **14-bit DNG** |
| What you get per shot | JPG + the camera's 14-bit `.RAW` dump; convert it with [m8raw2dng2](https://github.com/botrx555/m8raw2dng2) | JPG + a `.RAW` file that **Lightroom opens directly**, with exposure, ISO and date (no conversion) |
| Firmware | 2.014 (camera-tested) | 2.014 (camera-tested) |
| Size of the change | 5 bytes | 5 bytes + 1,634 bytes of new code and data |

Pick Option 1 if you're happy converting files on the computer. Pick Option 2 to open the files in
Lightroom straight from the card.

### Add-on: INFO Camera stats (`--info`, experimental)

Either option can include a Camera stats screen. On a stock M8 the INFO button does nothing in
shooting mode; with `--info` it shows:

| Shots taken | Battery | Temperature | Lens code | Firmware |
|---|---|---|---|---|
| the body's shutter counter | Empty … Full | the body's reading, shown as °C | the code the body reads from the lens mount | 2.014 + INFO |

INFO or SET closes it; every other key is ignored while it is open. The values are the ones Leica's
hidden service page "Body Debug Data" shows; the screen asks the body controller for them the same
way that page does (a read-only request). Service mode is unchanged: after the service button
sequence, INFO still opens the service menu. The screen is in English only. Tested on the author's
camera with both options.

With Option 2, each JPG fine+RAW shot produces:

- `L10xxxxx.JPG`: the camera's normal JPG, used by in-camera review.
- `L10xxxxx.RAW`: 21,049,052 bytes. Its contents are a complete 14-bit DNG (uncompressed CFA, M8
  colour matrices, white level 16383, black level matched to the ISO) with exposure time, exposure program, ISO,
  shutter value, exposure bias, max aperture, focal length and date from the shot. Lightroom opens
  the `.RAW` file as is; for other software, rename the extension to `.DNG`. It still converts with
  m8raw2dng2 too.

With either option, the other Compression modes (JPG fine, JPG basic, DNG, DNG+JPG) are unchanged
stock code. Switching to one of them turns the new code off completely.

## Requirements

- A Leica M8 running firmware **2.014**, the only version these patches are made and tested for.
- Leica's stock 2.014 update file, unmodified: `m8-2_014.upd`, SHA-256
  `99f5254847a92c68086f37b1a4140c359379801b479df12052136abb73f09ed0`. The same file is used to
  return to stock, and a camera on another version can be moved to 2.014 with it.
- Python 3 (any recent version; the one built into macOS works). Nothing else to install.

## Build your firmware file

Download or clone this repository, then run, with the path to your stock file:

```sh
python3 m8patch.py raw-menu  ~/Downloads/m8-2_014.upd     # Option 1
python3 m8patch.py dng       ~/Downloads/m8-2_014.upd     # Option 2
```

Add `--info` to either command for the Camera stats add-on, for example
`python3 m8patch.py dng ~/Downloads/m8-2_014.upd --info`.

The script:

- only reads your stock file and never changes it;
- refuses anything that isn't Leica's unmodified 2.014 file;
- writes the result to `build/m8-2_014-raw-menu.upd` or `build/m8-2_014-dng.upd` (with `--info`:
  `…-raw-menu-info.upd`, `…-dng-info.upd`). It never overwrites an existing file; `--out-dir DIR`
  writes somewhere else;
- writes it only if it is byte-identical to the build tested by the author, and prints its SHA-256
  and the next steps.

| Result | SHA-256 |
|---|---|
| Option 1, 2.014 | `f6589c41a583d1a44fbce77c4acda707640d255acec97a0d2e1ac829c2e70396` |
| Option 2, 2.014 | `55264b11f86dd66e61f1412c5c341afdaa8553ce0d10ade270e52de1f24c944c` |
| Option 1 + `--info`, 2.014 | `fa4ae63a22e2df9749e989ccc570808ac24dabe1a3992593c4c37d27ad6c1c43` |
| Option 2 + `--info`, 2.014 | `32e6854ec0bc451667ef4f8f6b40dfb4c8af406a43db84e94b90abeb380408f8` |

## Flash it

1. **Fully charged battery.**
2. Keep a **second card holding only the stock `m8-2_014.upd`**, ready to roll back.
3. Format a card in the camera and copy the built file from `build/` onto it. **On the card, rename
   it to `M8-2_014.UPD`**: the updater only looks for `M8.UPD` or `M8-x_yyy.UPD`. Rename the copy on the card, not your stock file.
4. Run the camera's normal firmware update, the same as for Leica's own file. The progress bar
   usually pauses around 60% before completing. **Don't touch the battery or card while it runs.**
5. After the restart: SET → Compression → **JPG fine+RAW**. Take a test shot and check it on the
   computer. With `--info`, press INFO in shooting mode: Camera stats appears, INFO or SET closes it.

## Safety and recovery

**What the patches don't touch.** Both builds leave the bootloader (RedBoot, not in the update file at
all), the SD-card updater, startup code, settings load/save, and every other part of the update file
(DSP, FPGA, body controller, fonts, lens table) byte-identical. The patch scripts check this
automatically on every build. The new DNG code runs only while a JPG fine+RAW shot is being saved,
never at startup or during an update. It writes only into the unused last sensor row of the image
buffer, and it range-checks every write. The `--info` code runs only when INFO is pressed in shooting
mode; it opens the screen the way the camera's own service menu does, draws with the camera's own
drawing routines, and changes no settings.

**Rolling back.** The updater accepts the same or an older version, so flashing the stock
`m8-2_014.upd` from the card always returns the camera to stock. The author has done
patched → stock → patched on hardware. Before sending the camera to Leica for service, reflash stock.

**If something looks wrong while shooting** (freeze, error, odd behaviour):

1. **Pull the battery first.** Not the power switch, and don't remove the card. Power-state changes
   and card insert/remove make the camera save its settings; a battery pull saves nothing.
2. Power on, set Compression to **JPG fine** (the new code never runs then), and reflash stock or
   Option 1.

## Known limitations

- **Tested on one camera.** Single shots, power cycles, and continuous shooting until the buffer
  fills (on Option 1) are tested; Option 2 hasn't had the full burst test yet.
- **Option 2's files are named `.RAW`, not `.DNG`.** A build that names them `.DNG` exists (stage 5,
  for developers), but on the camera, review of a JPG + `.DNG` pair then shows only the DNG's file
  name and can't reach the JPG, because these DNGs have no embedded preview. Keeping `.RAW` keeps
  in-camera review working normally.
- **White balance:** Lightroom starts from a fixed daylight balance (Auto and the presets work
  normally); the camera's WB setting isn't carried over yet.
- **Black level** follows the ISO (92 at ISO 160, doubling per step to 1472 at ISO 2500, the rule
  from Arvid Kuehl's m8raw2dng, confirmed on the author's camera). One value for all four colour
  channels; whether green needs a slightly higher value is still open.
- **Not included yet:** lens name, body serial, the Leica MakerNote, and an embedded preview.
- **`.BIA` dark frames** (written for long exposures) also get the TIFF header bytes, but no DNG tags.
  Converters that skip the header, such as m8raw2dng2, aren't affected.
- **Firmware 2.014 only.** Other versions haven't been tested, and the scripts refuse them.
- **`--info`:** the screen is English only, and the temperature is the body's own reading, shown as
  °C. If the camera is switched off while Camera stats is open, the service page "Body Debug Data"
  shows Camera stats instead until the next restart (no effect outside service mode).

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
- **INFO Camera stats (`--info`):** one branch in the GUI's key handler sends INFO (outside service
  mode, where stock ignores it) to new code in the space of two unused Blackfin-test debug commands.
  It opens the service menu's Body Debug Data dialog the way the service menu does, with its own
  drawing and key methods while open, and restores the dialog's methods on close.

Every address, offset and decision, with the evidence for it, is in
[`docs/FINDINGS.md`](docs/FINDINGS.md). The design, staging and risk assessment are in
[`docs/DNG_PLAN.md`](docs/DNG_PLAN.md).

## For developers

`m8patch.py` is a thin front end. The builds come from the tools in `tools/`:

- `tools/m8_rawpatch.py` builds Option 1. `--no-menu` keeps the hidden button sequence for
  selecting RAW but still makes the choice stick.
- `tools/m8_dngpatch.py --stage N` builds the staged DNG builds; Option 2 is stage 4. The others are
  kept for diagnosis: 1 = header canary, 2 = new code present but not hooked in, 3 = metadata dump,
  5 = `.DNG` names. It prints every changed instruction and checks that nothing outside the
  declared regions changed.
- INFO add-on: stage 8 = Option 2 + `--info`, stage 10 = Option 1 + `--info` (both camera-tested).
  Stages 6 (INFO opens the service page) and 7 (an INFO histogram, dropped) are kept as history.
  See `docs/FINDINGS.md`, "GUI".

```sh
python3 -m venv work/venv && work/venv/bin/pip install -r requirements.txt   # Capstone, Unicorn, …
work/venv/bin/python tools/m8_dngpatch.py firmware/stock/m8-2_014.upd firmware/patched/m8-2_014-stage4.upd --stage 4
```

## Testing without a camera

Unicorn-based emulator suites run the real firmware code from the stock file:

```sh
work/venv/bin/python tools/m8_emutest.py              # settings loader + SET menu, stock vs RAW patch
work/venv/bin/python tools/m8_savetest.py --stage 4   # a simulated shot through the real save path, Option 2
work/venv/bin/python tools/m8_savetest.py             # the same for every stage
```

How long they take (Apple M4 Max; expect longer on slower machines). Each prints `N passed, 0 failed`
at the end and prints little before that, so a long silence is normal.

| Command | What it covers | Time |
|---|---|---|
| `m8_emutest.py` | Option 1: settings loader and SET menu | ~1 s |
| `m8_savetest.py --stage 4` | Option 2: one build through the save path | ~2.5 min |
| `m8_savetest.py --quick` | every stage, fewer variants per sample | ~3.5 min |
| `m8_savetest.py` | every stage, all variants | ~9 min |
| `m8_infotest.py` | `--info` builds (stages 6–10): key handling, every key in every GUI state | ~10 s |
| `m8_inforender.py` | `--info` screen: renders it with the camera's drawing code (PNG) | ~2 s |

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
| `m8patch.py` | Build Option 1 or Option 2 (optionally `--info`) from your stock file (start here) |
| `CHANGELOG.md` | Versions of this project, with the build hash of each option |
| `tools/m8_rawpatch.py` | Persistent-RAW patch (2.014) |
| `tools/m8_dngpatch.py` | Staged builds (`--stage 1…10`: DNG 1–5, INFO 6–10), with region and hash checks |
| `tools/asm/` | Assembly source of the new code (DNG: `m8_header.s`, `m8_dnghook.s`; INFO: `m8_info*.s`) |
| `tools/m8_asm.py` | Assembles one source with clang and checks it against the frozen bytes |
| `tools/m8_wrapdng.py` | Desktop RAW → DNG wrapper; the reference for the in-camera file and its tag template |
| `tools/m8_emutest.py`, `tools/m8_savetest.py`, `tools/m8_infotest.py`, `tools/m8_inforender.py` | Emulator tests (durations under [Testing](#testing-without-a-camera)) |
| `tools/m8_font.py` | Decodes and renders the camera's GUI fonts |
| `tools/m8_reclaim.py` | Ranks unused debug commands as space for new code |
| `tools/armtools.py`, `tools/split_upd.py`, `tools/ghidra/` | Analysis helpers |
| `docs/FINDINGS.md` | Reverse-engineering notes: addresses, formats, hardware test log |
| `docs/DNG_PLAN.md` | Design and staged plan for the in-camera DNG |
| `firmware/`, `build/`, `sampleraws/`, `work/` | Local only (git-ignored): firmware files, build output, camera samples, scratch |

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
