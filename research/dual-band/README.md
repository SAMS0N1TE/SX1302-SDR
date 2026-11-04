# Dual-band bench data

Run from this directory with Python 3.10 or newer, NumPy and Matplotlib. The offline checks do not open a serial port or require an SDR.

```sh
python verify.py
python figures.py
```

The four-tone check returns `[[4, 0], [0, 4]]`. Rows are receive lanes, columns are transmitted payload families. The paging check returns exact-word counts of `15, 16, 15, 16, 16` across the five recognized batches.

| File | What it contains |
| --- | --- |
| `data/split-band-bins.npz` | The entire 48 s experiment reduced to four complex bins per lane. Signed 16-bit I/Q sums over 128 consecutive device samples, 976.5625 sums/s. Array axes are time, lane, tone, I/Q. |
| `data/trigger-903-915.npz` | The entire triggered 2,048-pair capture at 125 kS/s. Signed int8 columns IA, QA, IB, QB, chronological from the frozen ring. Includes RF centers and the P4 observation index. |
| `data/paging-156250.cs8` | Signed, interleaved int8 I/Q recorded from a synthetic 512-baud POCSAG waveform at 125 kS/s. RF center 156.230 MHz, signal 156.250 MHz. The sidecars identify discontinuities and likely stale samples in device time. |
| `data/433-spectra.npz` | Spectrum bins around the expected +20 kHz IF at a 433.900 MHz receiver center. Rows are earlier mute/on and 433 MHz antenna mute/on. Each row is relative to its local FFT median. |
| `data/antenna-433.csv` | Four matched before/after antenna comparisons with both RX centers. |
| `data/frequency-sweep.csv` | Results by lane and tone. A lane passes only if both tone shifts pass. Each peak must land within 250 Hz, exceed the local median by 15 dB and exceed both control windows by 8 dB. |

`reduce_split.py` regenerates the complex bins from a full paired capture and its segment map. `reduce_spectra.py` takes the earlier and later capture directories and regenerates the plotted spectral subset. The repository includes the derived files and the full trigger and paging captures. Only controlled laboratory signals are included.

For the split-band verification, the receiver searches symbol phase and carrier offset, checks the sync, verifies each CRC and compares all payload bytes with the test sequence. For the paging verification, missing transport samples and reported erasures are zero-filled. The code selects timing by BCH correctability and correction count before comparing with the transmitted codewords. [Results and waveform figures](../../docs/dual-band-bench.md)
