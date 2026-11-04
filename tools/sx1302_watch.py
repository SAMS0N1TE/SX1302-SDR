"""Arm the WM1302 locally and save a chronological 2048-pair triggered I/Q snapshot."""

import argparse, base64, re, time
import struct, serial
import numpy as np


def encode(op):
    assert 0 <= op < 0x4000
    return op | (op.bit_count() % 4) << 14


class Bench:
    def __init__(self, port):
        self.s = serial.Serial()
        self.s.port = port
        self.s.baudrate = 115200
        self.s.timeout = 0.025
        self.s.rts = False
        self.s.dtr = False
        self.s.open()
        self.s.write(b"\r\n")
        time.sleep(0.1)
        self.s.reset_input_buffer()
        self.cmd([])

    def cmd(self, lines, timeout=10):
        self.s.write(("\r\n".join([*lines, "ver"]) + "\r\n").encode())
        end = time.monotonic() + timeout
        data = b""
        while b"SX1302 version 0x10 (v1.0)" not in data and time.monotonic() < end:
            data += self.s.read(4096)
        if b"SX1302 version 0x10 (v1.0)" not in data:
            raise RuntimeError(f"Unexpected console reply: {data[-300:]!r}")
        if data.count(b"wr -> 0") != sum(x.startswith("wr ") for x in lines):
            raise RuntimeError("Register write failed")
        return data.decode(errors="replace")

    def regs(self, cmds):
        return [
            int(x, 16) for x in re.findall(r"rd 0x\w+ = 0x(\w+) \(0\)", self.cmd(cmds))
        ]

    def core(self, ctrl, program, flip=0):
        addr = 0 if ctrl == 0x5780 else 0x2000
        normal = self.regs([f"rd {ctrl}"])[0] & ~7
        raw = b"".join(
            struct.pack("<H", encode(op) ^ (flip if i == 0 else 0))
            for i, op in enumerate(program)
        )
        self.cmd([f"wr {ctrl} {normal | 4}", f"wr {ctrl} {normal | 6}", "wr 0x5600 0"])
        for i in range(0, len(raw), 32):
            block = raw[i : i + 32]
            out = self.cmd(
                [
                    *(f"wr {addr + i + k} {v}" for k, v in enumerate(block)),
                    f"rdb {addr + i} {len(block)}",
                ]
            )
            actual = bytes.fromhex(
                " ".join(re.findall(r"(?m)^  ([0-9A-F ]+)\r*$", out))
            )
            if actual != block:
                raise RuntimeError("MCU instruction readback mismatch")
        self.cmd([f"wr {ctrl} {normal | 4}", f"wr {ctrl} {normal}"])
        return self.regs([f"rd {ctrl}", f"rd {ctrl + 1}"])

    def restore(self):
        text = self.cmd(["tune 904300000 905000000", "cap 12"])
        print("RESTORE", text[-1600:], flush=True)
        if "lgw_start -> 0" not in text or "capture 12 -> 0" not in text:
            raise RuntimeError("Stock MCU restoration failed")


def read_port(addr):
    return [0x3000 | addr, 0x95, 0x1497, 0x1097, 0x080D]


def arm_detector(b, thresholds):
    # 0x40 holds sticky history, 0x41 live flags, 0x42/43 dwell counters.
    code = [0x01C0, 0x01C2, 0x01C3]
    loop = len(code)
    code.append(0x01C1)
    for i, threshold in enumerate(thresholds):
        if not 1 <= threshold <= 255:
            raise ValueError("AGC threshold must be 1..255")
        counter = 0x42 + i
        code += read_port(0x21 + 2 * i) + [0x3C00 | (threshold - 1), 0x1C03]
        hi = len(code) + 3
        code += [0x2800 | hi, 0x0180 | counter, 0]
        # Require eight consecutive high observations before reporting RF.
        code += [
            0x0A80 | counter,
            0x1C00 | (3 << 7) | counter,
            0,
            0x0380 | counter,
            0x1400 | (i << 7) | 0x41,
        ]
        end = len(code)
        code[hi - 1] = 0x2800 | end
        code[hi + 2] = 0x2800 | end
    code += [0x0841, 0x04C0, 0x0E40, 0x0441, 0x009B, 0x2800 | loop]
    state = b.core(0x5780, code)
    if state[0] & 1:
        raise RuntimeError("AGC program check failed")


