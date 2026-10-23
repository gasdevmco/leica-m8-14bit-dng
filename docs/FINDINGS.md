# Leica M8 firmware — findings

Everything below was found by static analysis of the stock update files. Hardware results
are marked **[tested]**.

## Hardware results

- **2026-10-19 [tested]** Patched 2.014 (`f6589c41…`) flashed on the author's M8 (was stock 2.014).
  Update ran normally (progress bar paused around 60%, then completed) and asked for a restart.
  Camera boots normally; SET → Compression lists JPG fine+RAW; selection survives power-off
  and sleep/wake; RAW + JPG files are written and convert with m8raw2dng2.
- **2026-10-20 [tested]** **Stage 4 (`3b451b4d…`) flashed: the camera writes a 14-bit DNG.**
  Update and boot normal. `fromcameraimports/L1031916.RAW` (JPG fine+RAW): header `4949 2a00 cc0f
  4101`; m8_wrapdng.check passes (35 tags); the 902-byte template arrived intact; LibRaw decodes it
  (RGGB, white 16383, black 92); bottom image rows clean (no cache artefact). Per-shot slots vs the
  JPG: ExposureTime 2777/1000000, ExposureProgram 3, ISO 160, ShutterSpeedValue, ExposureBias,
  MaxAperture, FocalLength **all match → those S offsets are confirmed**. **Date wrong**:
  `:10:21 08:58:15` + 4 stray bytes — the date string is at **job+0x20 (S+0x1C)**, not S+0x20.
  Fixed in m8_wrapdng.SHOT_FIELDS (3 bytes of the slot table). DNG-mode (L1031918) and JPG files
  normal.
  **Lightroom opened the camera-written file** (copy named L1031916.DNG). Burst test on stage 4 not
  done yet. Corrected builds: stage 4 `59aff4a3…`, stage 5 `d9a94feb…` (differ from the flashed
  stage 4 only in the three date-slot source bytes 0x24 → 0x20 at 0x28C9A/0x28CBA/0x28CC2).
- **2026-10-21 [tested]** **Stage 4 with BlackLevel per ISO (`55264b11…`) flashed — current build.**
  ISO series L1031949–53: BlackLevel 92/184/368/736/1472 as intended, all files valid (35 tags);
  Lightroom: blacks correct at every ISO (previously lifted/washed out at high ISO). White balance
  still opens at the fixed daylight value (known, parked).
- **2026-10-20 [tested]** **Stage 5 playback problem → back to stage 4.** In-camera review of a
  camera-written stage-5 pair (JPG + our `.DNG`) shows the DNG's filename in the centre and does not
  navigate to the JPG — unlike the earlier test with Mac-copied files. Our DNG has no embedded
  preview. Decision: run stage 4 (`59aff4a3…`, date-fixed; same content, `.RAW` name). **Lightroom
  opens the `.RAW` file directly** (no rename needed). Recovery check on `59aff4a3` repeated: pass.
- **2026-10-20 [tested]** **Stage 5 (`d9a94feb…`) flashed — goal reached.** JPG fine+RAW writes
  `L1031919.JPG` + `L1031919.DNG` (21,049,052 bytes, 14-bit). Structure check passes (35 tags),
  LibRaw decodes it, every per-shot slot equals the JPG's EXIF **including the date** (2026:10:20
  21:13:45; date fix confirmed), ExposureTime 1333/1000000, ISO 160. **Lightroom imports it
  directly.** DNG-mode (L1031921) and JPG-only (L1031920) frames normal. Not yet checked: on-camera
  playback/delete of a stage-5 pair, burst, long exposure (.BIA).
- **2026-10-20 [tested]** Continuous-shooting test in JPG fine+RAW until the buffer filled
  (scratch card, on the stage-1 build): passed. Burst files not kept.
- **2026-10-20 [tested]** Rollback drill, first half: from the patched 2.014 build, flashing stock
  `firmware/stock/m8-2_014.upd` worked without issue; reflashing patched `f6589c41…` also worked,
  RAW setting back and working. **Round trip complete.**
- **2026-10-20 [tested]** Stage-1 canary build (`3f84b34a…`) flashed; updated and booted normally.
  Files in `fromcameraimports/`: L1031903 JPG fine+RAW pair, L1031904 DNG mode, L1031905 JPG fine.
  RAW header `ffff 0c00 3600 a500` — u16[3] = 0xA5 is the only header change vs stock, exactly as
  emulated; size 21,049,052, pixels 122–16383. RAW converts with m8_wrapdng.py and m8raw2dng2
  (both decode in LibRaw); DNG-mode and JPG files normal. **The camera runs our header code: we
  control the RAW file contents.** Camera clock reads 2026-10-21 08:17 (a day ahead of the Mac).

## Stock files

| File | Version | Build date | SHA-256 |
|---|---|---|---|
| `firmware/stock/m8-2_014.upd` | 2.014 | 30 May 2011 | `99f5254847a92c68086f37b1a4140c359379801b479df12052136abb73f09ed0` |
| `firmware/stock/m8-2_024.upd` | 2.024 | 23 Jul 2014 | `95dbb319ba6b2d675437853402a8bbabe8e96796b74a52ed325fa5c8b3f68acb` |

2.014 came from TousLesDrivers (a mirror). It was checked against 2.024: same container
layout and rules, byte-identical FPGA, M16C, FSL, fonts, frame-line images and
translations. Of the 859 KB PXA image only 531 bytes differ: build dates, version
strings, new lens names in 2.024, and one ~400-byte code change at 0xAE8BC.

## Update file format (`.upd`)

- A Doom-style **PWAD** container: `"PWAD"`, lump count, directory offset; 16-byte directory
  entries (offset, size, 8-byte name). Names may carry junk after the NUL.
- Unencrypted and uncompressed. **No checksum over the file**; it ends exactly at the last lump.
- Lumps: `RULES` (XML board-ID rules), `LUTS` (nested PWAD: GAMMA, GAIN, LEICA, BLEMISH,
  WREF, OBJ = lens table, VERSION), `PXA` (main ARM code), `BF` (Blackfin DSP),
  `GUI` (nested: TRANS, IMAGES = JPEG frame lines, FONT1, FONT2), `M16C` (body controller,
  S-records), `FPGA` (Xilinx), `FSL` (first-stage loader).
- Not in the file: **RedBoot** (main bootloader), per-camera calibration (CCD calib,
  TWOCHAN, AWB, WREF, BLEMISH, CCDSNR stored in flash with their own CRC32), user settings.

## Updater behaviour (PXA)

- Scans the SD card for `M8.UPD` or `M8-x_yyy.UPD`; if several, picks the highest number.
- Reads the version string from the file's PXA lump; only rejects 0.0.
- **No comparison with the installed version** — same-version reinstall and downgrades are allowed
  (matches owner reports of 2.024 → 2.014 downgrades).
- Gates: RULES board IDs (ccd 0, ccdboard 0–2, ctrlboard 0, m16c 0), battery level, user confirmation.
- The SD updater lives in the PXA app → **a PXA that crashes early in boot blocks SD recovery**
  (RedBoot serial / Leica service would then be needed). Never touch boot/update paths.

## PXA image layout

- Intel XScale (ARMv5TE), ARM mode, load base **0x20000**, image ends at **0xF1BB0**.
- `.bss` (zeroed) starts at exactly 0xF1BB0 and runs to 0x1837E0; stacks at 0xF1C30–0xF2CB0.
  → **The image cannot grow.** New code must go into existing space (e.g. unused debug commands).
- eCos + RedBoot FIS flash filesystem ("fisfs"). Lots of debug strings and a debug shell.
- Settings: profile records of 0x50 bytes; field base +0x1C; **compression at +0x2C (u16)**.
  Values: 0 DNG, 1 JPG fine, 2 JPG basic, 3 DNG+JPG fine, 4 DNG+JPG basic, **5 JPG fine+RAW**.
  Name table at 0xEF5A8.
- Settings are saved to EEPROM as one 0x400-byte block with a checksum (writer 0x2105C,
  reader in 0x2184C); no per-field filtering.

