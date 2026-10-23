@ Stage 9: stage 8 (INFO -> Camera stats, included unchanged) + a full-screen histogram on the
@ playback histogram page (PLAY -> INFO): UP or DOWN shows it, UP or DOWN again returns.
@ Region 0x2ABD0-0x2B6E8 (as stage 7): stage 8, then this code around the kept stubs of
@ bf_memtest3 (0x2B338) and bf_checktrans (0x2B4B0), pinned by `.org`.
@
@ hist_key (0x2B0E8, right after bf_memtest2's stub): reached through the playback page's key table
@          (0x46C94; the words for 'd' 0x46C98 and 'u' 0x46CDC, stock 0x46D04 = ignored) from its key
@          method 0x46C54 with r5 = the page, inside that method's frame; leaves through 0x46D04
@          (`ldm sp, {r4-r7, fp, sp, pc}`) with sp as found.
@   - Full-screen view showing (marker pixels at (0,0) and (319,0))? -> ask the page to redraw
@     itself (method +0x1C, as show() 0x9AEFC): the camera's page comes back.
@   - Otherwise draw the view over the page: the histogram the page draws (its widget page+0x1128
@     points to the histogram object), in the style of the MENU setting (active profile +0x10):
@     0/1 brightness (bins +0x10), 2/3 R, G, B (bins +0x410/+0x810/+0xC10); 1/3 also print the share
@     of pixels at 0 and 255.
@ Reads: the page, its histogram object, the settings profile, two framebuffer pixels. Writes: the
@ screen (by the GUI routines), our stack. No settings, flash or EEPROM.

    .include "m8_infostats.s"       @ stage 8 at 0x2ABD0-0x2B0E8, bytes unchanged

    .equ PAGE_RET,   0x00046D04     @ playback page key method epilogue
    .equ P_SETTINGS, 0x000D4230
    .equ P_DISP,     0x0017F988
    .equ UDIV,       0x000CAB28     @ r0 / r1, unsigned
    .equ VLINE,      0x00098C34     @ (x, y, length, colour565, [sp] 0)
    .equ MARK,       0x0821         @ (8, 4, 8): marker pixel colour
    .equ MARK24,     0x080408       @ the same as framebuffer bytes R, G, B
    .equ FRAME,      0x2965         @ (45, 45, 45)
    .equ LUMA,       0x9CF3         @ (150, 156, 150)
    .equ RED,        0xE1E7
    .equ GREEN,      0x3E47
    .equ BLUE,       0x53DF
    .equ GX,         32             @ graph: 256 bins x 1 px
    .equ GY,         40
    .equ GH,         150

hist_key:                           @ r5 = playback page (frame of 0x46C54 is live)
    push    {r4-r11}
    sub     sp, sp, #64
    ldr     r0, =P_DISP
    ldr     r0, [r0]
    ldr     r1, [r0]
    mov     lr, pc
    ldr     pc, [r1, #0x14]         @ framebuffer, as 0x98AEC
    ldrb    r1, [r0]
    ldrb    r2, [r0, #1]
    ldrb    r3, [r0, #2]
    orr     r1, r1, r2, lsl #8
    orr     r1, r1, r3, lsl #16
    ldr     r2, =(((MARK24 & 0xFF) << 16) | (MARK24 & 0xFF00) | (MARK24 >> 16))
    cmp     r1, r2
    bne     hk_draw
    add     r0, r0, #960            @ (319, 0) = 957 bytes in
    sub     r0, r0, #3
    ldrb    r1, [r0]
    ldrb    r2, [r0, #1]
    ldrb    r3, [r0, #2]
    orr     r1, r1, r2, lsl #8
    orr     r1, r1, r3, lsl #16
    ldr     r2, =(((MARK24 & 0xFF) << 16) | (MARK24 & 0xFF00) | (MARK24 >> 16))
    cmp     r1, r2
    bne     hk_draw
    mov     r0, r5                  @ view showing: the page redraws itself
    ldr     r3, [r5]
    mov     lr, pc
    ldr     pc, [r3, #0x1C]
    b       hk_ret

hk_draw:
    add     r0, r5, #0x1100
    ldr     r4, [r0, #0x28]         @ histogram object the page's widget draws
    cmp     r4, #0
    beq     hk_ret
    ldr     r0, =P_SETTINGS         @ style = active profile u16 +0x10 (as 0x550EC)
    ldr     r0, [r0]
    ldrh    r1, [r0, #2]
    ldr     r2, =0xFFFF
    cmp     r1, r2
    ldrheq  r1, [r0]
    mov     r2, #0x50
    mla     r0, r1, r2, r0
    ldrh    r6, [r0, #0x2C]         @ +0x1C profile base + 0x10
    cmp     r6, #3
    movhi   r6, #0
    @ background, title bar, markers
    mov     r0, #0
    mov     r1, #0
    mov     r2, #320
    mov     r3, #240
    mov     ip, #0
    lcall   hfill
    mov     r0, #0
    mov     r1, #0
    mov     r2, #320
    mov     r3, #25
    ldr     ip, =BAR
    lcall   hfill
    mov     r0, #0
    mov     r1, #0
    mov     r2, #1
    mov     r3, #1
    ldr     ip, =MARK
    lcall   hfill
    ldr     r0, =319
    mov     r1, #0
    mov     r2, #1
    mov     r3, #1
    ldr     ip, =MARK
    lcall   hfill
    la      r2, s_hrgb
    cmp     r6, #2
    ldrlo   r2, =(BASE + s_hluma - stub)
    mov     r0, #8
    mov     r1, #4
    ldr     r3, =(WHITE | F3)
    lcall   text
    la      r2, s_hfoot
    mov     r0, #8
    mov     r1, #218
    ldr     r3, =(FOOT | F3)
    lcall   text
    @ graph frame
    mov     r0, #(GX - 1)
    mov     r1, #(GY - 1)
    mov     r2, #256
    add     r2, r2, #2
    mov     r3, #(GH + 2)
    ldr     ip, =FRAME
    lcall   hfill
    mov     r0, #GX
    mov     r1, #GY
    mov     r2, #256
    mov     r3, #GH
    mov     ip, #0
    lcall   hfill
    @ scale: largest bin of the channels shown, bins 1..254 (ends are often clipped spikes)
    cmp     r6, #2
    addlo   r7, r4, #0x10           @ first channel
    movlo   r8, #1                  @ channel count
    addhs   r7, r4, #0x400
    addhs   r7, r7, #0x10
    movhs   r8, #3
    mov     r9, #1                  @ max
    mov     r10, #0
1:  add     r0, r7, r10, lsl #10    @ channel r10
    mov     r1, #1
2:  ldr     r2, [r0, r1, lsl #2]
    cmp     r2, r9
    movhi   r9, r2
    add     r1, r1, #1
    cmp     r1, #255
    blo     2b
    add     r10, r10, #1
    cmp     r10, r8
    blo     1b
    @ draw: brightness filled; R, G, B as curves
    cmp     r6, #2
    bhs     4f
    mov     r10, #0
3:  ldr     r0, [r7, r10, lsl #2]
    lcall   height
    mov     r2, r0
    rsb     r1, r0, #(GY + GH)
    add     r0, r10, #GX
    ldr     r3, =LUMA
    lcall   hvline
    add     r10, r10, #1
    cmp     r10, #256
    blo     3b
    b       6f
4:  mov     r11, #0                 @ channel 0..2
5:  add     r8, r7, r11, lsl #10
    la      r0, colours
    ldr     r0, [r0, r11, lsl #2]
    str     r0, [sp]                @ colour of this channel
    lcall   curve
    add     r11, r11, #1
    cmp     r11, #3
    blo     5b
6:  b       hk_clip

@ ---- bf_memtest3 entry (0x2B338): kept as a stub returning 0
    .org    0x2B338 - BASE
    mov     r0, #0
    bx      lr

hk_clip:                            @ clipping figures for styles 1 and 3
    tst     r6, #1
    beq     hk_ret
    cmp     r6, #2                  @ channel count again (the RGB loop used r8 for bins)
    movlo   r8, #1
    movhs   r8, #3
    add     r0, r4, #0x10           @ total = sum of one channel (every pixel counted once)
    cmp     r6, #2
    addhs   r0, r4, #0x400
    addhs   r0, r0, #0x10
    mov     r1, #0
    mov     r2, #0
7:  ldr     r3, [r0, r2, lsl #2]
    add     r1, r1, r3
    add     r2, r2, #1
    cmp     r2, #256
    blo     7b
    cmp     r1, #0
    beq     hk_ret
    mov     r9, r1                  @ total
    mov     r10, #0                 @ shadows = max over shown channels of bin 0
    mov     r11, #0                 @ highlights = ... of bin 255
    mov     r2, #0
8:  add     r0, r7, r2, lsl #10
    ldr     r3, [r0]
    cmp     r3, r10
    movhi   r10, r3
    ldr     r3, [r0, #1020]
    cmp     r3, r11
    movhi   r11, r3
    add     r2, r2, #1
    cmp     r2, r8
    blo     8b
    mov     r0, r10
    lcall   permille
    mov     r10, r0
    mov     r0, r11
    lcall   permille
    mov     r11, r0
    la      r1, s_shad              @ "Shadows x.x %" left, "Highlights x.x %" right
    mov     r2, r10
    lcall   pct
    mov     r0, #8
    mov     r1, #(GY + GH + 6)
    add     r2, sp, #8
    ldr     r3, =(WHITE | F3)
    lcall   text
    la      r1, s_high
    mov     r2, r11
    lcall   pct
    mov     r0, #312
    mov     r1, #(GY + GH + 6)
    add     r2, sp, #8
    ldr     r3, =(WHITE | F3)
    lcall   text_r
hk_ret:
    add     sp, sp, #64
    pop     {r4-r11}
    ldr     pc, =PAGE_RET

@ ---- helpers (r9 = scale max, preserved)
height:                             @ r0 = bin -> min(GH, bin * GH / max)
    push    {lr}
    mov     r1, #GH
    mul     r0, r1, r0
    mov     r1, r9
    fcall   UDIV
    cmp     r0, #GH
    movhi   r0, #GH
    pop     {pc}

permille:                           @ r0 = count -> count * 1000 / total (r9 = total)
    push    {lr}
    ldr     r1, =1000
    mul     r0, r1, r0
    mov     r1, r9
    fcall   UDIV
    pop     {pc}

@ ---- bf_checktrans entry (0x2B4B0): kept as a stub returning 0
    .org    0x2B4B0 - BASE
    mov     r0, #0
    bx      lr

pct:                                @ r1 = format, r2 = per mille -> sprintf(caller sp+8, fmt, r2/10, r2%10)
    push    {r4, r5, lr}
    mov     r4, r1
    mov     r5, r2
    mov     r0, r2
    mov     r1, #10
    fcall   UDIV
    mov     r2, r0
    add     r3, r0, r0, lsl #2
    sub     r3, r5, r3, lsl #1
    add     r0, sp, #(12 + 8)       @ caller's sp + 8 (we pushed 3 words)
    mov     r1, r4
    fcall   SPRINTF
    pop     {r4, r5, pc}

hfill:                              @ (x, y, w, h), ip = colour
    push    {lr}
    sub     sp, sp, #4
    str     ip, [sp]
    fcall   FILL
    add     sp, sp, #4
    pop     {pc}

hvline:                             @ (x, y, length, colour)
    push    {lr}
    sub     sp, sp, #4
    mov     ip, #0
    str     ip, [sp]
    fcall   VLINE
    add     sp, sp, #4
    pop     {pc}

curve:                              @ r8 = bins, [sp, #4] (caller's [sp]) = colour; r9 = max
    push    {r4-r7, lr}
    ldr     r7, [sp, #20]           @ colour (caller's sp)
    ldr     r0, [r8]
    lcall   height
    mov     r5, r0                  @ previous height
    mov     r6, #0
9:  ldr     r0, [r8, r6, lsl #2]
    lcall   height
    mov     r4, r0
    cmp     r4, r5
    movhs   r1, r4                  @ r1 = higher, r2 = lower
    movhs   r2, r5
    movlo   r1, r5
    movlo   r2, r4
    sub     r2, r1, r2
    add     r2, r2, #1              @ segment from the previous height to this one
    rsb     r1, r1, #(GY + GH)
    cmp     r1, #(GY + GH)
    movhs   r1, #(GY + GH - 1)
    movhs   r2, #1
    add     r0, r6, #GX
    mov     r3, r7
    lcall   hvline
    mov     r5, r4
    add     r6, r6, #1
    cmp     r6, #256
    blo     9b
    pop     {r4-r7, pc}

    .align  2
colours:
    .word   RED, GREEN, BLUE
s_hluma:  .asciz "Histogram: brightness"
s_hrgb:   .asciz "Histogram: R, G, B"
s_hfoot:  .asciz "UP / DOWN: back"
s_shad:   .asciz "Shadows %d.%d %%"
s_high:   .asciz "Highlights %d.%d %%"
    .align  2
    .ltorg
