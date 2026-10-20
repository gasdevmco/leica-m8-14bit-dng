#!/usr/bin/env python3
"""
Leica M8 firmware 2.014 -- in-camera 14-bit DNG, staged builds (docs/DNG_PLAN.md §8 step 5).

Every build starts from the stock file, applies the persistent-RAW patch (P1-P3 from
m8_rawpatch.py; the result must be the flashed build f6589c41...), then the pieces of one
stage. Stages are not cumulative: each is a complete build, one flash per stage.

  Stage  Pieces                          Proves                                Status
  1      canary                          we control file contents              camera-tested 2026-10-20
  2      canary, ldimg                   idle test: nothing else runs ldimg    emulator-tested
  3      canary, ldimg (dump), hook      metadata offsets, from the camera     emulator-tested
  4      tiff, ldimg, hook               first in-camera 14-bit DNG (.RAW)     emulator-tested
  5      tiff, ldimg, hook, ext          files named .DNG                      emulator-tested

Pieces (each in one declared region, REGIONS):
  canary  0x3CEA0 mov r0,#7 -> #0xA5: RAW header u16[3] = 0xA5
  tiff    0x3CE48-0x3CEFC header block rewritten (tools/asm/m8_header.s): u16[0..3] = TIFF header
  ldimg   0x28AB0-0x29104 dng_hook code (tools/asm/m8_dnghook.s) + mode/slot tables + IFD template
          (m8_wrapdng.build_template), rest filled with undefined instructions; entry = stub
          returning 0. "ldimg (dump)" = same bytes with mode 1 instead of 2.
  hook    0x3C6A8 b 0x3C5EC -> bl 0x28AB8 (RAW producer, last block)
  ext     0x3CFF8 store routine's "RAW" literal 0xD6590 -> "DNG" 0xD6570 (only reader: 0x3CCE0)

Assembled bytes are frozen here with their SHA-256; m8_savetest.py reassembles the sources and
fails if they no longer match.

Safety checks run on every build (the build is refused if one fails):
  - input is the stock 2.014 file (SHA-256), base equals the flashed build;
  - each piece finds the expected original bytes (or their SHA-256 for long regions);
  - the output differs from the flashed build only inside the PXA lump, and there only in
    the regions the stage's pieces declare; every other lump is byte-identical;
  - every changed instruction is printed as Capstone disassembly at its real address.

Test before flashing: work/venv/bin/python tools/m8_savetest.py --stage N
Copy the output to the card as M8-2_014.UPD (the updater looks for M8.UPD / M8-x_yyy.UPD).

Usage: python3 m8_dngpatch.py firmware/stock/m8-2_014.upd firmware/patched/m8-2_014-stageN.upd --stage N
Needs: capstone (work/venv)
"""
import hashlib, os, struct, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from m8_rawpatch import PATCHES as RAW_PATCHES, PXA_BASE, find_lump
import m8_wrapdng

STOCK_SHA = '99f5254847a92c68086f37b1a4140c359379801b479df12052136abb73f09ed0'
FLASHED_SHA = 'f6589c41a583d1a44fbce77c4acda707640d255acec97a0d2e1ac829c2e70396'

# Regions a stage may change (vaddr ranges, end exclusive). FINDINGS "Image save path",
# "Reclaimable space", "Staged DNG builds".
REGIONS = {
    'header': (0x3CE48, 0x3CF20),   # RAW header block in the store routine 0x3CA58
    'hook':   (0x3C6A8, 0x3C6AC),   # last-block branch of the RAW producer (b 0x3C5EC)
    'ldimg':  (0x28AB0, 0x29104),   # reclaimed debug command, incl. literal pool
    'ext':    (0x3CFF8, 0x3CFFC),   # store routine's literal -> "RAW" (0xD6590)
}

