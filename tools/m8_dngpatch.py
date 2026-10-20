#!/usr/bin/env python3
"""
Leica M8 firmware 2.014 -- in-camera 14-bit DNG, staged builds (docs/DNG_PLAN.md §8 step 5).

Every build starts from the stock file, applies the persistent-RAW patch (P1-P3 from
m8_rawpatch.py; the result must be the flashed build f6589c41...), then the changes of
one stage. Stages are not cumulative: each is a complete build, one flash per stage.

  Stage  Change                                                           Status
  1      Canary: RAW header u16[3] 7 -> 0xA5 (0x3CEA0 mov r0,#7)          camera-tested 2026-10-20
  2      Routine + template in ldimg, hook off (idle test)                not built yet
  3      Hook on, job metadata dump into the trailing row                 not built yet
  4      Hook on, real template + TIFF header, still .RAW                 not built yet
  5      Extension "RAW" -> "DNG"                                         not built yet

Safety checks run on every build (the build is refused if one fails):
  - input is the stock 2.014 file (SHA-256), base equals the flashed build;
  - each change finds the expected original bytes;
  - the output differs from the flashed build only inside the PXA lump, and there only in
    the regions the stage declares (REGIONS); every other lump is byte-identical;
  - every changed instruction is printed as Capstone disassembly at its real address.

Test before flashing: work/venv/bin/python tools/m8_savetest.py --stage N
Copy the output to the card as M8-2_014.UPD (the updater looks for M8.UPD / M8-x_yyy.UPD).

Usage: python3 m8_dngpatch.py firmware/stock/m8-2_014.upd firmware/patched/m8-2_014-stageN.upd --stage N
Needs: capstone (work/venv)
"""
import hashlib, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from m8_rawpatch import PATCHES as RAW_PATCHES, PXA_BASE, find_lump

STOCK_SHA = '99f5254847a92c68086f37b1a4140c359379801b479df12052136abb73f09ed0'
FLASHED_SHA = 'f6589c41a583d1a44fbce77c4acda707640d255acec97a0d2e1ac829c2e70396'

# Regions a stage may change (vaddr ranges, end exclusive). FINDINGS "Image save path",
# "Reclaimable space".
REGIONS = {
    'header': (0x3CE48, 0x3CF20),   # RAW header block in the store routine 0x3CA58
    'hook':   (0x3C6A8, 0x3C6AC),   # last-block branch of the RAW producer (b 0x3C5EC)
    'ldimg':  (0x28AB0, 0x29104),   # reclaimed debug command, incl. literal pool
    'ext':    (0xD6590, 0xD6594),   # "RAW\0" extension string
}

# stage -> (title, regions it may touch, [(name, vaddr, old bytes, new bytes)])
STAGES = {
    1: ('canary: RAW header u16[3] 7 -> 0xA5', {'header'}, [
        ('C1 header u16[3]', 0x3CEA0, bytes.fromhex('0700a0e3'), bytes.fromhex('a500a0e3')),
    ]),
}
PLANNED = {
    2: 'routine + template in ldimg, hook off (idle test)',
    3: 'hook on, job metadata dump into the trailing row',
    4: 'hook on, real template + TIFF header, still .RAW',
    5: 'extension "RAW" -> "DNG"',
}
KNOWN_OUTPUTS = {  # stage builds whose emulator run passed (see FINDINGS)
    '3f84b34a225aeebe3f5f18cb658d4b14028d49d98e1fd1d1366ccf25a5830e66':
        'stage 1, m8_savetest 32/0; flashed and camera-tested 2026-10-20',
}


def _apply(buf, pos, changes):
    for name, va, old, new in changes:
        off = pos + va - PXA_BASE
        cur = bytes(buf[off:off + len(old)])
        if cur != old:
            raise SystemExit(f'{name}: unexpected bytes {cur.hex()} at 0x{va:X} (want {old.hex()})')
        buf[off:off + len(new)] = new


