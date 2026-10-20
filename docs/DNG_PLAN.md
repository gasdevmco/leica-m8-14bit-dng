# Plan: native 14-bit DNG written by the camera

Status: **firmware phase** (2026-10-20): staged patch tool and emulated save path done, stage 1
(canary) flashed and camera-tested 2026-10-20 (header shows `a500`). Next: stage 2. Builds on the persistent-RAW patch
(see `FINDINGS.md`), which is flashed and working on the author's M8 (patched 2.014).

Goal: when Compression = JPG fine+RAW, the camera writes a real 16-bit DNG (14-bit data) that
Lightroom opens natively as an M8 file — no m8raw2dng2 conversion step, no Lightroom plugin.

---

## 1. Why this looks feasible

- The camera already captures and saves the full 14-bit sensor data in RAW mode (the `.RAW` dump).
- It already has a DNG writer (8-bit, companded via a stored linearization table) and full
  per-shot metadata (it writes EXIF + Leica MakerNote into the JPG).
- The tonight-proven facts (2026-10-19): the camera accepts and runs a modified PXA image;
  RAW mode works outside service mode and at startup; the static analysis map is accurate.

## 2. The RAW dump format (from m8raw2dng2 `docs/PROCESSING.md`, botrx555)

- Exactly **21,049,052 bytes**, little-endian unsigned 16-bit samples.
- **54 header samples (108 bytes)**, then **2,646 rows × 3,976 samples**, then 1 trailing
  stride row (ignored). Check: (54 + 2,647 × 3,976) × 2 = 21,049,052.
- Each row: **3,968 active pixels + 8 padding samples**. Active frame 3,968 × 2,646.
- 14-bit values, max 16,383. CFA mosaic (RGGB default in the converter). No metadata in the file.
- Converter details worth matching: WhiteLevel 16383; optional BlackLevel 92;
  DefaultCropOrigin (2,2), DefaultCropSize 3964 × 2642; UniqueCameraModel "M8 Digital Camera";
  ColorMatrix1/2 (illuminants 17 = Std A, 21 = D65); AsShotNeutral computed per shot;
  aperture estimated from the two light meters for uncoded lenses; MakerNote copied from JPG.
- Optional converter corrections (bias frame `.BIA`, column darkfield, defect-column repair)
  are quality extras — **leave them to post-processing**.
- Sibling checkout: `../m8raw2dng2` — read its source for exact tag values and byte layouts.

## 3. Chosen approach: "wrap the RAW dump as a DNG" (no new DNG writer)

**Rule for all desktop prototypes/tests:** do only what the camera can do. Constant tags,
per-shot values the camera already has (clock, ISO, shutter, WB preset, lens), no pixel
processing, no per-frame analysis. Constants may be measured offline (e.g. black level from a
dark frame) and baked in. Anything else is analysis only and never goes into the output file.

TIFF only needs an 8-byte header at offset 0; the IFD (tag directory) can live anywhere,
including **after** the pixel data. So:

1. Overwrite the first 8 bytes of the 108-byte RAW header with a TIFF header
   (`II*\0` + offset of IFD0 at end of file).
2. Pixels stay where they are: StripOffsets = 108, ImageWidth = **3,976** (padding included),
   ImageLength = 2,646 (or 2,647 and crop), BitsPerSample 16, uncompressed, single strip.
   **DefaultCrop hides the 8 padding columns** (and edge pixels), so the padding is harmless.