## Service mode ("button dance")

- Service flag = RAM word at `[[0xD4220]] + 0x254A0` whose low 24 bits equal **0x010304**,
  built byte by byte by the key handler at 0x44C68 / 0x44E34; cleared by 0x40410 on a wrong key.
- Gate function **0x403F0** returns 0 when service mode is active. Its only callers:
  timing log (0x3D564), the dance handlers (0x44C84, 0x44EB8, 0x44F50, 0x44F60),
  SET-menu loader (0x4EEC8, 0x4F0C0). **Capture/save code never checks it.**
- `+0x2548F` byte = "debug menu open" (blocks normal key handling); unrelated to capture. (Was noted
  as +0x2558F until 2026-10-23: a typo; 0x44F7C-0x44F88 and camInfoMenu 0x654E4 use 0x25400 + 0x8F.)

## Why RAW resets

1. **Boot/wake** — settings loader (0x2184C, after "Could not load Settings from eeprom"):
   `if compression == 5 → set 1` at 0x21914–0x21978. No service check. *This is the observed reset.*
2. **SET menu load** (0x4ED94): entry count = 5 normally, 6 in service mode (0x4EED4);
   case 5 without service mode writes 1 back to the profile (0x4F0C8 → 0x4F104).
- Menu save routine (0x4E4D4): selecting entry 5 writes 5 (0x4E8C0), no service check.

## Persistent-RAW patch (`tools/m8_rawpatch.py`) — 2.014 build [tested]

Identical code at identical addresses in 2.014 and 2.024 (file offsets differ by 4).

| | Address | Stock | Patched | Effect |
|---|---|---|---|---|
| P1 | 0x2191C | `0800000a` beq | `0000a0e1` nop | boot no longer resets RAW |
| P2 | 0x4F0C8 | `beffff0a` beq | `beffffea` b | SET menu no longer resets RAW |
| P3 | 0x4EED4 | `0530a013` movne #5 | `0630a013` movne #6 | RAW always listed (no dance) |

`--no-menu` applies P1+P2 only. Output differs from stock in exactly 5 bytes of the PXA lump.

| Patched file | SHA-256 |
|---|---|
| `firmware/patched/m8-2_014.upd` | `f6589c41a583d1a44fbce77c4acda707640d255acec97a0d2e1ac829c2e70396` |
| `firmware/patched/m8-2_024.upd` | `6c411873891a965d03ad83f1bcb9b2030329595a4d00848cf369eaec45a9c94e` (historical; never camera-tested) |

**2026-10-21: 2.024 is no longer supported.** It was never tested on a camera, so the user script
(`m8patch.py`) and `tools/m8_rawpatch.py` accept only the stock 2.014 file. The 2.024 notes in this
file are research (version comparison, known issue), not a statement of support.

Test plan: full battery, card formatted in camera, only the patched file on it. Select
JPG fine+RAW, shoot, power-cycle, confirm SET still shows it, convert with m8raw2dng2.
Once, on a scratch card, test continuous shooting until the buffer fills. Rollback = flash stock.

## Emulator test (`tools/m8_emutest.py`) — 2026-10-19

Unicorn harness that runs the real settings loader (0x21848) and SET-menu loader (0x4ED94)
from the PXA lump of stock, patched and an in-memory `--no-menu` build of 2.014. Only the
listed firmware functions execute (defaults 0x20F9C/0x21724–0x21848, crc32 0xBD0B4, gate
0x403F0, the two loaders); EEPROM read, printf, 0x4568C, OS calls 0xB485C/0xB48A0/0xB48BC,
menu items 0x9AF4C/0x9AF84 and two menu vtable calls (+0x1C, +0x48) are stubs; any other
call fails the run. EEPROM blocks are built with the firmware's own defaults and crc32.
Result: **126 passed, 0 failed**. Swapping stock/patched makes 24 checks fail (sanity check).

- Loader: stock turns compression 5 → 1 (store at 0x21978 executes); patched and no-menu keep 5.
  Values 0–4 unchanged in all builds. Stock vs patched settings block differs only in the
  compression byte, with identical call traces (no extra EEPROM writes).
- Bad CRC or failed read → factory defaults (profile 0, JPG fine) in all builds;
  read failure prints "Could not load Settings from eeprom".
- Menu (entries, selected, profile compression after), compression 5:
  stock (5, 1, 1) / service (6, 5, 5); patched (6, 5, 5) either way; no-menu (5, 5, 5) / service (6, 5, 5).
- Settings block layout: u16 [0] = profile index, u16 [2] = override index (0xFFFF = use [0]),
  +8 version (0xC), +0xC crc32 (init 0, no final xor, computed with the field zeroed),
  +0x10 size (0x1FC), six 0x50-byte profiles at +0x1C. Factory default: [0]=0, [2]=0xFFFF.
- **Profile 0 is rebuilt from defaults (0x20F9C at 0x21898) on every boot, patched or not**,
  so RAW (and every other setting) only persists in profiles 1–5. The test camera keeps RAW,
  so it is presumably not on profile 0; which menu profile maps to index 0 is not yet known.

CPU model: PXA270 (`ctl_set_cpu_model`, MIDR 0x69054110, Intel XScale). Unicorn/QEMU does
**not** model ARMv5 rotated unaligned LDR (default and PXA270 both return v7-style results), so the
harness fails any misaligned 2/4/8-byte access instead (stricter than hardware; verified it fires).
Stock code paths: 126/126 pass, no misaligned accesses.

Run: `work/venv/bin/python tools/m8_emutest.py [-v]` (venv: `python3 -m venv work/venv &&
work/venv/bin/pip install unicorn capstone`). The same harness is the base for testing DNG code.

## Image save path (static analysis, 2026-10-19) — DNG work Phase 1, in progress

- **0x3CA5C = store routine for every image file** (only reference: pointer at 0xEF110).
  r7 = capture context, job struct = `[ctx+0x4634]`. File type chosen from job flags:
  `+0x21A` byte → "BIA", `+0x150`==1 → "DNG" (type 2), `+0x14C`==1 → "JPG" (type 1),
  `+0x154`==1 → "RAW" (type 0); type stored at `ctx+0x4638`. Extension strings: "RAW" = 0xD6590
  (tail of `\DCIM\100LEICA\L1000001.RAW`), "BIA" 0xD7CD8, "DNG" 0xD6570, "JPG" 0xD6638.
  0x8817C builds the file name; 0x90F9C(out, type, size) **returns the image geometry** for the
  type (8 bytes from a cached table; RAW = 3976 samples × 2647 rows → header u16 14/15, 10/11) —
  corrected 2026-10-20, it does not create the file. The file is opened via the vtable call at
  0x3CC20 (`[ctx+0x4210]` +8), returning 0 on success. Size args from job: RAW +0x16C, DNG +0x164,
  JPG +0x168. 0xCACB0 = unsigned modulo (ring wrap).
- **The 108-byte RAW header is written by PXA CPU code**, 0x3CE48–0x3CF0C, into the output ring
  buffer: u16 [0]=0xFFFF (`mvn r0,#0` at 0x3CE80 / `strh` 0x3CE94), [1]=0x0C (0x3CE9C), [2]=0x36
  (0x3CE98), [3]=7 (0x3CEA0), [10]/[11] and [14]/[15] from ctx+0x422C / 0x4228 bytes, [16..18] from
  job+0x210, bytes 0x2C–0x6B = 64-byte memcpy from `[job]+0xE8`; then commit(0x6C). Matches the sample
  (65535, 12, 54, 7, …, 87, 10, …, 136, 15, 1). → **Step-1 canary site** (change one immediate).
- **Output ring buffer** at ctx+0x46C8: 0x3C4AC = get write pointer + contiguous free space;
  0x3C500 = commit n bytes (handles wrap, signals event via 0xB49A0). Producers: 0x3CA5C (header),
  0x3C5A8, 0x3C6B4, 0x3C800 (not yet read — likely the pixel-chunk commits; find the last chunk /
  trailing row here). A separate task drains the buffer to the card.
