# SX1302 MCUs

The SX1302 has two small MCUs, AGC and ARB. `sx1302_hal` loads an 8 KB image into each at start-up (`agc_fw_sx1250.var`, `arb_fw.var`, plus `cal_fw.var` for radio calibration). Their instruction set is the mid-range PIC16 one.

## Image format

- 4096 words, 16 bits, little endian, loaded at page 0: AGC at 0x0000, ARB at 0x2000.
- Bits 13:0 are a PIC16 instruction.
- Bit 14 is even parity of bits 13:0, on all 16,384 words of the four images.
- Bits 15:14 together equal the number of set bits in the 14-bit instruction modulo four. The rule matches all 16,384 words in the four stock images. For example, 0x3FFF has 14 set bits, so it is stored as 0xBFFF. Both cores raised the parity flag when either check bit in a custom MOVLW was inverted.

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

The calibration image drives a register port to the radio:

| File register | Use |
| --- | --- |
| 0x15 | 8-bit register address |
| 0x16 | write data |
| 0x17 bit 0 | write strobe (BSF then BCF) |
| 0x17 bit 1 | read strobe |
| 0x0D | read data |

The 8-bit addresses match radio registers, so this is the MCU's link to the SX125x/SX1250, not to the SX1302's own register space.

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

At 771 cycles per count (PIC16 timing) that is 16.0 million instruction cycles per second. The program runs with either value of bit 15; the parity error flag is set in both cases, so a fixed value of bit 15 gives some instructions an incorrect check field. `tune` reloads the gateway firmware.

## Open

- Direct or indirect access from either core to capture RAM remains open.
- The rest of the file register map: mailboxes, radio and front-end control, and whether the MCUs can reach the capture RAM.

## Volatile firmware experiments

On one WM1302, both cores ran three-instruction status reporters with check bits clear of errors. The ARB read host debug configuration bytes 0 through 3 at internal port addresses 0x28..0x2B. Internal writes to addresses 0x01..0x04 appeared at host debug status bytes 0 through 3. The 0x15/0x16/0x17/0x0D register interface on ARB therefore reaches on-chip resources. A bytewise 32-bit XOR returned the expected four bytes for eight challenges.

A seven-instruction routine at unused ARB program words 0x030..0x036 replaced the stock boot literal at 0x46A with a jump, read a host challenge, XORed it with 0xA5 and jumped back to 0x46B. On three restarts the stock handshake published the three expected responses, advanced from status 1 to 0, and a source-12 capture completed. Packet demodulation under the modified image was not tested.

With A at 904.300 MHz and B at 915.000 MHz, AGC peripheral reads at 0x21 and 0x23 separately followed a nearby HackRF tone on A and B. An AGC program thresholded both values, returned two live bits and latched which chains had seen RF since launch. It retained both events across a test with no host commands during or between the bursts. Register scale, update rate and minimum detectable pulse duration remain uncharacterized.