def flashed_file(stock):
    """Stock .upd bytes -> the flashed persistent-RAW build (P1-P3), verified by hash."""
    if hashlib.sha256(stock).hexdigest() != STOCK_SHA:
        raise SystemExit('input is not the stock m8-2_014.upd (SHA-256 mismatch)')
    buf = bytearray(stock)
    pos, _ = find_lump(buf, b'PXA')
    _apply(buf, pos, RAW_PATCHES)
    if hashlib.sha256(buf).hexdigest() != FLASHED_SHA:
        raise SystemExit('RAW-patched base does not match the flashed build f6589c41')
    return bytes(buf)


def stage_file(stock, stage):
    """Stock .upd bytes -> (flashed build, stage build), region check passed."""
    if stage not in STAGES:
        why = PLANNED.get(stage, 'no such stage')
        raise SystemExit(f'stage {stage} ({why}) is not built yet')
    _, regions, changes = STAGES[stage]
    base = flashed_file(stock)
    buf = bytearray(base)
    pos, size = find_lump(buf, b'PXA')
    _apply(buf, pos, changes)
    bad = region_violations(base, bytes(buf), pos, size, regions)
    if bad:
        raise SystemExit('changes outside the declared regions: ' + ', '.join(bad))
    return base, bytes(buf)


def changed_ranges(a, b):
    """[(start, end)] of differing bytes between two equal-length buffers."""
    assert len(a) == len(b), 'size changed'
    out, i, n = [], 0, len(a)
    while i < n:
        if a[i] != b[i]:
            j = i
            while j < n and a[j] != b[j]:
                j += 1
            out.append((i, j))
            i = j
        else:
            i += 1
    return out


def region_violations(base, new, pos, size, regions):
    """File-level diff vs the flashed build; every changed byte must lie in a declared region."""
    allowed = [REGIONS[r] for r in regions]
    bad = []
    for s, e in changed_ranges(base, new):
        if not (pos <= s and e <= pos + size):
            bad.append(f'file 0x{s:X}-0x{e:X} (outside PXA lump)')
            continue
        va, vb = PXA_BASE + s - pos, PXA_BASE + e - pos
        if not any(lo <= va and vb <= hi for lo, hi in allowed):
            bad.append(f'0x{va:X}-0x{vb:X}')
    return bad


def pxa_of(upd):
    pos, size = find_lump(upd, b'PXA')
    return upd[pos:pos + size]


def show(base, new):
    """Disassemble every changed word, old and new, at its real address."""
    import capstone
    md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_ARM)
    pa, pb = pxa_of(base), pxa_of(new)
    words = sorted({(s & ~3) + k for s, e in changed_ranges(pa, pb) for k in range(0, e - (s & ~3), 4)})
    for o in words:
        va = PXA_BASE + o
        old = next(md.disasm(pa[o:o + 4], va), None)
        neu = next(md.disasm(pb[o:o + 4], va), None)
        fmt = lambda i, raw: f'{raw.hex()}  {i.mnemonic} {i.op_str}' if i else f'{raw.hex()}  (data)'
        print(f'  0x{va:X}: {fmt(old, pa[o:o + 4])}  ->  {fmt(neu, pb[o:o + 4])}')


def main():
    args = [a for a in sys.argv[1:]]
    if '--stage' not in args or len(args) != 4:
        raise SystemExit(__doc__)
    i = args.index('--stage')
    stage = int(args[i + 1])
    del args[i:i + 2]
    src, dst = args
    title = STAGES[stage][0] if stage in STAGES else PLANNED.get(stage, '?')
    print(f'stage {stage}: {title}')
    base, new = stage_file(open(src, 'rb').read(), stage)
    print('base: flashed persistent-RAW build', FLASHED_SHA[:8])
    show(base, new)
    pos, size = find_lump(new, b'PXA')
    n = sum(e - s for s, e in changed_ranges(base, new))
    print(f'differs from the flashed build in {n} byte(s), all inside declared regions '
          f'{sorted(STAGES[stage][1])}; other lumps identical')
    open(dst, 'wb').write(new)
    sha = hashlib.sha256(new).hexdigest()
    print('wrote', dst, 'sha256', sha)
    print('known build:', KNOWN_OUTPUTS.get(sha, 'no (run m8_savetest.py before flashing)'))


if __name__ == '__main__':
    main()
