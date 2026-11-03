"""Record continuous I/Q from the SX1302-SDR firmware over its USB UART.

usage: sx1302_stream.py PORT SRC SECONDS [--baud 3000000] [--out FILE] [--png FILE]

Sends 'pcstream SRC MS BAUD', switches the port to BAUD, checks every frame
(CRC, sequence, sample index) and writes interleaved I/Q: .cs8 for the 8-bit
channel sources, .cs16 for the 16-bit ones. --png draws a waterfall.
Needs pyserial, plus numpy and matplotlib for --png."""
import argparse, struct, sys, time, zlib
import serial

ap = argparse.ArgumentParser()
ap.add_argument("port")
ap.add_argument("src", type=int)
ap.add_argument("seconds", type=float)
ap.add_argument("--baud", type=int, default=3000000)
ap.add_argument("--out")
ap.add_argument("--png")
a = ap.parse_args()

ser = serial.Serial()
ser.port = a.port; ser.baudrate = 115200; ser.timeout = 0.05
ser.dtr = False; ser.rts = False
ser.open()
ser.write(b"\r\n"); time.sleep(0.3); ser.read(65536)
ms = int(a.seconds * 1000)
ser.write(f"pcstream {a.src} {ms} {a.baud}\r\n".encode())

line = b""
end = time.time() + 5
while b"PCSTREAM" not in line and time.time() < end:
    line += ser.read(256)
if b"PCSTREAM" not in line:
    sys.exit("no PCSTREAM reply: " + line.decode("utf-8", "replace"))
hdr = line.split(b"PCSTREAM", 1)[1].split(b"\n", 1)[0].split()
fs, fmt = int(hdr[1]), hdr[3].decode()
time.sleep(0.05)
ser.baudrate = a.baud
ser.reset_input_buffer()

out = a.out or f"sx1302_src{a.src}.{'cs8' if fmt == 'iq8' else 'cs16'}"
f = open(out, "wb")
buf = bytearray()
frames = bad_crc = seq_err = idx_err = gaps = lost = 0
samples = 0
next_seq = None
next_idx = 0
endrec = None
t0 = time.time()
deadline = t0 + a.seconds + 10
while time.time() < deadline and endrec is None:
    buf += ser.read(65536)
    while True:
        k = buf.find(b"SX\x01")
        if k < 0:
            del buf[:-2]
            break
        if k:
            del buf[:k]
        if len(buf) < 12:
            break
        typ = buf[3]
        seq, ln, idx = struct.unpack_from("<HHI", buf, 4)
        if ln > 4096:
            del buf[:1]
            continue
        if len(buf) < 16 + ln:
            break
        crc = struct.unpack_from("<I", buf, 12 + ln)[0]
        if zlib.crc32(bytes(buf[2:12 + ln])) != crc:
            bad_crc += 1
            del buf[:1]
            continue
        pl = bytes(buf[12:12 + ln])
        del buf[:16 + ln]
        frames += 1
        if next_seq is not None and seq != next_seq:
            seq_err += 1
        next_seq = (seq + 1) & 0xFFFF
        if typ in (0x10, 0x11):
            n = ln // (2 if typ == 0x10 else 4)
            if idx != next_idx:
                idx_err += 1
            f.write(pl)
            samples += n
            next_idx = (idx + n) & 0xFFFFFFFF
        elif typ == 0x12:
            gaps += 1
            g = struct.unpack("<I", pl)[0]
            lost += g
            next_idx = (idx + g) & 0xFFFFFFFF
        elif typ == 0x1F:
            endrec = struct.unpack("<QIIII", pl)
f.close()
dt = time.time() - t0
ser.baudrate = 115200
time.sleep(0.5)
tail = ser.read(65536).decode("utf-8", "replace")
ser.close()

print(f"file {out}: {samples} samples, {samples / fs:.3f} s at {fs} S/s")
print(f"frames {frames}, crc errors {bad_crc}, seq errors {seq_err}, index errors {idx_err}, gaps {gaps} ({lost} samples lost)")
if endrec:
    words, laps, bogus, dms, efs = endrec
    print(f"device: {words} samples in {dms} ms, laps {laps}, pointer glitches {bogus}; host got {100.0 * samples / max(words, 1):.3f}%")
else:
    print("no END frame (stream cut short)")
for l in tail.splitlines():
    if l.startswith(("stream", "phase", "uart")):
        print("device: " + l)

if a.png:
    import numpy as np
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    raw = np.fromfile(out, dtype=np.int8 if fmt == "iq8" else np.int16).astype(np.float32)
    x = raw[0::2] + 1j * raw[1::2]
    nfft = 256 if fs <= 250000 else 1024
    rows = len(x) // nfft
    x = x[:rows * nfft].reshape(rows, nfft) * np.hanning(nfft)
    w = 10 * np.log10(np.abs(np.fft.fftshift(np.fft.fft(x, axis=1), axes=1)) ** 2 + 1e-6)
    fig, ax = plt.subplots(figsize=(8, 9))
    ext = [-fs / 2e3, fs / 2e3, rows * nfft / fs, 0]
    lo, hi = np.percentile(w, 5), np.percentile(w, 99.9)
    ax.imshow(w, aspect="auto", extent=ext, cmap="viridis", vmin=lo, vmax=hi, interpolation="nearest")
    ax.set_xlabel("kHz offset"); ax.set_ylabel("s")
    ax.set_title(f"SX1302 source {a.src}, {fs / 1e3:.0f} kS/s, {samples / fs:.1f} s continuous")
    fig.tight_layout(); fig.savefig(a.png, dpi=110)
    print("waterfall " + a.png)
