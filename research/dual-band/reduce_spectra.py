"""Extract the spectrum around the predicted +20 kHz tone from a 433.900 MHz recording."""

import argparse
from pathlib import Path
import numpy as np
from capture_data import DATA


def spectrum(path):
    iq = np.memmap(path, mode="r", dtype="i1").reshape(-1, 2)
    offsets = np.loadtxt(str(path) + ".segments", dtype=int, ndmin=2)[:, 0]
    n = 131072
    window = np.hanning(n)
    blocks = []
    for start, end in zip(offsets, np.r_[offsets[1:], len(iq)]):
        for k in range(start, end - n + 1, n):
            part = iq[k : k + n]
            x = part[:, 0].astype(float) + 1j * part[:, 1]
            blocks.append(abs(np.fft.fft(window * x)) ** 2)
    power = np.mean(blocks, axis=0)
    f = np.fft.fftfreq(n, 1 / 125000) - 20000
    use = abs(f) <= 150
    floor = np.median(power[(abs(f) > 130) & (abs(f) < 2500)])
    return f[use], 10 * np.log10(power[use] / floor)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("previous", type=Path)
    ap.add_argument("whips", type=Path)
    a = ap.parse_args()
    traces = []
    for folder in (a.previous, a.whips):
        for state in (0, 1):
            f, y = spectrum(folder / f"433900000-{state}.cs8")
            traces.append(y)
    np.savez_compressed(DATA / "433-spectra.npz", offset_hz=f, power_db=traces)
