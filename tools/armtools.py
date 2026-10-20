"""ARM analysis helpers for the Leica M8 PXA image (XScale/ARMv5, load base 0x20000).

Usage:  import armtools as a; a.load(); print("\n".join(a.dis(0x4eec8, 6)))
Needs:  pip install capstone
"""
import struct, sys, capstone
from capstone import arm

BASE = 0x20000
# PXA image to analyse: $M8_PXA, else work/split-2.014/PXA.bin (make it with split_upd.py)
import os
_DEFAULT = os.environ.get('M8_PXA') or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '..', 'work', 'split-2.014', 'PXA.bin')
D = b''
END = BASE


def load(path=_DEFAULT):
    """Load a PXA image (base 0x20000). Call again to switch images."""
    global D, END, _ALL
    D = open(path, 'rb').read()
    END = BASE + len(D)
    _ALL = None


md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_ARM)
md.detail = True

def u32(a):
    return struct.unpack_from('<I', D, a - BASE)[0]

def cstr(a):
    o = a - BASE
    e = D.index(b'\0', o)
    return D[o:e].decode('latin1')

def dis(a, n=40):
    out = []
    for ins in md.disasm(D[a - BASE:a - BASE + n * 4], a):
        extra = ''
        if ins.mnemonic.startswith('ldr') and '[pc' in ins.op_str:
            for op in ins.operands:
                if op.type == arm.ARM_OP_MEM and op.mem.base == arm.ARM_REG_PC:
                    lit = ins.address + 8 + op.mem.disp
                    if BASE <= lit < END:
                        v = u32(lit)
                        extra = f'   ; =0x{v:x}'
                        if BASE <= v < END:
                            try:
                                s = cstr(v)
                                if len(s) >= 3 and all(32 <= ord(c) < 127 or c in '\n\r' for c in s):
                                    extra += f' "{s[:60]}"'
                            except ValueError:
                                pass
        out.append(f'{ins.address:08x}: {ins.bytes.hex():8s} {ins.mnemonic:8s} {ins.op_str}{extra}')
    return out

def words_equal(v):
    res = []
    for o in range(0, len(D) - 3, 4):
        if struct.unpack_from('<I', D, o)[0] == v:
            res.append(BASE + o)
    return res

def ldr_refs(lits):
    """find pc-relative LDRs that load from any literal address in lits"""
    lits = set(lits)
    res = []
    for o in range(0, len(D) - 3, 4):
        w = struct.unpack_from('<I', D, o)[0]
        # LDR Rd,[PC,#+-imm12] : cond 01 0 1 U 0 0 1 1111 Rd imm12
        if (w & 0x0F7F0000) == 0x051F0000:
            imm = w & 0xFFF
            disp = imm if (w >> 23) & 1 else -imm
            lit = BASE + o + 8 + disp
            if lit in lits:
                res.append((BASE + o, lit))
    return res

def bl_targets_to(target):
    res = []
    for o in range(0, len(D) - 3, 4):
        w = struct.unpack_from('<I', D, o)[0]
        if (w & 0x0F000000) == 0x0B000000:
            off = w & 0xFFFFFF
            if off & 0x800000:
                off -= 0x1000000
            if BASE + o + 8 + off * 4 == target:
                res.append(BASE + o)
    return res

def func_start(a, maxback=0x2000):
    """walk back to find a STMFD sp!,{...lr} prologue"""
    x = a
    while x > a - maxback:
        w = u32(x)
        if (w & 0xFFFF4000) == 0xE92D4000:
            return x
        x -= 4
    return None

md.skipdata = True
_ALL = None
def all_ins():
    global _ALL
    if _ALL is None:
        _ALL = [i for i in md.disasm(D, BASE) if i.mnemonic != '.byte']
    return _ALL


if os.path.exists(_DEFAULT):
    load()
