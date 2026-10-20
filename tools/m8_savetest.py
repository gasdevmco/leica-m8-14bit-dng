#!/usr/bin/env python3
"""
Emulated RAW save path for the M8 2.014 PXA image: a simulated shutter press runs the real
store routine and the real per-block DMA handler, and the bytes that reach the "card" are
compared with a real camera file. Base for testing every m8_dngpatch.py stage before flashing.

What runs as firmware code (REAL): store routine 0x3CA58 (file type, name, RAW header,
DMA set-up), DMA chain builder 0x3BFBC, DMA start 0x3C1E0, block handler 0x3C900, RAW
producer 0x3C5A4, ring buffer set-up/get-space/commit 0x3C454-0x3C5A4 and 0x3D2A0, string
append 0x8817C, 0x90064, memcpy 0xB3F78, division/modulo 0xCAB28-0xCAE54.

Modelled in Python (everything else is a test failure):
  - eCos mutex/flag calls (0xB4998, 0xB49A0, 0xB48BC setbits, 0xB48C0 maskbits, 0xB48C4 wait);
  - sensor/FPGA/GPIO control (0x94E2C, 0x94E98, 0x90C40, 0x90F2C), event post 0x98324,
    0x716F8 (resets the ctx+0x47C0 object at end of file);
  - geometry 0x90F9C (cached sensor table): RAW = 3976 samples x 2647 rows;
  - the PXA DMA controller: when DCSR1 gets RUN, the descriptor chain at DDADR1 is walked
    and filled from the "sensor" stream = the sample file's bytes after its header
    (0xEE once the stream is used up);
  - the card-writer task (writer object [ctx+0x4210] vtable +8 open, +0xC start,
    +0x10 kick, +0x18 finish): drains the ring exactly like 0x3D00C (contiguous readable),
    0x3D050 (consume, sets flag bit 0 once free >= margin) and 0x3D714 (rounding modes).
    Drain policies vary when it runs; the file must come out the same under all of them.

Checks (per build): file bytes vs the camera sample, file name, ring/DMA bookkeeping,
writes by the header block (0x3CE48-0x3CF20) same addresses as the flashed build, call
trace identical to the flashed build, only the type-0 path reaches the header block,
settings loader/menu unchanged (m8_emutest), declared-regions diff (m8_dngpatch).

Usage:  work/venv/bin/python tools/m8_savetest.py [--stage N] [--quick] [-v]
        (default: every built stage; --quick = one sample, one drain policy)
"""
import hashlib, os, struct, sys, time
from unicorn import UC_HOOK_MEM_WRITE, UC_MEM_WRITE
from unicorn.arm_const import UC_ARM_REG_PC

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import m8_dngpatch as dp
import m8_emutest as et
from m8_rawpatch import PXA_BASE

ROOT = et.ROOT
SAMPLES = ['sampleraws/L1031902.RAW', 'sampleraws/L1031901.RAW']
RAW_SIZE, HDR, ROW_BYTES, ROWS = 21_049_052, 108, 3976 * 2, 2647

STORE = 0x3CA58             # event 0x2AFB handler (0xEF110): store one image file
BLOCK_DONE = 0x3C900        # event 0x2AFA handler (0xEF100): DMA block complete
RING_SETUP = 0x3D2A0        # ctx vtable +0x3C: ring at 0x2841D00, 8 MB raw, align 0x200, margin 0x40000
REAL = [
    (0x3BFBC, 0x3C1F4),     # DMA chain builder, DMA start
    (0x3C454, 0x3C6B0),     # ring set-up, get-space, commit, RAW producer
    (0x3C900, 0x3D00C),     # block handler, store routine
    (0x3D2A0, 0x3D2D4),     # ring set-up method
    (0x8817C, 0x881F0),     # string append (file name)
    (0x90064, 0x9006C),     # returns 0
    (0xB3F78, 0xB40D4),     # memcpy
    (0xCAB28, 0xCAE54),     # unsigned divide / modulo
]
HEADER = dp.REGIONS['header']
DMA_BUF, DMA_PARITY = 0x026F44E0, 0x3E080   # CPU view of the DMA target (phys 0xA26F44E0)
PHYS = 0xA0000000                            # SDRAM physical base; CPU address = phys - PHYS
DCSR1, DDADR1, OSCR = 0x40000004, 0x40000210, 0x40A00010

# Emulator memory (inside the 64 MB RAM map; the firmware's own addresses are below 0x3042000)
CTX, JOB, MSG, W, W_VTBL = 0x3800000, 0x3810000, 0x3811000, 0x3812000, 0x3812100
NAMEBUF, DIRSTR, STATUS = 0x3813000, 0x3814000, 0x3815000
RAM = 0x4000000
SENT = et.SENTINEL + 0x200                   # writer vtable slot stubs
RING = CTX + 0x46C8
DIR = b'\\DCIM\\100LEICA\\L1031902.'

