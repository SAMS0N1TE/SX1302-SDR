# SX1302 MCUs

The SX1302 has two small MCUs, AGC and ARB. `sx1302_hal` loads an 8 KB image into each at start-up (`agc_fw_sx1250.var`, `arb_fw.var`, plus `cal_fw.var` for radio calibration). Their instruction set is the mid-range PIC16 one.

## Image format

- 4096 words, 16 bits, little endian, loaded at page 0: AGC at 0x0000, ARB at 0x2000.
- Bits 13:0 are a PIC16 instruction.
- Bit 14 is even parity of bits 13:0, on all 16,384 words of the four images.
- Bit 15 is not a linear function of the instruction, the address or the neighbouring words. Unused words are stored as 0xBFFF (0x3FFF with bit 15 set).

`tools/sx1302_mcu_disasm.py FILE.var [--stats]` decodes an image.

## Evidence for PIC16

- Every image starts `BCF PCLATH,3` then `GOTO`, the reset stub of PIC16 C compilers, with unprogrammed 0x3FFF words over the interrupt vector.
- The AGC start-up code clears two RAM ranges through FSR with the IRP bit (STATUS bit 7) and jumps to `main` on page 1 through PCLATH bit 3.
- The ARB image opens with a computed jump table, `ADDWF PCL,F` followed by `RETLW 0x01, 0x02, 0x04 ... 0x80`.
- All 466 CALL and GOTO targets in the AGC image and all 103 in the ARB image land on used words. The ARB image uses only 1054 of its 4096 words.

| Image | Words used | CALL + GOTO |
| --- | ---: | ---: |
| agc_fw_sx1250 | 3538 | 466 |
| agc_fw_sx1257 | 3460 | 250 |
| arb_fw | 1054 | 103 |
| cal_fw | 3091 | 223 |

## Host interface

| MCU file register | Host register | Seen as |
| --- | --- | --- |
| 0x1B | 0x5781 MCU_AGC_STATUS | AGC `main` writes 0x01 here; the HAL waits for status 0x01 after loading |

AGC `main` also writes 0x0A, the firmware version the HAL expects (10), to file 0x20 early on.

## A program of our own

`mcutest [bit15]` loads this into the AGC MCU in place of Semtech's image:

```
000 CLRF   0x1B
001 CLRF   0x22
002 DECFSZ 0x22,F
003 GOTO   002
004 INCF   0x1B,F
005 GOTO   002
```

The host then reads 0x5781 for 200 ms:

| Bit 15 | Parity error flag | Status counts | Rate |
| ---: | ---: | ---: | ---: |
| 0 | 1 | 4155 in 0.200 s | 20,774 counts/s |
| 1 | 1 | 4155 in 0.200 s | 20,777 counts/s |

At 771 cycles per count (PIC16 timing) that is 16.0 million instruction cycles per second. The program runs with either value of bit 15; the parity error flag is set in both cases, so the loader's check covers something not yet understood. `tune` reloads the gateway firmware.

## Open

- Bit 15 and the parity error flag.
- The rest of the file register map: mailboxes, radio and front-end control, and whether the MCUs can reach the capture RAM.
