#!/usr/bin/env python3
"""
Unicorn harness: run the M8 2.014 settings loader and SET-menu loader on stock and
patched PXA code and check that the persistent-RAW patch behaves as documented in
docs/FINDINGS.md.

Only the functions listed in REAL run as firmware code; the calls listed in STUBS are
replaced by Python. Execution reaching any other address is a test failure, so every
external dependency is accounted for.

Usage:  python3 tools/m8_emutest.py [stock.upd] [patched.upd] [-v]
Needs:  pip install unicorn
"""
import hashlib, os, struct, sys
from unicorn import (Uc, UcError, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE, UC_HOOK_MEM_INVALID,
                     UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE)
from unicorn.arm_const import *

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from m8_rawpatch import PATCHES, PXA_BASE, find_lump

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
STOCK_SHA = '99f5254847a92c68086f37b1a4140c359379801b479df12052136abb73f09ed0'
PATCHED_SHA = 'f6589c41a583d1a44fbce77c4acda707640d255acec97a0d2e1ac829c2e70396'

# Firmware addresses (2.014; see FINDINGS)
SETTINGS_LOAD = 0x21848      # settings loader, called from 0x35DA8 with r0 = [0xD4230]
SETTINGS_DEFAULTS = 0x21798  # reset whole block to defaults
CRC32 = 0xBD0F4              # crc32(buf, len), init 0, no final xor
MENU_LOAD = 0x4ED94          # SET-menu loader, r0 = menu object
P_SETTINGS = 0xD4230         # -> settings block (0x14C910)
P_SVC_BASE = 0xD4220         # -> base; service flag word at base + 0x254A0
SVC_MAGIC = 0x010304
COMP = 0x2C                  # compression field, offset within a profile record
MENU_SEL = 0x490             # menu object: selected Compression entry
MENU_COUNT = 0x498           # menu object: number of Compression entries

REAL = [  # (start, end) of firmware functions executed for real
    (0x20F9C, 0x2105C),      # profile record defaults
    (0x21724, 0x2199C),      # defaults helpers, version check, settings loader
    (0xBD0B4, 0xBD104),      # crc32
    (0x403F0, 0x40410),      # service-mode gate
    (0x4ED94, 0x4F278),      # SET-menu loader
]
STUBS = {  # addr -> name; behaviour in Emu._stub
    0x362E8: 'eeprom_read',
    0xB3C5C: 'printf',
    0x4568C: 'apply_setting_4568c',
    0xB485C: 'os_b485c', 0xB48A0: 'os_b48a0', 0xB48BC: 'os_b48bc',
    0x9AF4C: 'menu_item_9af4c', 0x9AF84: 'menu_item_9af84',
}

MEM_LO, MEM_HI = 0x0, 0x200000          # image (0x20000..0xF1BB0) + .bss (..0x1837E0)
STACK, MENU_OBJ, SCRATCH, SENTINEL = 0x800000, 0x900000, 0x940000, 0xA00000
MENU_VTBL = MENU_OBJ + 0x8000           # fake vtable for the menu object ([r5])
for _slot in (0x1C, 0x48):              # virtual calls at the end of the menu loader
    STUBS[SENTINEL + 0x100 + _slot] = f'menu_vcall_{_slot:x}'


def load_pxa(path, want_sha):
    data = open(path, 'rb').read()
    sha = hashlib.sha256(data).hexdigest()
    if sha != want_sha:
        raise SystemExit(f'{path}: sha256 {sha} does not match FINDINGS ({want_sha})')
    pos, size = find_lump(data, b'PXA')
    return data[pos:pos + size]


def apply_patches(pxa, names):
    """Build a variant in memory from stock PXA (used for the --no-menu build)."""
    b = bytearray(pxa)
    for name, va, old, new in PATCHES:
        if name[:2] in names:
            o = va - PXA_BASE
            assert b[o:o + 4] == old, name
            b[o:o + 4] = new
    return bytes(b)


class Escape(Exception):
    pass