3. Append ~2 KB: IFD0 + EXIF sub-IFD + value data.
4. Name the file `.DNG` instead of `.RAW` (probably a small change; verify the camera's own
   playback/file browser doesn't choke on it — it may expect only its own DNG/JPG).

Advantages: no pixel processing, no memory copies, independent of where the 14→8-bit
companding happens (Blackfin/FPGA/ARM — doesn't matter, the RAW path already has 14-bit data).

Alternative considered: modify the existing 8-bit DNG writer to 16-bit (point it at the 14-bit
buffer, BitsPerSample 8→16, drop the linearization table, double the data size). Cleaner but
harder and depends on where companding happens. Keep as fallback.

## 4. Tags

**Constant (template baked into firmware):** NewSubFileType, ImageWidth/Length, BitsPerSample 16,
Compression 1, PhotometricInterpretation 32803 (CFA), SamplesPerPixel 1, PlanarConfiguration 1,
CFARepeatPatternDim / CFAPattern, DNGVersion / DNGBackwardVersion, UniqueCameraModel
"M8 Digital Camera", Make/Model as the camera's own DNGs, WhiteLevel 16383, BlackLevel 92,
DefaultCropOrigin/Size, ColorMatrix1/2 + CalibrationIlluminant1/2, Orientation, StripOffsets 108,
StripByteCounts, RowsPerStrip.

- **Copy ColorMatrix/Calibration tags (and Make/Model strings) byte-for-byte from a real M8 DNG
  out of this camera**, so Lightroom's built-in M8 profiles (Adobe Standard for M8, Adobe Color,
  etc.) render identically to normal M8 files. Lightroom picks profiles by UniqueCameraModel.
  (Note: Adobe may not ship "Camera Matching" profiles for the M8 — check Profile Browser on a
  normal M8 DNG; whatever appears there will appear for these files too.)

**Per shot (filled in by new code from data the camera already has for the JPG):**
exposure time, ISO, DateTime/DateTimeOriginal, lens / focal length, body serial, Software
(firmware string), optionally FNumber (light-meter estimate) and the Leica MakerNote.

**White balance (decided: keep it simple, user adjusts in Lightroom):** AsShotNeutral must still
be present or Lightroom opens the image strongly green. Use either a fixed daylight neutral or a
small constant table mapped from the camera's WB preset (Auto/Daylight/Tungsten/Fluorescent/
Cloudy/Shadow/Flash/Kelvin). No per-shot pixel statistics.

## 5. Firmware constraints (verified)

- **PXA image cannot grow**: load base 0x20000, image ends 0xF1BB0; `.bss` starts exactly at
  0xF1BB0 (to 0x1837E0) and stacks sit at 0xF1C30–0xF2CB0 (from the reset handler). Appending
  code would be overwritten/zeroed at boot.
- Budget needed: ~2 KB template + a few hundred bytes of code (≤ ~3 KB).
- **Make room by reclaiming unused debug/factory code** (verify no normal-path callers first).
  Candidates from debug-shell strings: "create a rgb test image", "create a bayer pattern test
  image", "bicubic Image Resizing", "write image as jpeg with IPP", memory dump/test commands
  (`bf_memtest1/2`, `rrmem`, `rree`), etc. ~19 KB of 0x00 runs exist but are likely real data
  tables — don't assume they're free.
- New code: **ARMv5TE ARM mode (Intel XScale)**, no Thumb-2, no VFP/NEON, APCS frame style like
  the surrounding code. Assemble/compile with the target set explicitly and **disassemble every
  instruction of the output** to verify.
- Never touch RedBoot, FSL, M16C, FPGA, or PXA boot/update paths. The SD updater lives in PXA,
  so a startup crash would block SD recovery.

## 6. Safety design

- New code runs **only when saving a RAW shot**, never at startup. Worst realistic case:
  bad/unreadable file or a freeze while saving (battery pull), possibly card filesystem damage
  (reformat). Camera still boots and accepts stock firmware from SD.
- Test on scratch cards first.
- Keep `firmware/stock/m8-2_014.upd` and the current `firmware/patched/m8-2_014.upd` as rollbacks.
- Same verification discipline as the RAW patch: minimal change, byte diff vs base, disassembly
  of every changed region, document in FINDINGS.

**Why these rules (2026-10-19):**
- *Mode choice:* hook JPG fine+RAW, not DNG+JPG. The RAW path already copies 14-bit data unchanged
  (plain memcpy); we change only ~760 bytes (header + template in the junk trailing row), so file
  size, file creation, buffers and timing stay as they are. Stock firmware never uses this mode, so
  a bug can only affect it, and the other modes remain untouched stock code — switching Compression
  is an instant kill switch. Changing the DNG path would mean replacing companding/crop, doubling
  the file size (file creation, buffers, burst, shots-remaining), rewriting the camera's own DNG
  layout that its playback reads, and losing the known-good mode.
