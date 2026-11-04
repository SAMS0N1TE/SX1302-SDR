"""Recalculate QPSK error, relative phase and chirp ridge measurements."""

from pathlib import Path
import numpy as np
from recovery import recover

DATA = Path(__file__).resolve().parent / "data"


def relative_phase(raw):
    x = raw.astype(float)
    a = x[:, 0] + 1j * x[:, 1]
    b = x[:, 2] + 1j * x[:, 3]
    c = np.vdot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))
    return np.angle(c, deg=True), abs(c)


def chirp_ridge(raw, fs):
    z = raw[:, 0].astype(float) + 1j * raw[:, 1]
    win = np.lib.stride_tricks.sliding_window_view(z, 96)[::8] * np.hanning(96)
    ps = abs(np.fft.fft(win, 512)) ** 2
    f = np.fft.fftfreq(512, 1 / fs)
    use = np.flatnonzero(abs(f) < 680000)
    peaks = f[use[ps[:, use].argmax(1)]]
    us = (np.arange(len(peaks)) * 8 + 48) * 1e6 / fs
    best = None
    for start in range(256):
        u = (us - start) % 256
        inside = (u > 22) & (u < 170)
        err = np.median(abs(peaks[inside] - (-600000 + 6250 * u[inside])))
        if best is None or err < best[0]:
            best = (err, u, inside)
    err, u, inside = best
    slope = np.polyfit(u[inside], peaks[inside], 1)[0]
    return slope / 1000, err / 1000


if __name__ == "__main__":
    for name in ["qpsk", "qpsk-muted"]:
        x = np.load(DATA / (name + ".npz"))["iq"]
        fit = [recover(x[:, i : i + 2]) for i in (0, 2)]
        print(
            name,
            [(r["errors"], round(100 * r["evm"], 2), r["cfo"]) for r in fit],
            "(errors / 96, EVM %, CFO Hz)",
        )
        if name == "qpsk" and any(r["errors"] for r in fit):
            raise SystemExit("QPSK held-out decisions changed")
    for path in sorted(DATA.glob("phase-*.npz")):
        phase, rho = relative_phase(np.load(path)["iq"])
        print(
            path.stem,
            round(phase, 2),
            round(rho, 4),
            "(B relative to A in degrees, normalized correlation magnitude)",
        )
    for name in ["chirp", "chirp-muted"]:
        d = np.load(DATA / (name + ".npz"))
        print(
            name,
            chirp_ridge(d["iq"], int(d["rate"])),
            "(kHz/us, median ridge error kHz)",
        )
