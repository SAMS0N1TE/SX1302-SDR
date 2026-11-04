"""Generate the bench figures from the measured data shipped next to this script."""

import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.ticker import MaxNLocator
from capture_data import DATA, device_iq
from verify import paging_batches

DEST = DATA.parents[2] / "docs/images"
INK, SUB, BLUE, RED, GRID = "#152d3d", "#536a76", "#006d82", "#b24d24", "#d7e1e4"
CMAP = LinearSegmentedColormap.from_list(
    "rf", ["#f5f8f8", "#d6e5e8", "#8fbec5", "#217c88", "#103d54"]
)
plt.rcParams.update(
    {
        "font.family": "DejaVu Sans",
        "font.size": 11,
        "axes.titlesize": 12,
        "axes.titleweight": "bold",
        "axes.labelcolor": SUB,
        "text.color": INK,
        "xtick.color": SUB,
        "ytick.color": SUB,
        "axes.edgecolor": GRID,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "legend.frameon": False,
        "savefig.facecolor": "white",
    }
)


def head(fig, title, sub):
    fig.text(0.09, 0.944, title, fontsize=21, weight="bold", va="top")
    fig.text(0.09, 0.858, sub, fontsize=11, color=SUB, va="top")


def save(fig, name):
    fig.savefig(DEST / name, dpi=155, bbox_inches="tight", pad_inches=0.18)
    plt.close(fig)


def split():
    d = np.load(DATA / "split-band-bins.npz")
    z = d["sums"][..., 0].astype(float) + 1j * d["sums"][..., 1]
    fs = float(d["sample_rate"])
    n = np.arange(len(z))
    width = 80
    hop = 12
    fig, axes = plt.subplots(2, 1, figsize=(10.8, 6.0), sharex=True)
    fig.subplots_adjust(left=0.16, right=0.83, top=0.72, bottom=0.14, hspace=0.50)
    head(
        fig,
        "Two receivers held 277.67 MHz apart",
        "One 48 s recording. The HackRF sent a different four-tone payload on each band in succession.",
    )
    for j, (ax, cfo) in enumerate(zip(axes, (17, 40))):
        rotated = z[:, j, :] * np.exp(-2j * np.pi * cfo * n / fs)[:, None]
        cs = np.vstack([np.zeros(4), np.cumsum(rotated, axis=0)])
        power = abs(cs[width::hop] - cs[: len(cs) - width : hop]) ** 2
        t = (np.arange(len(power)) * hop + width / 2) / fs
        quiet = (t > 25) & (t < 39) if j == 0 else (t > 3) & (t < 17)
        db = 10 * np.log10((power + 1) / (np.median(power[quiet], axis=0) + 1))
        im = ax.imshow(
            db.T,
            origin="lower",
            aspect="auto",
            extent=[t[0] - hop / (2 * fs), t[-1] + hop / (2 * fs), -0.5, 3.5],
            cmap=CMAP,
            vmin=-3,
            vmax=12,
            interpolation="nearest",
        )
        ax.set(
            yticks=range(4),
            yticklabels=["−15.625", "−7.8125", "+7.8125", "+15.625"],
            ylabel="Offset (kHz)",
        )
        ax.set_title(
            ["A   /   156.250 MHz", "B   /   433.920 MHz"][j],
            loc="left",
            color=INK,
            pad=6,
        )
    axes[-1].set_xlabel("Device sample time (s)")
    axes[-1].set_xticks([0, 8, 16, 24, 32, 40, 48])
    cb = fig.colorbar(
        im, cax=fig.add_axes([0.86, 0.22, 0.017, 0.42]), ticks=[-3, 0, 3, 6, 9, 12]
    )
    cb.set_label("dB above quiet median")
    save(fig, "split-band-156-433.png")


def trigger():
    d = np.load(DATA / "trigger-903-915.npz")
    x = d["iq"]
    obs = int(d["observation_index"])
    t = (np.arange(len(x)) - obs) / 125
    fig = plt.figure(figsize=(10.8, 6.2))
    g = fig.add_gridspec(
        2,
        2,
        left=0.09,
        right=0.97,
        bottom=0.11,
        top=0.73,
        hspace=0.80,
        wspace=0.28,
        height_ratios=[1.2, 1],
    )
    head(
        fig,
        "One trigger froze both I/Q channels",
        "The 903 MHz burst led the 915 MHz burst by 1.536 ms. Both lanes share the same sample clock.",
    )
    ax = fig.add_subplot(g[0, :])
    colors = [BLUE, RED]
    for j, hz in enumerate((31250, -23437.5)):
        z = x[:, 2 * j].astype(float) + 1j * x[:, 2 * j + 1]
        env = abs(
            (z * np.exp(-2j * np.pi * hz * np.arange(len(z)) / 125000))
            .reshape(-1, 16)
            .mean(1)
        )
        ax.plot(
            t[::16] + 0.06,
            env / np.percentile(env, 94),
            color=colors[j],
            lw=1.8,
            label=["903 MHz", "915 MHz"][j],
        )
    ax.axvline(0, c=SUB, ls=":", lw=1)
    ax.set(
        xlim=(-3, 6),
        ylim=(-0.04, 1.45),
        xlabel="Time from P4 trigger observation (ms)",
        ylabel="Relative amplitude",
    )
    ax.legend(ncol=2, loc="upper right")
    ax.grid(axis="y", color=GRID, alpha=0.65)
    # Index 1264 is inside the overlap. Plot the signed bytes directly.
    start = 1264
    sl = slice(start, start + 36)
    for j in (0, 1):
        bx = fig.add_subplot(g[1, j])
        bx.plot(
            8 * np.arange(36),
            x[sl, 2 * j],
            color=colors[j],
            lw=1.8,
            marker=".",
            label="I",
        )
        bx.plot(
            8 * np.arange(36), x[sl, 2 * j + 1], color=INK, ls="--", lw=1.25, label="Q"
        )
        bx.set_title(
            ["903 MHz  ·  raw I and Q", "915 MHz  ·  raw I and Q"][j], loc="left"
        )
        bx.set(xlabel="Time within excerpt (µs)", ylabel="Signed sample counts")
        bx.legend(
            loc="lower right",
            bbox_to_anchor=(1, 1.01),
            ncol=2,
            borderaxespad=0,
            handlelength=1.4,
        )
        bx.grid(axis="y", color=GRID, alpha=0.65)
    save(fig, "trigger-iq.png")


