"""Data-aided QPSK timing/carrier recovery. The last 96 symbols are held out."""

import numpy as np
from signals import symbols, IF_RATE, CARRIER, SYMBOL_RATE


def recover(iq):
    fs = IF_RATE
    ref = symbols()
    pilot = ref[:32]
    ns = 16
    x = iq[:, 0].astype(float) + 1j * iq[:, 1]
    t = np.arange(len(x)) / fs
    f = abs(np.fft.fftfreq(len(x), 1 / fs))
    rrc = np.cos(
        np.pi / 2 * np.clip((f - 0.325 * SYMBOL_RATE) / (0.35 * SYMBOL_RATE), 0, 1)
    )

    def fit(cfo):
        y = np.fft.ifft(np.fft.fft(x * np.exp(-2j * np.pi * (CARRIER + cfo) * t)) * rrc)
        best = (-1, None)
        for phase in range(ns):
            v = y[phase::ns]
            windows = np.lib.stride_tricks.sliding_window_view(np.r_[v, v[:31]], 32)
            gains = (windows @ pilot.conj()) / len(pilot)
            score = abs(gains) ** 2 / (np.mean(abs(windows) ** 2, axis=1) + 1e-20)
            k = np.argmax(score)
            if score[k] > best[0]:
                best = (score[k], (np.roll(v, -k) / gains[k], phase + ns * k, gains[k]))
        return best

    freqs = np.arange(-200, 201, 10)
    coarse = freqs[np.argmax([fit(hz)[0] for hz in freqs])]
    freqs = np.arange(coarse - 10, coarse + 11, 1)
    fits = [fit(hz) for hz in freqs]
    j = np.argmax([v[0] for v in fits])
    score, (v, start, gain) = fits[j]
    held = v[32:]
    truth = ref[32:]
    wrong = np.count_nonzero(
        (np.sign(held.real) != np.sign(truth.real))
        | (np.sign(held.imag) != np.sign(truth.imag))
    )
    return dict(
        cfo=float(freqs[j]),
        start=int(start),
        gain=gain,
        score=float(score),
        points=v,
        errors=int(wrong),
        evm=float(np.sqrt(np.mean(abs(held - truth) ** 2))),
    )
