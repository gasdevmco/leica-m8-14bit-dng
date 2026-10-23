#!/usr/bin/env python3
"""
Emulator test of the INFO builds (m8_dngpatch.py --stage 6, 7 and 8) against stage 4.

Runs the camera's real application key handler 0x44E30 (and the service gate 0x403F0) on both
builds, for every key code in every GUI state below, and records each call out of the handler
(with its arguments) and each memory write outside the stack. Every other firmware address is
a test failure (m8_emutest.Emu), so every dependency is accounted for.

Expected (FINDINGS "GUI"): each build behaves like stage 4, except for INFO ('i') in the normal
state, where it additionally shows camInfoMenu (0x58FE8(app+0x6F6C, 1)), writes app+0x2548F = 1
and menu+0x99 = 0, and shows BodyDebugDataDialog (0x40360(app+0x70A4, 1)) -- the same calls and
values as the camera's own service-mode path -- and nothing else; stage 7 also points the dialog
at its own method table (one word, dialog+0 = vt_hist) before showing it.

Also checked: the sources reassemble to the frozen bytes; each build differs from stage 4 only in
its code region and infokey; the only references into the new code are the INFO branch and the
debug-shell registrations' pointers to the (stub) command entries.

Usage:  work/venv/bin/python tools/m8_infotest.py [-v]
Needs:  unicorn, capstone (work/venv); clang for the reassembly check
"""
import os, struct, sys
from unicorn import UC_HOOK_MEM_WRITE
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_SP

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import m8_dngpatch as d
import m8_asm
from m8_emutest import Emu, Escape, Results, STACK, SENTINEL, P_SVC_BASE, SVC_MAGIC
from m8_rawpatch import PXA_BASE

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
KEY_HANDLER = 0x44E30
APP = 0x1000000                     # fake GUI application object (app = [0xD4220] on the camera)
APP_SIZE = 0x30000
CTX2 = 0x1100000                    # fake object behind [0xD421C] (body link etc.)
MENU = APP + 0x6F6C                 # camInfoMenu
DIALOG = MENU + 0x138               # BodyDebugDataDialog

REAL = [(KEY_HANDLER, 0x450AC),     # application key handler incl. its literal pool
        (0x403F0, 0x40410),         # service-mode gate
        (0x2ABD0, 0x2B6E8)]         # new code (stage 6: up to 0x2AF90; stage 8: 0x2B0E8; stage 7)
# Calls out of the handler. Each records (name, r0, r1); none has side effects here.
STUB_ADDRS = {
    0x41F64: 'key_when_254a8',      # tail call when app+0x254A8 bit 0 is set
    0x44C64: 'dance_tracker',
    0x41788: 'f_41788',
    0x8BB88: 'timer_stop',
    0x58FE8: 'show_page',           # (page, 1)
    0x40360: 'show',                # (window, show)
    0x66074: 'show_lensinfo',
    0x44D24: 'play_key',
    0x9AF84: 'menu_item_9af84',
    0x4E440: 'show_set_menu',       # SET key: tail call (app+0x425C, 1)
}
STATES = {  # name -> (app+0x254A0 service word, app+0x25741, app+0x254A8, [0x169CC8], app+0x2548C)
    'normal':   (0, 0, 0, 0, 0),
    'service':  (SVC_MAGIC, 0, 0, 0, 0),
    'lensinfo': (0, 1, 0, 0, 0),
    'svc+lens': (SVC_MAGIC, 1, 0, 0, 0),
    '254a8':    (0, 0, 1, 0, 0),
    '169cc8':   (0, 0, 0, 1, 0),
    '2548c':    (0, 0, 0, 0, 1),
}


def rel(v):
    if APP <= v < APP + APP_SIZE:
        return f'app+0x{v - APP:X}'
    if CTX2 <= v < CTX2 + APP_SIZE:
        return f'ctx2+0x{v - CTX2:X}'
    return f'0x{v:X}'


def run(pxa, state, key, unknown):
    """-> (trace list, return value). trace = calls and non-stack writes, in order."""
    trace = []
    stubs = {}
    for addr, name in STUB_ADDRS.items():
        def fn(emu, r0, r1, r2, name=name):
            trace.append(('call', name, rel(r0), rel(r1)))
            return 0
        fn.__name__ = name
        stubs[addr] = fn
    e = Emu(pxa, real=REAL, stubs=stubs, ram=0x200000)
    uc = e.uc
    uc.mem_map(APP, APP_SIZE)
    uc.mem_map(CTX2, APP_SIZE)
    e.w32(P_SVC_BASE, APP)          # [0xD4220] -> app
    e.w32(0xD421C, CTX2)            # [0xD421C] -> ctx2
    svc, lens, b254a8, g169, b2548c = STATES[state]
    e.w32(APP + 0x254A0, svc)
    uc.mem_write(APP + 0x25741, bytes([lens]))
    uc.mem_write(APP + 0x254A8, bytes([b254a8]))
    uc.mem_write(0x169CC8, bytes([g169]))
    uc.mem_write(APP + 0x2548C, bytes([b2548c]))

    def on_write(uc_, access, addr, size, value, _):
        if not STACK <= addr < STACK + 0x10000:
            trace.append(('write', rel(addr), size, value & ((1 << 8 * size) - 1)))
    uc.hook_add(UC_HOOK_MEM_WRITE, on_write)
    try:
        ret = e.call(KEY_HANDLER, APP, key)
    except Escape as x:
        unknown.add(str(x))
        return trace + [('escape', str(x))], None
    if e.uc.reg_read(UC_ARM_REG_SP) != STACK + 0xF000:
        trace.append(('sp not restored',))
    return trace, ret


