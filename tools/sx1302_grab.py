"""Pull capture RAM dumps from the SX1302-SDR firmware and plot them.

usage: sx1302_grab.py PORT OUTDIR src[:count] ...

Runs 'cap <src> b64' count times per source, saves the samples as
OUTDIR/srcNN.npy (complex64, one row per capture) and writes an averaged
spectrum and a time plot to OUTDIR/srcNN.png. Needs numpy, matplotlib and
pyserial."""
import base64, os, sys, time
import numpy as np
import serial
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

port, out = sys.argv[1], sys.argv[2]
os.makedirs(out, exist_ok=True)
jobs = []
for a in sys.argv[3:]:
    s, _, n = a.partition(":")
    jobs.append((int(s), int(n or 1)))

ser = serial.Serial(); ser.port = port; ser.baudrate = 115200; ser.timeout = 0.05
ser.dtr = False; ser.rts = False
ser.open(); ser.reset_input_buffer()
ser.write(b"\r\n"); time.sleep(0.5); ser.read(65536)


def grab(src):
    ser.write(f"cap {src} b64\r\n".encode())
    buf = b""
    end = time.time() + 15
    while time.time() < end and b"B64END" not in buf:
        buf += ser.read(65536)
    txt = buf.decode("utf-8", "replace")
    if "B64BEGIN" not in txt or "B64END" not in txt:
        raise RuntimeError("no dump: " + txt[-300:])
    head = txt.split("B64BEGIN", 1)[1].split("\n", 1)
    meta = head[0].split()
    body = head[1].split("B64END")[0]
    raw = base64.b64decode("".join(l.strip() for l in body.splitlines()))
    stats = [l for l in txt.splitlines() if l.startswith("src ")]
    return int(meta[1]), int(meta[3]), int(meta[4]), raw, stats


def to_iq(src, raw):
    b = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 4)
    if 10 <= src <= 17:
        i = b[:, 3].astype(np.int8).astype(np.float32)
        q = b[:, 1].astype(np.int8).astype(np.float32)
    else:
        i = (b[:, 2].astype(np.uint16) | (b[:, 3].astype(np.uint16) << 8)).astype(np.int16).astype(np.float32)
        q = (b[:, 0].astype(np.uint16) | (b[:, 1].astype(np.uint16) << 8)).astype(np.int16).astype(np.float32)
    return i + 1j * q


for src, n in jobs:
    caps = []
    for k in range(n):
        fs, rf0, rf1, raw, stats = grab(src)
        iq = to_iq(src, raw)
        caps.append(iq)
        print(stats[0] if stats else f"src {src} capture {k}")
    iq_all = np.stack(caps)
    np.save(os.path.join(out, f"src{src:02d}.npy"), iq_all.astype(np.complex64))
    nfft = 1024
    win = np.hanning(nfft)
    segs = []
    for iq in caps:
        for o in range(0, len(iq) - nfft + 1, nfft // 2):
            x = iq[o:o + nfft]
            x = x - x.mean()
            segs.append(np.abs(np.fft.fftshift(np.fft.fft(x * win))) ** 2)
    psd = 10 * np.log10(np.mean(segs, axis=0) + 1e-9)
    f = np.fft.fftshift(np.fft.fftfreq(nfft, 1 / fs))
    centre = rf0 if src in (2, 4, 9) else (rf1 if src in (3, 5) else rf0)
    fig, ax = plt.subplots(2, 1, figsize=(10, 7))
    ax[0].plot((centre + f) / 1e6 if fs >= 1e6 else f / 1e3, psd, lw=0.8)
    ax[0].set_xlabel("MHz (assuming radio A/B centre)" if fs >= 1e6 else "kHz offset")
    ax[0].set_ylabel("dB")
    ax[0].set_title(f"SX1302 capture src {src}, fs {fs/1e3:.0f} kS/s, {n} x {len(caps[0])} samples")
    ax[0].grid(alpha=0.3)
    t = np.arange(len(caps[0])) / fs * 1e3
    ax[1].plot(t, caps[0].real, lw=0.5, label="I")
    ax[1].plot(t, caps[0].imag, lw=0.5, label="Q")
    ax[1].set_xlabel("ms"); ax[1].legend(); ax[1].grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(os.path.join(out, f"src{src:02d}.png"), dpi=110)
    plt.close(fig)
    pk = np.argmax(psd)
    print(f"  src {src}: psd span {psd.max() - np.median(psd):.1f} dB above median, peak at {f[pk]/1e3:+.1f} kHz")
ser.close()
