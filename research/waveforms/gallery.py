"""Build capture plates from the signed samples. No transmit templates are plotted as received I/Q."""

from pathlib import Path
import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator
from p25_audio import DATA, paired, channel
from recovery import recover

DEST = DATA.parents[2] / "docs/images"
INK = "#172844"
TEAL = "#007e89"
VIOLET = "#8f3399"
GRAY = "#576983"
GRID = "#dce3ed"
plt.rcParams.update(
    {
        "font.family": "DejaVu Sans",
        "font.size": 10,
        "axes.labelcolor": GRAY,
        "text.color": INK,
        "axes.edgecolor": GRID,
        "xtick.color": GRAY,
        "ytick.color": GRAY,
        "axes.spines.right": False,
        "axes.spines.top": False,
        "legend.frameon": False,
        "savefig.facecolor": "white",
    }
)


def plate(title, subtitle, rate):
    fig, axes = plt.subplots(2, 2, figsize=(12, 7.65))
    fig.subplots_adjust(
        top=0.736, left=0.083, right=0.945, bottom=0.11, hspace=0.65, wspace=0.28
    )
    fig.text(
        0.083,
        0.953,
        "SX1302-SDR    /    CAPTURE DETAIL",
        size=10,
        weight="bold",
        color=TEAL,
    )
    fig.text(0.083, 0.880, title, size=26, weight="bold")
    fig.text(0.083, 0.823, subtitle, size=10.8, color=GRAY)
    fig.text(0.947, 0.953, "915.000 MHz RX", size=13, ha="right", weight="bold")
    fig.text(0.947, 0.907, rate, size=10.5, ha="right", color=GRAY)
    return fig, axes.flat


def label(ax, num, title):
    ax.set_title(
        f"{num:02d}   {title.upper()}", loc="left", fontsize=10, pad=10, weight="bold"
    )
    ax.grid(axis="y", alpha=0.7, color=GRID, lw=0.6)
    ax.set_axisbelow(True)


def finish(fig, name, foot):
    fig.text(0.083, 0.022, foot, size=8.3, color=GRAY)
    fig.savefig(DEST / name, dpi=150)
    plt.close(fig)


def traces(ax, t, z):
    ax.plot(t, z.real, color=TEAL, lw=1.6, label="I")
    ax.plot(t, z.imag, color=VIOLET, lw=1.4, label="Q")
    ax.legend(ncol=2, fontsize=9, loc="upper right", borderaxespad=0, handlelength=1.4)
    ax.set_xlim(t[0], t[-1])
    ax.margins(y=0.17)
    ax.set_ylabel("Signed sample counts")


def stft(z, fs, n, hop, nfft=None):
    win = np.lib.stride_tricks.sliding_window_view(z, n)[::hop] * np.hanning(n)
    p = np.fft.fftshift(abs(np.fft.fft(win, nfft, axis=1)) ** 2, axes=1)
    return (
        (np.arange(len(p)) * hop + n / 2) / fs,
        np.fft.fftshift(np.fft.fftfreq(p.shape[1], 1 / fs)),
        p,
    )


def spec(ax, f, p, xunit, unit, lim):
    db = 10 * np.log10(np.maximum(p, 1e-16) / p.max())
    ax.plot(f / xunit, db, color=TEAL, lw=1.3)
    ax.fill_between(f / xunit, np.maximum(db, -60), -60, color=TEAL, alpha=0.1)
    ax.set(
        xlabel=f"Frequency offset ({unit})",
        ylabel="Relative power (dB)",
        xlim=lim,
        ylim=(-60, 3),
    )


def water(fig, ax, t, f, p, time_unit, freq_unit, lim, tx, fx):
    use = (f / freq_unit >= lim[0]) & (f / freq_unit <= lim[1])
    db = 10 * np.log10(np.maximum(p[:, use], 1e-16) / p.max())
    tt = t * time_unit
    ff = f[use] / freq_unit
    im = ax.pcolormesh(
        tt, ff, db.T, cmap="magma", vmin=-34, vmax=0, shading="auto", rasterized=True
    )
    ax.set(xlabel=f"Capture time ({tx})", ylabel=f"Frequency offset ({fx})", ylim=lim)
    cb = fig.colorbar(im, ax=ax, aspect=24, pad=0.022)
    cb.set_label("dB rel. peak", size=8)
    cb.ax.tick_params(labelsize=8)


def radio(name):
    d = np.load(DATA / name)
    a = d["iq"].astype(float)
    return a[:, 0] + 1j * a[:, 1], int(d["rate"])


def chirp():
    z, fs = radio("chirp.npz")
    z /= 16  # signed 12-bit values occupy the high bits
    fig, ax = plate(
        "A 1.2 MHz chirp in capture RAM",
        "Two gated up-sweeps appear in a single 512 µs snapshot from radio A.",
        "4 MS/s   ·   radio tap 2",
    )
    label(ax[0], 1, "Raw I/Q waveform")
    sl = slice(96, 169)
    traces(ax[0], np.arange(len(z))[sl] / fs * 1e6, z[sl])
    ax[0].set_xlabel("Capture time (µs)")
    label(ax[1], 2, "Received envelope")
    n = 16
    env = np.sqrt(np.mean(abs(z.reshape(-1, n)) ** 2, axis=1))
    ax[1].plot((np.arange(len(env)) * n + n / 2) / fs * 1e6, env, color=TEAL)
    ax[1].set(
        xlabel="Capture time (µs)", ylabel="Complex RMS (12-bit counts)", xlim=(0, 512)
    )
    t, f, p = stft(z, fs, 96, 8, 512)
    label(ax[2], 3, "Capture spectrum")
    spec(ax[2], f, p.mean(0), 1e6, "MHz", (-1.6, 1.6))
    label(ax[3], 4, "Sweep through baseband")
    water(fig, ax[3], t, f, p, 1e6, 1e6, (-0.85, 0.85), "µs", "MHz")
    finish(
        fig,
        "waveform-wide-chirp.png",
        "2,048 sample instants  /  Hann spectrum and waterfall  /  nominal sweep −600 to +600 kHz in 192 µs  /  uncalibrated receive level",
    )


