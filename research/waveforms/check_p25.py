"""Run stock DSD-neo on both SX1302 lanes and check the ordered folded IMBE words."""

import argparse, hashlib, json, re, subprocess, tempfile, wave
from pathlib import Path
from p25_audio import DATA, discriminator, fold_repetitions

EXPECTED = "0a3734e15e07fa7a67b6169abe9b4cca18cada0b37dfb1ec3ad4af44b153a37e"


def check(exe, lane, fold, tmp):
    path = DATA / "p25.pair8"
    pcm = (fold_repetitions if fold else discriminator)(path, lane)
    wav = tmp / f"lane-{lane}-{fold}.wav"
    frames = wav.with_suffix(".txt")
    with wave.open(str(wav), "wb") as w:
        w.setparams((1, 2, 48000, 0, "NONE", ""))
        w.writeframes(pcm.tobytes())
    result = subprocess.run(
        [
            str(exe),
            "-f1",
            "-mc",
            "-i",
            str(wav),
            "-o",
            "null",
            "--frame-log",
            str(frames),
            "--frontend",
            "none",
        ],
        capture_output=True,
        check=True,
    )
    log = (result.stdout + result.stderr).decode(errors="replace")
    words = re.findall(
        r"FRAME IMBE slot=\d+ data=([0-9A-Fa-f]{22})", frames.read_text()
    )
    log = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", log)
    units = re.findall(r"NAC/CC: ([0-9A-Fa-f]+);\s*(LDU1|LDU2|TDU|HDU)", log)
    digest = hashlib.sha256(bytes.fromhex("".join(words))).hexdigest()
    row = dict(
        lane=lane,
        folded=fold,
        units=units,
        imbe_count=len(words),
        reference_value_matches=sum(
            w.upper() in {"09B0880CC621F680A82600", "09B0880CC621F680A82601"}
            for w in words
        ),
        imbe_sha256=digest,
        errors=dict(
            re.findall(
                r"Total (audio errors|header errors|irrecoverable header errors): (\d+)",
                log,
            )
        ),
    )
    if fold and (len(words) != 18 or digest != EXPECTED):
        raise RuntimeError(f"Unexpected folded sequence: {row}")
    return row


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("executable", type=Path)
    args = ap.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        results = [
            check(args.executable.resolve(), lane, fold, Path(tmp))
            for lane in range(2)
            for fold in (False, True)
        ]
    print(json.dumps(results, indent=2))
