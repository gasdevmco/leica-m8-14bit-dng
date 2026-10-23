@ INFO button in shooting mode opens Body Debug Data (shot count, battery, temperature, lens code).
@ Code placed over the `bf_memtest1` debug command (0x2ABD0-0x2AF90, FINDINGS "Reclaimable space").
@
@ 0x2ABD0  bf_memtest1 handler entry, now a stub that returns 0. The boot-time registration of the
@          command is untouched; the shell can still call it, it just does nothing.
@ 0x2ABD8  info_open: reached by `bne` from the application key handler 0x44E30, INFO branch, in
@          the case stock ignores (0x44F68 `bne 0x44F8C`: not in service mode, app+0x25741 clear).
@          r4 = GUI application. The handler's frame is still live; we leave through its epilogue
@          0x44F8C (`ldm sp, {r4, r5, fp, sp, pc}`) with sp and r4 as we found them.
@
@ It repeats the camera's own path "service mode, INFO, Body Debug Data" (FINDINGS "GUI"):
@   0x44F6C-0x44F88  show camInfoMenu (app+0x6F6C) with 0x58FE8(menu, 1); app+0x2548F = 1
@   0x65630, 0x6567C menu+0x99 = 0; 0x40360(menu+0x138, 1) shows BodyDebugDataDialog
@ SET closes the dialog; it sends 'a' to camInfoMenu, which clears app+0x2548F and hides itself.
@ Writes: those two flag bytes (same values the firmware writes there). Calls: only 0x58FE8 and
@ 0x40360. No flash, EEPROM or settings writes; the dialog's body request is command 0x33 (read).

    .syntax unified
    .arm
    .text

    .equ MENU,       0x6F6C         @ camInfoMenu inside the application object
    .equ DIALOG,     0x138          @ BodyDebugDataDialog inside camInfoMenu
    .equ SHOW_PAGE,  0x00058FE8     @ as 0x44F78
    .equ SHOW,       0x00040360     @ as 0x6567C
    .equ RETURN,     0x00044F8C     @ key handler epilogue

stub:
    mov     r0, #0
    bx      lr

info_open:
    add     r0, r4, #(MENU & 0xFF00)
    add     r0, r0, #(MENU & 0x00FF)
    mov     r1, #1
    mov     lr, pc                  @ pc reads as this + 8 = the instruction after the ldr
    ldr     pc, =SHOW_PAGE
    add     r3, r4, #0x25400
    mov     r2, #1
    strb    r2, [r3, #0x8F]         @ app+0x2548F = 1 ("debug menu open"), as 0x44F88
    add     r0, r4, #(MENU & 0xFF00)
    add     r0, r0, #(MENU & 0x00FF)
    mov     r3, #0
    strb    r3, [r0, #0x99]         @ menu+0x99 = 0, as 0x65630
    add     r0, r0, #DIALOG
    mov     r1, #1
    mov     lr, pc
    ldr     pc, =SHOW
    ldr     pc, =RETURN

    .ltorg