POLICIES = {  # card-writer behaviour: (unit drained on kick or None, unit drained when the producer waits)
    'eager':  (1, 1),               # writer keeps up completely
    'sector': (0x2000, 0x2000),     # 0x3D714 mode 1 on every kick
    'big':    (0x20C000, 0x2000),   # 0x3D714 mode 0 on kick; mode 1 when the ring is full
    'lazy':   (None, 0x2000),       # writer only runs when the producer blocks on a full ring
}


class Writer:
    """Card-writer task model over the firmware's ring struct (FINDINGS "Image save path")."""
    def __init__(self, e, policy):
        self.e, self.kick_unit, self.wait_unit = e, *POLICIES[policy]
        self.out = bytearray()
        self.waits = self.kicks = 0

    def f(self, off): return self.e.u32(RING + off)

    def readable(self):             # 0x3D00C
        count, w, r = self.f(0x18), self.f(0x10), self.f(0x14)
        if count == 0:
            return 0
        return w - r if w > r else self.f(8) - r

    def consume(self, n):           # 0x3D050
        e, size = self.e, self.f(8)
        e.w32(RING + 0x14, (self.f(0x14) + n) % size)
        e.w32(RING + 0x18, self.f(0x18) - n)
        if size - self.f(0x18) >= self.f(0xC):
            e.w32(RING + 0x20, e.u32(RING + 0x20) | 1)

    def drain(self, unit, until_space=False):   # 0x3D714: whole units unless the readable part wraps
        while True:
            if until_space and self.e.u32(RING + 0x20) & 1:
                return
            n = self.readable()
            if self.f(0x14) < self.f(0x10):     # 0x3D0C0 = 0: not wrapped -> round down
                n -= n % unit
            if n == 0:
                return
            self.out += self.e.read(self.f(0) + self.f(0x14), n)
            self.consume(n)

    def kick(self, e, *_):
        self.kicks += 1
        if self.kick_unit:
            self.drain(self.kick_unit)

    def wait(self, e, flag, pattern, mode):     # 0xB48C4 cyg_flag_wait(flag, 1, OR)
        assert (pattern, mode) == (1, 2), (pattern, mode)
        if not e.u32(flag) & pattern:
            self.waits += 1
            self.drain(self.wait_unit, until_space=True)
            assert e.u32(flag) & pattern, 'writer could not free space'
        return pattern

    def finish(self, e, *_):
        self.drain(1)


class SaveEmu(et.Emu):
    def __init__(self, pxa, sensor, policy='eager'):
        self.writer = Writer(self, policy)
        stubs = {
            0xB4998: 'mutex_lock', 0xB49A0: 'mutex_unlock',
            0xB48BC: flag_set, 0xB48C0: flag_mask, 0xB48C4: self.writer.wait,
            0x98324: 'event_post_98324', 0x94E2C: 'sensor_94e2c', 0x94E98: 'sensor_94e98',
            0x90C40: 'fpga_cmd_90c40', 0x90F2C: 'fpga_90f2c', 0x716F8: 'reset_obj_716f8',
            0x90F9C: geometry,
            SENT + 0x08: 'writer_open', SENT + 0x0C: 'writer_start',
            SENT + 0x10: self.writer.kick, SENT + 0x18: self.writer.finish,
        }
        super().__init__(pxa, real=REAL, stubs=stubs, ram=RAM, per_block=True)
        uc = self.uc
        uc.mem_map(0x40000000, 0x1000)          # DMA controller
        uc.mem_map(0x40A00000, 0x1000)          # OS timer
        uc.hook_add(UC_HOOK_MEM_WRITE, self._dma, begin=DCSR1, end=DCSR1 + 3)
        self.sensor, self.spos = sensor, 0
        self.chains = []                        # bytes moved per DMA run
        self.hdr_writes = []                    # (address, size, value) written by the header block

    def _align(self, uc, access, addr, size, value, _):
        super()._align(uc, access, addr, size, value, _)
        if access == UC_MEM_WRITE:
            pc = uc.reg_read(UC_ARM_REG_PC)
            if HEADER[0] <= pc < HEADER[1]:
                self.hdr_writes.append((addr, size, value & ((1 << 8 * size) - 1)))

    def _dma(self, uc, access, addr, size, value, _):
        if not value & 0x80000000:              # RUN
            return
        desc, moved = self.u32(DDADR1) - PHYS, 0
        while True:
            nxt, src, dst, cmd = struct.unpack('<4I', self.read(desc, 16))
            n = cmd & 0x1FFF
            chunk = self.sensor[self.spos:self.spos + n]
            self.spos += len(chunk)
            uc.mem_write(dst - PHYS, chunk + b'\xEE' * (n - len(chunk)))
            moved += n
            if nxt & 1:                         # STOP
                break
            desc = nxt - PHYS
        self.chains.append(moved)


