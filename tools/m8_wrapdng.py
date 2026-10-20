#!/usr/bin/env python3
"""
Turn an M8 14-bit .RAW dump into a DNG the way the camera would (docs/DNG_PLAN.md §3):

  1. overwrite the first 8 bytes of the 108-byte RAW header with a TIFF header
     pointing at IFD0 in the trailing sensor row;
  2. leave every image pixel where it is (StripOffsets = 108, width 3976 incl. padding);
  3. copy a constant ~900-byte template (IFD0 + EXIF IFD + values), with the per-shot
     "slots" in SHOT_FIELDS patched, over the start of the trailing row (sensor row 2647,
     outside the image strip). File size is unchanged.

In camera (FINDINGS "Image save path"): step 1 = header code at 0x3CE48; step 3 = hook in
the RAW producer's last-block branch (0x3C6A8) copying the template into the DMA buffer
before it is copied to the card.

The template is the exact blob the firmware would carry; -t writes it out with its slot
offsets.

Rule: this is the proof of concept for the in-camera writer, so it does only what the
camera can do -- constant tags, a few per-shot values the camera already knows, no pixel
processing and no per-frame analysis. Per-shot values come from the camera's metadata struct S
(job+4, FINDINGS "Per-shot metadata"); on the desktop they are read from the same-stem .JPG's
EXIF (the camera writes that JPG from S), else date = RAW mtime and the rest = camera defaults.
AsShotNeutral = fixed daylight (later a WB-preset table); BlackLevel = constant 92 (later scaled
by ISO gain, which the camera knows).

Usage: python3 tools/m8_wrapdng.py in.RAW [out.DNG] [--black N (default 92, 0 = omit)] [-t template.bin]
"""
import os, struct, sys, time

RAW_SIZE = 21_049_052                  # 54 header u16 + 2647 sensor rows x 3976
HDR = 108
W, H, W_ACTIVE = 3976, 2646, 3968
STRIP = W * H * 2
BASE = HDR + STRIP                     # trailing row (7,952 bytes): IFD0 offset
TRAIL = RAW_SIZE - BASE

# Tag values copied from a 2.014 in-camera DNG (L1030602.DNG); matrices as the camera writes them.
MAKE, MODEL, UNIQUE, SOFTWARE = 'Leica Camera AG', 'M8 Digital Camera', 'M8 Digital Camera', '2.014'
CM1 = [10469, -5314, 1280, -4326, 12176, 2419, -886, 2473, 7160]      # /10000, Std A
CM2 = [7675, -2195, -305, -5860, 14118, 1857, -2425, 4007, 6578]      # /10000, D65
DAYLIGHT_NEUTRAL = [(16384, 31315), (16384, 16384), (16384, 20850)]   # m8raw2dng2 default
BLACK = 92                             # sensor black pedestal (m8raw2dng2 base value)

BYTE, ASCII, SHORT, LONG, RATIONAL, UNDEF, SRATIONAL = 1, 2, 3, 4, 5, 7, 10
SIZE = {BYTE: 1, ASCII: 1, SHORT: 2, LONG: 4, RATIONAL: 8, UNDEF: 1, SRATIONAL: 8}
FMT = {BYTE: 'B', SHORT: 'H', LONG: 'I'}

DT0 = '0000:00:00 00:00:00'
# Per-shot slots: (tag, name, type, default, where the camera holds it). Defaults as the camera's
# metadata init (0x6DF5C). In camera each slot is filled by copying from S; offsets per FINDINGS.
SHOT_FIELDS = [
    (306,   'DateTime',          ASCII,     DT0,             'S+0x20'),
    (33434, 'ExposureTime',      RATIONAL,  [(0, 1)],        'S+0x64'),
    (34850, 'ExposureProgram',   SHORT,     0,               'S+0x60'),
    (34855, 'ISO',               SHORT,     100,             'S+0x62'),
    (36867, 'DateTimeOriginal',  ASCII,     DT0,             'S+0x20'),
    (36868, 'DateTimeDigitized', ASCII,     DT0,             'S+0x20'),
    (37377, 'ShutterSpeedValue', SRATIONAL, [(0, 65536)],    'S+0x6C'),
    (37380, 'ExposureBias',      SRATIONAL, [(0, 65536)],    'S+0x8C'),
    (37381, 'MaxAperture',       RATIONAL,  [(0, 65536)],    'S+0x94'),
    (37386, 'FocalLength',       RATIONAL,  [(0, 1000)],     'S+0xA8'),
    (50728, 'AsShotNeutral',     RATIONAL,  DAYLIGHT_NEUTRAL, 'WB preset table'),
]
SLOT_TAGS = {tag: (name, typ) for tag, name, typ, _, _ in SHOT_FIELDS}
EXIF_TAGS = {33434, 34850, 34855, 36864, 36867, 36868, 37377, 37380, 37381, 37386}