- *Bootloader / updater:* RedBoot is in flash and not in the .upd; new code never writes flash. The
  SD updater code stays byte-identical (diff check). New code runs only while saving a RAW shot, so
  it cannot stop the camera booting or finding a .upd. A RAM-corrupting bug causes a freeze or crash
  that a battery pull clears.
- *The one persistent-damage path:* corrupt RAM settings → camera saves them to EEPROM with a fresh
  CRC → next boot loads garbage (loader checks only size, version, CRC) → if that crashes startup
  *before* the SD update check, recovery needs more than a card. Closed by: bounded writes with an
  in-code range check, emulator write-bounds test. Boot order checked (FINDINGS "Boot order"): the
  update dialog runs after settings load, so the path is real in principle; but settings live at
  0x14C910, ~37 MB from the DMA buffer our code writes, and a freeze → battery pull saves nothing.
  Settings are saved on power-state changes (off/standby/on), card insert/remove (GPIO95, likely
  card-detect) and after a boot with a card inserted — hence: after an anomaly, pull the battery
  first, never use the power switch or remove the card first.
- *Other worst cases:* unreadable file; damaged filesystem on the shooting card (reformat). The
  recovery card is kept separate so it cannot be damaged this way.

## 7. Leads in the firmware (starting points, 2.014 addresses = 2.024)

- `"\DCIM\100LEICA\L1000001.RAW"` at 0xD6578, referenced at 0x28EA8 (debug "load RAW file" path,
  "Raw-Header: %d Byte", "Failed to load RAW File") — shows which file API the firmware uses.
- `"DNG"` string 0xD6570 referenced at 0x28E5C, 0x39224, 0x3CDFC, 0x41370, 0x46158, 0x46404;
  `"JPG"` 0xD6638 at 0x28FB0, 0x39238, 0x3CE2C, 0x4139C, 0x4613C, 0x46450 — file naming/saving.
  0x3CA5C is a capture-store routine that picks the "DNG"/"JPG" extension (DMA/store context).
- 0x2A48C prints per-buffer save state ("SaveState: JPG: %s, DNG: %s, RAW: %s") with per-buffer
  flags at `[[0xD421C]] + 0x1669C / 0x166A0 / 0x166A4` (JPG/DNG/RAW) — find who sets the RAW flag.
- 0x33AB8 reads compression (+0x2C) and maps it to buffer flags (bitmask logic around 0x33F68);
  it also uses "%Y:%m:%d %T" → likely builds per-shot metadata (EXIF date). Called from 0x28B68, 0x343A0.
- 0x47574: info-screen text for compression ("DNG + %s").
- Settings profile struct: base `[[0xD4230]]`, 0x50-byte records, +0x1C field base; WB etc. live
  in the same record (offsets in the SET-menu loader 0x4ED94 / saver 0x4E4D4).
- Debug shell commands exist (e.g. "go through images on card", "load image from DSP") — may help
  locate file I/O helpers.

## 8. Work plan (do in Claude Code in VS Code, one task per session)

0. Inputs into the project folder: one RAW+JPG pair from the camera and one normal M8 DNG.
1. **Unicorn emulator harness** (`pip install unicorn capstone`): load PXA at 0x20000, stub RAM,
   run individual functions. First use: confirm the RAW patch logic on stock vs patched
   (settings loader 0x2184C with compression=5; SET-menu loader 0x4ED94 with service mode off).
