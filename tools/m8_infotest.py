#!/usr/bin/env python3
"""
Emulator test of the INFO build (m8_dngpatch.py --stage 6) against stage 4 (the flashed build).

Runs the camera's real application key handler 0x44E30 (and the service gate 0x403F0) on both
builds, for every key code in every GUI state below, and records each call out of the handler
(with its arguments) and each memory write outside the stack. Every other firmware address is
a test failure (m8_emutest.Emu), so every dependency is accounted for.

Expected (FINDINGS "GUI"): the two builds behave identically, except for INFO ('i') in the normal
state, where stage 6 additionally shows camInfoMenu (0x58FE8(app+0x6F6C, 1)), writes
app+0x2548F = 1 and menu+0x99 = 0, and shows BodyDebugDataDialog (0x40360(app+0x70A4, 1)) --
the same calls and values as the camera's own service-mode path -- and nothing else.

Also checked: m8_info.s reassembles to the frozen bytes; stage 6 differs from stage 4 only in
the memtest and infokey regions; the only references into the new code are the INFO branch and
the debug-shell registration's pointer to the (stub) handler entry.

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
        (0x2ABD0, 0x2AF90)]         # new code (stage 6)
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


def main():
    verbose = '-v' in sys.argv
    res = Results(verbose)
    stock = open(os.path.join(ROOT, 'firmware/stock/m8-2_014.upd'), 'rb').read()
    _, s4 = d.stage_file(stock, 4)
    _, s6 = d.stage_file(stock, 6)
    p4, p6 = d.pxa_of(s4), d.pxa_of(s6)

    # 1. frozen bytes, regions, references
    res.check('m8_info.s reassembles to INFO_CODE',
              m8_asm.assemble(os.path.join(ROOT, 'tools/asm/m8_info.s')) == d.INFO_CODE, True)
    import hashlib
    res.check('stage 4 is the flashed build 55264b11',
              hashlib.sha256(s4).hexdigest()[:8], '55264b11')
    pos, size = d.find_lump(s6, b'PXA')
    res.check('stage 6 vs stage 4: changes only in memtest + infokey',
              d.region_violations(s4, s6, pos, size, {'memtest', 'infokey'}), [])
    lo, hi = d.REGIONS['memtest']
    refs = []
    for o in range(0, len(p6) - 3, 4):
        w, = struct.unpack_from('<I', p6, o)
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
    # 0x2DAC0: literal of the debug-command initializer 0x2C9F4 (loaded at 0x2CD10) = registration
    res.check('references into the new code', refs, ['word 0x2DAC0 = 0x2ABD0', 'branch 0x44F68'])

    # 2. key handler, every key in every state, stage 4 vs stage 6
    unknown = set()
    common = [('call', 'dance_tracker', 'app+0x0', '0x69'),     # every key, before the switch
              ('call', 'f_41788', 'app+0x0', '0x0'),
              ('call', 'timer_stop', 'app+0x2534C', '0x0')]
    expect_extra = [('call', 'show_page', 'app+0x6F6C', '0x1'),
                    ('write', 'app+0x2548F', 1, 1),
                    ('write', 'app+0x7005', 1, 0),
                    ('call', 'show', 'app+0x70A4', '0x1')]
    for state in STATES:
        diffs = []
        for key in range(256):
            t4, r4 = run(p4, state, key, unknown)
            t6, r6 = run(p6, state, key, unknown)
            if (t4, r4) != (t6, r6):
                diffs.append((key, t4, t6))
        if state == 'normal':
            res.check('normal state: only INFO differs', [chr(k) for k, _, _ in diffs], ['i'])
            if diffs:
                _, t4, t6 = diffs[0]
                res.check('INFO, stage 4: ignored (only the calls every key makes)', t4, common)
                res.check('INFO, stage 6: those + service-menu path to Body Debug Data', t6, common + expect_extra)
        else:
            res.check(f'{state}: stage 6 identical to stage 4 for all 256 keys', [k for k, _, _ in diffs], [])
        if verbose and state != 'normal':
            t, _ = run(p6, state, ord('i'), unknown)
            print(f'    INFO in {state}: {t}')
    res.check('no escapes to unlisted firmware code', sorted(unknown), [])
    print(f'{res.ok} passed, {res.bad} failed')
    sys.exit(1 if res.bad else 0)


if __name__ == '__main__':
    main()
