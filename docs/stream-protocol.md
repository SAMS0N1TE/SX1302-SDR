# Stream protocol

`pcstream <src> [ms] [baud]` streams the capture ring to the host on UART0. The firmware prints one text line at 115200, switches the UART to `baud` (default 3,000,000), sends binary frames, then switches back to 115200 and prints its statistics.

```
PCSTREAM <src> <sample rate> <baud> <iq8|iq16>
```

The host should switch its port to `baud` straight after reading that line. `tools/sx1302_stream.py` does this.

## Frames

All integers are little endian.

| Offset | Size | Field |
| ---: | ---: | --- |
| 0 | 2 | sync `53 58` ("SX") |
| 2 | 1 | version, 1 |
| 3 | 1 | type |
| 4 | 2 | sequence, counts every frame |
| 6 | 2 | payload length, 0 to 4096 |
| 8 | 4 | index of the first sample in the frame |
| 12 | length | payload |
| 12 + length | 4 | CRC-32 (IEEE, as zlib) over bytes 2 to 11 + length |

| Type | Payload |
| ---: | --- |
| 0x10 | I/Q, signed 8-bit pairs (channel sources 10 to 17) |
| 0x11 | I/Q, signed 16-bit pairs |
| 0x12 | u32 samples lost in a ring overrun; the next frame's index skips them |
| 0x13 | erasure: u32 first sample, u16 count; those samples repeat the previous ring lap |
| 0x1F | end: u64 samples, u32 overruns, u32 pointer glitches, u32 ms, u32 sample rate |

A gap shows as a 0x12 frame or as an index that does not follow on from the previous frame. Erasure frames arrive before the data frame that holds those samples. `sx1302_stream.py` writes them to `FILE.erasures`, one `first_sample count` per line. About 3% of samples are erased, see [capture-ram.md](capture-ram.md#missed-writes-while-streaming).

## Rates

| Source | Format | Payload | At 3 Mbaud |
| --- | --- | ---: | ---: |
| channel, 125 kS/s | iq8 | 250 KB/s | 83% of the line |
| 16-bit, 125 kS/s | iq16 | 500 KB/s | needs about 5 Mbaud |

Measured: 1,249,918 samples from source 12 in 10 s, 0 CRC errors, 0 index errors, 0 gaps.
