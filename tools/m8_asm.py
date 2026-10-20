#!/usr/bin/env python3
"""
Assemble one ARM source file with Apple clang for the M8 PXA (ARMv5TE, ARM mode) and return the
.text bytes. Refuses relocations and any other section with contents, so the result is
self-contained (position independent, literal pools included in .text).

The patch script never calls this: it carries the frozen bytes and their SHA-256. This tool
regenerates and checks them: python3 tools/m8_asm.py tools/asm/X.s  (prints hex + sha256).
"""
import hashlib, os, struct, subprocess, sys, tempfile

FLAGS = ['--target=armv5te-none-eabi', '-march=armv5te', '-marm', '-c']


def assemble(src):
    with tempfile.TemporaryDirectory() as d:
        obj = os.path.join(d, 'out.o')
        subprocess.run(['clang', *FLAGS, src, '-o', obj], check=True)
        elf = open(obj, 'rb').read()
    assert elf[:4] == b'\x7fELF' and elf[4] == 1 and elf[5] == 1, 'not ELF32 LE'
    shoff, = struct.unpack_from('<I', elf, 0x20)
    shentsize, shnum, shstrndx = struct.unpack_from('<HHH', elf, 0x2E)
    secs = [struct.unpack_from('<10I', elf, shoff + i * shentsize) for i in range(shnum)]
    names = secs[shstrndx]
    name = lambda s: elf[names[4] + s[0]:].split(b'\0')[0].decode()
    text = None
    for s in secs:
        n, typ, size = name(s), s[1], s[5]
        if typ in (4, 9):                                   # SHT_RELA, SHT_REL
            raise SystemExit(f'{src}: relocations in {n}')
        if n == '.text':
            text = elf[s[4]:s[4] + size]
        elif typ == 1 and size and n not in ('.ARM.attributes',):   # PROGBITS with contents
            raise SystemExit(f'{src}: unexpected section {n} ({size} bytes)')
    return text


if __name__ == '__main__':
    b = assemble(sys.argv[1])
    print(f'{len(b)} bytes, sha256 {hashlib.sha256(b).hexdigest()}')
    print(b.hex())