2. Read `../m8raw2dng2` source; write a desktop Python script that turns RAW+JPG into the
   **wrapper-style DNG** (8-byte header + appended IFD, pixels untouched). Verify it opens in
   Lightroom with correct colour. This proves the format before any firmware work.
   **In progress (2026-10-19):** `tools/m8_wrapdng.py` (RAW only, no JPG metadata yet). Constant
   template 734 bytes (IFD0 34 tags + EXIF IFD), per-shot slots DateTime / AsShotNeutral /
   DateTimeOriginal. Sample `sampleraws/L1031901.RAW` → DNG decodes correctly in LibRaw
   (RGGB, crop 2,2 3964×2642, padding hidden by DefaultCrop).
   **Layout changed (2026-10-19, after save-path analysis):** IFD template now goes into the
   trailing sensor row (offset 21,041,100) instead of being appended — file size unchanged, matches
   the planned in-camera hook (FINDINGS "Image save path"). **Lightroom re-test OK (2026-10-19):
   opens, metadata shows 14 bits per channel** (from WhiteLevel 16383; BitsPerSample is 16).
   → Desktop format proof complete for RAW-only; remaining for step 2: JPG-derived per-shot
   fields once a RAW+JPG pair is available.
   **Per-shot EXIF added (2026-10-19):** template 902 bytes, 11 slots (DateTime ×3, ExposureTime,
   ExposureProgram, ISO, ShutterSpeedValue, ExposureBias, MaxAperture, FocalLength, AsShotNeutral),
   each mapped to its offset in the camera's metadata struct S (`SHOT_FIELDS`). Desktop stand-in:
   values read from the same-stem JPG. `sampleraws/L1031902.DNG` carries 1/1000 s, ISO 160, A mode,
   17:32:24. MakerNote deliberately left out (v1). **Lightroom OK (2026-10-19): shutter speed and
   ISO shown for the 14-bit DNG.** → Desktop prototype = complete v1 file; remaining work is firmware.
   **Lightroom (2026-10-19, appended layout): imports, M8 built-in profile active, Auto WB works.** Without
   BlackLevel, Lightroom's Auto gave odd colours: the ~92 pedestal (darkest block R 92.6 / G 96 /
   B 97) was treated as light and tinted magenta by the WB gains. BlackLevel 92 fixed it → now
   the default (`--black 0` omits it). Open question: per-channel black (green slightly high?)
   — settle with a lens-cap dark frame; result would be baked in as constants, never measured per shot.
