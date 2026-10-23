#!/usr/bin/env python3
"""
Render and test the INFO screens (stage 8: tools/asm/m8_infostats.s; stage 7: m8_infoscreens.s) by running the camera's
own GUI code in Unicorn: the dialog's base paint 0x605AC, the GUI's fill / line / text routines
with the real FONT1 / FONT2 registered by the real 0x886FC, our title / content / key methods.
The display object is faked to hand out an emulated 320x240x3 framebuffer, which is saved as PNG.

Inputs faked (everything else is firmware code; any other address is a failure):
  - the last displayed image (app+0x251A8): a camera JPG scaled to 320x240 like the review image,
    or none;
  - the body debug data (0x3E238, command 0x33): fixed field values written into the dialog
    buffer, or a failure code;
  - the dialog object: geometry 0,0,320,240 (as constructed by 0x6046C), our method table.

Checks: the frozen stage-7 bytes equal the reassembled source; every store made by our code goes
to the framebuffer or the stack; on_key switches pages, closes through the dialog's own SET path
with its own method table restored, ignores other keys.

Usage:  work/venv/bin/python tools/m8_inforender.py [image.JPG] [--stage 7|8|10] [--out DIR] [-v]
Needs:  unicorn, Pillow (work/venv)
"""
import os, struct, sys
from unicorn import UC_HOOK_MEM_WRITE
from unicorn.arm_const import (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3,
                               UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import m8_dngpatch as d
import m8_asm
from m8_emutest import Emu, Escape, Results, STACK, SENTINEL
from m8_rawpatch import PXA_BASE

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
# stage -> (source, region in m8_dngpatch.REGIONS, frozen-bytes attribute in m8_dngpatch)
STAGES = {7: ('tools/asm/m8_infoscreens.s', 'bfmem', 'SCREENS_CODE'),
          8: ('tools/asm/m8_infostats.s', 'memtest12', 'STATS_CODE'),
          10: ('tools/asm/m8_infostats.s', 'memtest12', 'STATS_CODE')}   # Option 1 + INFO
STAGE = 8
SRC = os.path.join(ROOT, STAGES[STAGE][0])
LO, HI = d.REGIONS[STAGES[STAGE][1]]       # region of the new code
APP, FONTS, FB, DISP, DLG, IMG = 0x1000000, 0x2000000, 0x3000000, 0x3100000, 0x3200000, 0x3300000
CTX2 = 0x3400000
REAL = [(0x605AC, 0x606B4),                 # dialog base paint
        (0x886FC, 0x88768),                 # font registration
        (0x88990, 0x88A00),                 # string lookup used by 0x996EC
        (0x95000, 0x95600),                 # pixel offset
        (0x98A40, 0x9A400),                 # GUI drawing: fill, lines, text
        (0xB3000, 0xBE000),                 # C library: memcpy, memset, sprintf
        (0xC7000, 0xCD000),                 # printf engine, integer divide / modulo
        (0xCD34C, 0xCD378)]                 # window getters x, y, w, h, nop methods
DLG_VT = 0xED1B8


def configure(stage):
    """Select the build under test (sets SRC, LO, HI)."""
    global STAGE, SRC, LO, HI
    STAGE = stage
    SRC = os.path.join(ROOT, STAGES[stage][0])
    LO, HI = d.REGIONS[STAGES[stage][1]]
BODY = {0xE4: (4, 12345), 0xC8: (1, 3), 0xC4: (4, 31), 0xDD: (1, 6)}   # NumExposures, battery, temp, lens


def gui_lumps(upd):
    def lumps(base):
        n, off = struct.unpack_from('<II', upd, base + 4)
        for i in range(n):
            o, s, nm = struct.unpack_from('<II8s', upd, base + off + 16 * i)
            yield nm.split(b'\0')[0].decode('latin1'), base + o, s
    for nm, o, _ in lumps(0):
        if nm == 'GUI':
            return {n: upd[o2:o2 + s2] for n, o2, s2 in lumps(o)}


def build_pxa(stock):
    """PXA of the selected stage from the patch script (frozen bytes); checks them against the source."""
    _, sn = d.stage_file(stock, STAGE)
    code = m8_asm.assemble(SRC)
    assert code == getattr(d, STAGES[STAGE][2]), f'frozen bytes differ from {STAGES[STAGE][0]}'
    return d.pxa_of(sn), code


class Screen:
    def __init__(self, pxa, gui, image, body_ok=True):
        self.calls, self.bad_writes = [], []
        stubs = {0x3E238: self._body}
        self.body_ok = body_ok
        self.e = e = Emu(pxa, real=[(LO, HI)] + REAL, stubs=stubs, ram=0x200000)
        uc = e.uc
        for base, size in ((APP, 0x30000), (FONTS, 0x400000), (FB, 0x40000), (DISP, 0x1000),
                           (DLG, 0x1000), (IMG, 0x40000), (CTX2, 0x10000)):
            uc.mem_map(base, size)
        uc.mem_write(FONTS, gui['FONT1'])
        uc.mem_write(FONTS + 0x200000, gui['FONT2'])
        e.call(0x886FC, FONTS, len(gui['FONT1']))           # -> font 3
        e.call(0x886FC, FONTS + 0x200000, len(gui['FONT2']))  # -> font 4
        # display object: vtable +0x14 = framebuffer; +0x10 bytes per pixel
        vt = DISP + 0x100
        for i in range(0, 0x40, 4):
            e.w32(vt + i, SENTINEL + 0x200 + i)
            e.stubs[SENTINEL + 0x200 + i] = self._disp(i)
        e.w32(DISP, vt)
        for off, v in {4: 320, 8: 240, 0xC: 960, 0x10: 3}.items():
            e.w32(DISP + off, v)
        e.w32(0x17F988, DISP)
        e.w32(0x17F984, 320)
        e.w32(0x17F980, 240)
        e.w32(0xD4220, APP)
        e.w32(0xD421C, CTX2)
        if image is not None:
            uc.mem_write(IMG, image)
            e.w32(APP + 0x251A8, IMG)
        # dialog: geometry as 0x6046C builds it (getters +0x18 x, +0x1C y, +0x14 w, +0x10 h)
        for off, v in {0x10: 240, 0x14: 320, 0x18: 0, 0x1C: 0}.items():
            e.w32(DLG + off, v)
        e.stubs[0x9A47C] = self._stub('redraw')            # method +0x1C
        e.stubs[0x61868] = self._stub('dialog_key')        # dialog's own key method
        self.ours = set()
        uc.hook_add(UC_HOOK_MEM_WRITE, self._write)

    def _disp(self, slot):
        def fn(emu, r0, r1, r2):
            if slot == 0x14:
                return FB
            self.calls.append(('display', hex(slot)))
            return 0
        fn.__name__ = f'display_{slot:x}'
        return fn

    def _stub(self, name):
        def fn(emu, r0, r1, r2):
            self.calls.append((name, r0, r1))
            return 0
        fn.__name__ = name
        return fn

    def _body(self, emu, r0, r1, r2):
        self.calls.append(('body_data', r0, r1))
        if not self.body_ok:
            return 1
        for off, (size, v) in BODY.items():
            emu.uc.mem_write(r1 - 0xB0 + off, v.to_bytes(size, 'little'))
        return 0

    def _write(self, uc, access, addr, size, value, _):
        pc = uc.reg_read(UC_ARM_REG_PC)
        if LO <= pc < HI:
            ok = FB <= addr < FB + 320 * 240 * 3 or STACK <= addr < STACK + 0x10000
            if not ok:
                self.bad_writes.append((hex(pc), hex(addr), size))

    def call(self, fn, *args):
        return self.e.call(fn, *args)

    def png(self, path):
        from PIL import Image
        img = Image.frombytes('RGB', (320, 240), self.e.read(FB, 320 * 240 * 3))
        img.resize((640, 480), Image.NEAREST).save(path)


def review_image(path):
    """A camera JPG as the review buffer holds it: 320x240 RGB, the 3:2 photo in rows 13..226."""
    from PIL import Image
    im = Image.open(path).convert('RGB').resize((320, 214), Image.BILINEAR)
    canvas = Image.new('RGB', (320, 240))
    canvas.paste(im, (0, 13))
    return canvas.tobytes()


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('-')]
    verbose = '-v' in sys.argv
    for opt in ('--out', '--stage'):
        if opt in sys.argv:
            args.remove(sys.argv[sys.argv.index(opt) + 1])
    out = sys.argv[sys.argv.index('--out') + 1] if '--out' in sys.argv else os.path.join(ROOT, 'work')
    configure(int(sys.argv[sys.argv.index('--stage') + 1]) if '--stage' in sys.argv else 8)
    jpg = args[0] if args else os.path.join(ROOT, 'fromcameraimports/L1031949.JPG')
    res = Results(verbose)
    stock = open(os.path.join(ROOT, 'firmware/stock/m8-2_014.upd'), 'rb').read()
    gui = gui_lumps(stock)
    pxa, code = build_pxa(stock)
    sym = symbols()
    vt_stats = LO + sym['vt_stats']
    vt_hist = LO + sym['vt_hist'] if 'vt_hist' in sym else None
    os.makedirs(out, exist_ok=True)

    screens = [('stats', review_image(jpg), vt_stats, True), ('stats-nodata', None, vt_stats, False)]
    if vt_hist:
        screens = [('hist', review_image(jpg), vt_hist, True), ('hist-noimage', None, vt_hist, True)] + screens
    for name, image, page, body_ok in screens:
        s = Screen(pxa, gui, image, body_ok)
        s.e.w32(DLG, page)
        try:
            s.call(0x605AC, DLG)
            err = None
        except Escape as x:
            err = str(x)
        res.check(f'{name}: paint runs to the end', err, None)
        res.check(f'{name}: our stores only to framebuffer / stack', s.bad_writes[:5], [])
        p = os.path.join(out, f'info{STAGE}-{name}.png')
        s.png(p)
        if verbose:
            print('   ', p, s.calls)

    # keys
    s = Screen(pxa, gui, None)
    def key(page, k):
        s.calls.clear()
        s.e.w32(DLG, page)
        s.call(LO + sym['on_key'], DLG, k)
        return s.e.u32(DLG), list(s.calls)
    close = (DLG_VT, [('dialog_key', DLG, ord('s'))])
    if vt_hist:
        res.check('INFO on "Last shot": stats page + redraw', key(vt_hist, ord('i')),
                  (vt_stats, [('redraw', DLG, ord('i'))]))
        res.check('SET on "Last shot": own methods back, dialog SET path', key(vt_hist, ord('s')), close)
    res.check('INFO on "Camera stats": own methods back, dialog SET path', key(vt_stats, ord('i')), close)
    res.check('SET on "Camera stats": same', key(vt_stats, ord('s')), close)
    first = vt_hist or vt_stats
    others = [k for k in range(256) if k not in (ord('i'), ord('s')) and key(first, k) != (first, [])]
    res.check('every other key ignored', others, [])
    print(f'{res.ok} passed, {res.bad} failed; PNGs in {out}')
    sys.exit(1 if res.bad else 0)


def symbols():
    """label -> offset, from the assembled object (clang + llvm-nm)."""
    import subprocess, tempfile
    with tempfile.TemporaryDirectory() as t:
        obj = os.path.join(t, 'o.o')
        subprocess.run(['clang', *m8_asm.FLAGS, SRC, '-o', obj], check=True)
        nm = subprocess.run(['xcrun', 'llvm-nm', obj], capture_output=True, text=True, check=True).stdout
    return {n: int(v, 16) for v, t_, n in (l.split() for l in nm.splitlines() if len(l.split()) == 3)
            if t_ in 'tT'}


if __name__ == '__main__':
    main()