def pack_value(typ, v):
    if typ == ASCII:
        return v.encode('latin1') + b'\0'
    if typ in (BYTE, UNDEF) and isinstance(v, bytes):
        return v
    if typ in (RATIONAL, SRATIONAL):
        return b''.join(struct.pack('<ii' if typ == SRATIONAL else '<II', *r) for r in v)
    v = v if isinstance(v, (list, tuple)) else [v]
    return struct.pack('<%d%s' % (len(v), FMT[typ]), *v)


def build_template(black=BLACK):
    """Return (template bytes, {slot name: (offset in template, length, type)})."""
    shot = [(tag, typ, default) for tag, _, typ, default, _ in SHOT_FIELDS]
    exif = [(36864, UNDEF, b'0220')] + [e for e in shot if e[0] in EXIF_TAGS]   # ExifVersion + slots
    ifd0 = [
        (254, LONG, 0),                                          # main image = raw
        (256, LONG, W), (257, LONG, H),
        (258, SHORT, 16), (259, SHORT, 1), (262, SHORT, 32803),  # 16-bit, uncompressed, CFA
        (271, ASCII, MAKE), (272, ASCII, MODEL),
        (273, LONG, HDR), (274, SHORT, 1), (277, SHORT, 1),
        (278, LONG, H), (279, LONG, STRIP), (284, SHORT, 1),
        (305, ASCII, SOFTWARE),
        (33421, SHORT, [2, 2]), (33422, BYTE, b'\x00\x01\x01\x02'),   # RGGB
        (34665, LONG, 0),                                        # ExifIFD, fixed up below
        (50706, BYTE, b'\x01\x00\x00\x00'), (50707, BYTE, b'\x01\x00\x00\x00'),
        (50708, ASCII, UNIQUE),
        *([(50714, SHORT, black)] if black else []),
        (50717, LONG, 16383),
        (50719, SHORT, [2, 2]), (50720, SHORT, [W_ACTIVE - 4, H - 4]),  # hides padding + 2px edge
        (50721, SRATIONAL, [(x, 10000) for x in CM1]),
        (50722, SRATIONAL, [(x, 10000) for x in CM2]),
        (50731, RATIONAL, [(1, 1)]), (50732, RATIONAL, [(1, 1)]),  # BaselineNoise/Sharpness
        (50733, LONG, 500), (50738, RATIONAL, [(0, 1)]),         # BayerGreenSplit, AntiAlias (none)
        (50778, SHORT, 17), (50779, SHORT, 21),
        *[e for e in shot if e[0] not in EXIF_TAGS],             # DateTime, AsShotNeutral slots
    ]
    ifd0_len = 2 + 12 * len(ifd0) + 4
    exif_off = ifd0_len
    data_off = exif_off + 2 + 12 * len(exif) + 4
    out, data, slots = bytearray(), bytearray(), {}

    def emit(entries, next_ifd=0):
        blob = struct.pack('<H', len(entries))
        for tag, typ, v in sorted(entries):
            if tag == 34665:
                v = BASE + exif_off
            raw = pack_value(typ, v)
            count = len(raw) // SIZE[typ]
            if len(raw) <= 4:
                field = raw.ljust(4, b'\0')
                where = len(out) + len(blob) + 8
            else:
                where = data_off + len(data)
                field = struct.pack('<I', BASE + where)
                data.extend(raw + b'\0' * (len(raw) & 1))       # keep word alignment
            if tag in SLOT_TAGS:
                name, _ = SLOT_TAGS[tag]
                slots[name] = (where, len(raw), typ)
            blob += struct.pack('<HHI', tag, typ, count) + field
        return blob + struct.pack('<I', next_ifd)

    out += emit(ifd0)
    assert len(out) == exif_off
    out += emit(exif)
    assert len(out) == data_off
    return bytes(out + data), slots


def wrap(raw, template, slots, shot):
    """What the camera does per shot: header, slot patches (from S), template into trailing row."""
    assert len(raw) == RAW_SIZE, f'RAW is {len(raw)} bytes, expected {RAW_SIZE}'
    t = bytearray(template)
    for name, value in shot.items():
        off, n, typ = slots[name]
        v = pack_value(typ, value)
        assert len(v) == n, f'{name}: {len(v)} bytes, slot holds {n}'
        t[off:off + n] = v
    assert len(t) <= TRAIL
    return b'II*\0' + struct.pack('<I', BASE) + raw[8:BASE] + bytes(t) + raw[BASE + len(t):]