def flag_set(e, flag, bits, _):
    e.w32(flag, e.u32(flag) | bits)


def flag_mask(e, flag, mask, _):
    e.w32(flag, e.u32(flag) & mask)


def geometry(e, out, typ, size):
    assert typ == 0, f'geometry for type {typ}'
    e.w32(out, ROW_BYTES // 2)
    e.w32(out + 4, ROWS)
    return out


def save(pxa, raw, policy='eager', bia=False):
    """One simulated RAW (or .BIA) shot through the real save path; returns the emulator."""
    e = SaveEmu(pxa, raw[HDR:], policy)
    # ring buffer, set up by the firmware's own method
    e.call(RING_SETUP, CTX, RING)
    # capture context: file-name buffer {ptr, len, cap}, writer object
    e.w32(CTX + 0x463C, NAMEBUF)
    e.w32(CTX + 0x4644, 0x100)
    e.w32(W, W_VTBL)
    for slot in (0x08, 0x0C, 0x10, 0x18):
        e.w32(W_VTBL + slot, SENT + slot)
    # job: RAW flag (+0x154) or BIA flag (+0x21A), directory/stem, header fields
    e.uc.mem_write(DIRSTR, DIR + b'\0')
    e.w32(JOB + 0x17C, DIRSTR)
    e.w32(JOB + 0x180, len(DIR))
    e.w32(JOB + 0x154, 1)
    e.uc.mem_write(JOB + 0x21A, bytes([bia]))
    e.w32(JOB + 0x210, 1)                       # header u16[16..18] (sample: 1, 0, 0)
    # message: +8 job, +0xC writer
    e.w32(MSG + 8, JOB)
    e.w32(MSG + 0xC, W)
    r = e.call(STORE, CTX, MSG)
    assert r == 0, f'store routine returned {r}'
    e.blocks = e.u32(CTX + 0x421C)
    e.w32(STATUS + 8, 4)                        # DCSR ENDINTR
    for i in range(e.blocks):
        assert e.u32(CTX + 0x4220) == i
        e.call(BLOCK_DONE, CTX, STATUS)
    e.name = e.cstr(NAMEBUF)
    e.done = e.read(CTX + 0x4630, 1)[0]
    return e


def branches_into(pxa, lo, hi):
    """Addresses of B/BL instructions (any condition) and literal words that target [lo, hi)
    from outside it."""
    out = []
    for o in range(0, len(pxa) - 3, 4):
        a = PXA_BASE + o
        if lo <= a < hi:
            continue
        w = struct.unpack_from('<I', pxa, o)[0]
        if (w >> 25) & 7 == 5 and w >> 28 != 0xF:
            off = w & 0xFFFFFF
            off -= (off & 0x800000) << 1
            if lo <= a + 8 + 4 * off < hi:
                out.append(a)
        elif lo <= w < hi:
            out.append(a)
    return out


def main():
    verbose = '-v' in sys.argv
    quick = '--quick' in sys.argv
    stages = sorted(dp.STAGES)
    if '--stage' in sys.argv:
        stages = [int(sys.argv[sys.argv.index('--stage') + 1])]
    R = et.Results(verbose)
    stock_upd = open(os.path.join(ROOT, 'firmware/stock/m8-2_014.upd'), 'rb').read()
    stock = dp.pxa_of(stock_upd)
    flashed_upd = dp.flashed_file(stock_upd)
    flashed = dp.pxa_of(flashed_upd)
    R.check('flashed build file on disk = generated base',
            hashlib.sha256(open(os.path.join(ROOT, 'firmware/patched/m8-2_014.upd'), 'rb').read())
            .hexdigest(), dp.FLASHED_SHA)
    builds = {'stock': stock, 'flashed': flashed}
    for n in stages:
        base, new = dp.stage_file(stock_upd, n)          # refuses on a region violation
        builds[f'stage{n}'] = dp.pxa_of(new)
        R.check(f'stage {n} declared regions vs flashed', dp.region_violations(
            base, new, *dp.find_lump(new, b'PXA'), dp.STAGES[n][1]), [])
    samples = SAMPLES[:1] if quick else SAMPLES
    policies = ['eager'] if quick else list(POLICIES)
    raws = {s: open(os.path.join(ROOT, s), 'rb').read() for s in samples}

    print('Save path: stock and flashed builds reproduce the camera files byte for byte')
    ref = {}
    for name in ('stock', 'flashed'):
        for s, raw in raws.items():
            for pol in policies if s == samples[0] else ['eager']:
                t = time.time()
                e = save(builds[name], raw, pol)
                out = bytes(e.writer.out)
                R.check(f'{name:7s} {os.path.basename(s)} {pol:6s} file == camera file '
                        f'({time.time() - t:.1f}s, {e.writer.kicks} kicks, {e.writer.waits} waits)',
                        (len(out), out == raw), (RAW_SIZE, True))
                if pol == 'eager':
                    ref[name, s] = e
    e = ref['flashed', samples[0]]
    R.check('file name', e.name, (DIR + b'RAW').decode())
    R.check('blocks / DMA bytes per block', (e.blocks, set(e.chains)), (166, {16 * ROW_BYTES}))
    R.check('DMA runs (one per block) / sensor bytes consumed', (len(e.chains), e.spos),
            (166, RAW_SIZE - HDR))
    R.check('end-of-file flag ctx+0x4630, ring empty', (e.done, e.u32(RING + 0x18)), (1, 0))
    R.check('ring geometry (base, size, margin)', (e.u32(RING), e.u32(RING + 8), e.u32(RING + 0xC)),
            (0x2841D00, 0x7C0000, 0x40000))
    R.check('stock/flashed call traces identical', ref['stock', samples[0]].calls == e.calls, True)
    # the header block is entered only from the type-0 (RAW/BIA) branch of the store routine
    R.check('branches/pointers into the header block', [hex(a) for a in branches_into(flashed, *HEADER)],
            ['0x3cd58'])

    for n in stages:
        b = f'stage{n}'
        pxa = builds[b]
        print(f'Stage {n}: {dp.STAGES[n][0]}')
        R.check(f'{b} branches/pointers into the header block',
                [hex(a) for a in branches_into(pxa, *HEADER)], ['0x3cd58'])
        for s, raw in raws.items():
            for pol in policies if s == samples[0] else ['eager']:
                e = save(pxa, raw, pol)
                out = bytes(e.writer.out)
                diff = [(s0, out[s0:e0].hex(), raw[s0:e0].hex()) for s0, e0 in dp.changed_ranges(out, raw)] \
                    if len(out) == len(raw) else 'size'
                want = {1: [(6, 'a5', '07')]}[n]
                R.check(f'{b} {os.path.basename(s)} {pol:6s} file vs camera file: differences', diff, want)
                if pol == 'eager' and s == samples[0]:
                    f = ref['flashed', s]
                    R.check(f'{b} file name', e.name, (DIR + b'RAW').decode())
                    R.check(f'{b} call trace == flashed', e.calls == f.calls, True)
                    R.check(f'{b} header-block write addresses == flashed ({len(f.hdr_writes)} writes)',
                            [(a, z) for a, z, _ in e.hdr_writes] == [(a, z) for a, z, _ in f.hdr_writes], True)
                    ring = e.u32(RING)
                    R.check(f'{b} header-block writes differing from flashed (ring offset, value)',
                            [(a - ring, v) for (a, _, v), (_, _, fv) in zip(e.hdr_writes, f.hdr_writes)
                             if v != fv], [(6, 0xA5)])
                    R.check(f'{b} DMA/ring bookkeeping == flashed', e.chains == f.chains and
                            (e.blocks, e.spos, e.done) == (f.blocks, f.spos, f.done), True)
        # .BIA (dark frame) uses the same type-0 path: the canary appears there too
        e = save(pxa, raws[samples[0]], 'eager', bia=True)
        f = save(flashed, raws[samples[0]], 'eager', bia=True)
        R.check(f'{b} .BIA: name, diff vs flashed .BIA', (e.name, dp.changed_ranges(bytes(e.writer.out),
                bytes(f.writer.out))), ((DIR + b'BIA').decode(), [(6, 7)]))
        # settings loader and SET menu behave exactly as on the flashed build
        same = all(et.run_loader(pxa, et.make_eeprom(pxa, p, c))['block'] ==
                   et.run_loader(flashed, et.make_eeprom(flashed, p, c))['block']
                   for p in (1, 3) for c in range(6))
        same &= all(et.run_menu(pxa, 1, c, sv) == et.run_menu(flashed, 1, c, sv)
                    for c in range(6) for sv in (False, True))
        R.check(f'{b} settings loader + SET menu == flashed', same, True)

    print(f'{R.ok} passed, {R.bad} failed')
    sys.exit(1 if R.bad else 0)


if __name__ == '__main__':
    main()
