"""Two-source capture (2k x 64 capture RAM) from the SX1302-SDR firmware.

usage: sx1302_cap2.py PORT SRC_A SRC_B [--out FILE.npz]

Runs 'cap2 A B b64', splits each 64-bit word into its two 32-bit halves and
prints, for each half, the strongest tone and its level. Needs numpy and
pyserial."""
import argparse, base64, sys, time
import numpy as np
import serial

ap = argparse.ArgumentParser()
ap.add_argument("port")
ap.add_argument("a", type=int)
ap.add_argument("b", type=int)
ap.add_argument("--out")
args = ap.parse_args()

FS = {**{s: 4e6 for s in range(7)}, 9: 1e6, **{s: 125e3 for s in range(10, 18)}}

ser = serial.Serial(); ser.port = args.port; ser.baudrate = 115200; ser.timeout = 0.05
ser.dtr = False; ser.rts = False
ser.open(); ser.write(b"\r\n"); time.sleep(0.3); ser.read(65536)
ser.write(f"cap2 {args.a} {args.b} b64\r\n".encode())
buf = b""
end = time.time() + 15
while time.time() < end and b"B64END" not in buf:
    buf += ser.read(65536)
ser.close()
txt = buf.decode("utf-8", "replace")
for l in txt.splitlines():
    if l.startswith("cap2"):
        print(l)
if "B64END" not in txt:
    sys.exit("no dump")
body = txt.split("B64BEGIN", 1)[1].split("\n", 1)[1].split("B64END")[0]
raw = np.frombuffer(base64.b64decode("".join(l.strip() for l in body.splitlines())), dtype=np.uint8)
w = raw.reshape(-1, 8)


def iq(half, src):
    b = half
    if 10 <= src <= 17:
        return b[:, 3].astype(np.int8).astype(np.float32) + 1j * b[:, 1].astype(np.int8).astype(np.float32)
    i = (b[:, 2].astype(np.uint16) | (b[:, 3].astype(np.uint16) << 8)).astype(np.int16).astype(np.float32)
    q = (b[:, 0].astype(np.uint16) | (b[:, 1].astype(np.uint16) << 8)).astype(np.int16).astype(np.float32)
    return i + 1j * q


res = {}
for name, half in (("low", w[:, 0:4]), ("high", w[:, 4:8])):
    for src in (args.a, args.b):
        x = iq(half, src)
        fs = FS.get(src, 125e3)
        n = len(x)
        p = np.abs(np.fft.fftshift(np.fft.fft((x - x.mean()) * np.hanning(n)))) ** 2
        f = np.fft.fftshift(np.fft.fftfreq(n, 1 / fs))
        k = int(np.argmax(p))
        span = 10 * np.log10(p[k] / np.median(p) + 1e-12)
        print(f"{name} half read as src {src} format: rms {np.sqrt(np.mean(np.abs(x) ** 2)):8.1f}, peak {f[k] / 1e3:+8.1f} kHz, {span:5.1f} dB above median")
        res[f"{name}_as_{src}"] = x
eq = np.mean(np.all(w[:, 0:4] == w[:, 4:8], axis=1))
print(f"halves identical in {100 * eq:.1f}% of words")
if args.out:
    np.savez(args.out, **res)