class Emu:
    def __init__(self, pxa, real=REAL, stubs=STUBS):
        self.pxa, self.real, self.stubs = pxa, real, stubs
        self.uc = uc = Uc(UC_ARCH_ARM, UC_MODE_ARM)
        uc.ctl_set_cpu_model(UC_CPU_ARM_PXA270)     # Intel XScale, ARMv5TE
        uc.mem_map(MEM_LO, MEM_HI - MEM_LO)
        uc.mem_write(PXA_BASE, pxa)
        for base in (STACK, MENU_OBJ, SCRATCH, SENTINEL):
            uc.mem_map(base, 0x10000)
        uc.hook_add(UC_HOOK_CODE, self._code)
        uc.hook_add(UC_HOOK_MEM_INVALID, self._badmem)
        # Unicorn does not model ARMv5 rotated unaligned loads, so fail on any misaligned access.
        uc.hook_add(UC_HOOK_MEM_READ | UC_HOOK_MEM_WRITE, self._align)
        self.eeprom = None          # bytes returned by eeprom_read, or int error code
        self.calls = []
        self.log = []
        self.err = None

    # -- memory helpers
    def u16(self, a): return struct.unpack('<H', self.uc.mem_read(a, 2))[0]
    def u32(self, a): return struct.unpack('<I', self.uc.mem_read(a, 4))[0]
    def w16(self, a, v): self.uc.mem_write(a, struct.pack('<H', v))
    def w32(self, a, v): self.uc.mem_write(a, struct.pack('<I', v))
    def read(self, a, n): return bytes(self.uc.mem_read(a, n))
    def cstr(self, a): return self.read(a, 200).split(b'\0')[0].decode('latin1')

    @property
    def settings(self): return self.u32(P_SETTINGS)
    def svc_addr(self): return self.u32(P_SVC_BASE) + 0x254A0

    def profile(self, s=None):
        """Address of the active profile record, same rule as the firmware."""
        s = self.settings if s is None else s
        cur, idx = self.u16(s + 2), self.u16(s)
        return s + 0x1C + 0x50 * (idx if cur == 0xFFFF else cur)

    # -- hooks
    def _code(self, uc, addr, size, _):
        if addr in self.stubs:
            self._stub(self.stubs[addr])
        elif addr != SENTINEL and not any(a <= addr < b for a, b in self.real):
            self.err = f'execution escaped to 0x{addr:X} (lr=0x{uc.reg_read(UC_ARM_REG_LR):X})'
            uc.emu_stop()

    def _align(self, uc, access, addr, size, value, _):
        if size in (2, 4, 8) and addr % size:
            self.err = self.err or (f'misaligned {size}-byte access 0x{addr:X} at '
                                    f'pc=0x{uc.reg_read(UC_ARM_REG_PC):X}')
            uc.emu_stop()

    def _badmem(self, uc, access, addr, size, value, _):
        self.err = f'bad memory access 0x{addr:X} at pc=0x{uc.reg_read(UC_ARM_REG_PC):X}'
        return False

    def _stub(self, name):
        uc = self.uc
        r = [uc.reg_read(x) for x in (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2)]
        self.calls.append(name)
        ret = 0
        if name == 'eeprom_read':
            if isinstance(self.eeprom, int):
                ret = self.eeprom
            else:
                assert r[2] == 0x400
                uc.mem_write(r[1], self.eeprom)
        elif name == 'printf':
            self.log.append(self.cstr(r[0]).strip())
        uc.reg_write(UC_ARM_REG_R0, ret & 0xFFFFFFFF)
        uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR))

    def call(self, fn, *args):
        uc = self.uc
        for reg, v in zip((UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3), args):
            uc.reg_write(reg, v)
        uc.reg_write(UC_ARM_REG_SP, STACK + 0xF000)
        uc.reg_write(UC_ARM_REG_LR, SENTINEL)
        self.err = None
        try:
            uc.emu_start(fn, SENTINEL, count=2_000_000)
        except UcError as e:
            self.err = self.err or f'{e} at pc=0x{uc.reg_read(UC_ARM_REG_PC):X}'
        if self.err:
            raise Escape(self.err)
        if uc.reg_read(UC_ARM_REG_PC) != SENTINEL:
            raise Escape(f'did not return (pc=0x{uc.reg_read(UC_ARM_REG_PC):X})')
        return uc.reg_read(UC_ARM_REG_R0)


def make_eeprom(pxa, profile, comp, crc_ok=True):
    """Factory-default 0x400 EEPROM block built by the firmware's own defaults code,
    with the given active profile and compression and a CRC from the firmware's crc32."""
    e = Emu(pxa)
    e.call(SETTINGS_DEFAULTS, SCRATCH)
    e.w16(SCRATCH, profile)
    assert e.u16(SCRATCH + 2) == 0xFFFF
    e.w16(e.profile(SCRATCH) + COMP, comp)
    size = e.u32(SCRATCH + 0x10)
    e.w32(SCRATCH + 0xC, 0)
    crc = e.call(CRC32, SCRATCH, size)
    e.w32(SCRATCH + 0xC, crc if crc_ok else crc ^ 1)
    return e.read(SCRATCH, 0x400)


