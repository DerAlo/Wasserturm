#!/usr/bin/env python3
# Testwerkzeug auf dem Coral: spricht das Turret-Protokoll mit dem Core.
#
#   core_cli.py [--start] [--repl] [schritt ...]
#     --start   Core per Strg+C in die REPL holen und turret_main.main() starten
#     --repl    am Ende per Strg+C zurück in die REPL (Servos stoppen)
#   Schritte, der Reihe nach:
#     wait:<s>                 nur mitlesen
#     drive:<pan%>:<dtilt>:<s> C-Befehle mit 20 Hz senden (dtilt in Grad/s)
#     <beliebige Zeile>        direkt senden, z. B. K,debug_rc,1  oder  X,80  oder  ?
import sys
import time

import serial


def main():
    args = sys.argv[1:]
    start = '--start' in args
    repl = '--repl' in args
    steps = [a for a in args if not a.startswith('--')]

    s = serial.Serial('/dev/ttyACM0', 115200, timeout=0.05, write_timeout=1)
    pending = b''

    def pump(t):
        nonlocal pending
        end = time.time() + t
        while time.time() < end:
            pending += s.read(4096)
            while b'\n' in pending:
                line, pending = pending.split(b'\n', 1)
                line = line.decode('ascii', 'replace').rstrip()
                if line:
                    print('<', line)

    if start:
        s.write(b'\x03')
        pump(0.5)
        s.write(b'\x03\r\n')
        pump(0.5)
        s.write(b'import sys\r\nsys.modules.pop("turret_main", None)\r\n')
        pump(0.3)
        s.write(b'import turret_main; turret_main.main()\r\n')
        pump(1.5)

    for step in steps:
        print('>', step)
        if step.startswith('wait:'):
            pump(float(step.split(':')[1]))
        elif step.startswith('drive:'):
            _, pan, rate, secs = step.split(':')
            end = time.time() + float(secs)
            while time.time() < end:
                s.write('C,0,{},{:.2f},0\n'.format(pan, float(rate) / 20.0).encode())
                pump(0.05)
            s.write(b'C,0,0,0,0\n')
            pump(0.3)
        else:
            s.write(step.encode() + b'\n')
            pump(0.4)

    if repl:
        s.write(b'\x03')
        pump(0.8)
    s.close()


if __name__ == '__main__':
    main()
