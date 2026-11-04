"""Regenerate the Nano digital-control figure from the published measurements."""
import json
from pathlib import Path
import matplotlib.pyplot as plt


def main():
    folder = Path(__file__).resolve().parent
    rows = json.loads((folder / "data/p25-nano-controls.json").read_text())
    figure, axes = plt.subplots(2, 1, figsize=(9, 6.4), sharex=True)
    for row in rows:
        color = "#167968" if row["consistent"] else "#92512d"
        for axis, key in zip(axes, ["score", "distance"]):
            axis.scatter(row["amp"], row[key], s=38, color=color, alpha=.9)
    axes[0].set(ylabel="Cadence score", ylim=(-.03, 1), title="Twelve frame-sync markers ranked by the Nano")
    axes[1].axhline(6, ls=":", color="#56616c", lw=1)
    axes[1].set(xlabel="Digitally added C4FM amplitude (signed I/Q counts)", ylabel="Wrong bits / 64",
                title="Independent network identifier check on the saved window")
    for axis in axes:
        axis.grid(axis="y", alpha=.17)
        axis.spines[["top", "right"]].set_visible(False)
    figure.text(.13, .015, "Green points passed both header checks (sync correlation ≥ 0.75 and at most six wrong NID bits).", fontsize=9)
    figure.tight_layout(rect=(0, .04, 1, 1))
    figure.savefig(folder.parents[1] / "docs/images/p25-nano-scan.png", dpi=155)


if __name__ == "__main__":
    main()