def check(dng, raw):
    """Structural self-check: re-read the TIFF and confirm pixels are untouched."""
    assert dng[:4] == b'II*\0' and struct.unpack_from('<I', dng, 4)[0] == BASE
    assert len(dng) == RAW_SIZE, 'file size changed'
    assert dng[8:BASE] == raw[8:BASE], 'pixel/header bytes changed'
    n = struct.unpack_from('<H', dng, BASE)[0]
    tags = {}
    for i in range(n):
        tag, typ, cnt, val = struct.unpack_from('<HHII', dng, BASE + 2 + 12 * i)
        tags[tag] = (typ, cnt, val)
    assert list(tags) == sorted(tags), 'tags not ascending'
    assert tags[273][2] == HDR and tags[279][2] == STRIP and HDR + STRIP <= RAW_SIZE
    assert tags[256][2] == W and tags[257][2] == H
    for tag, (typ, cnt, val) in tags.items():
        if SIZE[typ] * cnt > 4:
            assert val % 2 == 0 and val + SIZE[typ] * cnt <= len(dng), f'tag {tag} out of range'
    return n


def jpg_shot(path):
    """Desktop stand-in for S: the per-shot slot values from the camera's own JPG EXIF."""
    d = open(path, 'rb').read()
    i = 2
    while i + 4 < len(d) and d[i] == 0xFF:
        n = struct.unpack('>H', d[i + 2:i + 4])[0]
        if d[i + 1] == 0xE1 and d[i + 4:i + 10] == b'Exif\0\0':
            break
        i += 2 + n
    else:
        return {}
    t = d[i + 10:i + 2 + n]
    e = '<' if t[:2] == b'II' else '>'
    want = {tag: name for tag, (name, _) in SLOT_TAGS.items()}
    out = {}

    def ifd(off):
        for k in range(struct.unpack_from(e + 'H', t, off)[0]):
            tag, typ, cnt, val = struct.unpack_from(e + 'HHII', t, off + 2 + 12 * k)
            voff = off + 2 + 12 * k + 8
            if tag == 34665:
                ifd(val)
            elif tag in want:
                if typ == ASCII:
                    out[want[tag]] = t[val:val + cnt].split(b'\0')[0].decode('latin1')
                elif typ == SHORT:
                    out[want[tag]] = struct.unpack_from(e + 'H', t, voff)[0]
                elif typ in (RATIONAL, SRATIONAL):
                    out[want[tag]] = [struct.unpack_from(e + ('ii' if typ == SRATIONAL else 'II'), t, val)]
    ifd(struct.unpack_from(e + 'I', t, 4)[0])
    return out


def main():
    args = [a for a in sys.argv[1:]]
    black, tpl_out = BLACK, None
    if '--black' in args:
        i = args.index('--black'); black = int(args[i + 1]); del args[i:i + 2]
    if '-t' in args:
        i = args.index('-t'); tpl_out = args[i + 1]; del args[i:i + 2]
    if not args:
        raise SystemExit(__doc__)
    src = args[0]
    dst = args[1] if len(args) > 1 else os.path.splitext(src)[0] + '.DNG'
    raw = open(src, 'rb').read()
    template, slots = build_template(black)
    jpg = os.path.splitext(src)[0] + '.JPG'
    shot = jpg_shot(jpg) if os.path.exists(jpg) else {}
    if 'DateTime' not in shot:   # no JPG: RAW mtime stands in for the camera clock
        when = time.strftime('%Y:%m:%d %H:%M:%S', time.localtime(os.path.getmtime(src)))
        shot.update(DateTime=when, DateTimeOriginal=when, DateTimeDigitized=when)
    dng = wrap(raw, template, slots, shot)
    n = check(dng, raw)
    open(dst, 'wb').write(dng)
    print(f'template {len(template)} bytes, {n} IFD0 tags, {len(slots)} slots; per-shot values from '
          + (f'{os.path.basename(jpg)}: ' + ', '.join(f'{k}={v}' for k, v in shot.items()) if os.path.exists(jpg)
             else 'defaults + RAW mtime'))
    print(f'wrote {dst} ({len(dng)} bytes, same as RAW); changed: bytes 0-7 and '
          f'{len(template)} of {TRAIL} trailing-row bytes')
    if tpl_out:
        open(tpl_out, 'wb').write(template)
        print('template written to', tpl_out)


if __name__ == '__main__':
    main()
