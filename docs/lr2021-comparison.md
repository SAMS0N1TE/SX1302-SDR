# SX1302 and LR2021

How the SX1302 on a WM1302 module compares with the LR2021 in [LR2021-SDR](https://github.com/SAMS0N1TE/lr2021-sdr), both on an ESP32-P4 over SPI.

| | LR2021 | SX1302 (WM1302 US915) |
| --- | --- | --- |
| Receive range | 100 MHz to 2.74 GHz | SX1250 150 to 960 MHz; the module's SAW filters pass 902 to 928 MHz |
| I/Q source | capture bank, one stream | capture RAM, 32 sources: 2 radios, 8 channels, more |
| Continuous I/Q over SPI | 250 kS/s 16-bit drained by the host; up to 800 kS/s 8-bit over Wi-Fi | 125 kS/s 8-bit per channel, about 3% erasures |
| Wide snapshots | | 4 MS/s 16-bit, 4096 samples, both radios at once |
| On-chip buffer | 4 KB | 16 KB |
| Clean SPI clock | 16 MHz | 20 MHz on jumper wires |
| Image rejection | about 41 dB | 38 to 40 dB |
| Programmable core | ARCv2, 4 KB patch RAM, programs and toolchain from Alex Beal's lr2021-re | two PIC16-type MCUs, 4096 words each, 16 M instruction cycles/s |
| On-chip processing shown | FFT, sweep, LoRa scan, down-conversion | a counter program in the AGC MCU |
| Transmit | bursts of custom I/Q | not tried |

Measured with the same HackRF CW tone at 904.330 MHz for the SX1302 rows.