def run_loader(pxa, eeprom):
    e = Emu(pxa)
    e.eeprom = eeprom
    s = e.settings
    e.call(SETTINGS_LOAD, s)
    return {'comp': e.u16(e.profile() + COMP), 'block': e.read(s, 0x400),
            'prof': e.profile() - s, 'calls': e.calls, 'log': e.log}


def run_menu(pxa, profile, comp, service):
    e = Emu(pxa)
    e.eeprom = make_eeprom(pxa, profile, comp)
    e.call(SETTINGS_LOAD, e.settings)
    e.w16(e.profile() + COMP, comp)            # stock loader turns 5 into 1; menu sees 5
    e.w32(e.svc_addr(), SVC_MAGIC if service else 0)
    e.calls.clear()
    e.w32(MENU_OBJ, MENU_VTBL)
    for slot in (0x1C, 0x48):
        e.w32(MENU_VTBL + slot, SENTINEL + 0x100 + slot)
    e.call(MENU_LOAD, MENU_OBJ)
    return {'count': e.u32(MENU_OBJ + MENU_COUNT), 'sel': e.u32(MENU_OBJ + MENU_SEL),
            'comp': e.u16(e.profile() + COMP), 'calls': e.calls}


class Results:
    def __init__(self, verbose):
        self.ok = self.bad = 0
        self.verbose = verbose

    def check(self, label, got, want):
        good = got == want
        self.ok += good
        self.bad += not good
        if self.verbose or not good:
            print(f'  {"ok  " if good else "FAIL"} {label}: got {got}, want {want}')


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('-')]
    verbose = '-v' in sys.argv
    stock_path = args[0] if args else os.path.join(ROOT, 'firmware/stock/m8-2_014.upd')
    patched_path = args[1] if len(args) > 1 else os.path.join(ROOT, 'firmware/patched/m8-2_014.upd')
    stock = load_pxa(stock_path, STOCK_SHA)
    patched = load_pxa(patched_path, PATCHED_SHA)
    nomenu = apply_patches(stock, {'P1', 'P2'})
    assert apply_patches(stock, {'P1', 'P2', 'P3'}) == patched
    builds = {'stock': stock, 'patched': patched, 'no-menu': nomenu}
    R = Results(verbose)

    print('Settings loader (0x21848): EEPROM block -> compression after boot')
    for name, pxa in builds.items():
        for prof in (1, 2, 5):
            for comp in range(6):
                r = run_loader(pxa, make_eeprom(pxa, prof, comp))
                want = 1 if (comp == 5 and name == 'stock') else comp
                R.check(f'{name:8s} profile {prof} comp {comp}', r['comp'], want)
    # The patch must change nothing but the compression field, and make no other calls.
    for prof in (1, 3):
        for comp in range(6):
            a = run_loader(stock, make_eeprom(stock, prof, comp))
            b = run_loader(patched, make_eeprom(patched, prof, comp))
            diff = [i for i in range(0x400) if a['block'][i] != b['block'][i]]
            want = [a['prof'] + COMP] if comp == 5 else []
            R.check(f'stock/patched block diff, profile {prof} comp {comp}', diff, want)
            R.check(f'stock/patched call trace, profile {prof} comp {comp}',
                    a['calls'] == b['calls'], True)
    # Fallback paths: bad CRC, failed read -> factory defaults (profile 0, JPG fine).
    for name, pxa in builds.items():
        r = run_loader(pxa, make_eeprom(pxa, 1, 5, crc_ok=False))
        R.check(f'{name:8s} bad CRC -> defaults', (r['prof'], r['comp']), (0x1C, 1))
        r = run_loader(pxa, -5)
        R.check(f'{name:8s} read error -> defaults', (r['prof'], r['comp']), (0x1C, 1))
        R.check(f'{name:8s} read error message', r['log'][:1],
                ['Could not load Settings from eeprom ! res=%d'])
        # Profile 0 is rebuilt from defaults on every boot, patched or not.
        r = run_loader(pxa, make_eeprom(pxa, 0, 5))
        R.check(f'{name:8s} profile 0 comp 5 (rebuilt each boot)', r['comp'], 1)

    print('SET-menu loader (0x4ED94): entries / selected entry / profile compression')
    for name, pxa in builds.items():
        for service in (False, True):
            for comp in range(6):
                r = run_menu(pxa, 1, comp, service)
                count = 6 if (service or name == 'patched') else 5
                keep = comp != 5 or service or name != 'stock'
                want = (count, comp if keep else 1, comp if keep else 1)
                R.check(f'{name:8s} service={service:d} comp {comp}',
                        (r['count'], r['sel'], r['comp']), want)

    print(f'{R.ok} passed, {R.bad} failed')
    sys.exit(1 if R.bad else 0)


if __name__ == '__main__':
    main()
