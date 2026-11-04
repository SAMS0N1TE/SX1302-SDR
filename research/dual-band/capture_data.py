"""Read signed I/Q using the device sample clock across UART discontinuities."""

from pathlib import Path
import numpy as np

DATA = Path(__file__).resolve().parent / "data"


def device_iq(path, width):
    raw = np.memmap(path, mode="r", dtype="i1").reshape(-1, width)
    markers = np.loadtxt(str(path) + ".segments", dtype=int, ndmin=2)
    timeline = np.zeros((markers[-1, 1] + len(raw) - markers[-1, 0], width), dtype="i1")
    for (offset, index), end in zip(markers, np.r_[markers[1:, 0], len(raw)]):
        timeline[index : index + end - offset] = raw[offset:end]
    return timeline