# tools/asm/m8_header.s at 0x3CE48 (46 instructions, replaces the stock block of the same size)
HEADER_TIFF = bytes.fromhex(
    '64301be5061097e7092097e7030097e770601be51032d1e51142d1e51252d1e520e4a0e1ff0000e222c4a0e1ff2002e2'
    '1fc00ce21fe00ee2bc01c6e1b421c6e1b6c1c6e1bee1c6e1b032c6e1b242c6e1b452c6e1490ca0e3490080e3b000c6e1'
    '2a20a0e3b220c6e10f3ca0e3cc3083e3b430c6e1050da0e3010080e3b600c6e1b8a0c6e1baa0c6e1bca0c6e1bea0c6e1'
    'b0a1c6e1b2a1c6e1b8a1c6e1baa1c6e1b6a2c6e1b8a2c6e1baa2c6e1e81081e24020a0e32c0086e2')
HEADER_TIFF_SHA = '4b8eda09af11190f7a0f65ba6830ee2f5ef2b07e31a62adf5a7b3d06d9b7ea23'
HEADER_STOCK_SHA = '93399af36122e9a734c63f84f258ba8933d85fd43a607d443c8f2e41f8bb4def'

# tools/asm/m8_dnghook.s at 0x28AB0 (stub, dng_hook, .Lcopy, literal pool; `tables` follows)
HOOK_CODE = bytes.fromhex(
    '0000a0e31eff2fe1f04f2de9728f8fe246cc84e234509ce51a12d5e5000051e35100001a42cc84e228109ce52c209ce5'
    '20a09ce584319fe5030051e180319f05030052014800001a78619fe501001ae374319f1503608610076086e0016046e0'
    '60319fe5030056e13f00003a5c319fe5030056e13c00008a009098e5020059e31f00000a010059e33700001a0600a0e1'
    '121e8fe20820a0e30fe0a0e1340000ea080086e2421c84e2101081e23020a0e30fe0a0e12e0000ead0042de9380086e2'
    '0d10a0e11020a0e30fe0a0e1280000ea10d08de2800086e20510a0e10a2da0e30fe0a0e1220000eae4109fe5001091e5'
    '030c86e2022ca0e30fe0a0e11c0000ea100000ea042098e508b098e50c9088e28b1189e00600a0e10fe0a0e1140000ea'
    '01b05be20700004ab200d9e0b210d9e0b420d9e0000086e0011085e00fe0a0e10b0000eaf5ffffea1f00c6e3021b86e2'
    '3a0f07ee360f07ee200080e2010050e1faffff3a0000a0e39a0f07eef04fbde8c0f04ee2060050e11eff2f3102c080e0'
    '00005ce11eff2f3130309fe5033086e003005ce11eff2f8138309fe503005ce11eff2f81012052e20130d1540130c054'
    'fbffff5a1eff2fe14d3844554d503031101f0000570a0000e0446f0280e00300e0bd760230420d00e0c57602')
HOOK_CODE_SHA = '9c61fa9d67f740ddc19b8ddd71658c8860b2171806cdbf8ccf9ce8b1f8a0442e'
HOOK_ENTRY = 0x28AB8                       # dng_hook
TABLES = 0x28AB0 + len(HOOK_CODE)          # `adr r8, tables` in dng_hook points here
LDIMG_STOCK_SHA = 'c28db4ffa67195ca427394eb3e21a6c2ff6e9a3a89a37ac0150f3e802019f6f5'
TEMPLATE_SHA = '5cb22fb2582678f4abacd6d0e85378179c3485f515d8251a3b0b683d1e564052'   # 902 bytes
UDF = bytes.fromhex('f000f0e7')            # permanently undefined: fills the unused rest of ldimg
MODE_DUMP, MODE_DNG = 1, 2


def template():
    t, slots = m8_wrapdng.build_template(m8_wrapdng.BLACK)
    if hashlib.sha256(t).hexdigest() != TEMPLATE_SHA:
        raise SystemExit('IFD template changed (m8_wrapdng.build_template); re-test and update TEMPLATE_SHA')
    return t, slots


