#!/usr/bin/env python3
"""
Build a patched Leica M8 firmware file from your own copy of Leica's stock update file.

  Option 1  raw-menu   "JPG fine+RAW" (14-bit RAW + JPG) listed in SET -> Compression and kept
                       after power-off.
  Option 2  dng        Option 1, plus the camera writes a 14-bit DNG in JPG fine+RAW mode (the
                       file keeps the .RAW name; Lightroom opens it).
  --info               add-on for either option (experimental): INFO in shooting mode shows a
                       Camera stats screen (shots taken, battery, temperature, lens code).
Both need Leica's stock firmware 2.014 (the only version tested); other files are refused.

Usage:  python3 m8patch.py raw-menu|dng path/to/m8-2_014.upd [--info] [--out-dir DIR]

Your stock file is only read, never changed. The result is written to DIR (default: build/ next
to this script) as m8-<version>-<option>[-info].upd. An existing file is never overwritten, and only a
result identical to the build tested by the author is written. Then copy it to an SD card and
rename it there, as the script explains (README "Flash it").

Needs only Python 3 (standard library).
"""
import hashlib, os, sys

VERSION = '0.3.0'                   # project version (CHANGELOG.md), not a Leica firmware version
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, 'tools'))
from m8_rawpatch import KNOWN_INPUTS, PATCHES as RAW_PATCHES, find_lump
import m8_dngpatch

# (option, firmware, info add-on) -> (SHA-256 of the result, status). Only these exact results
# are written.
TESTED = {
    ('raw-menu', '2.014', False): ('f6589c41a583d1a44fbce77c4acda707640d255acec97a0d2e1ac829c2e70396',
                                   'tested on a camera (2026-10-19)'),
    ('dng', '2.014', False): ('55264b11f86dd66e61f1412c5c341afdaa8553ce0d10ade270e52de1f24c944c',
                              'tested on a camera (2026-10-21)'),
    ('dng', '2.014', True): ('32e6854ec0bc451667ef4f8f6b40dfb4c8af406a43db84e94b90abeb380408f8',
                             'tested on a camera (2026-10-23)'),
}
# Built and emulator-tested, waiting for a camera test: refused until then.
PENDING = {
    ('raw-menu', '2.014', True): 'fa4ae63a22e2df9749e989ccc570808ac24dabe1a3992593c4c37d27ad6c1c43',
}
INFO_STAGE = {'raw-menu': 10, 'dng': 8}     # m8_dngpatch stages: the option + INFO Camera stats
CARD_NAME = {'2.014': 'M8-2_014.UPD'}
OPTIONS = {'raw-menu': 'Option 1: JPG fine+RAW in the menu, kept after power-off',
           'dng': 'Option 2: Option 1 + 14-bit DNG written by the camera'}


def fail(msg):
    raise SystemExit('error: ' + msg)


def build(option, stock, info=False):
    version = KNOWN_INPUTS.get(hashlib.sha256(stock).hexdigest())
    if not version:
        fail('this is not Leica\'s stock M8 2.014 update file (SHA-256 does not match).\n'
             '       Only 2.014 is supported. Use the unmodified file; see README "Requirements".')
    if (option, version, info) in PENDING:
        fail(f'{option} --info is not yet tested on a camera; nothing was written.')
    if info:
        _, out = m8_dngpatch.stage_file(stock, INFO_STAGE[option])   # region-checked
    elif option == 'raw-menu':
        buf = bytearray(stock)
        pos, _ = find_lump(buf, b'PXA')
        m8_dngpatch._apply(buf, pos, RAW_PATCHES)       # checks the original bytes first
        out = bytes(buf)
    else:
        _, out = m8_dngpatch.stage_file(stock, 4)       # stock -> RAW patch -> DNG; region-checked
    want, status = TESTED[option, version, info]
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
    info = '--info' in args
    if info:
        args.remove('--info')
    if args in (['--version'], ['-V']):
        raise SystemExit(f'm8patch v{VERSION}')
    if len(args) != 2 or args[0] not in OPTIONS:
        raise SystemExit(f'm8patch v{VERSION}\n' + __doc__)
    option, src = args
    if not os.path.isfile(src):
        fail(f'{src}: no such file')
    version, out, status = build(option, open(src, 'rb').read(), info)

    os.makedirs(out_dir, exist_ok=True)
    dst = os.path.join(out_dir, f'm8-{version.replace(".", "_")}-{option}{"-info" if info else ""}.upd')
    if os.path.exists(dst):
        fail(f'{dst} already exists; not overwriting it. Move or delete it first.')
    with open(dst, 'xb') as f:                      # 'x' = create only, never replace a file
        f.write(out)
    sha = hashlib.sha256(out).hexdigest()
    card = CARD_NAME[version]
    print(f"""m8patch v{VERSION} -- {OPTIONS[option]}{' + INFO Camera stats (experimental)' if info else ''}
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
  5. After the restart: SET -> Compression -> JPG fine+RAW."""
          + ("\n  6. INFO in shooting mode shows Camera stats; INFO or SET closes it." if info else ''))


if __name__ == '__main__':
    main()