- **Pixels: FPGA → SDRAM by PXA DMA.** 0x3BFBC builds two descriptor chains (double buffered):
  source 0x08000000 (chip select — FPGA sensor interface), target 0xA26F44E0+ in 0x1FE0-byte
  blocks (DCMD 0xE0031FE0); 0x3C1E0 starts DMA channel 1 (DCSR1 RUN). Data passes through RAM the
  CPU can access, but the file is **streamed**, not held whole.
- Implications for the DNG plan:
  - Header bytes 0–7 → TIFF header: changing immediates alone is not enough (0x4949, 0x2EDC,
    0x0141 are not ARM immediates); the header block's zero stores could be repacked in place to
    make room (no reclaimed space needed). To verify.
  - **IFD placement idea:** the trailing stride row (last 7,952 bytes, ignored junk) could hold the
    ~750-byte IFD template → file size unchanged, no change to file opening (0x3CC20) or job
    size fields. Needs a hook where the last chunk is committed (0x3C5A8/0x3C6B4/0x3C800).
- Header fields decoded: u16 [10]/[11] = bytes of `ctx+0x422C` = **2647 rows**; [14]/[15] = bytes
  of `ctx+0x4228` = **3976 samples/row** (row bytes after `<<1` at 0x3CF18). The "trailing row" is
  sensor row 2647, delivered in the last DMA block (blocks of 16 rows; 166 blocks, last = 7 rows).
- **0x3C904 = DMA block-complete handler** (pointer at 0xEF100): re-arms DMA ch.1 for the next
  block (0x3C1E0) unless last, then dispatches on type `ctx+0x4638`: 0 → **0x3C5A4 RAW producer**
  (also .BIA — same type 0), 1 → 0x3C7FC (JPG, calls encoder 0x74724), 2 → 0x3C6B0 (8-bit DNG,
  calls 0x76A3C companding); then block index `ctx+0x4220` += 1; after the last block it finishes
  the file (0x716F8, vtable +0x18, 0x90F2C).
- **0x3C5A4 RAW producer**: per block, memcpy from DMA buffer (0x26F44E0 + parity × 0x3E080)
  into the ring (in pieces limited by free space), commit, kick writer (vtable +0x10). Normal
  block size `ctx+0x4218`; **last block (idx == `ctx+0x421C`−1) takes a separate branch
  0x3C688–0x3C6A8** computing size = (rows − idx×16) × row bytes, then `b 0x3C5EC`.
  → **Hook site for the IFD: 0x3C6A8** (runs once per RAW/BIA file, block DMA already complete):
  copy template to source + (size − row bytes), i.e. the start of the trailing row, then continue.
  Gate out .BIA via job flag +0x21A.
- File extension: "RAW" at 0xD6590 is shared with the debug path string; changing it to "DNG" is a
  3-byte data change. In JPG fine+RAW mode this gives JPG+DNG pairs like the stock DNG+JPG mode;
  camera playback/card-scan behaviour with our DNG layout is untested (harness test first).
- Open: the card-writer task; header rewrite at 0x3CE48 to fit the TIFF
  header (repack zero stores).

## Emulated save path (`tools/m8_savetest.py`) — 2026-10-20

- **Entry points** (event table 0xEEF40–0xEF0E8 style, 16-byte entries): event 0x2AFB → **0x3CA58**
  store routine, 0x2AFA → **0x3C900** DMA block-complete handler, 0x2AF8 → 0x3D360 writer open.
  The real entries are the `mov ip, sp` one word before the addresses listed above (0x3CA5C,
  0x3C904); the RAW producer's entry is 0x3C5A4 as listed. Store routine args: (ctx, msg) with
  msg+8 = job, msg+0xC = writer object (→ ctx+0x4210). Block handler args: (ctx, status) and it
  acts only if `[status+8]` has DCSR ENDINTR (bit 2).
- **Ring buffer** struct at ctx+0x46C8: +0 base, +4 raw size, +8 size, +0xC margin, +0x10 write,
  +0x14 read, +0x18 count, +0x1C total committed, +0x20 eCos flag (bit 0 = space), +0x28 mutex.
  Set up by 0x3C454(ring, base, raw, align, margin) via ctx vtable +0x3C = 0x3D2A0: **base
  0x2841D00, 8 MB, align 0x200, margin 0x40000 → size 0x7C0000** (256 KB overflow slack after it;
  commit 0x3C500 copies a write that runs past `size` back to the start). Commit clears flag bit 0
  when count ≥ size − margin; get-space 0x3C4AC waits on bit 0 (0xB48C4, OR mode).
  Consumer: 0x3D00C (readable contiguous bytes), 0x3D050 (consume; sets bit 0 once free ≥ margin),
  writer drain 0x3D714(W, mode): mode 0 whole 0x20C000 units, mode 1 whole 0x2000 units, else all;
  a wrapped tail is written whole; fwrite 0xA83D4. (A second set-up at 0x3DA00 has no references.)
- **DMA**: 0x3BFBC(ctx, row bytes, rows) → ctx+0x4218 block bytes (rows×16 = 127,232), +0x421C block
  count ⌈rows/16⌉ = 166, +0x4224 = 90 % of it; two chains of 16-byte descriptors at ctx+0x4230 /
  +0x4430 (16 descriptors, 0x1FE0 bytes each except the last, which has ENDIRQEN and STOP), targets
  0xA26F44E0 / +0x3E080, then cache clean/invalidate (cp15 c7). Block handler re-arms DDADR1 with the
  other chain and starts it (0x3C1E0) **before** producing the current block (double buffering).
- **Harness**: the functions above + 0x8817C (string append, file name), memcpy, divide run as
  firmware; eCos mutex/flag calls, FPGA/GPIO/sensor calls (0x94E2C, 0x94E98, 0x90C40, 0x90F2C),
  0x98324, 0x716F8 and geometry 0x90F9C are stubs; the DMA controller and the card-writer task are
  Python models (writer mirrors 0x3D00C/0x3D050/0x3D714, four drain timings). Sensor stream = the
  sample file after its header. ~8 s per simulated shot (per-block escape check).
- **Result: stock and flashed builds reproduce `L1031902.RAW` and `L1031901.RAW` byte for byte**
  (all four drain timings; the "lazy" one fills the ring three times and blocks the producer), file
  name `…L1031902.RAW`, 166 DMA runs of 127,232 bytes, ring empty and end flag ctx+0x4630 set at the
  end, identical call traces. The header block 0x3CE48–0x3CF20 is reached only from 0x3CD58 (type 0
  = RAW and .BIA). Mutation check: changing the last-block row computation (0x3C6A0) makes the run
  fail. Run: `work/venv/bin/python tools/m8_savetest.py [--stage N] [--quick] [-v]`.

## Staged DNG builds (`tools/m8_dngpatch.py`)

Each build = stock → P1–P3 (must equal flashed `f6589c41…`) → the stage's pieces; refused if any
byte differs from the flashed build outside the pieces' declared regions (header 0x3CE48–0x3CF20,
hook 0x3C6A8, ldimg 0x28AB0–0x29104, ext literal 0x3CFF8) or outside the PXA lump.

Pieces (sources in `tools/asm/`, bytes frozen with SHA-256 in the patch script; the test reassembles
and compares):
- **canary** 0x3CEA0 `mov r0,#7` → `#0xA5`.
- **tiff** 0x3CE48–0x3CEFC rewritten (`m8_header.s`, same 46 instructions): u16[0..3] = `4949 002A
  0FCC 0141` = "II", 42, IFD0 at **21,041,100 = 0x01410FCC**; all other header fields as stock. Room
  from loading job+0x210 bytes with three `ldrb` instead of ldr + shifts + masks. No hook needed.
  (A first version had 0x0ECC — a hex slip; the save-path test caught it against m8_wrapdng.BASE.)
