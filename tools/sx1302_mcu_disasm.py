"""Disassemble the SX1302 MCU firmware images in sx1302_hal (.var files).

usage: sx1302_mcu_disasm.py FILE.var [--out FILE.asm] [--stats]

Each image is 8192 bytes: 4096 little-endian 16-bit words. Bits 13:0 decode
as the mid-range PIC16 instruction set; bits 15:14 are check bits. --stats
prints the instruction mix, branch targets and the check-bit fit."""
import argparse, re, sys
from collections import Counter

ap = argparse.ArgumentParser()
ap.add_argument("var")
ap.add_argument("--out")
ap.add_argument("--stats", action="store_true")
a = ap.parse_args()

txt = open(a.var).read()
body = txt[txt.index("{") + 1:txt.rindex("}")]
data = bytes(int(v, 16) for v in re.findall(r"0x[0-9A-Fa-f]{2}", body))
if len(data) != 8192:
    sys.exit(f"expected 8192 bytes, got {len(data)}")
raw = [data[i] | data[i + 1] << 8 for i in range(0, len(data), 2)]
ops = [w & 0x3FFF for w in raw]
chk = [w >> 14 for w in raw]

BYTE_OPS = {
    0x07: "ADDWF", 0x05: "ANDWF", 0x09: "COMF", 0x03: "DECF", 0x0B: "DECFSZ",
    0x0A: "INCF", 0x0F: "INCFSZ", 0x04: "IORWF", 0x08: "MOVF", 0x0D: "RLF",
    0x0C: "RRF", 0x02: "SUBWF", 0x0E: "SWAPF", 0x06: "XORWF",
}
SFR = {0x00: "INDF", 0x02: "PCL", 0x03: "STATUS", 0x04: "FSR", 0x0A: "PCLATH", 0x0B: "INTCON"}


def f(x):
    return SFR.get(x, f"0x{x:02X}")


def dis(w):
    if w == 0x0008: return "RETURN", None
    if w == 0x0009: return "RETFIE", None
    if w == 0x0063: return "SLEEP", None
    if w == 0x0064: return "CLRWDT", None
    if w & 0x3F9F == 0x0000: return "NOP", None
    if w & 0x3F80 == 0x0080: return f"MOVWF {f(w & 0x7F)}", None
    if w & 0x3F80 == 0x0100: return "CLRW", None
    if w & 0x3F80 == 0x0180: return f"CLRF {f(w & 0x7F)}", None
    top = w >> 12
    if top == 0:
        op = (w >> 8) & 0x0F
        if op in BYTE_OPS:
            return f"{BYTE_OPS[op]} {f(w & 0x7F)},{'F' if w & 0x80 else 'W'}", None
        return f".dw 0x{w:04X}", None
    if top == 1:
        b = (w >> 7) & 7
        name = ("BCF", "BSF", "BTFSC", "BTFSS")[(w >> 10) & 3]
        return f"{name} {f(w & 0x7F)},{b}", None
    if top == 2:
        k = w & 0x7FF
        return (f"CALL 0x{k:03X}" if not w & 0x800 else f"GOTO 0x{k:03X}"), ("call" if not w & 0x800 else "goto", k)
    k = w & 0xFF
    sub = (w >> 8) & 0x0F
    if sub <= 3: return f"MOVLW 0x{k:02X}", None
    if sub <= 7: return f"RETLW 0x{k:02X}", None
    if sub == 8: return f"IORLW 0x{k:02X}", None
    if sub == 9: return f"ANDLW 0x{k:02X}", None
    if sub == 0xA: return f"XORLW 0x{k:02X}", None
    if sub in (0xC, 0xD): return f"SUBLW 0x{k:02X}", None
    return f"ADDLW 0x{k:02X}", None


lines, mix, targets = [], Counter(), []
used = [w != 0x3FFF for w in ops]
for pc, w in enumerate(ops):
    s, br = dis(w)
    mix[s.split()[0]] += 1
    if br and used[pc]:
        targets.append((pc, br[0], br[1]))
    lines.append(f"{pc:03X}: {w:04X}  {s}")

if a.out:
    open(a.out, "w").write("\n".join(lines) + "\n")
else:
    print("\n".join(lines))

if a.stats:
    n_used = sum(used)
    print(f"\nwords used {n_used} of 4096, unused (0x3FFF) {4096 - n_used}", file=sys.stderr)
    print("instruction mix: " + ", ".join(f"{k} {v}" for k, v in mix.most_common(20)), file=sys.stderr)
    # branch targets: inside the program and on a used word (low 11 bits plus PCLATH page unknown)
    hits = sum(1 for _, _, t in targets if any(used[(page << 11) | t] for page in (0, 1)))
    print(f"CALL/GOTO {len(targets)}, target used on page 0 or 1: {hits}", file=sys.stderr)
    # check bits: test parity of bit groups
    best = []
    for split in range(1, 14):
        for mode in ("even", "odd"):
            def par(x):
                return bin(x).count("1") & 1
            ok = 0
            for w, c in zip(ops, chk):
                hi = par(w >> split); lo = par(w & ((1 << split) - 1))
                if mode == "odd":
                    hi ^= 1; lo ^= 1
                ok += (c == (hi << 1 | lo))
            best.append((ok, split, mode))
    best.sort(reverse=True)
    ok, split, mode = best[0]
    print(f"check bits: best fit bit15 = {mode} parity of bits 13:{split}, bit14 = {mode} parity of bits {split - 1}:0, matches {ok}/4096", file=sys.stderr)
