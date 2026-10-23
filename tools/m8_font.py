#!/usr/bin/env python3
"""
Decode the M8's GUI fonts (GUI lump FONT1 / FONT2) and render text or a glyph sheet. Read-only.

Format (2.014; the loader is 0x414D4, the registration 0x886FC):
  last 20 bytes  <5I: line height, descent, glyph count, glyph-table offset, 0
  glyph table    count x 12 bytes, indexed by Unicode code point:
                 x offset (s8), y offset (s8, negative = below the baseline), width, height,
                 advance (u8), 3 pad bytes, bitmap offset (u32)
  bitmaps        1 bit per pixel, MSB first, rows padded to whole bytes

Usage:  work/venv/bin/python tools/m8_font.py work/split-2.014/GUI_FONT1.bin sheet out.png
        work/venv/bin/python tools/m8_font.py work/split-2.014/GUI_FONT1.bin text "ISO 640" out.png
"""
import struct, sys
from PIL import Image


class Font:
    def __init__(self, path):
        self.d = open(path, 'rb').read()
        self.height, self.descent, self.count, self.table, _ = struct.unpack('<5I', self.d[-20:])
        assert self.table + self.count * 12 == len(self.d) - 20, 'unexpected font layout'

    def glyph(self, code):
        """(x_off, y_off, w, h, advance, rows) where rows is a list of lists of 0/1."""
        if code >= self.count:
            code = ord('?')
        xo, yo, w, h, adv, off = struct.unpack_from('<bbBBB3xI', self.d, self.table + code * 12)
        bpr = (w + 7) // 8
        rows = [[(self.d[off + r * bpr + c // 8] >> (7 - c % 8)) & 1 for c in range(w)] for r in range(h)]
        return xo, yo, w, h, adv, rows

    def draw(self, img, x, y, text, colour):
        """Draw text with its baseline at y; returns the x after the last glyph."""
        px = img.load()
        for ch in text:
            xo, yo, w, h, adv, rows = self.glyph(ord(ch))
            top = y - h - yo
            for r, row in enumerate(rows):
                for c, bit in enumerate(row):
                    if bit and 0 <= x + xo + c < img.width and 0 <= top + r < img.height:
                        px[x + xo + c, top + r] = colour
            x += adv
        return x

    def width(self, text):
        return sum(self.glyph(ord(ch))[4] for ch in text)


def main():
    path, mode = sys.argv[1], sys.argv[2]
    f = Font(path)
    if mode == 'text':
        text, out = sys.argv[3], sys.argv[4]
        img = Image.new('RGB', (f.width(text) + 8, f.height + 8), (0, 0, 0))
        f.draw(img, 4, 4 + f.height - f.descent, text, (255, 255, 255))
    else:
        out = sys.argv[3]
        chars = [chr(c) for c in range(0x20, 0x7F)] + [chr(c) for c in range(0xA0, 0x100)]
        cols, cell = 32, f.height + 6
        img = Image.new('RGB', (cols * cell, (len(chars) + cols - 1) // cols * cell), (0, 0, 0))
        for i, ch in enumerate(chars):
            f.draw(img, i % cols * cell + 3, i // cols * cell + 3 + f.height - f.descent, ch, (255, 255, 255))
    img = img.resize((img.width * 3, img.height * 3), Image.NEAREST)
    img.save(out)
    print('wrote', out, f'(height {f.height}, descent {f.descent}, {f.count} glyphs)')


if __name__ == '__main__':
    main()