- **ldimg** 0x28AB0: stub `mov r0,#0; bx lr`; 0x28AB8 `dng_hook` (`m8_dnghook.s`, 476 bytes incl.
  literals), then tables (mode word, template length, 10 slots {template offset, job offset, length},
  902-byte template from `m8_wrapdng.build_template`), rest of the region `udf` (0xE7F000F0).
  dng_hook: skips .BIA (job+0x21A), any geometry other than 7952 bytes × 2647 rows, and any
  destination outside the DMA buffer; dest = trailing row of the last block's buffer; mode 1 dumps
  "M8DUMP01", ctx+0x4210..0x4240, hook inputs, job+0..0x280, settings block 0x200 into the trailing
  row; mode 2 copies the template and fills the slots from S (job+4); then cleans + invalidates the
  D-cache lines of dest..dest+0x800 and drains the write buffer. All stores go through one copy loop
  that writes nothing unless the range lies in the trailing row and the DMA buffer. Calls no firmware
  function. Returns with `sub pc, lr, #0xC0` (→ 0x3C5EC), so it is position independent.
- **hook** 0x3C6A8 `b 0x3C5EC` → `bl 0x28AB8` (`02b1ffeb`). lr is dead there (the producer saved it).
- **ext** literal 0x3CFF8 0xD6590 ("RAW") → 0xD6570 ("DNG", used by DNG mode). Its only reader is
  0x3CCE0. Not the string itself: **"RAW" at 0xD6590 is referenced from 7 places** (0x38B30,
  0x38C34, 0x38DA8, 0x38F34, 0x3CFF8, 0x699C0, 0x6B028).

| Stage | Change | File | SHA-256 | Status |
|---|---|---|---|---|
| 1 | canary (file bytes 6–7 `07 00` → `a5 00`) | `firmware/patched/m8-2_014-stage1.upd` | `3f84b34a225aeebe3f5f18cb658d4b14028d49d98e1fd1d1366ccf25a5830e66` | emulator pass; **flashed, camera-tested 2026-10-20** |
| 2 | canary, ldimg (hook off: idle test) | `…-stage2.upd` | `ff6b3f63a0f2a8c7a6231cc98e53c6b977c63734a2ef16ea4a8e30a56d8d45e9` | emulator 145/0; not flashed |
| 3 | canary, ldimg mode 1 (dump), hook | `…-stage3.upd` | `77e35e778e5b945bc5f119ab399803b40eb5628a6b27f352717ea07059e4d2ca` | emulator 145/0; not flashed |
| 4 | tiff, ldimg, hook (DNG content, named .RAW) | `…-stage4.upd` | `55264b11f86dd66e61f1412c5c341afdaa8553ce0d10ade270e52de1f24c944c` | emulator 150/0 (BlackLevel per ISO); **flashed, camera-tested 2026-10-21 — current build**. Previous: `59aff4a3…` (BlackLevel 92 at all ISOs) flashed and camera-tested 2026-10-20; first version `3b451b4d…` (date slot wrong) |
| 5 | tiff, ldimg, hook, ext (named .DNG) | `…-stage5.upd` | `00ed8542ed2949d873d5c084024c5e5fe4a522a01a3d878462763c6f30fc53ce` | emulator 150/0; not flashed (previous `d9a94feb…` flashed 2026-10-20, rolled back: in-camera review) |
| 8 | stage 4 + stats, stats key (INFO → Camera stats) | `…-stage8.upd` | `32e6854ec0bc451667ef4f8f6b40dfb4c8af406a43db84e94b90abeb380408f8` | m8_infotest 38/0, m8_inforender 7/0, m8_savetest 49/0 (2026-10-23); not flashed. See "GUI" |
| 7 | stage 4 + screens, screens key (INFO → Last shot → Camera stats) | `…-stage7.upd` | `c88e77c0fc57d98f022c81fdad8e73d23430b591d344c223b84ac6364d61dae4` | m8_infotest 26/0, m8_inforender 13/0, m8_savetest 49/0; **flashed 2026-10-23**: screens work, but the histogram kept showing the first shot after later shots → replaced by stage 8. See "GUI" |
| 6 | stage 4 + info, info key (INFO → Body Debug Data) | `…-stage6.upd` | `f8e8138d9b05cc546d76f7d1a2f5a7c6c7d223e9f798032155bb4c2fb656b07c` | m8_infotest 14/0, m8_savetest 49/0; **flashed, camera-tested 2026-10-23**: INFO opens Body Debug Data, SET closes it, INFO again does not (as in service mode). See "GUI" |

Stage 1 emulator result: the file differs from the camera sample only at byte 6; same call trace,
same header-block write addresses and DMA/ring bookkeeping as the flashed build; .BIA files get the
same canary (same type-0 header code); settings loader and SET menu identical to the flashed build.
m8raw2dng2 skips the 54 header samples (`data[header:...]`), so it still converts stage-1 RAWs.

Stages 2–5 emulator result (2026-10-20, `m8_savetest.py`): every file equals an independently
computed expectation (canary byte / dump contents / `m8_wrapdng.wrap()` output) under all four writer
timings and both samples; the new code runs exactly once per file (never in stages 1–2), and writes
only the trailing row and its own stack; same call trace, header-block write addresses and DMA/ring
bookkeeping as the flashed build; .BIA: hook entered, writes nothing (stack only), header as the
stage's header code; guards tested by calling dng_hook directly (.BIA flag, row bytes 7950, rows 2646,
destination below/above the buffer → no writes; registers r4–r11, sp preserved); settings loader and
SET menu identical; only references into the new code: the debug initializer's pointer (0x2DD48) and,
from stage 3, the hook. **The emulated stage-4 file is byte-identical to
`sampleraws/L1031902.DNG`**, the desktop-prototype DNG Lightroom opened (14-bit, shutter, ISO), and
decodes in LibRaw. Not modelled: the D-cache (the clean/invalidate ops execute but have no effect in
the emulator) and the slot offsets in S (the emulator puts values where the table expects them;
stage 3 checks the real offsets on the camera).

## Reclaimable space: debug-shell commands (2026-10-19, `tools/m8_reclaim.py`)

- Two command sets. Core shell (help, msg, ping, mi, ti, si, delay, reset, rbm/rwm/rqm, wbm/wwm/wqm):
  built at 0x8AA4C — keep (tiny; peek/poke may be useful). Application commands: 94 entries
  (92 handlers) built by the **C++ static initializer 0x2C9F4(1, 0xFFFF)** into 32-byte RAM
  entries: +0 name, +8 usage, +0xC description, +0x10/+0x14 (arg counts?), **+0x18 handler**.
  The tool extracts them by emulating the initializer (completes cleanly with only 0xB48A0 stubbed).
- Entrance rule: the initializer runs at boot, so **never patch the registration**. Instead keep
  the handler's first instructions as a stub that returns, and reuse the rest of its body.
- Reachability scan per handler range (start .. min(next prologue, next handler)): branches,
  data words, literal-pool reads and pc-relative adds from outside. Update/flash/power/EEPROM/
  RTC/mount commands are excluded (NEVER) whatever their counts.
- **Best candidates (0 other refs; name string referenced only by the initializer):**
  `ldimg` 0x28AB0, 1,620 bytes ("load image from DSP" — the debug RAW/DNG loader);
  `bf_memtest1` 0x2ABD0, 960 bytes; `writejpgipp` 0x26D98, 760 bytes. `ldimg` alone covers the
  ~750-byte template + ~160-byte routine.
- **Ghidra second opinion (12.1.4, headless, 2026-10-19): agrees.** Raw import at 0x20000,
  ARM:LE:32:v5t, aggressive instruction finder; 2,474 functions; code region 93.4% instructions,
  4.5% data, 2.0% (14.8 KB) undefined. References into each candidate from outside: exactly 2, both
  the initializer storing the handler pointer into its entry (`str ip,[fp,#-0x30]` + `stm ip,{r0-r3}`
  at 0x2DFE8/0x2DFFC ldimg, 0x2CD14/0x2CD34 bf_memtest1, 0x2D148/0x2D160 writejpgipp). Ghidra's
  function body for ldimg: 0x28AB0–0x29073 (+ literal pool to 0x29104, as in m8_reclaim).
  Combined coverage: m8_reclaim scans every word raw (cannot miss a direct branch/pointer even in
  undecoded bytes); Ghidra adds register data-flow. Residual gap: addresses computed arithmetically
  — covered by the on-camera idle test.