def slot_table():
    """[(name, template offset, job offset, length)] for the per-shot slots held in S (job+4)."""
    _, slots = template()
    out = []
    for _, name, _, _, where in m8_wrapdng.SHOT_FIELDS:
        if where.startswith('S+'):          # AsShotNeutral (WB table) stays the template default
            off, n, _ = slots[name]
            out.append((name, off, 4 + int(where[2:], 16), n))
    return out


def tables(mode):
    t, _ = template()
    slots = slot_table()
    b = struct.pack('<3I', mode, len(t), len(slots))
    b += b''.join(struct.pack('<4H', off, src, n, 0) for _, off, src, n in slots)
    return b + t


def ldimg_blob(mode):
    if hashlib.sha256(HOOK_CODE).hexdigest() != HOOK_CODE_SHA:
        raise SystemExit('HOOK_CODE does not match its SHA-256')
    lo, hi = REGIONS['ldimg']
    b = HOOK_CODE + tables(mode)
    b += b'\0' * (-len(b) % 4)
    if len(b) > hi - lo:
        raise SystemExit(f'ldimg overflow: {len(b)} > {hi - lo} bytes')
    return b + UDF * ((hi - lo - len(b)) // 4)


def bl(src, dst):
    return struct.pack('<I', 0xEB000000 | (((dst - src - 8) >> 2) & 0xFFFFFF))


def pieces():
    """name -> (region, vaddr, old bytes or SHA-256 of them, new bytes)"""
    if hashlib.sha256(HEADER_TIFF).hexdigest() != HEADER_TIFF_SHA:
        raise SystemExit('HEADER_TIFF does not match its SHA-256')
    lo, hi = REGIONS['ldimg']
    return {
        'canary': ('header', 0x3CEA0, bytes.fromhex('0700a0e3'), bytes.fromhex('a500a0e3')),
        'tiff': ('header', 0x3CE48, HEADER_STOCK_SHA, HEADER_TIFF),
        'ldimg': ('ldimg', lo, LDIMG_STOCK_SHA, ldimg_blob(MODE_DNG)),
        'ldimg (dump)': ('ldimg', lo, LDIMG_STOCK_SHA, ldimg_blob(MODE_DUMP)),
        'hook': ('hook', 0x3C6A8, bytes.fromhex('cfffffea'), bl(0x3C6A8, HOOK_ENTRY)),
        'ext': ('ext', 0x3CFF8, struct.pack('<I', 0xD6590), struct.pack('<I', 0xD6570)),
    }


# stage -> (title, pieces)
STAGES = {
    1: ('canary: RAW header u16[3] 7 -> 0xA5', ['canary']),
    2: ('dng_hook + template in ldimg, hook off (idle test); canary kept', ['canary', 'ldimg']),
    3: ('hook on, job metadata dump into the trailing row; canary kept', ['canary', 'ldimg (dump)', 'hook']),
    4: ('hook on, TIFF header + IFD template: 14-bit DNG content, still named .RAW', ['tiff', 'ldimg', 'hook']),
    5: ('as stage 4, files named .DNG', ['tiff', 'ldimg', 'hook', 'ext']),
}
KNOWN_OUTPUTS = {  # stage builds whose emulator run passed (see FINDINGS)
    '3f84b34a225aeebe3f5f18cb658d4b14028d49d98e1fd1d1366ccf25a5830e66':
        'stage 1, m8_savetest 32/0; flashed and camera-tested 2026-10-20',
    '3b451b4d7da62621179995ba11fa5962f347c7aa9d82e99a9e156e7801ee6e25':
        'stage 4, first version (date slot S+0x20, wrong); flashed 2026-10-20, Lightroom opens its files',
    '98011d7b48243917dee3807eda547719a50204f2576bea289d45c5473609a88b': 'stage 2, m8_savetest 145/0 (2026-10-20); not flashed',
    'c152d30593e52e41ebdb44f1b9573f5a113e5d52e34066d79fc6b48ead2dd526': 'stage 3, m8_savetest 145/0 (2026-10-20); not flashed',
    '59aff4a35f5c8fea4ca1fc8ab962ac3e0ac171131bd82410cf67c9231665273c': 'stage 4, date fixed, m8_savetest 145/0 (2026-10-20); not flashed',
    'd9a94feb9fba2681f46ba0f1e78ad75ed1e9383c088b0b0e3cba0f3b40333e66': 'stage 5, date fixed, m8_savetest 145/0; flashed 2026-10-20, Lightroom imports its DNGs',
}


def stage_regions(stage):
    p = pieces()
    return {p[name][0] for name in STAGES[stage][1]}


def _apply(buf, pos, changes):
    for name, va, old, new in changes:
        off = pos + va - PXA_BASE
        cur = bytes(buf[off:off + len(new)])
        ok = hashlib.sha256(cur).hexdigest() == old if isinstance(old, str) else cur == old
        if not ok:
            raise SystemExit(f'{name}: unexpected original bytes at 0x{va:X}')
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
        raise SystemExit(f'no stage {stage}')
    p = pieces()
    names = STAGES[stage][1]
    regions = [p[n][0] for n in names]
    if len(set(regions)) != len(regions):
        raise SystemExit(f'stage {stage}: two pieces in one region')
    base = flashed_file(stock)
    buf = bytearray(base)
    pos, size = find_lump(buf, b'PXA')
    _apply(buf, pos, [(n, *p[n][1:]) for n in names])
    bad = region_violations(base, bytes(buf), pos, size, set(regions))
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
    """Disassemble every changed instruction word, old and new, at its real address; the data
    part of ldimg (tables, template, fill) is summarised."""
    import capstone
    md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_ARM)
    pa, pb = pxa_of(base), pxa_of(new)
    words = sorted({(s & ~3) + k for s, e in changed_ranges(pa, pb) for k in range(0, e - (s & ~3), 4)})
    lo, hi = REGIONS['ldimg']
    data = [o for o in words if TABLES <= PXA_BASE + o < hi]
    for o in words:
        va = PXA_BASE + o
        if TABLES <= va < hi:
            continue
        old = next(md.disasm(pa[o:o + 4], va), None)
        neu = next(md.disasm(pb[o:o + 4], va), None)
        fmt = lambda i, raw: f'{raw.hex()}  {i.mnemonic} {i.op_str}' if i else f'{raw.hex()}  (data)'
        print(f'  0x{va:X}: {fmt(old, pa[o:o + 4])}  ->  {fmt(neu, pb[o:o + 4])}')
    if data:
        b = pb[TABLES - PXA_BASE:hi - PXA_BASE]
        mode, tlen, nslots = struct.unpack_from('<3I', b)
        used = 12 + 8 * nslots + tlen
        print(f'  0x{TABLES:X}-0x{hi:X}: data -- mode {mode}, {nslots} slots, template {tlen} bytes '
              f'(sha {hashlib.sha256(b[12 + 8 * nslots:used]).hexdigest()[:8]}), '
              f'{hi - TABLES - used} bytes padding/undefined fill')


def main():
    args = [a for a in sys.argv[1:]]
    if '--stage' not in args or len(args) != 4:
        raise SystemExit(__doc__)
    i = args.index('--stage')
    stage = int(args[i + 1])
    del args[i:i + 2]
    src, dst = args
    if stage not in STAGES:
        raise SystemExit(f'no stage {stage}')
    print(f'stage {stage}: {STAGES[stage][0]}')
    base, new = stage_file(open(src, 'rb').read(), stage)
    print('base: flashed persistent-RAW build', FLASHED_SHA[:8], '; pieces:', ', '.join(STAGES[stage][1]))
    show(base, new)
    n = sum(e - s for s, e in changed_ranges(base, new))
    print(f'differs from the flashed build in {n} byte(s), all inside declared regions '
          f'{sorted(stage_regions(stage))}; other lumps identical')
    open(dst, 'wb').write(new)
    sha = hashlib.sha256(new).hexdigest()
    print('wrote', dst, 'sha256', sha)
    print('known build:', KNOWN_OUTPUTS.get(sha, 'no (run m8_savetest.py before flashing)'))


if __name__ == '__main__':
    main()
