"""Send console commands to the SX1302-SDR firmware.

usage: sx1302_console.py PORT [--reset] [--boot SECS] [cmd [wait]] ...

Each command takes an optional wait in seconds (default 3). --reset pulses
RTS to reboot the board and prints the boot log. Output is also written to
sx1302_console.log in the current directory."""
import os, sys, time, serial
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

args = sys.argv[1:]
port = args.pop(0)
reset = False
boot = 3.0
if args and args[0] == "--reset":
    reset = True
    args.pop(0)
if args and args[0] == "--boot":
    args.pop(0)
    boot = float(args.pop(0))

cmds = []
while args:
    c = args.pop(0)
    w = 3.0
    if args:
        try:
            w = float(args[0]); args.pop(0)
        except ValueError:
            pass
    cmds.append((c, w))

s = serial.Serial(); s.port = port; s.baudrate = 115200; s.timeout = 0.05
s.dtr = False; s.rts = False
s.open()
log = open("sx1302_console.log", "w", encoding="utf-8")

def pump(secs):
    end = time.time() + secs
    while time.time() < end:
        b = s.read(8192)
        if b:
            t = b.decode("utf-8", "replace")
            sys.stdout.write(t); sys.stdout.flush(); log.write(t)

if reset:
    s.rts = True; time.sleep(0.15); s.rts = False
    pump(boot)
else:
    s.write(b"\r\n")
    pump(0.3)
for c, w in cmds:
    s.write((c + "\r\n").encode())
    pump(w)
s.close(); log.close()
