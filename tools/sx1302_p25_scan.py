"""Rank repeated P25 Phase 1 frame-sync candidates with the Nano and save the winning window."""
import argparse
import re
from pathlib import Path
import numpy as np
from sx1302_watch import Bench

def parse_window(text):
    winner = re.search(r"sync winner end=(\d+) score=([-\d.]+)", text)
    window = re.search(r"sync window first=(\d+) samples=(\d+)", text)
    event = re.search(r"(?m)^SYNC_EVENT ([0-9a-fA-F]+)\r?$", text)
    if not (winner and window and event):
        raise ValueError("No complete candidate record returned")
    first, count = map(int, window.groups())
    end = int(winner[1])
    if not (1024 <= count <= 2048 and end-first == 1023 and len(event[1]) == 8*count):
        raise ValueError("Inconsistent sample indices or record length")
    records = np.frombuffer(bytes.fromhex(event[1]), dtype=">u4").astype("<u4").view("u1").reshape(-1,4)
    record = dict(iq=records[:, :2].copy().view("i1"), energy=records[:, 2].copy(),
                stale=records[:, 3].copy(), first_sample=first, peak_end=end,
                score=float(winner[2]), sample_rate_hz=125000)
    header = re.search(r"sync header nac=([0-9A-F]+) duid=([0-9A-F]+) distance=(\d+)/64 correlation=([.\d]+) consistent=([01])", text)
    if header:
        record.update(expected_nac=int(header[1], 16), closest_duid=int(header[2], 16),
                      nid_bit_errors=int(header[3]), sync_correlation=float(header[4]),
                      header_consistent=bool(int(header[5])))
    return record

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("port")
    parser.add_argument("--carrier-hz", type=int, required=True)
    parser.add_argument("--cal-hz", type=int, help="Optional calibration-table frequency for probetune")
    parser.add_argument("--ms", type=int, default=20000)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--fixture-amplitude", type=int, help="Digitally add a sync fixture in signed I/Q counts")
    parser.add_argument("--nac", type=lambda s: int(s, 0), help="Expected 12-bit NAC for the voice-header check")
    parser.add_argument("--seed", type=int, default=1)
    args = parser.parse_args()
    if not 4000 <= args.ms <= 600000 or args.carrier_hz <= 20000:
        parser.error("Use 4000..600000 ms and a carrier above 20000 Hz")
    amp = args.fixture_amplitude
    if amp is not None and not 0 <= amp <= 100:
        parser.error("Use 0..100 digital fixture counts")
    if args.nac is not None and (not 0 <= args.nac <= 0xfff or amp is not None):
        parser.error("--nac accepts 0..0xfff for live scans; the digital fixture uses 0x293")
    if not 0 <= args.seed <= 0xffffffff:
        parser.error("Seed must fit in 32 bits")
    center = args.carrier_hz - 20000
    tune = f"tune {center} {center}" if args.cal_hz is None else f"probetune {center} {center} {args.cal_hz}"
    bench = Bench(args.port)
    try:
        if "lgw_start -> 0" not in bench.cmd([tune]):
            raise RuntimeError("Radio startup failed")
        cmd = f"p25scan {args.ms}" if amp is None else f"p25mix {args.ms} {amp} {args.seed}"
        if args.nac is not None:
            cmd += f" {args.nac}"
        response = bench.cmd([cmd], timeout=args.ms/1000+12)
    finally:
        bench.s.close()
    record = parse_window(response)
    with args.out.open("wb") as f:
        np.savez_compressed(f, **record, carrier_hz=args.carrier_hz, center_hz=center,
                            command=cmd, console=response.split("SYNC_EVENT ")[0])
    print(f"Candidate score {record['score']:.4f}, sample {record['peak_end']}, {len(record['iq'])} samples saved")

    if "header_consistent" in record:
        print(f"Expected NAC {record['expected_nac']:#05x}, distance {record['nid_bit_errors']}/64, consistent={record['header_consistent']}")

if __name__ == "__main__":
    main()
