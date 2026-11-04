"""Record continuous I/Q from the SX1302-SDR firmware over its USB UART.

usage: sx1302_stream.py PORT SRC SECONDS [--baud BAUD] [--out FILE] [--png FILE]
       sx1302_stream.py PORT 9 SECONDS --wide-rate 250000
       sx1302_stream.py PORT 12 SECONDS --pair 13

Pair records are four signed bytes, IA QA IB QB. Wide and pair streams use
6 Mbaud by default. A .segments sidecar maps file offsets (in sample instants)
to device indices across transport discontinuities. Erasures use device indices.

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
ap.add_argument("--baud", type=int)
ap.add_argument("--wide-rate", type=int, choices=(125000, 200000, 250000), help="sample source 9 at this capture clock, send upper 8 bits of I and Q")
ap.add_argument("--pair", type=int, choices=range(10, 18), help="second IF source, writes IA QA IB QB for each sample instant")
ap.add_argument("--out")
ap.add_argument("--png")
a = ap.parse_args()

if a.baud is None:
    a.baud = 6000000 if a.wide_rate or a.pair else 3000000
if a.wide_rate and a.src != 9:
    ap.error("--wide-rate requires source 9")

if a.pair and (a.wide_rate or a.src not in range(10, 18) or a.png):
    ap.error("--pair requires IF sources 10..17 and raw output")

ser = serial.Serial()
ser.port = a.port; ser.baudrate = 115200; ser.timeout = 0.05
ser.dtr = False; ser.rts = False
ser.open()
if sys.platform == "win32":
    ser.set_buffer_size(rx_size=1024 * 1024)
ser.write(b"\r\n"); time.sleep(0.3); ser.read(65536)
ms = int(a.seconds * 1000)
cmd = f"wide {a.wide_rate}" if a.wide_rate else f"pcstream {a.src}"
if a.pair:
    cmd = f"pcdual {a.src} {a.pair}"
ser.write(f"{cmd} {ms} {a.baud}\r\n".encode())

line = b""
end = time.time() + 5
while not any(row.startswith(b"PCSTREAM ") for row in line.split(b"\n")[:-1]) and time.time() < end:
    line += ser.read(256)
if b"PCSTREAM" not in line:
    sys.exit("no PCSTREAM reply: " + line.decode("utf-8", "replace"))
hdr = line.split(b"PCSTREAM", 1)[1].split(b"\n", 1)[0].split()
fs, fmt = int(hdr[1]), hdr[3].decode()
time.sleep(0.05)
ser.baudrate = a.baud
ser.reset_input_buffer()

if a.pair and fmt != "pair8":
    sys.exit("expected pair8 stream")
out = a.out or (f"sx1302_src{a.src}_{a.pair}.pair8" if a.pair else None) or f"sx1302_src{a.src}.{'cs8' if fmt == 'iq8' else 'cs16'}"
f = open(out, "wb")
buf = bytearray()
frames = bad_crc = seq_err = idx_err = gaps = lost = 0
samples = 0
segments = []
next_seq = None
next_idx = 0
endrec = None
erasures = []
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
        if typ in (0x10, 0x11, 0x14):
            n = ln // (2 if typ == 0x10 else 4)
            if not segments or idx != ((segments[-1][1] + samples - segments[-1][0]) & 0xFFFFFFFF):
                segments.append((samples, idx))
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
        elif typ == 0x13:
            s0, n = struct.unpack("<IH", pl)
            erasures.append((s0, n))
        elif typ == 0x1F:
            endrec = struct.unpack("<QIIII", pl)
f.close()
with open(out + ".segments", "w") as sf:
    sf.write("# file_sample device_index (first instant of each contiguous segment)\n")
    for file_sample, device_index in segments:
        sf.write(f"{file_sample} {device_index}\n")
dt = time.time() - t0
ser.baudrate = 115200
time.sleep(0.5)
tail = ser.read(65536).decode("utf-8", "replace")
ser.close()

print(f"file {out}: {samples} samples, {samples / fs:.3f} s at {fs} S/s")
print(f"frames {frames}, crc errors {bad_crc}, seq errors {seq_err}, index errors {idx_err}, gaps {gaps} ({lost} samples lost)")
erased = sum(n for _, n in erasures)
print(f"erasures: {len(erasures)} runs, {erased} samples ({100.0 * erased / max(samples, 1):.3f}%), listed in {out}.erasures")
with open(out + ".erasures", "w") as ef:
    ef.write("# first_sample count (samples the chip did not write; they repeat the previous ring lap)\n")
    for s0, n in erasures:
        ef.write(f"{s0} {n}\n")
if endrec:
    words, laps, bogus, dms, efs = endrec
    print(f"device: {words} samples in {dms} ms, laps {laps}, pointer glitches {bogus}; host got {100.0 * samples / max(words, 1):.3f}%")
else:
    print("no END frame (stream cut short)")
for l in tail.splitlines():
    if l.startswith(("stream", "phase", "uart", "stale:")):
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