def pager():
    path = DATA / "paging-156250.cs8"
    raw = device_iq(path, 2)
    z = raw[:, 0].astype(float) + 1j * raw[:, 1]
    for a, n in np.loadtxt(str(path) + ".erasures", dtype=int, ndmin=2):
        z[a : a + n] = 0
    t = np.arange(len(z)) / 125000
    start = 1.231
    edges = np.rint((start + np.arange(33) / 512) * 125000).astype(int)
    power = []
    for hz in (15517, 24517):
        cs = np.r_[0, np.cumsum(z * np.exp(-2j * np.pi * hz * t))]
        power.append(abs(np.diff(cs[edges])) ** 2)
    ev = 10 * np.log10((power[1] + 1) / (power[0] + 1))
    bits = np.unpackbits(np.frombuffer(bytes.fromhex("7cd215d8"), dtype="u1"))
    fig, (ax, bx) = plt.subplots(
        2, 1, figsize=(10.8, 5.6), gridspec_kw={"height_ratios": [2, 1]}
    )
    fig.subplots_adjust(left=0.09, right=0.97, top=0.73, bottom=0.12, hspace=0.73)
    head(
        fig,
        "Inside a 512-baud paging batch",
        "156.250 MHz  ·  controlled transmission  ·  signed tone-energy ratio across a 32-bit sync word",
    )
    ax.bar(np.arange(32), ev, color=np.where(ev > 0, BLUE, RED), width=0.80)
    ax.axhline(0, c=INK, lw=0.8)
    ax.set(xlim=(-0.7, 31.7), ylabel="Mark / space (dB)", xlabel="Sync bit, MSB first")
    ax.set_xticks([0, 4, 8, 12, 16, 20, 24, 28, 31])
    ax.grid(axis="y", color=GRID, alpha=0.5)
    ax.set_axisbelow(True)
    for i, bit in enumerate(bits):
        ax.text(
            i,
            0.98,
            str(bit),
            transform=ax.get_xaxis_transform(),
            va="top",
            ha="center",
            fontsize=8,
        )
    ax.set_ylim(min(-8, ev.min() - 2), ev.max() + 6)
    batches = paging_batches(path)
    counts = [r[2] for r in batches]
    bx.bar(range(5), [16] * 5, color=GRID, width=0.52)
    bx.bar(range(5), counts, color=BLUE, width=0.52)
    for j, k in enumerate(counts):
        bx.text(
            j, k - 0.6, f"{k}/16", ha="center", va="top", color="white", weight="bold"
        )
    bx.set(
        xticks=range(5),
        xticklabels=[f"{r[0]:.3f}" for r in batches],
        yticks=[0, 8, 16],
        ylim=(0, 17),
        ylabel="Exact words",
        xlabel="Recognized batch start (s)",
    )
    save(fig, "vhf-paging-sync.png")


def antennas():
    d = np.load(DATA / "433-spectra.npz")
    x = d["offset_hz"]
    p = d["power_db"]
    fig, (ax, bx) = plt.subplots(
        1, 2, figsize=(10.8, 4.6), gridspec_kw={"width_ratios": [1.4, 1]}
    )
    fig.subplots_adjust(top=0.68, bottom=0.16, left=0.09, right=0.96, wspace=0.46)
    head(
        fig,
        "Antenna swap at 433.920 MHz",
        "Same HackRF drive setting and FFT procedure. The receiver center was moved above and below the test signal.",
    )
    ax.plot(x, p[2], color="#a0a9ad", lw=0.8, label="Muted, new antennas")
    ax.plot(x, p[1], color=RED, lw=1.05, label="Earlier antennas")
    ax.plot(x, p[3], color=BLUE, lw=1.4, label="433 MHz antennas")
    ax.set(
        xlabel="Offset from predicted +20 kHz tone (Hz)",
        ylabel="dB above local FFT median",
        xlim=(-100, 105),
        ylim=(-11, 24),
    )
    ax.legend(fontsize=8, loc="upper left")
    ax.grid(axis="y", color=GRID, alpha=0.6)
    a = np.genfromtxt(DATA / "antenna-433.csv", delimiter=",", names=True)
    for i, row in enumerate(a):
        old, new = row["old_control_db"], row["new_control_db"]
        bx.plot([old, new], [i, i], color=GRID, lw=3)
        bx.scatter(old, i, color=RED, s=36)
        bx.scatter(new, i, color=BLUE, s=36)
    bx.set(
        yticks=range(4),
        yticklabels=["+20.000", "+27.812", "−20.000", "−12.188"],
        ylabel="Expected IF (kHz)",
        xlabel="Peak above strongest control (dB)",
        xlim=(11.9, 17.3),
    )
    bx.invert_yaxis()
    bx.xaxis.set_major_locator(MaxNLocator(integer=True))
    bx.set_title("Four matched comparisons", loc="left")
    ax.set_title("Carrier and muted reference", loc="left")
    save(fig, "433-antenna-repeat.png")


if __name__ == "__main__":
    split()
    trigger()
    pager()
    antennas()