- Still to do before use: on-camera idle test (region filled, hook off) before enabling.

## Boot order: SD update check vs settings load (2026-10-19, static)

- `.upd` scanner: **0x23100** (looks for "M8.UPD" 0xD46C0 / "M8-%d_%d.UPD" 0xD46C8). Called from
  0x23320 (← update GUI flow 0x60090 via 0xED08C, "Update failed!", "Could not open Update File!"),
  0x297D0 (`updatesd` debug cmd), 0x37BAC (card check, ← 0x37E20), 0x5F9E0 (via 0xED084).
- Startup function **0x35C68** (via 0xEBBE0) reads GPLR2 (0x40E00008) bit 31 = GPIO95 into
  `[ctx+0x17E54]`. **GPIO95 = 0** → 0x35E20: card check 0x37E20 (→ scanner) *before* the normal init
  at 0x35CA4; **GPIO95 = 1** → normal init directly. Normal init loads settings (0x21848 at 0x35DA8).
  GPIO95's meaning is unknown.
- The update itself (confirmation dialog, flashing in 0x60090) runs in the GUI state machine, i.e.
  after startup incl. settings load → the updater is *not* independent of stored settings.
- Settings written to EEPROM (writer 0x2105C) only from: 0x364D4 (event table 0xEF028),
  0x36B20 (0xEF068) and the `settingsback` debug command (0x25F08).
- Main camera task event table (0xEEF40–0xEF0E8): 16-byte entries {0, event id, handler, 0}.
  **Event 0x190 → 0x36B1C (saves settings) = power-state change broadcast**: sent by 0x2407C(state)
  to three tasks (0x369B0, 0x87520, 0x456C8); power states from the `power` debug command
  (0x28530 → 0x3DE0C): 0 = on, 1 = standby, 2 = off. Broadcaster callers are power-task handlers
  (table 0xEEC4C–0xEECBC: events 0x2AFF → 0x245B4, 0x2B00 → 0x24754, …).
  **Event 0x28AB → 0x364D0 (card check 0x37E20, then saves settings) = GPIO95 changed**: posted by
  the GPIO interrupt callback 0x31C68 (registered via 0x8D128 with vector 0x7F = 32 + 95; same
  scheme gives GPIOs 83, 53, 11 for the other callbacks) with the new level, and once at boot when
  GPIO95 = 0. 0x304F4 polls GPIO95 with a timer (debounce).
- **GPIO95 is most likely the SD card-detect switch, active low (0 = card inserted)** (debounced,
  card check on change, boot-time card/.upd scan when 0). Inferred from code, not hardware-tested.
- So settings are saved to EEPROM on: power off / standby / on transitions, card insert/remove,
  after a boot with a card inserted, and the `settingsback` debug command. A battery pull saves nothing.
  → Operating rule after any anomaly: pull the battery first (not the power switch, not the card).
- Consequence for DNG code: settings block 0x14C910 (main RAM) vs image DMA buffer 0x026F44E0+;
  new code's writes are range-checked to the DMA buffer, so it cannot reach settings. A crash/freeze
  → battery pull runs no settings-save handler.

## Per-shot metadata (static, 2026-10-19)

- **EXIF writers** (C++ class, vtable ~0xED8E8–0xED930; tag helper 0x76218(obj, tag, type, count,
  value), rational/8-byte append 0x76334, blob append 0x76384, ASCII 0x77D2C):
  0x77EF8 = the camera's own DNG IFD0 writer (NewSubFileType … ExifIFD, DateTimeOriginal,
  FocalPlane*, TIFF/EP, DNGVersion — matches a camera DNG exactly); 0x77E2C = ExifVersion +
  DateTimeDigitized; **0x6C630 = EXIF sub-IFD writer**: ExposureTime, ExposureProgram, ISO,
  ShutterSpeedValue, ExposureBias, MaxAperture, Metering, LightSource, Flash, FocalLength, **Leica
  MakerNote** (220 bytes, "LEICA" header 0xE1080, Leica tags 0x302–0x340), FileSource, SceneType,
  WhiteBalance, DigitalZoom, FocalLength35, SceneCapture, ImageUniqueID.
  Readers (playback): 0x6CC64 (vtable A) and 0x6DDAC/0x6DB74 (vtable B) — they *get* tags into a
  playback object; not useful for writing.
- **Metadata struct S** (writer takes it from `[writer+0xB0]`), values already EXIF-ready (the writer
  copies them straight into tags): +0x20 date "YYYY:MM:DD HH:MM:SS" (20 bytes) — **in the job copy
  the date is at job+0x20 = S+0x1C (camera-verified 2026-10-20); the other offsets below are
  camera-verified as listed**, +0x60 u16
  ExposureProgram, **+0x62 u16 ISO**, **+0x64 ExposureTime (num, den)**, +0x6C ShutterSpeedValue
  (srational, 16.16 APEX), +0x74–0x88 MakerNote values, +0x8C ExposureBias, +0x94 MaxAperture,
  +0xA8 FocalLength; also +0x10/+0x14 thumbnail 320×240, +0xB4 = 500 (BayerGreenSplit).
- Date: capture setup 0x33AB8 does time() 0xC0EB4 → localtime 0xC1590 (static tm 0x1827B4) →
  strftime 0xC05F4 into `[ctx+0x17E30] + 0x20`.
- **S lives inside the job struct at job+4**: job init 0x3AF88 calls defaults 0x6DF5C(job+4)
  (ISO 100, …). Per shot, **0x424AC copies the full metadata struct into the job (0x3B8EC) and then
  posts the job for storage**; callers 0x33640 / 0x35620 (capture flow).
- Timing: the camera's own DNG/JPG writers emit EXIF at the *start* of their files, so S is complete
  before storage begins; the DNG hook runs at the *end* of the RAW file → values are available.
  The store routine already holds the job (`[ctx+0x4634]`), so the hook reaches ISO at job+0x66,
  ExposureTime at job+0x68, date at job+0x24 etc. with plain loads.
- To verify with a RAW+JPG pair: one job per shot carries all file flags (RAW+JPG), so the RAW and
  JPG share S; compare the JPG's EXIF values with these offsets.
- **Sample pair `sampleraws/L1031902.RAW/.JPG`** (JPG fine+RAW, 2026-10-19 17:32:24): JPG EXIF =
  ExposureTime 1000/1000000, ExposureProgram 3, ISO 160, ShutterSpeedValue 655360/65536 (APEX 10.0,
  16.16), ExposureBias 0/65536, MaxAperture 0/65536, Metering 2, Flash 24, FocalLength 0/1000 (no
  lens data on this shot), WhiteBalance 0, PixelX/Y 3936×2624, ImageUniqueID …070C; MakerNote
  "LEICA\0\0\0" + 18 tags (0x300–0x340; 0x303 = body serial). JPG EXIF tag order differs
  from 0x6C630 (adds 0x9101, 0xA001, 0xA401, 0xA408–A; no FocalLength35) → the JPG uses its own
  writer, same value formats. RAW header identical to L1031901; bytes 0x2C–0x6B (from job+0xE8)
  are zero again.
- Offsets in S are not verifiable from files. Plan: **metadata-dump canary** — first hooked build
  copies ~256 bytes of job metadata into the junk trailing row; compare with the JPG on the desktop.

## Post-write checks on image files (static, 2026-10-19)

- **None.** CRC32 (0xBD0F4/0xBD15C) is used only by settings (0x21068, 0x21850), the .upd check
  (0x2387C), the `crcbb` debug command and 0xAFBB4 — not by the save path. No read-back/compare of
  RAW/JPG/DNG after saving. "Data verify failed after operation" (0xBD8D0) belongs to the flash
  driver's error table (updates). The SD filesystem (with `Journal.dat`) only reports driver errors
  (0xA4910: write/read error, disk full, EOF …); the DNG change keeps size and write path identical.
