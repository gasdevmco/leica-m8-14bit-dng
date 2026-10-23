# Changelog

Versions of this project (not Leica firmware versions). Every build is for Leica M8 firmware **2.014**.
Hashes are the SHA-256 of the file `m8patch.py` writes; if yours differs, don't flash it.

## v0.4.0 — 2026-10-23

- **New add-on, `--info` (experimental), for either option:** in shooting mode the INFO button (which
  does nothing on a stock M8) shows a Camera stats screen: shots taken (the body's shutter counter),
  battery, temperature and lens code, the values of Leica's hidden service page "Body Debug Data".
  INFO or SET closes it. Service mode is unchanged.
- Options 1 and 2 without `--info` are unchanged (same hashes as v0.3.0).
- Developers: emulator tests for the INFO builds (`m8_infotest.py`, every key in every GUI state;
  `m8_inforender.py`, renders the screen with the camera's own drawing code); README lists how long
  each test takes.

| Build | SHA-256 | Tested on a camera |
|---|---|---|
| 1 `raw-menu` | `f6589c41a583d1a44fbce77c4acda707640d255acec97a0d2e1ac829c2e70396` | yes (2026-10-19) |
| 2 `dng` | `55264b11f86dd66e61f1412c5c341afdaa8553ce0d10ade270e52de1f24c944c` | yes (2026-10-21) |
| 1 `raw-menu --info` | `fa4ae63a22e2df9749e989ccc570808ac24dabe1a3992593c4c37d27ad6c1c43` | yes (2026-10-23) |
| 2 `dng --info` | `32e6854ec0bc451667ef4f8f6b40dfb4c8af406a43db84e94b90abeb380408f8` | yes (2026-10-23) |

## v0.3.0 — 2026-10-23

- **One command for users:** `m8patch.py` builds either option from Leica's stock 2.014 file:
  - `raw-menu` (Option 1): "JPG fine+RAW" in SET → Compression, kept after power-off.
  - `dng` (Option 2): Option 1 plus a 14-bit DNG written by the camera.
  It only reads the stock file, never overwrites anything, and only writes results identical to
  the camera-tested builds.
- **Option 2: black level now follows the ISO** (92 at ISO 160, doubling per step to 1472 at ISO
  2500). High-ISO files no longer open lifted / washed out in Lightroom. Camera-tested at ISO 160,
  320, 640, 1250 and 2500.
- Firmware 2.024 is no longer offered (it was never tested on a camera).
- README: "Why 14-bit?", options table, step-by-step build and flash.

| Option | SHA-256 | Tested on a camera |
|---|---|---|
| 1 `raw-menu` | `f6589c41a583d1a44fbce77c4acda707640d255acec97a0d2e1ac829c2e70396` | yes (2026-10-19) |
| 2 `dng` | `55264b11f86dd66e61f1412c5c341afdaa8553ce0d10ade270e52de1f24c944c` | yes (2026-10-21) |

## v0.2.0 — 2026-10-20

- First in-camera 14-bit DNG (`tools/m8_dngpatch.py --stage 4`): JPG fine+RAW writes a JPG plus a
  `.RAW` file whose contents are a 14-bit DNG that Lightroom opens, with exposure, ISO and date.
  Build `59aff4a35f5c8fea4ca1fc8ab962ac3e0ac171131bd82410cf67c9231665273c`, camera-tested.
  BlackLevel was 92 at every ISO (fixed in v0.3.0).
- `.DNG` file names (stage 5) were tried and rolled back: in-camera review could not show the JPG.

## v0.1.0 — 2026-10-19

- Persistent "JPG fine+RAW" (`tools/m8_rawpatch.py`): listed in the SET menu without the button
  sequence and kept after power-off. Build
  `f6589c41a583d1a44fbce77c4acda707640d255acec97a0d2e1ac829c2e70396`, camera-tested.
