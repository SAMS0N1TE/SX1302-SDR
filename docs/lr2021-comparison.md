# SX1302 and LR2021

How the SX1302 on a WM1302 module compares with the LR2021 in [LR2021-SDR](https://github.com/SAMS0N1TE/lr2021-sdr), both on an ESP32-P4 over SPI.

| | LR2021 | SX1302 (WM1302 US915) |
| --- | --- | --- |
| Receive range | 100 MHz to 2.74 GHz | US915 module rated 902–928 MHz. Caged data reception verified at discrete frequencies including 156.250 and 433.920 MHz |
| I/Q source | capture bank, one stream | capture RAM, 32 sources: 2 radios, 8 channels, more |
| Continuous I/Q over SPI | Project reports up to 500 kS/s 16-bit and 800 kS/s 8-bit | Two simultaneous 125 kS/s IF channels or one subsampled 250 kS/s radio-A stream |
| Wide snapshots | | 4 MS/s 16-bit, 4096 samples, both radios at once |
| On-chip buffer | 4 KB | 16 KB |
| Clean SPI clock | 16 MHz | 20 MHz on jumper wires |
| Image rejection | about 41 dB | 38 to 40 dB |
| Programmable core | ARCv2, 4 KB patch RAM, programs and toolchain from Alex Beal's lr2021-re | two PIC16-type MCUs, 4096 words each, 16 M instruction cycles/s |
| On-chip processing shown | FFT, sweep, LoRa scan, down-conversion | two-chain RF detector, mailbox arithmetic, stock ARB boot hook |
| Transmit | bursts of custom I/Q | not tried |

The LR2021 remains the faster demonstrated single-stream receiver. The SX1302 captured overlapping signals 12 MHz apart and monitored two fixed bands 277.67 MHz apart in a single continuous recording. The latter used successive transmissions from one HackRF. See the [waveforms and packet checks](dual-band-bench.md) and the [LR2021 host measurements](https://github.com/SAMS0N1TE/lr2021-sdr/blob/df251bf/docs/host-sdr.md).
