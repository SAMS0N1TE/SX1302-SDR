"""Extract the four test-carrier bins from a paired .pair8 capture and its .segments."""

import argparse
import numpy as np
from capture_data import DATA, device_iq

OFFSETS = np.array([-15625.0, -7812.5, 7812.5, 15625.0])


def reduce_capture(path, out):
    raw = device_iq(path, 4)
    n = len(raw) // 128 * 128
    result = np.empty((n // 128, 2, 4, 2), dtype="int16")
    for lane in (0, 1):
        x = raw[:n, lane * 2].astype("f") + 1j * raw[:n, lane * 2 + 1]
        for j, offset in enumerate(OFFSETS):
            # One complex sum per 128 samples, in the original device timebase.
            hz = 20000 + offset
            osc = np.exp(-2j * np.pi * hz * np.arange(n) / 125000).astype("F")
            baseband = (x * osc).reshape(-1, 128).sum(axis=1)
            result[:, lane, j, 0] = np.rint(baseband.real)
            result[:, lane, j, 1] = np.rint(baseband.imag)
    np.savez_compressed(
        out,
        sums=result,
        sample_rate=125000 / 128,
        tone_offsets_hz=OFFSETS,
        carrier_hz=[156250000, 433920000],
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture")
    parser.add_argument("--out", default=DATA / "split-band-bins.npz")
    args = parser.parse_args()
    reduce_capture(args.capture, args.out)