def quiet_thresholds(b, margin=14):
    thresholds = []
    for ch in range(2):
        b.core(0x5780, read_port(0x21 + 2 * ch) + [0x9B, 0x2800])
        values = b.regs(["rd 0x5781"] * 24)
        thresholds.append(min(255, max(values) + margin))
    return thresholds


def until(b, marker, timeout):
    end = time.monotonic() + timeout
    buf = b""
    while marker not in buf and time.monotonic() < end:
        buf += b.s.read(256)
        if marker == b"WATCH ARMED" and b"WATCH end" in buf:
            break
    if marker not in buf:
        raise RuntimeError(buf.decode(errors="replace"))
    return buf


def buffer(b):
    reply = b.cmd(["event"])
    if "B64BEGIN" not in reply:
        raise RuntimeError("No frozen event on device")
    raw = base64.b64decode(
        "".join(
            reply.split("B64BEGIN")[1].split("\n", 1)[1].split("B64END")[0].split()
        ),
        validate=True,
    )
    if len(raw) != 16384:
        raise ValueError("Incomplete capture")
    x = np.frombuffer(raw, "i1").reshape(-1, 8)
    return np.column_stack([x[:, 3], x[:, 1], x[:, 7], x[:, 5]])


def watch(b, centers, thresholds, mask, post_us, timeout_ms, out, on_arm=None):
    arm_detector(b, thresholds)
    b.s.write(f"watch {mask} {post_us} {timeout_ms}\r\n".encode())
    early = until(b, b"WATCH ARMED", 2)
    print("ARMED", flush=True)
    if on_arm:
        on_arm()
    # ver is queued behind the autonomous P4 command and marks the end of its reply.
    b.s.write(b"ver\r\n")
    result = (early + until(b, b"(v1.0)", timeout_ms / 1000 + 3)).decode(
        errors="replace"
    )
    m = re.search(r"frozen=1 mask=(\d+) trigger=(\d+) stop=(\d+)", result)
    if not m:
        if "error=0 stale=0 matched=0 trigger=-1" in result:
            return None
        raise RuntimeError(result)
    hit, trig, stop = map(int, m.groups())
    physical = buffer(b)
    if not np.array_equal(physical, buffer(b)):
        raise RuntimeError("Frozen readback mismatch")
    iq = np.roll(physical, -stop, axis=0)
    observed = (trig - stop) % 2048
    np.savez_compressed(
        out,
        iq=iq,
        centers_hz=centers,
        rate=125000,
        mask=hit,
        observation_index=observed,
        post_us=post_us,
        thresholds=thresholds,
    )
    return hit, observed, iq


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("port", help="Probe USB UART")
    ap.add_argument("--a", type=int, default=904300000)
    ap.add_argument("--b", type=int, default=915000000)
    ap.add_argument(
        "--thresholds",
        nargs=2,
        type=int,
        help="Raw AGC thresholds for chains A/B. Omit to sample the quiet channel plus 14 counts.",
    )
    ap.add_argument("--mask", type=int, choices=(1, 2, 3), default=3)
    ap.add_argument("--post-us", type=int, default=7000)
    ap.add_argument("--timeout-ms", type=int, default=30000)
    ap.add_argument("--out", default="burst.npz")
    ap.add_argument(
        "--cal-hz",
        type=int,
        help="Optional image-calibration table frequency for experimental tuning",
    )
    a = ap.parse_args()
    if not (0 <= a.post_us <= 14000 and 1 <= a.timeout_ms <= 60000):
        ap.error("post-us 0..14000, timeout-ms 1..60000")
    b = Bench(a.port)
    try:
        tune = f"probetune {a.a} {a.b} {a.cal_hz}" if a.cal_hz else f"tune {a.a} {a.b}"
        if "lgw_start -> 0" not in b.cmd([tune]):
            raise RuntimeError("Radio startup failed")
        thresholds = a.thresholds or quiet_thresholds(b)
        print("AGC thresholds", thresholds, flush=True)
        r = watch(b, [a.a, a.b], thresholds, a.mask, a.post_us, a.timeout_ms, a.out)
        print(
            "Timeout"
            if r is None
            else f"Saved {a.out}, mask={r[0]}, observation index={r[1]}"
        )
    finally:
        try:
            b.restore()
        finally:
            b.s.close()
