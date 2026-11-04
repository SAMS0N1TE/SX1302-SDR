# Capture RAM

The SX1302 has a 16 KB capture RAM (4096 words of 32 bits) behind register page 1. Semtech's `test_loragw_capture_ram` fills it once from a chosen source and reads it back. The register block also has a wrap mode and a write pointer, which turn it into a ring buffer.

## Registers

| Address | Field | Use |
| --- | --- | --- |
| 0x6000 bit 4 | ENABLE | 1 to enable the block |
| 0x6000 bit 3 | CAPTUREWRAP | 0 stop when full, 1 wrap around |
| 0x6000 bit 2 | CAPTUREFORCETRIGGER | not used here |
| 0x6000 bit 1 | CAPTURESTART | 1 to run |
| 0x6000 bit 0 | RAMCONFIG | 0 is 4k x 32, 1 is 2k x 64 |
| 0x6001 | SOURCE_A_SOURCEMUX | source 0 to 31 |
| 0x6002 | SOURCE_B_SOURCEMUX | second source |
| 0x6003, 0x6004 | CAPTUREPERIOD | 32 MHz / (period + 1) |
| 0x6005 | CAPCOMPLETE | 1 when a one-shot capture is done |
| 0x6006, 0x6007 bits 3:0 | LASTRAMADDR | 12-bit word write pointer |
| 0x5600 bits 1:0 | COMMON_PAGE | 1 maps the capture RAM at 0x0000 |

Read the write pointer with page 0 selected. Reads taken with page 1 selected sometimes jump backwards.

## Sources

Measured with `lgw_start` running, radio A at 904.3 MHz and radio B at 905.0 MHz.

| Source | Rate | Format | Content |
| ---: | ---: | --- | --- |
| 0, 1 | 4 MHz | raw | radio A, B serial data |
| 2, 4 | 4 MS/s | I16 Q16 | radio A I/Q, 12 bits used |
| 3, 5 | 4 MS/s | I16 Q16 | radio B I/Q, 12 bits used |
| 6 | | | zero |
| 9 | 1 MS/s | I16 Q16 | radio A I/Q, filtered |
| 10 to 17 | 125 kS/s | I8 Q8 | IF channels 0 to 7 |
| 18 | 8 MHz | raw | slowly changing status |
| 19, 20 | 125 kHz | raw | constant |
| 21, 23, 24, 26, 30, 31 | | | zero |
| 27, 29 | 32 MHz | raw | constant |

Word layout, little endian: bytes 2 and 3 are I, bytes 0 and 1 are Q for the 16-bit sources. For the 8-bit channel sources I is byte 3 and Q is byte 1.

## Two sources

With RAMCONFIG 1 the RAM holds 2048 words of 64 bits. Bits 31:0 come from SOURCE_A and bits 63:32 from SOURCE_B, sampled together at SOURCE_A's period. `cap2 <a> <b>` and `tools/sx1302_cap2.py` read it.

| Pair | Result |
| --- | --- |
| 12, 12 | both halves identical |
| 12, 13 | channel 2 (CW at +30.0 kHz) and channel 3, same instants |
| 2, 3 | radio A (CW at +29.3 kHz) and radio B (CW at -669.9 kHz) at 4 MS/s, 2048 samples each |
| 9, 12 | channel 12 sampled at 1 MHz, each value held for 8 samples |

## Ring mode

With CAPTUREWRAP set, the write pointer free-runs at the source rate and wraps every 4096 words. CAPCOMPLETE stays 0.

| Source | Rate measured from the pointer | Ring length |
| ---: | ---: | ---: |
| 12 | 125.1 k words/s | 32.8 ms |
| 9 | 1.00 M words/s | 4.1 ms |

`stream` reads from its last position up to the pointer on each pass. At 16 MHz SPI a 125 kS/s channel uses about half the bus:

| Source | SPI | Delivered | Laps | Bus busy |
| ---: | ---: | ---: | ---: | ---: |
| 12 | 16 MHz | 125.0 kS/s, 100% | 0 | 46% |
| 9 | 16 MHz | 272 kS/s, 27% | 198 in 2 s | 60% |

With a CW tone in channel 2, a 10 s stream showed no phase jumps at any of its 16,132 read boundaries, so no sample was lost or repeated between reads.

## Missed writes while streaming

The capture engine sometimes skips writes while the host reads the capture RAM over SPI. The pointer still advances, so the skipped positions keep the sample from one lap (4096 samples) earlier. One-shot captures read after the fill do not have this.

| Load during a one-shot capture | Bad samples |
| --- | --- |
| none | 0 of 24,576 |
| register polls | 0 of 16,384 |
| 1 KB bursts from the RX buffer (page 0) | 0 of 16,384 |
| page 1 selected, no reads | 0 of 12,288 |
| 1 KB bursts from the capture RAM | runs of 64 |
| 512, 256, 128, 64, 32 byte bursts | runs of 32, 16, 8, 4, 2 |

A run lasts exactly as long as the burst that caused it. In a stream about one read in eight is affected, and in that read every sample written during its bursts is lost. The share of lost samples stays near 3% whatever the burst size, gap between bursts, chunk size, SPI clock (8, 16 or 20 MHz), page switching per burst, or with the AGC and ARB MCUs held in reset:

| SPI | Chunk | Burst | Lost |
| ---: | ---: | ---: | ---: |
| 16 MHz | 32 | 1024 B | 3.37% |
| 16 MHz | 256 | 128 B, page per burst | 3.10% |
| 16 MHz | 1024 | 1024 B | 2.98% |
| 8 MHz | 256 | 1024 B | 2.71% |
| 20 MHz | 256 | 1024 B | 3.19% |

`CLOCK_GATE_OVERRIDE` (0x6008) values 1, 2 and 3 make no difference; 0 stops the capture.

The firmware flags words equal to the same position on the previous lap. Long identical runs are strong evidence of missed writes. Quiet one-shot controls also produced isolated matches, so equality alone cannot classify every sample. `stream` reports the count and `pcstream` sends each run as an erasure frame. In an 8 s CW recording, 1,563 of 1,568 phase jumps fell on a flagged erasure.

## SPI

| Clock | 16 KB read | Data |
| ---: | ---: | --- |
| 2 MHz | 66.6 ms | ok |
| 8 MHz | 17.1 ms | ok |
| 16 MHz | 8.9 ms | ok |
| 20 MHz | 7.2 ms | ok |
| 26.7 MHz | 5.6 ms | corrupt |

Measured on jumper wires, CRC of a static buffer compared across clocks.

## Wideband impulses

Polling the chip over SPI while a 4 MS/s capture runs put impulses into the samples. One-shot captures wait out the fill time before polling; with that, the wideband captures stopped clipping (rms fell from about 8300 to 5100 counts). The firmware uses the weakest GPIO drive on SCK, MOSI and CS.

There is a fixed spur at 904.000 MHz on both radios.
