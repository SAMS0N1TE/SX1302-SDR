# Waveform captures and offline analysis

The samples here are controlled bench recordings. Both receivers were tuned to 915.000 MHz. A HackRF supplied the test signals through antennas in a shielded cage. The gallery and the audio use the synthetic signals described below.

```sh
python -m pip install numpy scipy matplotlib
python measure.py
python gallery.py
```

Run these commands from this directory. The analysis uses Python 3.10 or later. `measure.py` reports the chirp ridge fit, QPSK held-out symbol errors, EVM and inter-radio phase from the stored recordings. `gallery.py` renders three PNGs under `docs/images`.

| Data | Format and provenance |
| --- | --- |
| `chirp.npz`, `chirp-muted.npz` | 2,048 simultaneous instants at 4 MS/s. Signed 16-bit IA, QA, IB, QB with 12 bits left-justified. Sources 2 and 3. Both taken with the TX oscillator running, amp off, VGA setting 22 dB. Signal waveform scaled to 96 DAC counts. |
| `qpsk.npz`, `qpsk-muted.npz` | 2,048 simultaneous instants at 125 kS/s. Signed 8-bit IA, QA, IB, QB. Sources 12 and 15. TX VGA setting 22 dB; signal scaled to 40 DAC counts. |
| `phase-hold-*.npz`, `phase-boot-*.npz` | Same QPSK sequence at TX VGA setting 10 dB and amplitude 48. Four snapshots without a retune and four after fresh radio initializations. |
| `phase-digital.npz` | Same-source control, source 12 connected to both capture inputs. |
| `p25.pair8` | Both IF channels from a 3.2 s run, 125 kS/s per lane. Signed bytes IA, QA, IB, QB. The host received 397,526 of 399,574 device pairs. TX VGA 10 dB, RF amp off. |
| `p25.pair8.segments`, `p25.pair8.erasures` | File-to-device index map and previous-lap equality flags. Raw-file offsets close up at a missing transport frame. |
| `p25-verification.json`, `recovered-test-tone.wav` | DSD-neo summaries for each lane and processing mode; 8 kHz vocoder output from the combined lane-A data. |

### P25 verification

```sh
python p25_audio.py discriminator.wav --lane 0
python p25_audio.py folded.wav --lane 0 --fold
python check_p25.py /path/to/dsd-neo
```

Tested with DSD-neo v2.10.0 and MBElib-neo 2.1.0, decoder executable SHA-256 `f3217e79a8a403f303e2330e8c7f737e1f24b779b38e7aff808de7622ac64428`. The frontend mixes by −15.625 kHz, applies a 7 kHz FIR and FM-discriminates to 48 kHz PCM. Combined mode folds five 75,000-sample periods after mapping transport gaps back to device time. It expands erasure masks through the FIR and uses samples whose filtered amplitude exceeds 45 counts. The ordered SHA-256 in the verifier covers the 18 concatenated 11-byte IMBE words from one reference fixture repetition. Each lane independently reproduced this digest. [Upstream reference words](https://github.com/SAMS0N1TE/lr2021-sdr/blob/df251bf/research/tx-p25/reference/expected-imbe.json) · [Decoder](https://github.com/arancormonk/dsd-neo)

The transmitter used the sibling project's `voice-tone.p25` and `lr2021_make_p25.py` at commit `df251bf`. Its packed input SHA-256 is `d1fe7d57cc094c316a95fd83a0b6b1c3ef56834b2346a85feb4ffc0b0f7b3e8f`. The 19,200-sample/s modulated fixture was resampled to 8 MS/s and translated in complex baseband. HackRF LO was 913 MHz. No live radio-service traffic is included. [Fixture source](https://github.com/SAMS0N1TE/lr2021-sdr/tree/df251bf/research/tx-p25)

### Repeating the chirp and QPSK experiment

`signals.py` defines the complex baseband stimuli at 8 MS/s. Translate either one up by 2 MHz for the 913 MHz HackRF LO. Scale to the indicated signed DAC amplitude, interleave I/Q and repeat the block. For QPSK the helper already includes its 15.625 kHz IF offset. Allow the generator to settle before a snapshot. Run `tune 915000000 915000000` followed by `cap2 2 3 b64` for the chirp or `cap2 12 15 b64` for QPSK. A same-source control uses `cap2 12 12 b64`. The mute controls keep the oscillator running and send zero baseband. [Annotated figures and interpretation](../../docs/waveform-gallery.md)
