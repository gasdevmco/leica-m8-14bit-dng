#!/usr/bin/env python3
"""
Build a patched Leica M8 firmware file from your own copy of Leica's stock update file.

  Option 1  raw-menu   "JPG fine+RAW" (14-bit RAW + JPG) listed in SET -> Compression and kept
                       after power-off.
  Option 2  dng        Option 1, plus the camera writes a 14-bit DNG in JPG fine+RAW mode (the
                       file keeps the .RAW name; Lightroom opens it).
Both need Leica's stock firmware 2.014 (the only version tested); other files are refused.

Usage:  python3 m8patch.py raw-menu|dng path/to/m8-2_014.upd [--out-dir DIR]

Your stock file is only read, never changed. The result is written to DIR (default: build/ next
to this script) as m8-<version>-<option>.upd. An existing file is never overwritten, and only a
result identical to the build tested by the author is written. Then copy it to an SD card and
rename it there, as the script explains (README "Flash it").

Needs only Python 3 (standard library).
"""
import hashlib, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, 'tools'))
from m8_rawpatch import KNOWN_INPUTS, PATCHES as RAW_PATCHES, find_lump
import m8_dngpatch

# (option, firmware) -> (SHA-256 of the result, status). Only these exact results are written.
TESTED = {
    ('raw-menu', '2.014'): ('f6589c41a583d1a44fbce77c4acda707640d255acec97a0d2e1ac829c2e70396',
                            'tested on a camera (2026-10-19)'),
    ('dng', '2.014'): ('55264b11f86dd66e61f1412c5c341afdaa8553ce0d10ade270e52de1f24c944c',
                       'tested on a camera (2026-10-21)'),
}
CARD_NAME = {'2.014': 'M8-2_014.UPD'}
OPTIONS = {'raw-menu': 'Option 1: JPG fine+RAW in the menu, kept after power-off',
           'dng': 'Option 2: Option 1 + 14-bit DNG written by the camera'}


def fail(msg):
    raise SystemExit('error: ' + msg)


def build(option, stock):
    version = KNOWN_INPUTS.get(hashlib.sha256(stock).hexdigest())
    if not version:
        fail('this is not Leica\'s stock M8 2.014 update file (SHA-256 does not match).\n'
             '       Only 2.014 is supported. Use the unmodified file; see README "Requirements".')
    if option == 'raw-menu':
        buf = bytearray(stock)
        pos, _ = find_lump(buf, b'PXA')
        m8_dngpatch._apply(buf, pos, RAW_PATCHES)       # checks the original bytes first
        out = bytes(buf)
    else:
        _, out = m8_dngpatch.stage_file(stock, 4)       # stock -> RAW patch -> DNG; region-checked
    want, status = TESTED[option, version]
    if hashlib.sha256(out).hexdigest() != want:
        fail('the result does not match the tested build; nothing was written. Please report this.')
    return version, out, status


def main():
    args = sys.argv[1:]
    out_dir = os.path.join(HERE, 'build')
    if '--out-dir' in args:
        i = args.index('--out-dir')
        out_dir = args[i + 1]
        del args[i:i + 2]
    if len(args) != 2 or args[0] not in OPTIONS:
        raise SystemExit(__doc__)
    option, src = args
    if not os.path.isfile(src):
        fail(f'{src}: no such file')
    version, out, status = build(option, open(src, 'rb').read())

    os.makedirs(out_dir, exist_ok=True)
    dst = os.path.join(out_dir, f'm8-{version.replace(".", "_")}-{option}.upd')
    if os.path.exists(dst):
        fail(f'{dst} already exists; not overwriting it. Move or delete it first.')
    with open(dst, 'xb') as f:                      # 'x' = create only, never replace a file
        f.write(out)
    sha = hashlib.sha256(out).hexdigest()
    card = CARD_NAME[version]
    print(f"""{OPTIONS[option]}
  input:   {src}  (stock {version}, unchanged)
  output:  {dst}
  SHA-256: {sha}
  status:  matches the author's build, {status}

Next (README "Flash it" and "Safety and recovery"):
  1. Charge the battery fully. Keep a separate card holding only your stock {version} file.
  2. Format an SD card in the camera, then copy the output file onto it.
  3. On the card, rename it to exactly {card}  (the camera only looks for M8.UPD / M8-x_yyy.UPD).
     Rename the copy on the card, not your stock file.
  4. Run the camera's normal firmware update; don't touch the battery or card until it finishes.
  5. After the restart: SET -> Compression -> JPG fine+RAW.""")


if __name__ == '__main__':
    main()
