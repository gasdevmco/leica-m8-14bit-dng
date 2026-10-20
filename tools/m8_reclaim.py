#!/usr/bin/env python3
"""
Rank debug-shell command handlers as candidates for reclaimed code space (stock 2.014).

Command entries come from running the firmware's own C++ static initializer (0x2C9F4, args
1, 0xFFFF) in the Unicorn harness: it fills 32-byte entries
  +0x00 name  +0x08 usage  +0x0C description  +0x10/+0x14 (arg counts?)  +0x18 handler.

For each handler, the range is start .. min(next function prologue, next registered handler),
so its literal pool is included. Every other way into the range found anywhere in the PXA
image is listed:
  branch  b/bl/b<cond> from outside the range landing inside it
  data    aligned 32-bit word outside the range whose value points inside it
  pool    PC-relative LDR from outside the range reading a literal inside it
  adr     ADD/SUB rX, pc, #imm from outside the range producing an address inside it
Pointers to any registered handler held in the initializer's literal pool count as "reg".
A clean candidate has other refs = 0. Static analysis only: an address computed any other way
would not be seen, so results still need Ghidra and the on-camera idle test.
Commands touching updates/flash/boot are marked NEVER regardless of refs.

Usage: python3 tools/m8_reclaim.py [stock.upd]
"""
import os, re, struct, sys
import armtools as a
import m8_emutest as t
from unicorn import UC_HOOK_MEM_WRITE

INIT, INIT_END = 0x2C9F4, 0x2EC20       # static initializer that builds the command entries
ENTRY_HANDLER = 0x18
PROLOGUE_MASK, PROLOGUE = 0xFFFF4000, 0xE92D4000   # stmfd sp!, {..., lr}
MOV_IP_SP = 0xE1A0C00D
NEVER = re.compile(r'updat|flash|redboot|fsl|first stage|firmware|reset|mount|eeprom|rtc|power', re.I)


def func_end(start):
    """Next function start after `start` (a 'mov ip,sp' + push, or a bare push)."""
    x = start + 4
    while x < a.END:
        w = a.u32(x)
        if w == MOV_IP_SP and (a.u32(x + 4) & PROLOGUE_MASK) == PROLOGUE:
            return x
        if (w & PROLOGUE_MASK) == PROLOGUE and a.u32(x - 4) != MOV_IP_SP:
            return x
        x += 4
    return a.END


def commands(pxa):
    """[(name, usage, desc, handler)] by emulating the static initializer."""
    e = t.Emu(pxa, real=[(a.BASE, a.END)], stubs={0xB48A0: 'os_b48a0'})
    stores = {}
    e.uc.hook_add(UC_HOOK_MEM_WRITE,
                  lambda uc, acc, addr, size, val, _: stores.__setitem__(addr, val) if size == 4 else None)
    e.call(INIT, 1, 0xFFFF)

    def s(v):
        try:
            return a.cstr(v) if a.BASE <= v < a.END else ''
        except ValueError:
            return ''
    out = []
    for d, v in sorted(stores.items()):
        if a.BASE <= v < 0xD0000 and (d - ENTRY_HANDLER) in stores:
            base = d - ENTRY_HANDLER
            name = s(e.u32(base))
            if name:
                out.append((name, s(e.u32(base + 8)), s(e.u32(base + 0xC)), v))
    return out


def scan_refs():
    """One pass over the image: every branch target, data word, pool read and pc-relative add."""
    branches, words, pools, adrs = [], [], [], []
    D = a.D
    for o in range(0, len(D) - 3, 4):
        src = a.BASE + o
        w = struct.unpack_from('<I', D, o)[0]
        words.append((src, w))
        if (w & 0x0E000000) == 0x0A000000 and (w >> 28) != 0xF:          # b/bl<cond>
            off = w & 0xFFFFFF
            off -= (off & 0x800000) << 1
            branches.append((src, src + 8 + off * 4))
        if (w & 0x0F7F0000) == 0x051F0000:                               # ldr rd,[pc,#±imm]
            imm = w & 0xFFF
            pools.append((src, src + 8 + (imm if (w >> 23) & 1 else -imm)))
        if (w & 0x0FEF0000) in (0x028F0000, 0x024F0000):                 # add/sub rd, pc, #imm
            rot, imm = (w >> 8) & 0xF, w & 0xFF
            val = ((imm >> (2 * rot)) | (imm << (32 - 2 * rot))) & 0xFFFFFFFF
            adrs.append((src, src + 8 + (val if (w & 0x00E00000) == 0x00800000 else -val)))
    return branches, words, pools, adrs


def refs_into(lo, hi, refs, reg_srcs):
    branches, words, pools, adrs = refs
    inside = lambda x: lo <= x < hi
    r = {'branch': [], 'data': [], 'pool': [], 'adr': [], 'reg': []}
    for src, tgt in branches:
        if inside(tgt) and not inside(src):
            r['branch'].append(src)
    for src, v in words:
        if inside(v) and not inside(src):
            (r['reg'] if src in reg_srcs else r['data']).append(src)
    for src, lit in pools:
        if inside(lit) and not inside(src):
            r['pool'].append(src)
    for src, tgt in adrs:
        if inside(tgt) and not inside(src):
            r['adr'].append(src)
    return r


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(t.ROOT, 'firmware/stock/m8-2_014.upd')
    pxa = t.load_pxa(path, t.STOCK_SHA)
    a.D, a.END = pxa, a.BASE + len(pxa)
    cmds = commands(pxa)
    handlers = sorted({h for *_, h in cmds})
    reg_srcs = {x for x in range(INIT, INIT_END, 4) if a.u32(x) in handlers}
    refs = scan_refs()
    rows = []
    for name, usage, desc, h in cmds:
        nxt = next((x for x in handlers if x > h), a.END)
        lo, hi = h, min(func_end(h), nxt)
        r = refs_into(lo, hi, refs, reg_srcs)
        other = sum(len(v) for k, v in r.items() if k != 'reg')
        never = bool(NEVER.search(' '.join((name, usage, desc))))
        shared = sum(1 for *_, x in cmds if x == h) > 1
        rows.append((never, other, -(hi - lo), name, desc or usage, lo, hi, r, shared))
    rows.sort()
    print(f'{len(cmds)} commands, {len(handlers)} distinct handlers\n')
    print(f'{"name":14s} {"handler":>8s} {"bytes":>5s} {"refs":>4s}  description')
    for never, other, _, name, desc, lo, hi, r, shared in rows:
        tag = 'NEVER ' if never else ('shared ' if shared else '')
        detail = ', '.join(f'{k} {",".join(hex(x) for x in v[:3])}' for k, v in r.items() if v and k != 'reg')
        print(f'{name[:14]:14s} {lo:#8x} {hi - lo:5d} {other:4d}  {tag}{desc[:46]}' + (f'  [{detail}]' if detail else ''))


if __name__ == '__main__':
    main()