- Where the camera *does* read our file later: playback. As `.RAW` it is ignored (review shows the
  JPG). As `.DNG` the camera's DNG reader (0x6DDAC/0x6DB74) parses it and expects the camera's own
  layout (320×240 thumbnail as IFD0, PixelX/Y, LEICA MakerNote) → run that reader on our DNG in the
  emulator before changing the extension.
- Mitigation: we always write the JPG too. Playback very likely shows the JPG of a pair (stock
  DNG+JPG mode writes the same pairs; in RAW+JPG with B&W JPG the review is B&W). 0x46110 picks the
  display path per file by extension ("JPG" → 0x46198, "DNG" → 0x460C8); pair grouping in the file
  list not traced. The DNG reader still runs for a lone DNG (JPG deleted elsewhere) and maybe the
  info screen ("DNG + %s", 0x47574) — keep the emulator test before the rename.

## Camera's own 8-bit DNG vs the 14-bit data (file analysis, 2026-10-21)

From `fromcameraimports/L1031921.DNG` (camera DNG mode, ISO 160) compared with the stage-5 14-bit file
L1031919 (ISO 160, different scene). File-level evidence only; the firmware routines were not read.
- **Layout:** IFD0 = 320×240 RGB thumbnail (per-shot AsShotNeutral, ColorMatrix1/2 as ours, no
  BlackLevel); SubIFD = raw CFA 3920×2638, 8 bits/sample, uncompressed, strips of 16 rows, crop
  origin (2,2) size 3916×2634, WhiteLevel 16383, BayerGreenSplit 500.
- **Companding:** LinearizationTable (256 entries) is exactly `floor(code² / 4)` (0, 0, 1, 2, 4, 6,
  9, 12 … 16129, 16256) → the camera stores ≈ 2·√value: square-root companding. Code 1 never
  occurs (decodes to 0 like code 0). Quantization step ≈ √value, about the size of the shot noise at
  ISO 160 (var/mean ≈ 0.65 in the 14-bit file); the 14-bit file has 64× finer steps.
- **Black:** subtracted before companding and **clipped at 0** — 5.9 % of the 8-bit file's pixels are
  exactly 0, while the 14-bit file's darkest 0.1 % per channel are 72–79 (pedestal ≈ 92). Noise below
  black is discarded → deep shadows lose information and are biased slightly bright.
- **Crop:** 3920×2638 written (48 columns / 8 rows fewer than the 3968×2646 active area).
- **No spatial noise reduction detected:** correlation of neighbouring same-colour pixel differences
  in 138 flat dark patches = −0.493 (white noise −0.500; smoothing would move it toward 0); the
  14-bit file gives −0.467. No demosaic, sharpening or colour processing either (still CFA data, same
  colour matrices).
- **Where the encode table lives: not confirmed.** `LUTS_GAMMA` (31,760 bytes) is not a 14→8 table:
  a header, a reciprocal table (16384/n: 2048, 1820, 1638 …) and float constants (0.9, 2.6 …) —
  looks like JPEG-pipeline tone parameters. The DNG producer calls 0x76A3C (companding, not read);
  the table may be computed at runtime.
- Not ruled out: a subtle correction applied in both modes or only in DNG mode (e.g. defect-column
  repair). Definitive test (deferred): same tripod scene in DNG mode and JPG fine+RAW, plus a
  lens-cap pair; apply black → clip → table to the 14-bit file and compare pixel for pixel.

## Black level per ISO (2026-10-21, camera file)

- **Observed:** Option 2 files at high ISO open in Lightroom increasingly lifted / washed out — our
  template writes BlackLevel 92 at every ISO.
- **`fromcameraimports/L1031933.RAW` (ISO 1250, ISO slot read from our own DNG tags):** every sample
  value is a multiple of 8 (exactly 50 % multiples of 16); darkest 0.1 % per CFA channel 688–784,
  minimums 528–592: black noise straddles 736 = 92 × 8.
- **ISO series 2026-10-22, L1031944–48** (same scene, A mode, ISO 160/320/640/1250/2500, shot on
  stage 4 `59aff4a3`, so BlackLevel 92 in all): darkest 0.1 % per channel (R/G/G/B) 123/134/135/104,
  190/204/204/176, 348/360/364/328, 656/672/672/624, 1264/1280/1280/1216 — doubling per ISO step and
  sitting at/just below 92 × gain, as black noise should. **The rule is confirmed on this camera.**
- **Correction:** these five frames are **not** quantised (ISO 1250 included: values are not all
  multiples of 8), unlike L1031933. So "higher ISO = pure digital ×2^n, one bit lost per step" is
  not established; what differed in L1031933 is unknown. The black-level rule does not depend on it.
- Matches the rule in Arvid Kuehl's m8raw2dng (`-b`) and m8raw2dng2 (`-s -b`): **BlackLevel = 92 ×
  gain, gain = 2^round(log2(ISO/160))** → 92 / 184 / 368 / 736 / 1472 for ISO 160 / 320 / 640 /
  1250 / 2500; unknown ISO → 1.
