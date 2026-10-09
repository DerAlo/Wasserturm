# Serielle Verbindung zum CyberBrick Core (turret_main.py), Protokoll siehe dort.
# Eigener Thread: liest Statuszeilen, sendet Fahrbefehle mit 20 Hz und verbindet neu.
# Der Port wird mit Standard-DTR/RTS geöffnet, das löst am Core keinen Reset aus.
import logging
import os
import queue
import threading
import time

import serial

log = logging.getLogger('bridge')

SEND_HZ = 20.0
MOTION_TTL = 0.4        # s: älter -> Stopp


class CoreBridge(threading.Thread):
    def __init__(self, settings, port='/dev/ttyACM0'):
        threading.Thread.__init__(self, daemon=True)
        self.s = settings
        self.port = port
        self.connected = False
        self.status = {}            # letzte S-Zeile
        self.status_t = 0.0
        self.rc_raw = None
        self.core_cfg = {}          # vom Core bestätigte Parameter
        self.on_ready = None        # Callback nach (Neu-)Start des Core
        self._q = queue.Queue()
        self._motion = (0.0, 0.0, False, 0, 0.0)   # pan%, tilt °/s, fire, mode, Zeitstempel
        self._pan_end = None
        self._pan_cut = False       # Impulsende schon gesendet
        # Drehwinkel-Schätzung überlebt Neustarts des Core: Datei "<Start-Kennung des Core> <Grad>"
        self._pan_file = os.path.join(os.path.dirname(os.path.abspath(settings.path)), 'pan_est')
        self._core_id, self._pan_saved = '', 0
        try:
            with open(self._pan_file) as fh:
                a, b = fh.read().split()
                self._core_id, self._pan_saved = a, int(b)
        except (OSError, ValueError):
            pass
        self._pan_hold = float('inf')   # bis dahin Statuswerte nicht übernehmen
        self._pan_dirty = False
        self._pan_write_t = 0.0
        self._was_active = False
        self._fire_until = 0.0
        self._run = True

    # ------------------------------------------------------------ Schnittstelle
    def set_motion(self, pan, tilt_rate, fire=False, mode=0, pan_s=None):
        """pan_s: Drehen nur so viele Sekunden lang (Impuls), None = solange der Befehl gilt."""
        now = time.time()
        self._pan_end = now + pan_s if pan_s is not None else None
        self._motion = (pan, tilt_rate, fire, mode, now)

    def send(self, line):
        self._q.put(line)

    def set_param(self, name, value):
        self.send('K,%s,%s' % (name, value))

    def push_params(self):
        """Alle Core-Parameter übertragen. Scharf wird dabei immer zurückgenommen."""
        self.set_param('armed', 0)
        for k, v in self.s.items():
            if k.startswith('core.'):
                self.set_param(k[5:], self.s.core_value(k))
        self._pan_hold = float('inf')
        self.send('U')                  # Antwort U,<Kennung> -> ggf. Drehwinkel zurückgeben

    def _pan_write(self):
        self._pan_dirty = False
        self._pan_write_t = time.time()
        try:
            with open(self._pan_file + '.tmp', 'w') as fh:
                fh.write('%s %d\n' % (self._core_id, self._pan_saved))
            os.replace(self._pan_file + '.tmp', self._pan_file)
        except OSError as e:
            log.warning('Drehwinkel nicht gespeichert: %s', e)

    def fire(self, ms):
        """Schuss für ms Millisekunden anfordern. Der Core schießt nur, wenn er scharf ist."""
        self._fire_until = time.time() + ms / 1000.0

    def cease(self):
        self._fire_until = 0.0

    @property
    def firing(self):
        return time.time() < self._fire_until

    def stop(self):
        self._run = False

    @property
    def armed(self):
        return bool(self.status.get('armed')) and self.alive

    @property
    def alive(self):
        return self.connected and time.time() - self.status_t < 1.5

    # ------------------------------------------------------------------ Thread
    def run(self):
        while self._run:
            if not os.path.exists(self.port):
                time.sleep(1)
                continue
            try:
                ser = serial.Serial(self.port, 115200, timeout=0, write_timeout=0.5)
            except (serial.SerialException, OSError) as e:
                log.warning('Core nicht erreichbar: %s', e)
                time.sleep(2)
                continue
            log.info('Core verbunden (%s)', self.port)
            self.connected = True
            self.push_params()
            try:
                self._loop(ser)
            except (serial.SerialException, OSError) as e:
                log.warning('Verbindung zum Core verloren: %s', e)
            self.connected = False
            try:
                ser.close()
            except Exception:
                pass
            time.sleep(1)

    def _loop(self, ser):
        buf = b''
        last = time.time()
        while self._run:
            data = ser.read(4096)
            if data:
                buf += data
                while b'\n' in buf:
                    line, buf = buf.split(b'\n', 1)
                    self._parse(line.decode('ascii', 'replace').strip())
                if len(buf) > 4096:
                    buf = b''
            out = []
            while not self._q.empty():
                out.append(self._q.get_nowait())
            now = time.time()
            end = self._pan_end
            cut = end is not None and now >= end
            if now - last >= 1.0 / SEND_HZ or cut != self._pan_cut:     # Impulsanfang/-ende sofort senden
                self._pan_cut = cut
                dt, last = now - last, now
                pan, rate, fire, mode, t = self._motion
                if cut:
                    pan = 0.0
                fresh = now - t < MOTION_TTL
                firing = now < self._fire_until
                if fresh or firing:
                    if not fresh:
                        pan = rate = 0.0
                    out.append('C,%d,%d,%.2f,%d' % (mode, round(pan), rate * dt,
                                                    1 if (firing or (fresh and fire)) else 0))
                    self._was_active = True
                elif self._was_active:
                    out.append('C,0,0,0,0')
                    self._was_active = False
            if out:
                ser.write(('\n'.join(out) + '\n').encode('ascii'))
            time.sleep(0.005)

    def _parse(self, line):
        p = line.split(',')
        try:
            if p[0] == 'S' and len(p) == 8:
                self.status = {'src': p[1], 'pan': int(p[2]), 'pan_est': int(p[3]),
                               'tilt': float(p[4]), 'trig': int(p[5]),
                               'armed': int(p[6]), 'rc': int(p[7])}
                self.status_t = now = time.time()
                if now > self._pan_hold and self.status['pan_est'] != self._pan_saved:
                    self._pan_saved = self.status['pan_est']
                    self._pan_dirty = True
                if self._pan_dirty and now - self._pan_write_t > 1.0:
                    self._pan_write()
            elif p[0] == 'U' and len(p) == 2:
                if p[1] != self._core_id:       # Core ist neu gestartet und zählt wieder ab 0
                    self._core_id = p[1]
                    self.send('Z,%d' % self._pan_saved)
                    log.info('Drehwinkel %d° an den Core zurückgegeben', self._pan_saved)
                    self._pan_write()
                self._pan_hold = time.time() + 1.0
            elif p[0] == 'S' and len(p) == 2 and p[1] == 'ready':
                log.info('Core neu gestartet, übertrage Parameter')
                self.push_params()
                if self.on_ready:
                    self.on_ready()
            elif p[0] == 'K' and len(p) == 3:
                self.core_cfg[p[1]] = float(p[2])
            elif p[0] == 'R':
                self.rc_raw = [int(x) for x in p[1:]]
            elif line:
                log.info('Core: %s', line[:120])    # Startmeldungen, Fehlerausgaben
        except ValueError:
            pass