def refs_into(pxa, lo, hi):
    refs = []
    for o in range(0, len(pxa) - 3, 4):
        w, = struct.unpack_from('<I', pxa, o)
        va = PXA_BASE + o
        if lo <= va < hi:
            continue
        if (w & 0x0E000000) == 0x0A000000:                  # B / BL (any condition)
            off = w & 0xFFFFFF
            off -= (off & 0x800000) << 1
            if lo <= va + 8 + 4 * off < hi:
                refs.append(f'branch 0x{va:X}')
        if lo <= w < hi:
            refs.append(f'word 0x{va:X} = 0x{w:X}')
    return refs


def vt_address(stage, label):
    """Address of a method table in a stage's code (from the assembled source's symbols)."""
    import m8_inforender
    m8_inforender.configure(stage)
    return m8_inforender.LO + m8_inforender.symbols()[label]


def main():
    verbose = '-v' in sys.argv
    res = Results(verbose)
    stock = open(os.path.join(ROOT, 'firmware/stock/m8-2_014.upd'), 'rb').read()
    _, s4 = d.stage_file(stock, 4)
    p4 = d.pxa_of(s4)
    import hashlib
    res.check('stage 4 is the flashed build 55264b11', hashlib.sha256(s4).hexdigest()[:8], '55264b11')
    res.check('m8_info.s reassembles to INFO_CODE',
              m8_asm.assemble(os.path.join(ROOT, 'tools/asm/m8_info.s')) == d.INFO_CODE, True)
    res.check('m8_infoscreens.s reassembles to SCREENS_CODE',
              m8_asm.assemble(os.path.join(ROOT, 'tools/asm/m8_infoscreens.s')) == d.SCREENS_CODE, True)
    res.check('m8_infostats.s reassembles to STATS_CODE',
              m8_asm.assemble(os.path.join(ROOT, 'tools/asm/m8_infostats.s')) == d.STATS_CODE, True)

    common = [('call', 'dance_tracker', 'app+0x0', '0x69'),     # every key, before the switch
              ('call', 'f_41788', 'app+0x0', '0x0'),
              ('call', 'timer_stop', 'app+0x2534C', '0x0')]
    open_menu = [('call', 'show_page', 'app+0x6F6C', '0x1'),
                 ('write', 'app+0x2548F', 1, 1),
                 ('write', 'app+0x7005', 1, 0)]
    show_dialog = [('call', 'show', 'app+0x70A4', '0x1')]
    # registration literals of the debug-command initializer 0x2C9F4 (FINDINGS "Reclaimable space")
    stages = {
        6: ('memtest', ['word 0x2DAC0 = 0x2ABD0', 'branch 0x44F68'], open_menu + show_dialog),
        7: ('bfmem', ['word 0x2DAB0 = 0x2B4B0', 'word 0x2DAC0 = 0x2ABD0', 'word 0x2DACC = 0x2B0E0',
                      'word 0x2DAD8 = 0x2B338', 'branch 0x44F68'],
            open_menu + [('write', 'app+0x70A4', 4, vt_address(7, 'vt_hist'))] + show_dialog),
        8: ('memtest12', ['word 0x2DAC0 = 0x2ABD0', 'word 0x2DACC = 0x2B0E0', 'branch 0x44F68'],
            open_menu + [('write', 'app+0x70A4', 4, vt_address(8, 'vt_stats'))] + show_dialog),
    }
    unknown = set()
    for n, (region, want_refs, extra) in stages.items():
        _, sn = d.stage_file(stock, n)
        pn = d.pxa_of(sn)
        pos, size = d.find_lump(sn, b'PXA')
        res.check(f'stage {n} vs stage 4: changes only in {region} + infokey',
                  d.region_violations(s4, sn, pos, size, {region, 'infokey'}), [])
        res.check(f'stage {n}: references into the new code', refs_into(pn, *d.REGIONS[region]), want_refs)
        # key handler, every key in every state, stage 4 vs stage n
        for state in STATES:
            diffs = []
            for key in range(256):
                t4, r4 = run(p4, state, key, unknown)
                tn, rn = run(pn, state, key, unknown)
                if (t4, r4) != (tn, rn):
                    diffs.append((key, t4, tn))
            if state == 'normal':
                res.check(f'stage {n}, normal state: only INFO differs', [chr(k) for k, _, _ in diffs], ['i'])
                if diffs:
                    _, t4, tn = diffs[0]
                    res.check(f'stage {n}, INFO: stage 4 ignores it (only the calls every key makes)', t4, common)
                    res.check(f'stage {n}, INFO: + service-menu path to the dialog', tn, common + extra)
            else:
                res.check(f'stage {n}, {state}: identical to stage 4 for all 256 keys', [k for k, _, _ in diffs], [])
    res.check('no escapes to unlisted firmware code', sorted(unknown), [])
    print(f'{res.ok} passed, {res.bad} failed')
    sys.exit(1 if res.bad else 0)

if __name__ == '__main__':
    main()