3. ~~Find the RAW file write path~~ — done (FINDINGS "Image save path", "Per-shot metadata").
4. ~~Choose and verify reclaimable debug code space~~ — done (`ldimg`, 1,620 B; m8_reclaim + Ghidra).
5. **Build the complete solution locally, then flash it in stages** (agreed 2026-10-19):
   - One patch source, `tools/m8_dngpatch.py --stage N`, generates every staged build (like
     `m8_rawpatch.py --no-menu`). The full design is built and emulated first; each flashed build
     is a slice of that tested whole.
   - Pieces: header rewrite at 0x3CE48 (or one-instruction hook if it won't fit), hook at 0x3C6A8
     (last-block branch), routine + template in `ldimg` (stub kept at its entry), .BIA gate
     (job flag +0x21A), bounds check on the destination, extension "RAW" → "DNG" (0xD6590).
   - Emulator before any flash: simulated shutter press through the real save path
     (0x3C904 → 0x3C5A4 → hook) on `sampleraws/L1031902.RAW` producing a full DNG, compared
     byte-for-byte with `m8_wrapdng.py` output; write-bounds check (writes only in the DMA buffer
     and own stack); camera DNG reader (0x6DDAC/0x6DB74) run on the result; existing 126 tests;
     declared-regions diff vs the current flashed build.
   - Stages (one per flash, each re-emulated before flashing):

     | Stage | Flashed change | Proves |
     |---|---|---|
     | 1 | Canary: one header constant | We control file contents |
     | 2 | Routine + template in `ldimg`, hook **off** | Idle test: nothing else uses that space |
     | 3 | Hook on, copying job metadata (~256 B) into the trailing row | Metadata offsets, from the camera |
     | 4 | Hook on, real template + TIFF header, still `.RAW` | First in-camera 14-bit DNG |
     | 5 | Extension → `.DNG` | Playback copes (pairs and lone DNG) |
   - Caveat: what early stages show can change later pieces (e.g. stage 3 offsets) — the full
     build is a revisable plan, not a frozen product.
   - **Progress (2026-10-20):** `tools/m8_dngpatch.py --stage N` (stage 1 built; 2–5 refused as
     not built yet) and `tools/m8_savetest.py` (emulated save path, FINDINGS "Emulated save path")
     done. Stock reproduces both camera RAWs byte for byte through the real store routine, DMA
     handler and RAW producer. Stage 1 (`3f84b34a…`) passes 32/0: only file byte 6 changes.
     Stage 1 is flashed ahead of the full design because it is independent of it: one immediate in
     the header block, which stage 4 rewrites anyway.
   - **Stage 1 on the camera** (rules in §6 / CLAUDE.md; rollback drill already done):
     1. Full battery. Recovery card with only the stock `.upd` set aside. Update card with only
        `firmware/patched/m8-2_014-stage1.upd`, renamed `M8-2_014.UPD`. Flash as usual.
     2. After restart, on the scratch card: SET still shows JPG fine+RAW; take one single frame.
        Then one frame each in JPG fine and DNG (untouched modes), and switch back to JPG fine+RAW.
     3. Power-cycle, one more JPG fine+RAW frame.
     4. Desktop: `xxd -l 8 L10xxxxx.RAW` must show `ffff 0c00 3600 a500` (stock: `… 0700`);
        file size 21,049,052; m8raw2dng2 and `m8_wrapdng.py` convert it; the JPG and the DNG-mode
        file look normal.
     5. Pass → leave stage 1 installed until stage 2 (it is harmless). Anomaly → pull the battery
        first; rollback = flash `firmware/patched/m8-2_014.upd` (`f6589c41…`).
     **Result 2026-10-20: pass** (FINDINGS "Hardware results"); stage 1 stays installed.
   - **Stages 2–5 built and emulator-tested (2026-10-20)** — FINDINGS "Staged DNG builds". The
     header rewrite fits in place (no hook). Stage 5 changes the store routine's literal, not the
     shared "RAW" string. The emulated stage-4 file equals the Lightroom-tested prototype DNG byte for
     byte. Next on the camera: stage 2 (idle test), same procedure as stage 1 plus the burst test;
     the RAW header should still read `a500`.
6. Per stage on the camera: scratch card, full battery, single shots, power cycle, Lightroom
   import, then bursts; after any anomaly pull the battery first.

**Before stage 1 (no new firmware needed):** ~~rollback drill~~ (done 2026-10-20);
scratch-card playback test with our DNG (pair + lone copy) on the current build:
- Card: scratch card formatted in camera, one throwaway shot (creates `DCIM/100LEICA`). Copy
  `sampleraws/L1031902.JPG` + `L1031902.DNG` (pair) and a copy of the DNG as `L1039999.DNG`
  (lone) into `DCIM/100LEICA/` with `cp -X` (or `dot_clean` the card: no macOS `._` files). Eject.
- Camera: playback → pair (expect JPG preview; open info screen) → lone DNG (the real test) →
  delete the lone DNG in camera → power-cycle with card in → one normal shot.
- Freeze → pull battery, remove card, boot without it. Lone DNG misbehaves → add a small thumbnail
  to the template before stage 5.
- **Result 2026-10-20:** with our DNG (and RAW) next to the camera's JPG, playback shows the preview
  normally. **Lone DNG (no JPG): no crash; playback shows the filename in the centre instead of a
  preview** — graceful fallback, acceptable because the camera always writes the JPG alongside.
  Stage-5 risk retired; an embedded thumbnail is an optional nice-to-have, not required. macOS (Quick Look / sips) also decodes our DNG correctly
  at 3964×2642 (third decoder after Lightroom and LibRaw); Finder icons look dark because the
  scene is mostly dark.

**Deferred until stage 4 works (tuning, not implementation):**
- [ ] **Lens-cap dark frames** for the black-level constants. Lens cap on, JPG fine+RAW,
  ~1/250 s, one frame each at ISO 160 and ISO 2500 (ideally also 320/640/1250), keep the
  JPGs. Copy RAW+JPG pairs into `sampleraws/`. Answers two questions:
  (a) is black the same in all four CFA channels (green slightly high?) and
  (b) does it scale with ISO (original m8raw2dng writes 92 × gain 1/2/4/8/16; m8raw2dng2 a
  flat 92). Result: a ≤5-entry constant table indexed by ISO, baked into the template.

Optional tooling: Ghidra on the Mac (processor ARM:LE:32:v5t, base 0x20000) for decompilation;
REA (only from github.com/morluto/rea or npm `rea-agents`) if wanted.

## 9. Estimates (updated 2026-10-20, after stage 1 passed on the camera)

| Question | 10-19 end | 10-20 emulated | **10-20 after stage 1** |
|---|---|---|---|
| Camera writes a 14-bit DNG Lightroom opens (fixed date/WB) | ~85% | ~89% | **~91%** |
| Same, with full per-shot metadata (exposure, ISO, date, lens, WB preset) | ~80% | ~82% | **~83%** |
| No brick needing Leica/serial (whole project) | ~98% | ~98% | **~98.5%** |
| Bootloader and SD updater untouched | ~99%+ | ~99.9% | **~99.9%** (unchanged in every build so far; tool-checked) |
| Can always reflash stock from SD | ~99% | ~99% | **~99%+** (round trip tested; updater accepted a code-modified build) |

Per stage (first attempt / eventually, after fixes):

| Stage | Passes first try | Eventually | Main risk |
|---|---|---|---|
| 1 canary | — | **done 2026-10-20** | — |
| 2 `ldimg` filled, hook off (idle test) | ~95% | ~98% | a runtime-computed call into `ldimg` (no static or Ghidra reference found) |
| 3 metadata dump | ~85% | ~97% | offsets in S wrong or data not yet filled when the last block runs — the dump itself shows which |
| 4 first in-camera DNG (`.RAW`) | ~75% | ~92% | header rewrite fit; cache coherence of the template written into the DMA buffer |
| 5 `.DNG` extension | ~95% | ~98% | card scan/playback with many DNGs (lone and paired DNG already tested) |

What moved it (10-20):
- Emulated save path reproduces both camera RAWs byte for byte through the real firmware code,
  so later stages can be compared byte for byte before flashing; declared-regions check automatic.
- **Stage 1 on the camera:** the header bytes came out exactly as emulated — the static map and
  the emulator predict the hardware, the JPG fine+RAW save really runs this code, and the update
  path accepts and boots a code-modified build. Other modes unchanged.
Still limiting (needs running code): header rewrite fitting the TIFF header (0x4949, 0x0FCC,
0x0141 are not ARM immediates), DMA/cache coherence in the last block, metadata offsets in S,
unknown runtime callers of `ldimg`. Playback with `.DNG` is retired (tested 2026-10-20).
Next movers: stage 2 idle test (→ brick ~99%), stage 3 metadata dump (→ metadata ~88% if the
offsets hold), stage 4 (the big one: → ~97% if it opens in Lightroom).

- Effort: a few weeks of evenings; most time in steps 3 and 5.
- CPU cost: negligible (8-byte header + ~750-byte template into the trailing row). Bottleneck stays the SD card write
  (~21 MB + JPG per shot), same as RAW mode today. Per-pixel extras (per-shot WB, column
  correction) would cost ~1–2 s per shot on the ARM — deliberately out of scope.

## 10. Practical notes

- File size ~21 MB + JPG per shot (vs ~10 MB DNG): fewer shots per card, longer saves,
  smaller burst. Leica's 2006 reasons for 8-bit DNG were size/speed/card capacity, not safety.
- Continuous shooting in JPG fine+RAW until the buffer fills: passed 2026-10-20 (stage-1 build).
  Baseline for repeating the same burst test on each later stage.
  M8 spec ~2 fps normal; RAW slower. Recommend single frames until tested.

## 11. Related ideas parked

- **Menu emulator**: level 1 = run patched functions in Unicorn (planned above); level 2 = full
  menu subsystem rendered to a framebuffer (weeks); level 3 = full-system QEMU (months, overkill).
- **Lightroom Classic plugin** wrapping m8raw2dng2 (Lua; menu command → run converter → add to
  catalog). Becomes unnecessary if in-camera DNG works.
- **Sharing**: never publish .upd files (Leica copyright). Share scripts + docs only; patch script
  verifies stock hashes. Forum post draft exists (in chat 2026-10-19): one-camera-tested,
  at-own-risk, rollback steps, reflash stock before Leica service; credit Arvid (m8raw2dng),
  botrx555 (m8raw2dng2), Alex Hude. Strip personal lines from docs before making a public repo.
