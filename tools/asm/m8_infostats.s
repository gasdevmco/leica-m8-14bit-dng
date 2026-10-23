@ INFO screen (stage 8): INFO in shooting mode shows "Camera stats" (shot count, battery,
@ temperature, lens code, firmware); INFO or SET closes it.
@ Code placed over the `bf_memtest1` debug command, the two helpers only `bf_memtest2` calls and
@ `bf_memtest2` (0x2ABD0-0x2B338; FINDINGS "Reclaimable space"). Both command entries stay stubs
@ returning 0 (bf_memtest2's at 0x2B0E0 pinned by `.org`); m8_dngpatch.py fills the rest of
@ bf_memtest2 with undefined instructions. Registrations untouched.
@
@ 0x2ABD0  bf_memtest1 entry, stub returning 0.
@ 0x2ABD8  info_open: reached by `bne` from the application key handler 0x44E30 (0x44F68), as in
@          stage 6. Opens camInfoMenu and its BodyDebugDataDialog the camera's own way (stage 6),
@          but first points the dialog at vt_stats, our copy of its method table with our title,
@          content and key methods.
@ on_key   INFO or SET: restore the dialog's own table 0xED1B8, then its own SET path 0x61868
@          (hide, 'a' to camInfoMenu, which hides itself and clears app+0x2548F). Others ignored.
@ Painting: the dialog's base paint 0x605AC clears the window and calls our +0x48 (title) and
@ +0x4C (content). We draw only with the GUI's routines (fill 0x98A40, text 0x996EC, text width
@ 0x99C0C) and format with sprintf 0xB94EC.
@ Reads: the body debug data (command 0x33 via 0x3E238 into the dialog's own buffer +0xB0, as the
@ dialog's own paint 0x60FC0 does, once per paint).
@ Writes: the two flag bytes of stage 6, the dialog's method-table pointer (dialog+0), the
@ dialog's body-data buffer (by 0x3E238), the screen (by the GUI routines), our stack.

    .syntax unified
    .arm
    .text

    .equ BASE,       0x0002ABD0     @ load address of `stub` (for the method table)
    .equ MENU,       0x6F6C         @ camInfoMenu inside the application object
    .equ DIALOG,     0x138          @ BodyDebugDataDialog inside camInfoMenu
    .equ DLG_VT,     0x000ED1B8     @ the dialog's own method table
    .equ DLG_KEY,    0x00061868     @ the dialog's own key method (SET = close)
    .equ SHOW_PAGE,  0x00058FE8
    .equ SHOW,       0x00040360
    .equ RETURN,     0x00044F8C     @ application key handler epilogue
    .equ FILL,       0x00098A40     @ (x, y, w, h, [sp] colour565)
    .equ TEXT,       0x000996EC     @ (x, y, w, h, [sp] str, [sp+4] colour565, [sp+8] font)
    .equ TWIDTH,     0x00099C0C     @ (str, font) -> width + 1
    .equ SPRINTF,    0x000B94EC
    .equ BODY_DATA,  0x0003E238     @ (body link, dest) -> 0 = ok
    .equ P_CTX2,     0x000D421C
    .equ F3,         0x30000        @ font 3 (FONT1, 17 px) << 16
    .equ F4,         0x40000        @ font 4 (FONT2, 21 px) << 16
    .equ WHITE,      0xFFFF
    .equ GREY,       0x94B2         @ (150, 150, 150)
    .equ FOOT,       0x6B6D         @ (110, 110, 110)
    .equ BAR,        0x2945         @ (40, 40, 40)

.macro fcall addr                   @ call a firmware routine without a relocation
    mov     lr, pc                  @ pc reads as this + 8 = the instruction after the ldr
    ldr     pc, =\addr
.endm
.macro la reg, label                 @ absolute address of a label here (adr cannot reach)
    ldr     \reg, =(BASE + \label - stub)
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
    adr     r1, vt_stats
    str     r1, [r0]                @ the dialog paints and handles keys with our methods
    mov     r1, #1
    fcall   SHOW                    @ show it, as 0x6567C
    ldr     pc, =RETURN

on_key:                             @ (this, key)
    and     r1, r1, #0xFF
    cmp     r1, #'i'
    cmpne   r1, #'s'
    bxne    lr                      @ other keys: ignored
    ldr     r2, =DLG_VT             @ INFO or SET: close with the dialog's own methods
    str     r2, [r0]
    mov     r1, #'s'
    ldr     pc, =DLG_KEY

@ ---- helpers
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

@ ---- title bar (+0x48): bar, title, footer
title:                              @ (this)
    push    {lr}
    sub     sp, sp, #4
    ldr     ip, =BAR
    str     ip, [sp]
    mov     r0, #0
    mov     r1, #0
    mov     r2, #320
    mov     r3, #25
    fcall   FILL
    add     sp, sp, #4
    mov     r0, #8
    mov     r1, #4
    adr     r2, s_title
    ldr     r3, =(WHITE | F3)
    lcall   text
    mov     r0, #8
    mov     r1, #218
    la      r2, s_foot
    ldr     r3, =(FOOT | F3)
    lcall   text
    pop     {pc}

@ ---- content (+0x4C)
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
    beq     1f
    mov     r0, #8
    mov     r1, #100
    la      r2, s_nodata
    ldr     r3, =(WHITE | F4)
    lcall   text
    b       4f
1:  adr     r6, rows                @ {label, format, field offset | type << 16} x 4
    mov     r5, #40
2:  ldr     r2, [r6]
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
    beq     3f
    cmp     r2, #4
    movhi   r2, #5
    adr     r1, batt
    ldr     r2, [r1, r2, lsl #2]
    add     r2, r1, r2              @ table holds offsets from `batt`
3:  ldr     r1, [r6, #4]
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
    blo     2b
    mov     r0, #12                 @ firmware row
    mov     r1, r5
    la      r2, s_fw
    ldr     r3, =(GREY | F3)
    lcall   text
    mov     r0, #308
    sub     r1, r5, #2
    adr     r2, s_fwv
    ldr     r3, =(WHITE | F4)
    lcall   text_r
4:  add     sp, sp, #48
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

vt_stats:                           @ copy of 0xED1B8 with title / content / keys replaced
    .word   0xCD34C, 0xCD354, 0xCD35C, 0xCD364, 0x9A8D0, 0xD1E6C, 0xD1EB4, 0x9A47C
    .word   0xCD36C, 0x605AC, 0x9A8F0, BASE + (on_key - stub), 0x9ACD8, 0x9AD68, 0x9AD6C, 0x40360
    .word   0xCD370, 0xCD374, BASE + (title - stub), BASE + (stats_paint - stub), 0, 0

s_title:  .asciz "Camera stats"
s_foot:   .asciz "INFO / SET: close"
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

@ ---- bf_memtest2 entry (0x2B0E0): kept as a stub returning 0 (its old body: undefined fill)
    .org    0x2B0E0 - BASE
    mov     r0, #0
    bx      lr