def p25():
    raw = paired(DATA / "p25.pair8")
    z = raw[:, 0].astype(float) + 1j * raw[:, 1]
    fs = 125000
    filt = channel(raw, 0)
    fig, ax = plate(
        "P25 Phase 1 in raw I/Q",
        "The LR2021 repository’s synthetic voice-tone fixture, received here by the WM1302.",
        "125 kS/s   ·   IF tap 12",
    )
    label(ax[0], 1, "Raw I/Q waveform")
    sl = slice(32500, 32564)
    traces(ax[0], np.arange(sl.start, sl.stop) / fs * 1000, z[sl])
    ax[0].set_xlabel("Device time (ms)")
    ax[0].ticklabel_format(useOffset=False, axis="x")
    label(ax[1], 2, "Signal envelope")
    n = 250
    a = filt[: len(z) // n * n].reshape(-1, n)
    env = np.sqrt(np.mean(abs(a) ** 2, axis=1))
    t = (np.arange(len(env)) * n + n / 2) / fs
    ax[1].plot(t, env, color=TEAL, lw=0.9)
    ax[1].fill_between(t, env, 0, color=TEAL, alpha=0.10)
    ax[1].set(
        xlabel="Device time (s)",
        ylabel="Channel-filtered RMS (counts)",
        xlim=(0, t[-1]),
    )
    label(ax[2], 3, "Active-burst spectrum")
    _, f, p = stft(z[30000:67500], fs, 1024, 512)
    spec(ax[2], f - 15625, p.mean(0), 1000, "kHz", (-25, 25))
    label(ax[3], 4, "Burst arrival and release")
    tt, ff, p = stft(z[:90000], fs, 256, 96, 512)
    water(fig, ax[3], tt, ff - 15625, p, 1000, 1000, (-15, 15), "ms", "kHz")
    finish(
        fig,
        "waveform-p25-c4fm.png",
        "C4FM  /  4,800 symbols/s  /  spectrum and waterfall offsets from 915.015625 MHz  /  UART gaps zero-filled on the device timeline",
    )


def qpsk():
    raw = np.load(DATA / "qpsk.npz")["iq"]
    z, fs = radio("qpsk.npz")
    a, b = [recover(raw[:, i : i + 2]) for i in (0, 2)]
    fig, ax = plate(
        "QPSK on two receive chains",
        "A repeating 128-symbol block lets us compare the same RF modulation on radios A and B.",
        "125 kS/s   ·   IF taps 12 + 15",
    )
    label(ax[0], 1, "Raw I/Q waveform   ·   radio A")
    sl = slice(280, 357)
    traces(ax[0], np.arange(sl.start, sl.stop) / fs * 1000, z[sl])
    ax[0].set_xlabel("Capture time (ms)")
    label(ax[1], 2, "Recovered constellation")
    bx = ax[1]
    for j, (r, color) in enumerate([(a, TEAL), (b, VIOLET)]):
        pts = r["points"][32:]
        bx.scatter(
            pts.real,
            pts.imag,
            s=12,
            facecolors="none",
            edgecolors=color,
            linewidths=0.75,
            alpha=0.85,
            label=["A", "B"][j],
        )
    bx.axhline(0, color=GRID, lw=0.8)
    bx.axvline(0, color=GRID, lw=0.8)
    bx.set(
        aspect="equal",
        xlim=(-1.05, 1.05),
        ylim=(-1.05, 1.05),
        xlabel="Normalized I",
        ylabel="Normalized Q",
    )
    bx.legend(ncol=2, loc="upper center", bbox_to_anchor=(0.5, 1.04), fontsize=8)
    label(ax[2], 3, "Channel spectrum")
    _, f, p = stft(z, fs, 512, 128, 1024)
    spec(ax[2], f, p.mean(0), 1000, "kHz", (-45, 45))
    label(ax[3], 4, "Relative phase   ·   B versus A")
    for cat, prefix, col in [(0, "hold", TEAL), (1, "boot", VIOLET)]:
        phase = []
        for path in sorted(DATA.glob(f"phase-{prefix}-*.npz")):
            x = np.load(path)["iq"].astype(float)
            aa = x[:, 0] + 1j * x[:, 1]
            bb = x[:, 2] + 1j * x[:, 3]
            phase.append(np.angle(np.vdot(aa, bb), deg=True))
        xx = np.arange(len(phase)) + cat * 5
        ax[3].scatter(xx, phase, s=45, color=col, zorder=3)
    ax[3].set(
        xticks=[1.5, 6.5],
        xticklabels=["Same tuning", "Fresh initialization"],
        ylim=(-181, 181),
        yticks=[-180, -90, 0, 90, 180],
        ylabel="Phase (degrees)",
    )
    finish(
        fig,
        "waveform-qpsk-phase.png",
        "7,812.5 symbols/s  /  32 known symbols for acquisition  /  constellation shows 96 held-out symbol decisions per lane",
    )


if __name__ == "__main__":
    p25()
    chirp()
    qpsk()
