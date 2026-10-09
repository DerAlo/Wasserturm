# turret_main.py  –  CyberBrick Core (ESP32-C3) + Receiver Shield X11
# Wasserturm: Fernbedienung + Befehle vom Coral über USB-Serial (REPL-Port)
#
# Belegung wie in der Original-RC-Konfiguration (rc_config "Water+Turret"):
#   S1 = Drehen (360°-Servo, 1,5 ms = Stopp), S2 = Neigung, S3 = Abzug
#   S1..S4 -> GPIO 3,2,1,0 (Quelle: bbl/servos.py)
#   Abzug laut rc_config: Start 90°, Taste los = 20°, Taste gedrückt = 0° (Schuss)
#
# Protokoll Coral -> Core (eine Zeile pro Befehl):
#   C,<mode>,<pan%>,<dtilt°>,<fire>   Fahrbefehl, ~15-30 Hz
#                                     pan% -100..100, dtilt relativ, fire 0/1
#   K,<name>,<wert>                   Parameter setzen (siehe CFG)
#   X,<winkel>                        Neigung absolut
#   T,<winkel>                        Abzug-Servo testen: nur unscharf und nur im
#                                     Bereich trig_park..trig_rest (kein Schuss)
#   Z[,<grad>]                        Pan-Schätzung auf 0 (Lauf steht vorn) bzw. auf <grad>
#   U                                 Start-Kennung ausgeben (U,<hex>, neu bei jedem Start)
#   ?                                 alle Parameter ausgeben
# Core -> Coral:
#   S,<quelle>,<pan%>,<pan_est°>,<tilt°>,<abzug°>,<armed>,<rc>   alle 200 ms
#   R,<10 RC-Werte>                   nur wenn debug_rc = 1
#   K,<name>,<wert>                   Antwort auf K und ?
#
# Sicherheit:
#   - armed = 0 (Standard nach jedem Start): Abzug steht auf trig_park, es wird
#     NICHT geschossen, egal was Coral oder Fernbedienung melden.
#   - RC übersteuert Automatik für rc_hold_ms nach letzter Knüppelbewegung
#   - Kein gültiger C-Befehl seit cmd_timeout_ms -> Drehen stopp, Abzug aus
#   - Feuer max. fire_max_ms am Stück, dann erst nach Loslassen wieder
#   - Drehbereich per Koppelnavigation auf ±pan_limit begrenzt (Kabel!)
#     -> Turm beim Einschalten in Grundstellung (Lauf nach vorn) stellen
#
# Abbruch zum REPL: Strg+C.

import os
import sys
import time
import uselect
from machine import Pin, PWM

sys.path.append('/bbl')
sys.path.append('/app')

import rc_module

PIN_PAN, PIN_TILT, PIN_TRIG = 3, 2, 1

CFG = {
    'armed': 0,            # 1 = Abzug freigegeben
    'trig_park': 90,       # Abzug-Servo, solange unscharf
    'trig_rest': 20,       # scharf, wartet
    'trig_fire': 0,        # Schuss
    'fire_max_ms': 1500,
    'tilt_min': 15,
    'tilt_max': 165,
    'tilt_home': 90,
    'tilt_rc_rate': 60,    # Grad/s bei Vollausschlag
    'pan_max': 40,         # max. Drehgeschwindigkeit in %
    'pan_dead': 18,        # Totbereich des 360°-Servos in %, wird aufgeschlagen
    'pan_limit': 180,     # ±Grad ab Grundstellung, 0 = keine Begrenzung
    'pan_trim_us': -20,     # Korrektur der Stopp-Pulsbreite, falls S1 kriecht
    'deg_s0': 33,          # Grad/s, sobald das Servo dreht (Koppelnavigation)
    'deg_s': 260,          # zusätzliche Grad/s bei 100 %
    'idle_off_s': 30,      # ungesichert und so lange unbewegt: Neige-/Abzug-Servo stromlos (0 = nie)
    'rc_en': 1,
    'rc_fire_en': 0,       # Feuertaste der Fernbedienung erst nach Kalibrierung
    'rc_pan': 1,           # Index in rc_slave_data(): [L1,L2,L3,R1,R2,R3,K1..K4]
    'rc_tilt': 2,
    'rc_fire': 6,
    'rc_pan_sign': 1,
    'rc_tilt_sign': 1,
    'rc_pressed': 0,
    'rc_hold_ms': 3000,
    'cmd_timeout_ms': 300,
    'debug_rc': 0,
}