- **Fix built (2026-10-21):** dng_hook writes BlackLevel = base × 2^(number of thresholds 226 / 452 /
  905 / 1810 the shot's ISO exceeds), from S+0x62; table in `tables+12..+27` generated from
  `m8_wrapdng.black_for_iso` (same rule as m8raw2dng2 for every ISO 160–2599; unknown/low ISO → 92;
  capped at ×16). m8_savetest: 16 ISOs incl. every threshold edge + a full ISO 1250 shot (736) pass.
  Stage 4 `55264b11…` **camera-tested 2026-10-21**: L1031949–53 (ISO 160/320/640/1250/2500) carry
  BlackLevel 92/184/368/736/1472, darkest 0.1 % just below each; Lightroom blacks good at every ISO.
- Open: per-channel black (green slightly above R/B at base ISO? needs a lens-cap frame); whether
  intermediate ISOs exist (e.g. auto ISO) — the rule rounds to the nearest stop.

## Per-shot white balance (2026-10-21, static + file analysis, in progress)

- **The camera computes a per-shot neutral in JPG fine+RAW mode too.** The JPG's Leica MakerNote tags
  **0x322 / 0x323 / 0x324** hold it as rationals `16384/x` (R, G, B), the same form as DNG
  AsShotNeutral (offsets inside the MakerNote are relative to MakerNote start + 8). L1031919.JPG:
  16384/32656, 16384/16384, 16384/21856 (0.5017, 1, 0.7496); L1031902.JPG: 0.4641, 1, 0.8119.
  m8raw2dng2 copies exactly these into its DNG's AsShotNeutral (fallback: fixed daylight).
- **Camera DNG mode:** AsShotNeutral is written by **0x6CBB4** (DNG/EXIF writer class, vtable slot
  0xED904) via tag writer 0x76D50 (tag, count) + 0x76E18 (copy value bytes): 24 bytes from
  **object+0x12D0**, already rationals; the same method writes Orientation from object+0x12C2.
  Nothing writes +0x12D0 directly (likely filled by a block copy). Which instance it is: not found.
- **0x6C630 (camera-DNG EXIF/MakerNote writer, S = [writer+0xB0])** writes MakerNote 0x302–0x304,
  0x310 (lens, S+0x9C), 0x311–0x313 (meter values: S+0x84/0x88, S+0x7C/0x80, S+0x74/0x78), 0x320
  (S+0x134), 0x321 (S+0xC0), 0x325 (byte S+0xBD), 0x330–0x333 (S+0x138…0x144), 0x340 (S+0x18 + blob)
  — **not 0x322–0x324**. Correction: S+0x74–0x88 are the meter values, not WB; S extends to ≥ +0x144.
- A whole-image scan (constant evaluation at every call of the tag helpers 0x76218, 0x76334,
  0x76384, 0x77D2C, 0x76D50, 0x78304, 0x76E18) finds no other writer of 0x320–0x326, and the byte
  pattern of a 0x322 rational entry occurs in no lump. → **The JPG's MakerNote (with WB) is not built
  by the PXA tag writers**; most likely the Blackfin DSP (JPEG pipeline, auto WB). Where the neutral
  sits in PXA memory at hook time in JPG fine+RAW mode is unknown.

## GUI: screen, fonts, keys, windows (static, 2026-10-23, research for an INFO screen)

Read-only research; nothing patched. Goal: a shooting-mode INFO screen (INFO does nothing in
shooting mode on the camera; the top LCD shows battery and shots left).
- **Screen:** 320×240, 24-bit (3 bytes/pixel, "8:8:8"). Debug `fb` (0x257B8) streams `frames.bin`
  in 0x38400-byte frames into it. Display object = `[ctx+0x4210]` (ctx = `[0xD4220]`); vtable
  +0x14 = get framebuffer pointer, +0x1C = release/show. Debug `screenshot` 0x25A08, `readbmp`.
- **Fonts** (`tools/m8_font.py` decodes and renders them): the GUI lump has TRANS, IMAGES, FONT1, FONT2
  (no FONT3/4; the loader 0x414D4 then returns -1 after FONT2, harmlessly). No font name anywhere;
  the glyphs look like Arial (65,440 glyphs → probably Arial Unicode MS, rendered).
  - Last 20 bytes `<5I`: line height (FONT1 17, FONT2 21), descent (4, 5), glyph count
    (0xFFA0, 0x9FA6), glyph-table offset, 0. Registered by 0x886FC into the table at 0x17F98C
    (20 bytes per font; +0xC/+0x10 relocated to pointers).
  - Glyph table: 12 bytes per Unicode code point: x off (s8), y off (s8), w, h, advance, 3 pad,
    bitmap offset (u32). Bitmaps 1 bpp, MSB first, rows padded to bytes.
  - Text width 0x99C0C(str, font) (70 callers; UTF-8 via 0x991C0); wrapped text in a box 0x99494.
- **Keys:** events are posted to ctx (0x8B6F4): +0 type 0xA press / 0xB release, +0x10 key code
  (debug `key <c>` 0x279F4 sends the first character of its argument). Keypad driver 0x964E0
  (PXA keypad 0x415000xx); table at 0xF0DF8, 12-byte entries {code, bit, 0}:
  `u` `d` `l` `r` (matrix 7, 4, 6, 3), `m` 5, `v` 2, `x` 1, `t` 0, **`i` direct key 0**,
  `s` direct key 1. Reading (inferred from the letters): pad, MENU, PLAY (view), DELETE, PROTECT,
  **INFO**, SET.
- **Windows:** C++ classes, no RTTI names. Generic constructor 0x9AA08(this, parent, x, y, w, h,
  name, flags); **vtable +0x2C = key handler** (keys forwarded to children via `ldr pc,[r3,#0x2c]`).
  Named windows: GUI::Desktop (vtable 0xEE450, size from the display object), InformationPage
  (0x46790, vtable 0xEBFA4; builds NavigationWindow + Statusline; tied to the gallery = playback
  info), gallery, AutoReviewHist, MultiGallery, NavigationWindow, Statusline, FocusFrame,
  Scrollbar, MDPopUpMenu, evfastaccess, lensinfo; 24 more constructions without a name.
- SET-menu item classes: 13 vtables (constructors 0x4DBB8–0x501A0); e.g. 0x58560 handles `s`
  (permission 0x9AF84, then sub-window), `m`/`v` (state change 0x40360), others → base 0x56B2C.
- **Shutter count:** service menu `camInfoMenu` (built 0x651D8, opened from 0x404E8 / 0x40908 next to
  the service gate) → "Body Debug Data" = BodyDebugDataDialog (0x60F94…0x61AB4). It requests one debug
  block from the body ("Getting Debug Data failed!" on error) and prints **`NumExposures: %d`**
  (0x61688), battery state, temperature, BV intern/extern, body exposure time/aperture, lens code,
  main switch, release switch, flash present.
  - Paint 0x610A0: fetch 0x60FC0(this) → **0x3E238(`[0xD421C]+0x50C0`, this+0xB0)** → 0x3FFE4: sends the
    1-byte command **0x33** via 0x93BA8(link, cmd, 1, reply, &len), needs a 29-byte reply (else
    "Getting Debug Data failed!"), unpacks it; then re-arms a 100 ms timer (0x8BD10, id 0x271E).
  - Body-link commands by sender: 0x03 version (`rver`), 0x22 read parameter (`rgpara`), 0x29 read
    body EEPROM (`rree`, settings loader), 0x3FF0C write body EEPROM (`rwee`, settings writer 0x21064),
    0x18 event (`revent`), 0x07 (startup 0x35C68), 0x08 (update flow among others), 0x13, 0x23.
    **0x33 is used only by Body Debug Data** and carries no address or data, so it cannot write
    anything chosen by the caller; the service page sends it every 100 ms. Not verified on the M16C
    side (its handler for 0x33 is unread). A stats page should send it once per open.
- **Key path in shooting mode:** GUI task event table 0xEF22C (also holds timer 0x271E, power 0x190):
  key release (0xB) → **0x444D8**: posts 0x2AFD to `[0xD4214]`, special-cases `'a'`/`'S'`, then calls
  the focused window (`0x9A464` = `[0x17FE44]`) vtable +0x2C. With no page open the focus is the
  desktop (`[0x17FE40]`, vtable 0xEE450), whose +0x2C (0x9CB40) forwards to its owner `[desktop+0x44]`
  = the **GUI application** (constructor 0x40428 / 0x40848, base 0x9A3E0, vtable **0xEBF34**; pages
  are members: camInfoMenu +0x6F6C, lensinfo +0x8440, "Firmware Update" page built at 0x40608).
  Page show/hide: 0x40360(page, show) / 0x58FE8(page, 1); hiding back to the desktop clears
  `app+0x25731`.
- **Application key handler 0x44E30** (vtable +0x2C): switch on key-0x69 → `'i'` 0x44F18, `'m'` 0x44FFC,
  `'s'` 0x44FD8, `'v'` 0x44F90, others ignored (0x44F8C). **INFO:** if `app+0x254B0`==0 and the
  service gate 0x403F0(app+0x254A0) says active → show camInfoMenu (0x58FE8(app+0x6F6C, 1)) and set
  `app+0x2548F`=1 (the service menu, incl. Body Debug Data); **not in service mode → ignored by the
  branch at 0x44F68 (`bne 0x44F8C`)** = the hook point for an INFO screen (service path unchanged).
- **Opening Body Debug Data from INFO** (stage 6): the dialog is camInfoMenu+0x138 = app+0x70A4
  (vtable 0xED1B8, base dialog 0x6046C, parent = camInfoMenu). The menu opens it from its item
  handler 0x65570 (item menu+0x5E0): menu+0x99 = 0, 0x40360(menu+0x138, 1). Window flag bit 4 at
  +0x20 = hidden; show (0x9ADEC) clears it, redraws and focuses, without checking the parent, and
  redraws start at the root -- so the dialog is opened the camera's way: menu first, then dialog.
  Dialog keys (key-0x63): `u`/`c` up, `d`/`w` down, **`s` closes**: stops its timer, hides, sends
  `'a'` to the menu; camInfoMenu on `'a'` (0x654C8) clears app+0x2548F and hides itself (vtable
  +0x3C = 0x40360(this, 0)) → back to the desktop. Other keys are ignored while it is open.
  `app+0x25741` set → INFO opens `lensinfo` (0x45088 → 0x66074(app+0x8440, 1)); set by the GUI's
  event 0x28B0 handler 0x45BD0; untouched by stage 6.
- **Stage 6** (`tools/asm/m8_info.s` in bf_memtest1 0x2ABD0-0x2AF90; 0x44F68 `bne 0x44F8C` → `bne 0x2ABD8`):
  info_open (88 bytes incl. stub and literals) = show camInfoMenu (0x58FE8(app+0x6F6C, 1)),
  app+0x2548F = 1, menu+0x99 = 0, 0x40360(app+0x70A4, 1), return through 0x44F8C.
  `tools/m8_infotest.py`: runs the real key handler 0x44E30 + gate 0x403F0 on stage 4 and stage 6
  for all 256 key codes in 7 GUI states and compares every call and non-stack write: identical
  except INFO in the normal state, which adds exactly those two calls and two byte writes (the
  values the firmware's own service path writes); the only references into the new code are the
  INFO branch and the debug-command registration literal 0x2DAC0 (initializer 0x2C9F4).
  Not modelled: what the GUI does inside 0x58FE8 / 0x40360 / the dialog (drawing, timer, body
  request 0x33) -- that is the camera's own code path, reached today via service mode.
  **Camera test 2026-10-23 [tested]:** INFO in shooting mode shows Body Debug Data; SET closes it
  back to shooting; INFO while it is open does nothing (dialog ignores `i`, same as via service mode).
- **Drawing API** (all camera code; colours RGB565, framebuffer 320x240x3 bytes R,G,B, pixel offset
  0x952E4 = y*960 + x*3): fill 0x98A40(x, y, w, h, [sp] colour) (bounds vs `[0x17F984]` width,
  `[0x17F980]` height); outline 0x98F24(x, y, w, h, thickness, colour); vertical line
  0x98C34(x, y, len, colour, [sp] 0); text 0x996EC(x, y, w, h, [sp] str, colour, font) (string lookup
  0x88990, then the wrapping renderer 0x99494; UTF-8); width 0x99C0C(str, font); line height
  0x99D44(·, font). Display object `[0x17F988]`: +0x10 bytes/pixel, vtable +0x14 = framebuffer.
  Fonts: counter `[0xF0634]` starts at 3 (0-2 built in), so FONT1 = font 3 (17 px), FONT2 = font 4.
  Window getters (0xCD34C…): x +0x18, y +0x1C, w +0x14, h +0x10. Dialog base paint 0x605AC: clears
  the window black, then vtable +0x48 (title, 0x606B4) and +0x4C (content). BodyDebugDataDialog is
  0,0,320,240 (0x6046C).
- **Histograms:** InformationPage (playback info) owns a histogram object (+0x118; 0x7F9D0: 16-byte
  header, 4 x 256 u32 bins at +0x10/+0x410/+0x810/+0xC10) and a widget (+0x1128, paint 0x54964 /
  0x54B9C: one 0x98C34 line per bin, scaled with 0xCAB28). 0x550EC picks RGB (0x7FD84) or luma
  (0x7FC58) by the profile's histogram setting (+0x10) and is fed by 0x55260 with
  **`[app+0x251A8]` + 0x30C0, 320 x 214, stride 960** = the 3:2 photo inside the 320x240 RGB copy of
  the **last displayed image**, set by auto-review (0x4ABB0), playback (0x48124) and the gallery
  (0x4998C). Null until something has been displayed since power-on.
- **Body Debug Data fields** (dialog + offset, filled by 0x3E238): +0xB0/+0xB4 BV intern raw/normal,
  +0xC0/+0xC4 temperature raw/"normal", +0xC8 battery state (0 Empty … 4 Full), +0xD4 body exposure
  time, +0xDD lens code, **+0xE4 NumExposures**.
- **Stage 7: INFO screens** (`tools/asm/m8_infoscreens.s`, region **bfmem 0x2ABD0-0x2B6E8**: bf_memtest1,
  helpers 0x2AF90 / 0x2B05C (called only by bf_memtest2), bf_memtest2, bf_memtest3, bf_checktrans;
  the four command entries stay stubs returning 0, pinned by `.org`; their registrations
  0x2DAB0/0x2DAC0/0x2DACC/0x2DAD8 are the only outside references). INFO opens the dialog as in
  stage 6, after pointing it (dialog+0) at our copy of its method table with our title (+0x48),
  content (+0x4C) and keys (+0x2C). Two tables = two pages: **Last shot** (half-size thumbnail of
  the last displayed image + luma/R/G/B histogram, 128 bins from every 2nd pixel and row, drawn
  with 0x98C34; "No image yet" if `[app+0x251A8]` is 0) → INFO → **Camera stats** (one body request
  0x33 per paint, as the dialog's own paint; Shots taken, battery, temperature, lens code;
  "Body data unavailable" on failure) → INFO or SET → close: dialog+0 = 0xED1B8 again, then the
  dialog's own SET path 0x61868. Other keys ignored.
  `tools/m8_inforender.py` runs the dialog base paint and our methods with the real GUI drawing code
  and fonts into an emulated framebuffer (PNGs): our stores go only to the framebuffer and stack;
  keys switch/close/ignore as intended. Peak stack per paint 1.2 KB (stats page as much as the
  histogram page: sprintf + text engine); the GUI application task sets 0x4000 in task field +0xB0
  (0x9A410), most likely its stack size (not proven). If the screen is ever closed other than by
  INFO/SET (power-off etc.), the dialog keeps our table until restart, so service-mode Body Debug
  Data would show our screen until then.
- **Stage 7 camera test (2026-10-23) [tested]:** INFO opened "Last shot" and the screens worked, but
  after later shots the histogram/thumbnail still showed the **first** shot: `app+0x251A8` is not a
  reliable "last shot". Per-shot path: GUI event 0x2719 → **0x43100** copies the new 320x240x3 image
  (from 0x3B430) into `[app+0x1AAF8]` and sets app+0x251A8 to it, but only if the active profile's
  byte +0x34 is set or the event carries a flag, and `app+0x25608` > 1 (else 0x43320 / 0x43328,
  no copy). Other setters: 0x48344 (playback) and 0x4B2BC (AutoReviewHist onKey: copies review slot
  `[rv + [rv+0xA8]*0x1C + 0x54]` (rv = app+0x17D30) into `[app+0x1AAF4]`), 0x49A64 (gallery).
  `[app+0x1AAF4]` / `[app+0x1AAF8]` are fixed buffers set in the application constructor; the review
  paint 0x4B688 shows `[app+0x1AAF4]`. Owner's decision: drop the histogram (PLAY has one).
- **Stage 8: INFO → Camera stats only** (`tools/asm/m8_infostats.s`, region **memtest12
  0x2ABD0-0x2B338**: bf_memtest1, the two helpers only bf_memtest2 calls, bf_memtest2; stubs at both
  entries, the rest of bf_memtest2 undefined fill, so no dangling calls; registrations 0x2DAC0 /
  0x2DACC are the only outside references). Same opening as stage 7 with one method table
  (vt_stats); INFO or SET closes (dialog+0 = 0xED1B8, then 0x61868); other keys ignored.
- Still open: per-camera check that the temperature "normal" value is °C.

## Known 2.024 issue

Some bodies stop saving images after 2.024 (LED blinks, nothing written). Fixed for some
owners by downgrading to 2.014. 2.024 replaced the Blackfin code (build Jan 2008 → May 2010),
the most likely suspect (unconfirmed). Plan: stay on 2.014.

## Next project: in-camera 14-bit DNG (idea) — full plan in `docs/DNG_PLAN.md`

RAW dump (per m8raw2dng2 docs/PROCESSING.md): 21,049,052 bytes = 54 header u16 + 2,647 rows ×
3,976 u16 (3,968 active + 8 padding), little-endian, 14-bit. Plan: overwrite the first 8 bytes
with a TIFF header, append a ~2 KB IFD after the pixels (StripOffset 108, width 3976, DefaultCrop
hides padding), constant tags (WhiteLevel 16383, BlackLevel 92, CFA, M8 colour matrices copied
from a real M8 DNG, UniqueCameraModel "M8 Digital Camera"), AsShotNeutral from a WB-preset table,
per-shot EXIF from the camera's JPG metadata. No pixel processing. Code must fit in reclaimed
debug-command space, target ARMv5 ARM mode, no VFP. Test in a Unicorn harness before flashing.

## Tooling notes

- Ghidra could not be downloaded in the cloud workspace; analysis used Capstone.
  On the Mac, Ghidra (ARM:LE:32:v5t, base 0x20000) would speed up the DNG work.
- Reference: Alex Hude, "How to Hack an Expensive Camera…" (M8 PWAD format, M240 work).
