#!/usr/bin/env python3
"""
Draw the GitHub social-preview image (1280 x 640) for this repository.

Generic rangefinder outline (no Leica logo or red dot: trademarks), the repository name, and two
tonal ramps: 8-bit (steps exaggerated so the banding is visible) vs 14-bit (smooth).

Usage: work/venv/bin/python tools/make_social_preview.py [out.png]   (default docs/assets/social-preview.png)
Needs: Pillow (installed with the venv's imageio). Fonts: macOS system fonts.
"""
import os, sys
from PIL import Image, ImageDraw, ImageFont

W, H, S = 1280, 640, 2                      # final size, supersampling factor
BG_TOP, BG_BOT = (24, 26, 31), (12, 13, 16)
LINE = (214, 218, 224)
DIM = (150, 156, 166)
ACCENT = (232, 161, 58)
FONTS = '/System/Library/Fonts'


def font(name, size, index=0):
    return ImageFont.truetype(os.path.join(FONTS, name), size * S, index=index)


def s(*v):
    return [x * S for x in v]


def camera(d):
    w = 7 * S
    d.rounded_rectangle(s(96, 214, 566, 444), radius=34 * S, outline=LINE, width=w)          # body
    d.rounded_rectangle(s(136, 194, 186, 214), radius=6 * S, outline=LINE, width=w)          # rewind knob
    d.rounded_rectangle(s(470, 192, 506, 214), radius=6 * S, outline=LINE, width=w)          # shutter release
    d.rounded_rectangle(s(408, 186, 450, 214), radius=6 * S, outline=LINE, width=w)          # speed dial
    d.rounded_rectangle(s(132, 246, 186, 292), radius=8 * S, outline=LINE, width=w)          # rangefinder window
    d.rounded_rectangle(s(222, 252, 300, 284), radius=6 * S, outline=DIM, width=5 * S)       # frameline window
    d.rounded_rectangle(s(438, 240, 528, 298), radius=10 * S, outline=LINE, width=w)         # viewfinder
    cx, cy = 331, 352
    d.ellipse(s(cx - 104, cy - 104, cx + 104, cy + 104), fill=(18, 19, 23))                  # lens hides body
    for r, col, wd in ((104, LINE, 7), (80, LINE, 5), (50, DIM, 4)):                          # lens
        d.ellipse(s(cx - r, cy - r, cx + r, cy + r), outline=col, width=wd * S)
    d.ellipse(s(cx - 24, cy - 24, cx + 24, cy + 24), fill=ACCENT)                            # glass highlight


def ramp(img, x, y, w, h, steps=None):
    """Horizontal black-to-white ramp; steps=None is smooth."""
    px = img.load()
    for i in range(w * S):
        t = i / (w * S - 1)
        if steps:
            t = round(t * (steps - 1)) / (steps - 1)
        v = int(40 + t * (235 - 40))
        for j in range(h * S):
            px[x * S + i, y * S + j] = (v, v, v)


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(os.path.abspath(__file__)), '..', 'docs', 'assets', 'social-preview.png')
    img = Image.new('RGB', (W * S, H * S))
    d = ImageDraw.Draw(img)
    for yy in range(H * S):                                                                   # background
        t = yy / (H * S - 1)
        d.line([(0, yy), (W * S, yy)], fill=tuple(int(a + (b - a) * t) for a, b in zip(BG_TOP, BG_BOT)))
    camera(d)
    x0 = 640
    d.text(s(x0, 150), 'leica-m8-14bit-dng', font=font('Menlo.ttc', 50, 1), fill=(244, 245, 247))
    d.text(s(x0, 222), '14-bit DNG, written by the camera itself.', font=font('HelveticaNeue.ttc', 29), fill=DIM)
    d.text(s(x0, 260), 'Firmware patches for the Leica M8.', font=font('HelveticaNeue.ttc', 29), fill=DIM)
    lab = font('Menlo.ttc', 22)
    d.text(s(x0, 352), '8-bit', font=lab, fill=DIM)
    ramp(img, x0 + 104, 340, 480, 46, steps=20)
    d.rectangle(s(x0 + 104, 340, x0 + 584, 386), outline=(70, 74, 82), width=S)
    d.text(s(x0, 426), '14-bit', font=lab, fill=ACCENT)
    ramp(img, x0 + 104, 414, 480, 46)
    d.rectangle(s(x0 + 104, 414, x0 + 584, 460), outline=(70, 74, 82), width=S)
    d.text(s(x0, 520), 'persistent RAW  ·  in-camera DNG  ·  emulator-tested  ·  MIT',
           font=font('HelveticaNeue.ttc', 21), fill=(118, 124, 134))
    img = img.resize((W, H), Image.LANCZOS)
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    img.save(out, optimize=True)
    print('wrote', out, img.size, os.path.getsize(out), 'bytes')


if __name__ == '__main__':
    main()
