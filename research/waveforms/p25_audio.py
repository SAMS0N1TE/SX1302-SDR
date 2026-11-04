"""Offline P25 capture frontend. Write discriminator audio for an external decoder."""

import argparse
from pathlib import Path
import wave
import numpy as np
from scipy import signal

DATA = Path(__file__).resolve().parent / "data"


def paired(path):
    raw = np.fromfile(path, "i1").reshape(-1, 4)
    markers = np.loadtxt(str(path) + ".segments", dtype=int, ndmin=2)
    x = np.zeros((markers[-1, 1] + len(raw) - markers[-1, 0], 4), dtype="i1")
    for (pos, idx), end in zip(markers, np.r_[markers[1:, 0], len(raw)]):
        x[idx : idx + end - pos] = raw[pos:end]
    return x


def channel(x, lane):
    z = x[:, 2 * lane].astype(float) + 1j * x[:, 2 * lane + 1]
    t = np.arange(len(z)) / 125000
    return signal.fftconvolve(
        z * np.exp(-2j * np.pi * 15625 * t),
        signal.firwin(129, 7000, fs=125000),
        mode="same",
    )


def discriminator(path, lane):
    z = channel(paired(path), lane)
    hz = np.angle(z[1:] * z[:-1].conj()) * 125000 / (2 * np.pi)
    pcm = signal.resample_poly(hz, 48, 125)
    return np.clip(pcm * 5, -32767, 32767).astype("<i2")


def fold_repetitions(path, lane):
    """Combine five transmissions of the same fixture using the device clock."""
    raw = paired(path)
    z = channel(raw, lane)
    freq = np.angle(z[1:] * z[:-1].conj()) * 125000 / (2 * np.pi)
    # Zero weight for missing data and expand the invalid runs through the
    # 129-tap receive filter, whose group delay is 64 samples on each side.
    valid = np.ones(len(z), dtype=bool)
    markers = np.loadtxt(str(path) + ".segments", dtype=int, ndmin=2)
    for (file0, idx0), (file1, idx1) in zip(markers, markers[1:]):
        valid[idx0 + file1 - file0 : idx1] = False
    for start, n in np.loadtxt(str(path) + ".erasures", dtype=int, ndmin=2):
        valid[start : start + n] = False
    invalid = (
        signal.convolve(
            (~valid).astype(int), np.ones(131, dtype=int), mode="same", method="direct"
        )
        > 0
    )
    size = 75000  # 405 ms waveform plus 195 ms quiet time at 125 kS/s
    count = len(freq) // size
    freq = freq[: count * size].reshape(count, size)
    weight = ((~invalid[:-1]) & (abs(z[:-1]) > 45))[: count * size].reshape(count, size)
    total = weight.sum(0)
    combined = np.divide(
        (freq * weight).sum(0), total, out=np.zeros(size), where=total > 0
    )
    pcm = signal.resample_poly(combined, 48, 125)
    return np.clip(5 * pcm, -32767, 32767).astype("<i2")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("wav", type=Path)
    ap.add_argument("--lane", type=int, choices=(0, 1), default=0)
    ap.add_argument(
        "--fold",
        action="store_true",
        help="combine complete repetitions of this lab fixture",
    )
    args = ap.parse_args()
    with wave.open(str(args.wav), "wb") as w:
        w.setparams((1, 2, 48000, 0, "NONE", ""))
        w.writeframes(
            (fold_repetitions if args.fold else discriminator)(
                DATA / "p25.pair8", args.lane
            )
        )
