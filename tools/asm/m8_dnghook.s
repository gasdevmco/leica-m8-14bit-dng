@ In-camera DNG: code placed over the `ldimg` debug command (0x28AB0-0x29104, FINDINGS
@ "Reclaimable space"). Position independent; m8_dngpatch.py appends the data tables (`tables`).
@
@ 0x28AB0  ldimg handler entry, now a stub that returns 0. The boot-time registration of the
@          command is untouched; the shell can still call it, it just does nothing.
@ 0x28AB8  dng_hook: reached by `bl` from the RAW producer's last-block branch (0x3C6A8, stock
@          `b 0x3C5EC`), i.e. once per RAW/BIA file, after the last DMA block has arrived and
@          before it is copied into the ring. Returns to 0x3C5EC with every register except
@          r0-r3, ip, lr as it found them (r0-r3, ip, lr are dead there: 0x3C5EC reloads them).
@
@ What it does (mode word in `tables`):
@   skip a .BIA dark frame (job+0x21A), any other geometry than 3976 x 2647, or a destination
@   outside the DMA buffer; dest = start of the trailing sensor row in this block's buffer
@   (same address arithmetic as 0x3C61C-0x3C640, plus last-block bytes - row bytes).
@   mode 1: dump (stage 3) -- "M8DUMP01", ctx+0x4210..0x4240, hook inputs, job+0..0x280,
@           settings block (0x200 bytes) into the trailing row.
@   mode 2: DNG (stage 4) -- copy the IFD template, then fill each per-shot slot from the job.
@   then clean + invalidate the D-cache lines of the written span, drain the write buffer.
@ Every store goes through `.Lcopy`, which writes nothing unless the whole destination range lies
@ inside the trailing row and inside the DMA buffer. Reads: ctx, job, settings block, own data.
@ No calls to any firmware function.

    .syntax unified
    .arm
    .text

    .equ DMA_BUF,  0x026F44E0       @ CPU address of DMA buffer 0 (phys 0xA26F44E0)
    .equ DMA_ALT,  0x0003E080       @ offset of buffer 1
    .equ DMA_END,  0x0276C5E0       @ DMA_BUF + 2 * DMA_ALT
    .equ ROW_BYTES, 7952            @ 3976 samples
    .equ ROWS,     2647             @ incl. the trailing row
    .equ SPAN,     0x800            @ bytes after dest that may be written (cache maintenance)
    .equ P_SETTINGS, 0x000D4230     @ -> settings block

.macro call_copy                     @ bl .Lcopy, without the relocation clang emits for bl
    mov     lr, pc                  @ pc reads as this + 8 = the instruction after the b
    b       .Lcopy
.endm

ldimg_stub:                         @ 0x28AB0
    mov     r0, #0
    bx      lr

dng_hook:                           @ 0x28AB8
    push    {r4-r11, lr}
    adr     r8, tables
    add     ip, r4, #0x4600
    ldr     r5, [ip, #0x34]         @ job = [ctx+0x4634]
    ldrb    r1, [r5, #0x21A]        @ .BIA dark frame: leave it alone
    cmp     r1, #0
    bne     done
    add     ip, r4, #0x4200
    ldr     r1, [ip, #0x28]         @ row bytes [ctx+0x4228] (doubled by the store routine)
    ldr     r2, [ip, #0x2C]         @ rows [ctx+0x422C]
    ldr     r10, [ip, #0x20]        @ block index [ctx+0x4220]
    ldr     r3, =ROW_BYTES
    cmp     r1, r3
    ldreq   r3, =ROWS
    cmpeq   r2, r3
    bne     done                    @ only the geometry the template describes
    ldr     r6, =DMA_BUF            @ this block's buffer, as 0x3C61C-0x3C640
    tst     r10, #1
    ldrne   r3, =DMA_ALT
    addne   r6, r6, r3
    add     r6, r6, r7              @ + last-block bytes - row bytes = trailing row
    sub     r6, r6, r1
    ldr     r3, =DMA_BUF
    cmp     r6, r3
    blo     done
    ldr     r3, =DMA_END - SPAN
    cmp     r6, r3
    bhi     done
    ldr     r9, [r8]                @ mode
    cmp     r9, #2
    beq     dng
    cmp     r9, #1
    bne     done

dump:                               @ stage 3: raw material for checking the metadata offsets
    mov     r0, r6
    adr     r1, magic
    mov     r2, #8
    call_copy
    add     r0, r6, #0x8
    add     r1, r4, #0x4200
    add     r1, r1, #0x10
    mov     r2, #0x30
    call_copy                    @ ctx+0x4210..0x4240 (writer, block size/count/index, geometry)
    push    {r4, r6, r7, r10}       @ ctx, dest, last-block bytes, block index
    add     r0, r6, #0x38
    mov     r1, sp
    mov     r2, #16
    call_copy
    add     sp, sp, #16
    add     r0, r6, #0x80
    mov     r1, r5
    mov     r2, #0x280
    call_copy                    @ job+0..0x280 (metadata struct S at job+4)
    ldr     r1, =P_SETTINGS
    ldr     r1, [r1]
    add     r0, r6, #0x300
    mov     r2, #0x200
    call_copy                    @ settings block (profiles: WB etc.)
    b       flush

dng:                                @ stage 4: IFD template + per-shot slots
    ldr     r2, [r8, #4]            @ template length
    ldr     r11, [r8, #8]           @ slot count
    add     r9, r8, #12             @ slots: u16 template offset, job offset, length, 0
    add     r1, r9, r11, lsl #3     @ template follows the slots
    mov     r0, r6
    call_copy
slot:
    subs    r11, r11, #1
    bmi     flush
    ldrh    r0, [r9], #2
    ldrh    r1, [r9], #2
    ldrh    r2, [r9], #4
    add     r0, r6, r0
    add     r1, r5, r1
    call_copy
    b       slot

flush:                              @ written data to memory, no stale lines left behind
    bic     r0, r6, #31
    add     r1, r6, #SPAN
1:  mcr     p15, 0, r0, c7, c10, 1  @ clean D-cache line
    mcr     p15, 0, r0, c7, c6, 1   @ invalidate D-cache line
    add     r0, r0, #32
    cmp     r0, r1
    blo     1b
    mov     r0, #0
    mcr     p15, 0, r0, c7, c10, 4  @ drain write buffer

done:
    pop     {r4-r11, lr}
    sub     pc, lr, #0xC0           @ lr = 0x3C6AC -> continue at 0x3C5EC

@ .Lcopy: copy r2 bytes from r1 to r0 -- only if [r0, r0 + r2) lies inside the trailing row
@ [r6, r6 + ROW_BYTES) and inside the DMA buffer; otherwise nothing. Clobbers r0-r3, ip.
.Lcopy:
    cmp     r0, r6
    bxlo    lr
    add     ip, r0, r2
    cmp     ip, r0
    bxlo    lr                      @ length wrapped
    ldr     r3, =ROW_BYTES
    add     r3, r6, r3
    cmp     ip, r3
    bxhi    lr
    ldr     r3, =DMA_END
    cmp     ip, r3
    bxhi    lr
1:  subs    r2, r2, #1
    ldrbpl  r3, [r1], #1
    strbpl  r3, [r0], #1
    bpl     1b
    bx      lr

magic:
    .ascii  "M8DUMP01"
    .ltorg
tables:                             @ appended by m8_dngpatch.py: mode, template length,
                                    @ slot count, slots, template