RC_CENTER, RC_DEAD, RC_SPAN = 2048, 250, 1800
LOOP_MS = 20
STATUS_MS = 200


def clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


def dz(v):
    if -RC_DEAD < v < RC_DEAD:
        return 0.0
    v = v - RC_DEAD if v > 0 else v + RC_DEAD
    return clamp(v / (RC_SPAN - RC_DEAD), -1.0, 1.0)


class Servo:
    # Pulsbreiten wie bbl/servos.py: 0° = 0,49 ms, 180° = 2,48 ms, Stopp = 1,5 ms
    def __init__(self, pin):
        self.pwm = PWM(Pin(pin), freq=50, duty=0)
        self.us = None

    def pulse(self, us):
        us = int(us)
        if us != self.us:
            self.us = us
            self.pwm.duty_ns(us * 1000)

    def angle(self, deg):
        self.pulse(489 + clamp(deg, 0, 180) * 11.08)

    def speed(self, pct, trim=0):
        self.pulse(1500 + trim + clamp(pct, -100, 100) * 10)

    def off(self):
        self.pulse(0)


def main():
    rc_ok = rc_module.rc_slave_init() is not False

    pan_servo = Servo(PIN_PAN)
    tilt_servo = Servo(PIN_TILT)
    trig_servo = Servo(PIN_TRIG)

    # Servos bleiben nach dem Start stromlos, bis sich etwas bewegen soll (siehe idle_off_s):
    # ohne Akku hängt alles am USB des Coral, und der Anlaufstrom lässt den Core sonst neu starten.
    tilt = float(CFG['tilt_home'])
    trig = CFG['trig_park']
    trig_test = None

    poll = uselect.poll()
    poll.register(sys.stdin, uselect.POLLIN)
    buf = ''

    mode = 0
    cmd_pan, cmd_dtilt, cmd_fire = 0, 0.0, False
    cmd_t = time.ticks_ms() - 100000
    rc_t = cmd_t
    pan_est = 0.0
    pan = 0
    fire_start = None
    fire_locked = False
    src = 'idle'
    last = time.ticks_ms()
    stat_t = last
    rc_seen = 0
    held = (int(tilt * 10), int(trig))
    held_t = time.ticks_add(last, -3600000)

    boot_id = '%06x' % int.from_bytes(os.urandom(3), 'little')   # neu bei jedem Start

    print('S,ready')
    try:
        while True:
            now = time.ticks_ms()
            dt = time.ticks_diff(now, last) / 1000.0
            last = now

            # --- Befehle vom Coral
            while poll.poll(0):
                ch = sys.stdin.read(1)
                if ch != '\n':
                    buf = buf + ch if len(buf) < 48 else ''
                    continue
                p = buf.strip().split(',')
                buf = ''
                try:
                    if p[0] == 'C' and len(p) == 5:
                        mode = int(p[1])
                        cmd_pan = int(clamp(float(p[2]), -100, 100))
                        cmd_dtilt += clamp(float(p[3]), -10.0, 10.0)
                        cmd_fire = p[4] == '1'
                        cmd_t = now
                    elif p[0] == 'K' and len(p) == 3 and p[1] in CFG:
                        CFG[p[1]] = float(p[2]) if '.' in p[2] else int(p[2])
                        print('K,' + p[1] + ',' + str(CFG[p[1]]))
                        if p[1] == 'armed':
                            trig_test = None
                    elif p[0] == 'X' and len(p) == 2:
                        tilt = float(p[1])
                    elif p[0] == 'T' and len(p) == 2 and not CFG['armed']:
                        trig_test = float(p[1])
                    elif p[0] == 'Z':
                        pan_est = float(p[1]) if len(p) > 1 else 0.0
                    elif p[0] == 'U':
                        print('U,' + boot_id)
                    elif p[0] == '?':
                        for k in CFG:
                            print('K,' + k + ',' + str(CFG[k]))
                except Exception:
                    pass

            # --- Fernbedienung
            rc_pan = rc_tilt = 0.0
            rc_fire = False
            d = rc_module.rc_slave_data() if (rc_ok and CFG['rc_en']) else None
            rc_live = bool(d) and any(d)
            if rc_live:
                rc_seen = now
                rc_pan = dz(d[CFG['rc_pan']] - RC_CENTER) * CFG['rc_pan_sign']
                rc_tilt = dz(d[CFG['rc_tilt']] - RC_CENTER) * CFG['rc_tilt_sign']
                rc_fire = bool(CFG['rc_fire_en']) and d[CFG['rc_fire']] == CFG['rc_pressed']
                if rc_pan or rc_tilt or rc_fire:
                    rc_t = now

            # --- Quelle wählen
            pan = 0
            want_fire = False
            if time.ticks_diff(now, rc_t) < CFG['rc_hold_ms']:
                src = 'rc'
                pan = int(rc_pan * CFG['pan_max'])
                tilt += rc_tilt * CFG['tilt_rc_rate'] * dt
                want_fire = rc_fire
                cmd_dtilt = 0.0
            elif time.ticks_diff(now, cmd_t) < CFG['cmd_timeout_ms']:
                src = 'coral'
                pan = int(clamp(cmd_pan, -CFG['pan_max'], CFG['pan_max']))
                tilt += cmd_dtilt
                cmd_dtilt = 0.0
                want_fire = cmd_fire
            else:
                src = 'idle'
                cmd_dtilt = 0.0

            # --- Drehbereich begrenzen (Koppelnavigation)
            lim = CFG['pan_limit']
            if lim and ((pan > 0 and pan_est >= lim) or (pan < 0 and pan_est <= -lim)):
                pan = 0
            # Das Servo dreht ab dem kleinsten Befehl sofort mit deg_s0 und wird dann nur wenig schneller
            if pan:
                v = CFG['deg_s0'] + abs(pan) / 100.0 * CFG['deg_s']
                pan_est += v * dt if pan > 0 else -v * dt
            if pan == 0:
                pan_servo.off()
            else:
                dead = CFG['pan_dead']
                out = pan * (100 - dead) / 100.0 + (dead if pan > 0 else -dead)
                pan_servo.speed(out, CFG['pan_trim_us'])

            tilt = clamp(tilt, CFG['tilt_min'], CFG['tilt_max'])

            # --- Abzug
            if not want_fire:
                fire_locked = False
                fire_start = None
            elif fire_start is None:
                fire_start = now
            elif time.ticks_diff(now, fire_start) > CFG['fire_max_ms']:
                fire_locked = True

            if not CFG['armed']:
                lo = min(CFG['trig_park'], CFG['trig_rest'])
                hi = max(CFG['trig_park'], CFG['trig_rest'])
                trig = CFG['trig_park'] if trig_test is None else clamp(trig_test, lo, hi)
            elif want_fire and not fire_locked:
                trig = CFG['trig_fire']
            else:
                trig = CFG['trig_rest']

            # --- Servos stellen; ungesichert nach längerer Ruhe stromlos (schont den Akku)
            pose = (int(tilt * 10), int(trig))
            if pose != held or CFG['armed'] or src != 'idle':
                held = pose
                held_t = now
            if CFG['idle_off_s'] and time.ticks_diff(now, held_t) > CFG['idle_off_s'] * 1000:
                tilt_servo.off()
                trig_servo.off()
            else:
                tilt_servo.angle(tilt)
                trig_servo.angle(trig)

            # --- Status
            if time.ticks_diff(now, stat_t) >= STATUS_MS:
                stat_t = now
                print('S,%s,%d,%d,%.1f,%d,%d,%d' % (
                    src, pan, int(pan_est), tilt, int(trig), CFG['armed'],
                    1 if time.ticks_diff(now, rc_seen) < 1000 else 0))
                if CFG['debug_rc'] and d:
                    print('R,' + ','.join(str(x) for x in d))

            time.sleep_ms(LOOP_MS)
    finally:
        pan_servo.off()
        trig_servo.angle(CFG['trig_park'])
        print('S,stopped')
