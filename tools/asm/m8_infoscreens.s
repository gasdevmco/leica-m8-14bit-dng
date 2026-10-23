@ INFO screens (stage 7): INFO in shooting mode shows "Last shot" (thumbnail + histogram), INFO
@ again shows "Camera stats" (shot count, battery, temperature, lens code), INFO or SET closes.
@ Code placed over four Blackfin-test debug commands and their two private helpers
@ (0x2ABD0-0x2B6E8: bf_memtest1, 0x2AF90 + 0x2B05C (called only by bf_memtest2), bf_memtest2,
@ bf_memtest3, bf_checktrans; FINDINGS "Reclaimable space"). Each command entry stays a stub
@ returning 0; `.org` pins the stubs, so code overlapping one fails to assemble.
@
@ 0x2ABD0  bf_memtest1 entry, stub returning 0 (all four registrations untouched).
@ 0x2ABD8  info_open: reached by `bne` from the application key handler 0x44E30 (0x44F68), as in
@          stage 6. Opens camInfoMenu and its BodyDebugDataDialog the camera's own way (stage 6),
@          but first points the dialog at vt_hist, our copy of its method table with our title,
@          content and key methods. The page shown = which of our two tables the dialog uses.
@ on_key   INFO: hist -> stats (switch table, redraw); stats -> close. SET: close. Others ignored.
@          close = restore the dialog's own table 0xED1B8, then its own SET path 0x61868 (hide,
@          'a' to camInfoMenu, which hides itself and clears app+0x2548F).
@ Painting: the dialog's base paint 0x605AC clears the window and calls our +0x48 (title) and
@ +0x4C (content). We draw only with the GUI's routines (fill 0x98A40, vertical line 0x98C34,
@ text 0x996EC, text width 0x99C0C), plus the thumbnail copied pixel by pixel into the
@ framebuffer the display object hands out (as 0x98A40 does), inside 8..168 x 32..139.
@ Reads: app+0x251A8 (last displayed image, 320x240 RGB; histogram code 0x55260 uses the same),
@ the body debug data (command 0x33 via 0x3E238 into the dialog's own buffer +0xB0, as 0x60FC0).
@ Writes: the two flag bytes of stage 6, the dialog's method-table pointer (dialog+0), the
@ dialog's body-data buffer (by 0x3E238), the screen, our stack. No flash, EEPROM or settings.

    .syntax unified
    .arm
    .text

    .equ BASE,       0x0002ABD0     @ load address of `stub` (for the method tables)
    .equ MENU,       0x6F6C         @ camInfoMenu inside the application object
    .equ DIALOG,     0x138          @ BodyDebugDataDialog inside camInfoMenu
    .equ DLG_VT,     0x000ED1B8     @ the dialog's own method table
    .equ DLG_KEY,    0x00061868     @ the dialog's own key method (SET = close)
    .equ SHOW_PAGE,  0x00058FE8
    .equ SHOW,       0x00040360
    .equ RETURN,     0x00044F8C     @ application key handler epilogue
    .equ FILL,       0x00098A40     @ (x, y, w, h, [sp] colour565)
    .equ VLINE,      0x00098C34     @ (x, y, length, colour565, [sp] 0)
    .equ TEXT,       0x000996EC     @ (x, y, w, h, [sp] str, [sp+4] colour565, [sp+8] font)
    .equ TWIDTH,     0x00099C0C     @ (str, font) -> width + 1
    .equ SPRINTF,    0x000B94EC
    .equ MEMSET,     0x000B4034
    .equ UDIV,       0x000CAB28     @ r0 / r1, unsigned
    .equ BODY_DATA,  0x0003E238     @ (body link, dest) -> 0 = ok
    .equ P_APP,      0x000D4220
    .equ P_CTX2,     0x000D421C
    .equ P_DISP,     0x0017F988
    .equ F3,         0x30000        @ font 3 (FONT1, 17 px) << 16
    .equ F4,         0x40000        @ font 4 (FONT2, 21 px) << 16
    .equ WHITE,      0xFFFF
    .equ GREY,       0x94B2         @ (150, 150, 150)
    .equ FOOT,       0x6B6D         @ (110, 110, 110)
    .equ BAR,        0x2945         @ (40, 40, 40)
    .equ DOTOFF,     0x5AEB         @ (90, 90, 90)
    .equ FRAME,      0x2965         @ (45, 45, 45)
    .equ LUMA,       0x5AEB         @ (95, 95, 95)
    .equ RED,        0xE1E7
    .equ GREEN,      0x3E47
    .equ BLUE,       0x53DF
    .equ HX,         32             @ histogram: 128 bins x 2 px
    .equ HY,         146
    .equ HH,         70

.macro fcall addr                   @ call a firmware routine without a relocation
    mov     lr, pc                  @ pc reads as this + 8 = the instruction after the ldr
    ldr     pc, =\addr
.endm
.macro la reg, label, cond=al          @ absolute address of a label here (adr cannot reach)
    ldr\cond   \reg, =(BASE + \label - stub)
.endm
.macro lcall label                  @ call a local routine
    mov     lr, pc
    b       \label
.endm

stub:
    mov     r0, #0
    bx      lr

info_open:                          @ r4 = GUI application
    add     r0, r4, #(MENU & 0xFF00)
    add     r0, r0, #(MENU & 0x00FF)
    mov     r1, #1
    fcall   SHOW_PAGE               @ show camInfoMenu, as 0x44F78
    add     r3, r4, #0x25400
    mov     r2, #1
    strb    r2, [r3, #0x8F]         @ app+0x2548F = 1, as 0x44F88
    add     r0, r4, #(MENU & 0xFF00)
    add     r0, r0, #(MENU & 0x00FF)
    mov     r3, #0
    strb    r3, [r0, #0x99]         @ menu+0x99 = 0, as 0x65630
    add     r0, r0, #DIALOG
    la      r1, vt_hist
    str     r1, [r0]                @ the dialog paints and handles keys with our methods
    mov     r1, #1
    fcall   SHOW                    @ show it, as 0x6567C
    ldr     pc, =RETURN

on_key:                             @ (this, key)
    and     r1, r1, #0xFF
    cmp     r1, #'i'
    beq     1f
    cmp     r1, #'s'
    bxne    lr
0:  ldr     r2, =DLG_VT             @ close
    str     r2, [r0]
    mov     r1, #'s'
    ldr     pc, =DLG_KEY
1:  ldr     r2, [r0]
    la      r3, vt_hist
    cmp     r2, r3
    bne     0b                      @ INFO on the stats page closes
    la      r3, vt_stats
    str     r3, [r0]
    ldr     pc, [r3, #0x1C]         @ redraw (method +0x1C, as show() 0x9AEFC), r0 = this

@ ---- helpers
fill:                               @ (x, y, w, h), ip = colour
    push    {lr}
    sub     sp, sp, #4
    str     ip, [sp]
    fcall   FILL
    add     sp, sp, #4
    pop     {pc}

vline:                              @ (x, y, length, colour); length <= 0 draws nothing
    push    {lr}
    sub     sp, sp, #4
    mov     ip, #0
    str     ip, [sp]
    fcall   VLINE
    add     sp, sp, #4
    pop     {pc}

text:                               @ (x, y, str, colour | font << 16), box to the right edge
    push    {r4, lr}
    sub     sp, sp, #16
    str     r2, [sp]
    mov     r4, r3, lsr #16
    str     r4, [sp, #8]
    mov     r3, r3, lsl #16
    mov     r3, r3, lsr #16
    str     r3, [sp, #4]
    rsb     r2, r0, #320
    mov     r3, #30
    fcall   TEXT
    add     sp, sp, #16
    pop     {r4, pc}

text_r:                             @ as text, but r0 = right edge
    push    {r4-r7, lr}
    mov     r4, r0
    mov     r5, r1
    mov     r6, r2
    mov     r7, r3
    mov     r0, r2
    mov     r1, r3, lsr #16
    fcall   TWIDTH
    sub     r0, r4, r0
    mov     r1, r5
    mov     r2, r6
    mov     r3, r7
    lcall   text
    pop     {r4-r7, pc}

@ ---- title bar (+0x48): bar, page name, two page dots, footer
title:                              @ (this)
    push    {r4, lr}
    ldr     r4, [r0]
    mov     r0, #0
    mov     r1, #0
    mov     r2, #320
    mov     r3, #25
    ldr     ip, =BAR
    lcall   fill
    la      r0, vt_hist
    cmp     r4, r0
    la      r2, s_hist, eq
    la      r2, s_stats, ne
    mov     r0, #8
    mov     r1, #4
    ldr     r3, =(WHITE | F3)
    lcall   text
    la      r0, vt_hist
    cmp     r4, r0
    ldreq   ip, =WHITE
    ldrne   ip, =DOTOFF
    mov     r0, #288
    lcall   dot
    la      r0, vt_hist
    cmp     r4, r0
    ldrne   ip, =WHITE
    ldreq   ip, =DOTOFF
    mov     r0, #300
    lcall   dot
    la      r0, vt_hist
    cmp     r4, r0
    la      r2, s_foot1, eq
    la      r2, s_foot2, ne
    mov     r0, #8
    mov     r1, #218
    ldr     r3, =(FOOT | F3)
    lcall   text
    pop     {r4, pc}

dot:                                @ (x), ip = colour: 6 x 6 at y 10
    mov     r1, #10
    mov     r2, #6
    mov     r3, #6
    b       fill

@ ---- "Last shot" content (+0x4C)
hist_paint:                         @ (this)
    push    {r4-r11, lr}
    sub     sp, sp, #1024           @ bins: L, R, G, B; 128 x u16 each
    ldr     r0, =P_APP
    ldr     r0, [r0]
    add     r0, r0, #0x25000
    ldr     r4, [r0, #0x1A8]        @ last displayed image (as 0x55280)
    cmp     r4, #0
    beq     no_image
    add     r4, r4, #0x3000
    add     r4, r4, #0xC0           @ photo area: rows 13..226 (as 0x55290)
    mov     r0, sp
    mov     r1, #0
    mov     r2, #1024
    fcall   MEMSET
    ldr     r0, =P_DISP
    ldr     r0, [r0]
    ldr     r1, [r0]
    mov     lr, pc
    ldr     pc, [r1, #0x14]         @ framebuffer, as 0x98AEC
    add     r5, r0, #0x7800
    add     r5, r5, #0x18           @ thumbnail at (8, 32): 32 * 960 + 8 * 3
    mov     r10, sp
    mov     r6, #107                @ 214 rows / 2
2:  mov     r7, #160                @ 320 columns / 2
    mov     r8, r4
    mov     r9, r5
3:  ldrb    r0, [r8]
    ldrb    r1, [r8, #1]
    ldrb    r2, [r8, #2]
    strb    r0, [r9]
    strb    r1, [r9, #1]
    strb    r2, [r9, #2]
    mov     ip, #77                 @ luma = (77 R + 150 G + 29 B) >> 8
    mul     r11, r0, ip
    mov     ip, #150
    mla     r11, r1, ip, r11
    mov     ip, #29
    mla     r11, r2, ip, r11
    mov     r11, r11, lsr #8
    bic     r3, r11, #1             @ bin * 2 = byte offset
    add     r3, r3, r10
    ldrh    ip, [r3]
    add     ip, ip, #1
    strh    ip, [r3]
    bic     r3, r0, #1
    add     r3, r3, r10
    add     r3, r3, #256
    ldrh    ip, [r3]
    add     ip, ip, #1
    strh    ip, [r3]
    bic     r3, r1, #1
    add     r3, r3, r10
    add     r3, r3, #512
    ldrh    ip, [r3]
    add     ip, ip, #1
    strh    ip, [r3]
    bic     r3, r2, #1
    add     r3, r3, r10
    add     r3, r3, #768
    ldrh    ip, [r3]
    add     ip, ip, #1
    strh    ip, [r3]
    add     r8, r8, #6
    add     r9, r9, #3
    subs    r7, r7, #1
    bne     3b
    add     r4, r4, #1920           @ two source rows
    add     r5, r5, #960
    subs    r6, r6, #1
    bne     2b
    @ scale: m = largest bin of any channel, ignoring bins 0 and 127 (clipped ends)
    mov     r11, #1
    mov     r6, #0
4:  and     r0, r6, #127
    cmp     r0, #0
    cmpne   r0, #127
    beq     5f
    mov     r0, r6, lsl #1
    ldrh    r0, [r10, r0]
    cmp     r0, r11
    movhi   r11, r0
5:  add     r6, r6, #1
    cmp     r6, #512
    blo     4b
    @ every bin -> height min(HH, bin * HH / m)
    mov     r6, #0
6:  mov     r7, r6, lsl #1
    ldrh    r0, [r10, r7]
    mov     r1, #HH
    mul     r0, r1, r0
    mov     r1, r11
    fcall   UDIV
    cmp     r0, #HH
    movhi   r0, #HH
    strh    r0, [r10, r7]
    add     r6, r6, #1
    cmp     r6, #512
    blo     6b
    @ frame
    mov     r0, #(HX - 1)
    mov     r1, #(HY - 1)
    mov     r2, #256
    add     r2, r2, #2
    mov     r3, #(HH + 2)
    ldr     ip, =FRAME
    lcall   fill
    mov     r0, #HX
    mov     r1, #HY
    mov     r2, #256
    mov     r3, #HH
    mov     ip, #0
    lcall   fill
    @ luma: filled, 2 px per bin
    mov     r6, #0
7:  mov     r7, r6, lsl #1
    ldrh    r2, [r10, r7]
    rsb     r1, r2, #(HY + HH)
    add     r0, r7, #HX
    ldr     r3, =LUMA
    lcall   vline
    mov     r7, r6, lsl #1
    ldrh    r2, [r10, r7]
    rsb     r1, r2, #(HY + HH)
    add     r0, r7, #(HX + 1)
    ldr     r3, =LUMA
    lcall   vline
    add     r6, r6, #1
    cmp     r6, #128
    blo     7b
    @ R, G, B: curves (a vertical segment from the previous bin's height to this one's)
    mov     r8, #256
    ldr     r9, =RED
    lcall   curve
    mov     r8, #512
    ldr     r9, =GREEN
    lcall   curve
    mov     r8, #768
    ldr     r9, =BLUE
    lcall   curve
    b       8f
no_image:
    mov     r0, #8
    mov     r1, #100
    la      r2, s_noimg
    ldr     r3, =(WHITE | F4)
    lcall   text
8:  add     sp, sp, #1024
    pop     {r4-r11, pc}

curve:                              @ r10 = heights, r8 = channel byte offset, r9 = colour
    push    {lr}
    mov     r6, #0
    ldrh    r5, [r10, r8]           @ previous height
9:  add     r0, r8, r6, lsl #1
    ldrh    r4, [r10, r0]           @ this bin's height
    cmp     r4, r5
    movhs   r1, r4                  @ r1 = higher, r2 = lower
    movhs   r2, r5
    movlo   r1, r5
    movlo   r2, r4
    sub     r2, r1, r2
    add     r2, r2, #1              @ length
    rsb     r1, r1, #(HY + HH)      @ top y
    cmp     r1, #(HY + HH)          @ keep inside the box
    movhs   r1, #(HY + HH - 1)
    movhs   r2, #1
    push    {r1, r2}
    add     r0, r6, r6
    add     r0, r0, #HX
    mov     r3, r9
    lcall   vline
    pop     {r1, r2}
    add     r0, r6, r6
    add     r0, r0, #(HX + 1)       @ both columns of the 2 px bin
    mov     r3, r9
    lcall   vline
    mov     r5, r4
    add     r6, r6, #1
    cmp     r6, #128
    blo     9b
    pop     {pc}

@ ---- bf_memtest2 entry (0x2B0E0): kept as a stub returning 0
    .org    0x2B0E0 - BASE
    mov     r0, #0
    bx      lr

@ ---- "Camera stats" content (+0x4C)
stats_paint:                        @ (this)
    push    {r4-r6, lr}
    sub     sp, sp, #48
    mov     r4, r0
    ldr     r0, =P_CTX2
    ldr     r0, [r0]
    add     r0, r0, #0x5000
    add     r0, r0, #0xC0
    add     r1, r4, #0xB0
    fcall   BODY_DATA               @ command 0x33, as 0x60FC0
    cmp     r0, #0
    beq     10f
    mov     r0, #8
    mov     r1, #100
    la      r2, s_nodata
    ldr     r3, =(WHITE | F4)
    lcall   text
    b       11f
10: adr     r6, rows                @ {label, format, field offset | type << 16} x 4
    mov     r5, #40
12: ldr     r2, [r6]
    add     r2, r6, r2              @ label (offset from the row)
    mov     r0, #12
    mov     r1, r5
    ldr     r3, =(GREY | F3)
    lcall   text
    ldr     r3, [r6, #8]
    mov     r2, r3, lsl #16
    mov     r2, r2, lsr #16
    add     r2, r4, r2              @ field address
    tst     r3, #0x10000
    ldreq   r2, [r2]                @ type 0: u32, 1: byte
    ldrbne  r2, [r2]
    tst     r3, #0x20000            @ type 2: battery name
    beq     13f
    cmp     r2, #4
    movhi   r2, #5
    la      r1, batt
    ldr     r2, [r1, r2, lsl #2]
    add     r2, r1, r2              @ table holds offsets from `batt`
13: ldr     r1, [r6, #4]
    add     r1, r6, r1              @ format (offset from the row)
    mov     r0, sp
    fcall   SPRINTF
    mov     r0, #308
    sub     r1, r5, #2
    mov     r2, sp
    ldr     r3, =(WHITE | F4)
    lcall   text_r
    add     r6, r6, #12
    add     r5, r5, #34
    cmp     r5, #(40 + 4 * 34)
    blo     12b
    mov     r0, #12                 @ firmware row
    mov     r1, r5
    la      r2, s_fw
    ldr     r3, =(GREY | F3)
    lcall   text
    mov     r0, #308
    sub     r1, r5, #2
    la      r2, s_fwv
    ldr     r3, =(WHITE | F4)
    lcall   text_r
11: add     sp, sp, #48
    pop     {r4-r6, pc}

@ ---- data
    .align  2
rows:
    .word   s_shots - rows,      s_fmt_d - rows,  0x000E4     @ NumExposures (u32), as 0x61680
    .word   s_batt - (rows+12),  s_fmt_s - (rows+12), 0x200C8 @ battery state (byte), as 0x612D4
    .word   s_temp - (rows+24),  s_fmt_t - (rows+24), 0x000C4 @ temperature "normal", as 0x6124C
    .word   s_lens - (rows+36),  s_fmt_d - (rows+36), 0x100DD @ lens code (byte), as 0x615D8
batt:
    .word   b0 - batt, b1 - batt, b2 - batt, b3 - batt, b4 - batt, b5 - batt

vt_hist:                            @ copy of 0xED1B8 with title / content / keys replaced
    .word   0xCD34C, 0xCD354, 0xCD35C, 0xCD364, 0x9A8D0, 0xD1E6C, 0xD1EB4, 0x9A47C
    .word   0xCD36C, 0x605AC, 0x9A8F0, BASE + (on_key - stub), 0x9ACD8, 0x9AD68, 0x9AD6C, 0x40360
    .word   0xCD370, 0xCD374, BASE + (title - stub), BASE + (hist_paint - stub), 0, 0
vt_stats:
    .word   0xCD34C, 0xCD354, 0xCD35C, 0xCD364, 0x9A8D0, 0xD1E6C, 0xD1EB4, 0x9A47C
    .word   0xCD36C, 0x605AC, 0x9A8F0, BASE + (on_key - stub), 0x9ACD8, 0x9AD68, 0x9AD6C, 0x40360
    .word   0xCD370, 0xCD374, BASE + (title - stub), BASE + (stats_paint - stub), 0, 0

@ ---- bf_memtest3 entry (0x2B338): kept as a stub returning 0
    .org    0x2B338 - BASE
    mov     r0, #0
    bx      lr

@ ---- bf_checktrans entry (0x2B4B0): kept as a stub returning 0
    .org    0x2B4B0 - BASE
    mov     r0, #0
    bx      lr

s_hist:   .asciz "Last shot"
s_stats:  .asciz "Camera stats"
s_foot1:  .asciz "INFO: stats    SET: close"
s_foot2:  .asciz "INFO / SET: close"
s_noimg:  .asciz "No image yet"
s_nodata: .asciz "Body data unavailable"
s_shots:  .asciz "Shots taken"
s_batt:   .asciz "Battery"
s_temp:   .asciz "Temperature"
s_lens:   .asciz "Lens code"
s_fw:     .asciz "Firmware"
s_fwv:    .asciz "2.014 + INFO"
s_fmt_d:  .asciz "%d"
s_fmt_s:  .asciz "%s"
s_fmt_t:  .asciz "%d \302\260C"
b0:       .asciz "Empty"
b1:       .asciz "Almost empty"
b2:       .asciz "Half"
b3:       .asciz "Almost full"
b4:       .asciz "Full"
b5:       .asciz "Unknown"
    .align  2
    .ltorg
