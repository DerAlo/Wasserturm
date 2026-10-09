# Zielauswahl und Regelung.
# Drehen ist ein 360°-Servo, also Geschwindigkeit (%); Neigen wird als Rate (°/s) ausgegeben.
# Fehler sind auf die halbe Bildbreite/-höhe normiert (-1..1).
import time


STICKY = 0.1        # Vorsprung des bisherigen Ziels bei der Auswahl (Anteil der Konfidenz)
PULSE_PX0 = 8       # so viele Bildpunkte dreht das Servo schon beim kürzesten Impuls
PULSE_MAX = 0.35    # längster Drehimpuls (s)
STALL_N = 5         # so viele Impulse ohne Wirkung = Anschlag
STALL_PAUSE = 3.0   # dann so lange nicht mehr in diese Richtung drehen (s)


def clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


class Tracker:
    def __init__(self, settings):
        self.s = settings
        self.block_dir = 0          # überlebt reset(): Richtung, in der der Anschlag erreicht ist
        self.block_until = 0.0
        self.reset()

    def reset(self):
        self.last = None            # (cx, cy) des letzten Ziels in Pixel
        self.last_t = 0.0
        self.seen = 0               # aufeinanderfolgende Bilder mit Ziel
        self.stable = 0             # aufeinanderfolgende Bilder im Schussfenster
        self.ex = self.ey = 0.0
        self.prev_ex = 0.0
        self.prev_t = 0.0
        self.pulse_pan = 0.0        # laufender Drehimpuls
        self.pulse_end = 0.0
        self.push_dir = 0           # Anschlagerkennung: Richtung, Zähler, Fehler beim ersten Impuls
        self.push_n = 0
        self.push_ex = 0.0

    def update(self, dets, w, h):
        """-> dict(idx, locked, pan, tilt_rate, fire_ready, ex, ey, aim)"""
        s = self.s
        now = time.time()
        aim = (w * (0.5 + s['aim_x'] / 100.0), h * (0.5 + s['aim_y'] / 100.0))
        out = {'idx': -1, 'locked': False, 'pan': 0.0, 'pan_s': None, 'tilt_rate': 0.0,
               'fire_ready': False, 'ex': 0.0, 'ey': 0.0, 'aim': aim}
        target = s['target']
        cands = [(i, d) for i, d in enumerate(dets) if d[5] == target]
        if target == 'off' or not cands:
            if now - self.last_t > s['lost_hold']:
                self.reset()
            self.stable = 0
            return out

        # Immer die sicherste Erkennung nehmen. Das bisherige Ziel bekommt einen kleinen Bonus,
        # damit die Wahl bei zwei fast gleich sicheren Kandidaten nicht von Bild zu Bild springt.
        def score(c):
            d = c[1]
            if self.last is not None and d[0] <= self.last[0] <= d[2] and d[1] <= self.last[1] <= d[3]:
                return d[4] + STICKY
            return d[4]
        idx, d = max(cands, key=score)
        px = (d[0] + d[2]) / 2
        py = d[1] + s['box_aim'] * (d[3] - d[1])
        self.last = ((d[0] + d[2]) / 2, (d[1] + d[3]) / 2)
        self.last_t = now
        self.seen += 1
        out['idx'] = idx

        ex = (px - aim[0]) / (w / 2.0)
        ey = (py - aim[1]) / (h / 2.0)
        # Geglättet wird nur die Neigung. Beim Drehen macht Glätten im Bild das Pendeln schlimmer
        # (der Fehler hinkt der eigenen Bewegung hinterher).
        a = clamp(s['smooth'], 0.0, 0.95) if self.seen > 1 else 0.0
        self.ex = ex
        self.ey = a * self.ey + (1 - a) * ey
        out['ex'], out['ey'] = self.ex, self.ey

        if self.seen < s['lock_frames']:
            self.prev_ex, self.prev_t = self.ex, now
            return out
        out['locked'] = True

        dead = s['deadzone'] / 100.0
        # Nahe, große Ziele: die Boxmitte zappelt mit der Boxbreite, die Totzone wächst deshalb mit.
        dead_x = max(dead, s['dead_box'] * (d[2] - d[0]) / (w / 2.0))
        dt = now - self.prev_t if self.prev_t else 0.0
        dex = (self.ex - self.prev_ex) / dt if 0.005 < dt < 0.5 else 0.0
        self.prev_ex, self.prev_t = self.ex, now

        if s['pan_px_s'] > 0 and now < self.pulse_end:
            # Impuls läuft noch: zu Ende fahren, nicht mit einem veralteten Bild neu starten
            out['pan'] = self.pulse_pan
            out['pan_s'] = self.pulse_end - now
        elif s['pan_px_s'] > 0 and now < self.pulse_end + s['pan_settle']:
            out['pan_s'] = 0.0      # warten, bis ein Bild von nach der Bewegung da ist
        elif abs(self.ex) <= dead_x:
            self.push_n = 0
        elif now < self.block_until and (self.ex > 0) == (self.block_dir > 0):
            pass                    # in diese Richtung kam der Turm eben nicht weiter (Anschlag)
        else:
            # Anschlag erkennen: mehrere Impulse in dieselbe Richtung, ohne dass der Fehler kleiner wird
            side = 1 if self.ex > 0 else -1
            if side == self.push_dir and abs(self.ex) > 0.8 * abs(self.push_ex):
                self.push_n += 1
            else:
                self.push_n = 0
                self.push_ex = self.ex
            self.push_dir = side
            if self.push_n >= STALL_N:
                self.push_n = 0
                self.block_dir, self.block_until = side, now + STALL_PAUSE
            pan = s['kp_pan'] * self.ex + s['kd_pan'] * dex
            pan = clamp(pan, -s['pan_track_max'], s['pan_track_max'])
            if 0 < abs(pan) < s['pan_min']:
                pan = s['pan_min'] if pan > 0 else -s['pan_min']
            if now < self.block_until and side == self.block_dir:
                pan = 0.0
            out['pan'] = pan * s['pan_sign']
            # Das Servo kann nicht langsamer als pan_px_s drehen: Fehler mit einem Impuls anfahren,
            # der nur einen Teil des Wegs zurücklegt.
            if pan and s['pan_px_s'] > 0:
                v = s['pan_px_s'] * (1 + 0.08 * abs(pan))
                px_go = s['pan_pulse'] * abs(self.ex) * (w / 2.0) - PULSE_PX0
                out['pan_s'] = clamp(px_go / v, 0.02, PULSE_MAX)
                self.pulse_pan = out['pan']
                self.pulse_end = now + out['pan_s']
        if abs(self.ey) > dead:
            rate = clamp(s['kp_tilt'] * self.ey, -s['tilt_rate_max'], s['tilt_rate_max'])
            out['tilt_rate'] = rate * s['tilt_sign']

        zone = s['fire_zone'] / 100.0
        if abs(self.ex) <= max(zone, dead_x) and abs(self.ey) <= zone:
            self.stable += 1
        else:
            self.stable = 0
        out['fire_ready'] = self.stable >= s['fire_frames']
        return out
