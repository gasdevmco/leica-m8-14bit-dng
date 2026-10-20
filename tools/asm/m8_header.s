@ RAW header block of the store routine, rewritten for the DNG build (stage 4+).
@ Replaces 0x3CE48-0x3CEFC (46 instructions) in place; 0x3CF00 (bl memcpy) follows unchanged.
@
@ Stock writes u16[0..3] = 0xFFFF, 0x000C, 0x0036, 0x0007. This version writes the TIFF header
@ "II" 42, IFD0 offset 21,041,100 (0x01410FCC = 108 + 3976*2646*2, the trailing sensor row):
@ u16[0..3] = 0x4949, 0x002A, 0x0FCC, 0x0141. Every other header field is written exactly as stock.
@ Room for the extra instructions: job+0x210 bytes 0-2 are loaded with three ldrb instead of
@ ldr + 2 shifts + 3 masks (same values, little-endian).
@
@ Entry (as stock): r7 = ctx, r6 = 0x4634, sb = 0x422C, sl = 0, [fp-0x64] = 0x4228,
@ [fp-0x70] = ring write pointer. Exit at 0x3CF00 as stock: r0 = ring+0x2C, r1 = job+0xE8,
@ r2 = 0x40, r4/r5 = job+0x210 bytes 1/2, ip/lr = rows/samples >> 8 & 0x1F, r6 = ring.
@ r3 differs (stock 0x36, here 0x0FCC); memcpy writes r3 before reading it.

    .syntax unified
    .arm
    .text
header:
    ldr     r3, [fp, #-0x64]        @ 0x4228
    ldr     r1, [r7, r6]            @ job = [ctx+0x4634]
    ldr     r2, [r7, sb]            @ rows = [ctx+0x422C]
    ldr     r0, [r7, r3]            @ samples per row = [ctx+0x4228]
    ldr     r6, [fp, #-0x70]        @ ring write pointer
    ldrb    r3, [r1, #0x210]
    ldrb    r4, [r1, #0x211]
    ldrb    r5, [r1, #0x212]
    lsr     lr, r0, #8
    and     r0, r0, #0xff
    lsr     ip, r2, #8
    and     r2, r2, #0xff
    and     ip, ip, #0x1f
    and     lr, lr, #0x1f
    strh    r0, [r6, #0x1c]         @ [14] samples low
    strh    r2, [r6, #0x14]         @ [10] rows low
    strh    ip, [r6, #0x16]         @ [11] rows high
    strh    lr, [r6, #0x1e]         @ [15] samples high
    strh    r3, [r6, #0x20]         @ [16..18] job+0x210 bytes
    strh    r4, [r6, #0x22]
    strh    r5, [r6, #0x24]
    mov     r0, #0x4900             @ [0] "II"
    orr     r0, r0, #0x49
    strh    r0, [r6]
    mov     r2, #0x2a               @ [1] 42
    strh    r2, [r6, #2]
    mov     r3, #0xf00              @ [2..3] IFD0 offset 0x01410FCC
    orr     r3, r3, #0xcc
    strh    r3, [r6, #4]
    mov     r0, #0x140
    orr     r0, r0, #1
    strh    r0, [r6, #6]
    strh    sl, [r6, #8]            @ zero fields, as stock
    strh    sl, [r6, #0xa]
    strh    sl, [r6, #0xc]
    strh    sl, [r6, #0xe]
    strh    sl, [r6, #0x10]
    strh    sl, [r6, #0x12]
    strh    sl, [r6, #0x18]
    strh    sl, [r6, #0x1a]
    strh    sl, [r6, #0x26]
    strh    sl, [r6, #0x28]
    strh    sl, [r6, #0x2a]
    add     r1, r1, #0xe8           @ memcpy source: 64 bytes from job+0xE8
    mov     r2, #0x40
    add     r0, r6, #0x2c           @ memcpy destination: header bytes 0x2C-0x6B
