"""Periodic baseband test signals and the reference symbols used for verification."""

import numpy as np

DAC_RATE = 8_000_000
IF_RATE = 125_000
RADIO_RATE = 4_000_000
SYMBOL_RATE = 7812.5
CARRIER = 15625


def symbols():
    rng = np.random.default_rng(13029)
    return np.exp(1j * (np.pi / 4 + np.pi / 2 * rng.integers(0, 4, 128)))


def qpsk():
    # Frequency-domain root raised cosine pulse shape on the periodic symbol block.
    count = round(DAC_RATE / SYMBOL_RATE)
    up = np.zeros(128 * count, complex)
    up[::count] = symbols()
    f = np.abs(np.fft.fftfreq(len(up), 1 / DAC_RATE))
    roll = 0.35
    lo = (1 - roll) * SYMBOL_RATE / 2
    hi = (1 + roll) * SYMBOL_RATE / 2
    rc = np.clip((f - lo) / (hi - lo), 0, 1)
    z = np.fft.ifft(np.fft.fft(up) * np.cos(np.pi * rc / 2))
    t = np.arange(len(up)) / DAC_RATE
    return z / max(abs(z)) * np.exp(2j * np.pi * CARRIER * t)


def chirp():
    # Repeats every 256 us, including a quiet interval. 192 us linear sweep.
    t = np.arange(2048) / DAC_RATE
    u = t - 32e-6
    duration = 192e-6
    bw = 1_200_000
    phase = 2 * np.pi * (-bw / 2 * u + bw / (2 * duration) * u * u)
    ramp = np.clip(np.minimum(u, duration - u) / 4e-6, 0, 1)
    return np.sin(ramp * np.pi / 2) ** 2 * np.exp(1j * phase)
