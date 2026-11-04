"""Verify synthetic frame checks against the bench data. Uses no radio hardware."""

import binascii
import itertools
import numpy as np
from capture_data import DATA, device_iq

SYNC = 0x7CD215D8


def encode(data):
    v = data << 10
    r = v
    while r.bit_length() > 10:
        r ^= 0x769 << (r.bit_length() - 11)
    v |= r
    return (v << 1) | (v.bit_count() % 2)


def words():
    rng = np.random.default_rng(15625)
    return [encode(0x12340)] + [
        encode(0x100000 | int(rng.integers(1 << 20))) for _ in range(15)
    ]


def syn(w):
    p = w.bit_count() & 1
    r = w >> 1
    while r.bit_length() > 10:
        r ^= 0x769 << (r.bit_length() - 11)
    return 2 * r + p


correct = {
    syn(w): w
    for w in [0]
    + [1 << i for i in range(32)]
    + [(1 << i) | (1 << j) for i, j in itertools.combinations(range(32), 2)]
}
assert len(correct) == 529


def paging_batches(path):
    raw = device_iq(path, 2)
    y = raw[:, 0].astype(float) + 1j * raw[:, 1]
    for a, n in np.loadtxt(str(path) + ".erasures", dtype=int, ndmin=2):
        y[a : a + n] = 0
    t = np.arange(len(y)) / 125000
    acc = [np.r_[0, np.cumsum(y * np.exp(-2j * np.pi * h * t))] for h in (15517, 24517)]
    best = []
    expected = words()
    for phase in range(32):
        edges = ((phase / 32 + np.arange(len(y) * 512 / 125000)) * 125000 / 512).astype(
            int
        )
        edges = edges[edges < len(y)]
        bits = (abs(np.diff(acc[1][edges])) > abs(np.diff(acc[0][edges]))).astype("u1")
        for q in range(8):
            u = np.packbits(bits[q:])
            v = np.zeros(len(u) - 3, dtype="u4")
            for j in range(4):
                v = (v << 8) | u[j : j + len(v)]
            for k in np.flatnonzero(np.bitwise_count(v ^ SYNC) <= 2):
                ww = list(map(int, v[k + 4 : k + 68 : 4]))
                errs = [correct.get(syn(w)) for w in ww]
                wc = [w ^ e if e is not None else None for w, e in zip(ww, errs)]
                good = sum(e is not None for e in errs)
                flips = sum(e.bit_count() for e in errs if e is not None)
                if good < 5:
                    continue
                pos = edges[q + k * 8] / 125000
                score = (good, -flips, -(int(v[k]) ^ SYNC).bit_count())
                best.append((pos, score, wc))
    groups = []
    for row in sorted(best, key=lambda x: x[0]):
        if not groups or row[0] - groups[-1][0][0] > 0.02:
            groups.append([row])
        else:
            groups[-1].append(row)
    result = []
    for group in groups:
        pos, sc, wc = max(group, key=lambda x: x[1])
        exact_words = sum(a == b for a, b in zip(wc, expected))
        if exact_words >= 3:
            result.append((round(pos, 3), len(wc), exact_words))
    return result


def split_payloads(sums, lane, seed, start, end):
    # The bench frame has a 16-bit sync, four data bytes and a CRC-16.
    rng = np.random.default_rng(seed)
    payloads = set()
    for index in range(4):
        body = bytes([index]) + rng.bytes(3)
        payloads.add(
            bytes.fromhex("d391")
            + body
            + binascii.crc_hqx(body, 65535).to_bytes(2, "big")
        )
    a = sums[start:end, lane]
    z = (a[..., 0].astype(float) + 1j * a[..., 1]).T
    t = np.arange(z.shape[1]) / (125000 / 128)
    sync = np.array([3, 1, 0, 3, 2, 1, 0, 1])  # 0xd391, two bits per symbol
    positions = {}
    for offset in range(-40, 141, 4):
        cs = np.c_[np.zeros(4), np.cumsum(z * np.exp(-2j * np.pi * offset * t), axis=1)]
        for phase in range(0, 128, 4):
            symbols = abs(np.diff(cs[:, phase::128], axis=1)).argmax(axis=0)
            for i in np.flatnonzero(
                np.all(
                    np.lib.stride_tricks.sliding_window_view(symbols, 8) == sync, axis=1
                )
            ):
                v = symbols[i : i + 32]
                if len(v) < 32:
                    continue
                pkt = (
                    ((v[::4] << 6) | (v[1::4] << 4) | (v[2::4] << 2) | v[3::4])
                    .astype("u1")
                    .tobytes()
                )
                if (
                    binascii.crc_hqx(pkt[2:6], 65535) == int.from_bytes(pkt[6:], "big")
                    and pkt in payloads
                ):
                    positions.setdefault(pkt[2], []).append(i * 128 + phase)
    return sum(
        1 + np.count_nonzero(np.diff(np.sort(v)) > 256) for v in positions.values()
    )


if __name__ == "__main__":
    sums = np.load(DATA / "split-band-bins.npz")["sums"]
    cut = round(21 * 125000 / 128)
    counts = [
        [
            split_payloads(sums, lane, 15603, 0, cut),
            split_payloads(sums, lane, 43303, cut, len(sums)),
        ]
        for lane in (0, 1)
    ]
    batches = paging_batches(DATA / "paging-156250.cs8")
    print("Decoded VHF/UHF frames by lane:", counts)
    print("Pager batch start, available words, exact words:", batches)
    if counts != [[4, 0], [0, 4]] or [r[2] for r in batches] != [15, 16, 15, 16, 16]:
        raise SystemExit("Capture verification failed")
