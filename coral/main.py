#!/usr/bin/env python3
# Wasserturm – Coral-Seite: Kamera -> Erkennung (Edge TPU) -> Regelung -> Core, dazu Web-UI.
# Start: python3 app/main.py   (Web-UI auf Port 8080)
import asyncio
import glob
import json
import logging
import os
import socket
import subprocess
import threading
import time

import cv2
import numpy as np
from aiohttp import web, WSMsgType

from bridge import CoreBridge
from camera import Camera
from detect import Detector
from settings import BY_KEY, SCHEMA, Settings
from tracker import Tracker

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODELS = os.path.join(BASE, 'models')
WEB = os.path.join(BASE, 'web')
PORT = 8080
MANUAL_TTL = 0.4
BEAT_MAX = 30.0                # s ohne Durchlauf der Erkennungsschleife -> Dienst gilt als hängend
MODES = {'off': 0, 'cat': 1, 'person': 2}

log = logging.getLogger('turret')


class App:
    def __init__(self):
        self.s = Settings(os.path.join(BASE, 'settings.json'))
        names = sorted(os.path.basename(p) for p in glob.glob(os.path.join(MODELS, '*edgetpu*.tflite')))
        BY_KEY['model']['opts'] = [[n, n.replace('_edgetpu', '').replace('.tflite', '')] for n in names]
        if self.s['model'] not in names and names:
            self.s['model'] = names[0]
        self.cam = Camera(self.s)
        self.det = Detector()
        self.bridge = CoreBridge(self.s)
        self.tracker = Tracker(self.s)
        self.clients = set()
        self.loop = None
        self.det_beat = time.time()
        self.manual = (0.0, 0.0, 0.0)
        self.last_fire = 0.0
        self.det_fps = 0.0
        self.blocked = False
        self.model_error = ''

    # ------------------------------------------------------------ Erkennung
    def load_model(self):
        name = self.s['model']
        try:
            self.det.load(os.path.join(MODELS, name))
            self.model_error = ''
            self.note('Model loaded: ' + name)
        except Exception as e:
            log.exception('Modell %s', name)
            self.model_error = str(e)
            self.note('Model %s cannot be loaded: %s' % (name, e))

    def det_loop(self):
        self.load_model()
        s = self.s
        seq, n, t0, last_stream, last_det = 0, 0, time.time(), 0.0, 0.0
        while True:
            self.det_beat = time.time()
            wait = last_det + 1.0 / s['det_fps_max'] - time.time()
            if wait > 0:
                time.sleep(wait)
            jpeg, seq = self.cam.get(seq)
            last_det = time.time()
            if jpeg is None:
                self.det_fps = 0.0
                continue
            try:
                frame = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
                if frame is None:
                    continue
                h, w = frame.shape[:2]
                dets = self.det.infer(frame, {'cat': s['conf_cat'], 'person': s['conf_person']}, s['clahe'])
                tr = self.tracker.update(dets, w, h)
            except Exception:
                log.exception('Erkennung')
                time.sleep(0.5)
                continue
            now = time.time()
            self.blocked = (s['target'] == 'cat' and s['protect_person']
                            and any(d[5] == 'person' for d in dets))
            if self.blocked:
                self.bridge.cease()
            elif (s['auto_fire'] and tr['fire_ready'] and self.bridge.armed
                  and now - self.last_fire >= s['cooldown_s']):
                self.last_fire = now
                self.bridge.fire(s['burst_ms'])
                self.note('Fired (automatic)')

            mp, mt, mtime = self.manual
            if now - mtime < MANUAL_TTL:
                self.bridge.set_motion(mp * s['man_pan'] * s['pan_sign'],
                                       mt * s['man_tilt'] * s['tilt_sign'], False, 0)
            elif tr['locked']:
                self.bridge.set_motion(tr['pan'], tr['tilt_rate'], False, MODES.get(s['target'], 0),
                                       tr['pan_s'])

            n += 1
            if now - t0 >= 1.0:
                self.det_fps = n / (now - t0)
                n, t0 = 0, now
            if self.clients and now - last_stream >= 1.0 / s['stream_fps']:
                last_stream = now
                # Angezeigt wird nur eine Erkennung: das verfolgte Ziel, sonst die sicherste im Bild
                if tr['idx'] >= 0:
                    show = [dets[tr['idx']]]
                else:
                    show = [max(dets, key=lambda d: d[4])] if dets else []
                meta = json.dumps({
                    't': 'f', 'w': w, 'h': h, 'idx': 0 if tr['idx'] >= 0 else -1, 'locked': tr['locked'],
                    'ready': tr['fire_ready'], 'aim': [round(tr['aim'][0]), round(tr['aim'][1])],
                    'n': len(dets),
                    'dets': [[round(d[0]), round(d[1]), round(d[2]), round(d[3]),
                              round(d[4], 2), d[5]] for d in show]})
                self.loop.call_soon_threadsafe(self.broadcast, meta, jpeg)

    # ---------------------------------------------------------------- Web
    def broadcast(self, text, binary=None):
        for q in self.clients:
            if binary is not None and q.qsize() > 3:
                continue                      # langsamer Client: Bild auslassen
            q.put_nowait((text, binary))

    def note(self, msg):
        log.info(msg)
        if self.loop:
            self.loop.call_soon_threadsafe(
                self.broadcast, json.dumps({'t': 'log', 'msg': time.strftime('%H:%M:%S ') + msg}))

    def status(self):
        b = self.bridge
        st = dict(b.status) if b.alive else {}
        try:
            temp = int(open('/sys/class/thermal/thermal_zone0/temp').read()) / 1000.0
        except (OSError, ValueError):
            temp = 0
        return {'t': 'status', 'cam_ok': self.cam.ok, 'cam_fps': round(self.cam.fps, 1),
                'cam_dev': self.cam.device, 'det_fps': round(self.det_fps, 1),
                'infer_ms': round(self.det.infer_ms, 1), 'kind': self.det.kind,
                'model_error': self.model_error, 'core': b.alive, 'armed': b.armed,
                'firing': b.firing, 'blocked': self.blocked, 'temp': round(temp, 1),
                'rc_raw': b.rc_raw if self.s['core.debug_rc'] else None, 'core_status': st}

    async def status_task(self):
        while True:
            await asyncio.sleep(0.25)
            if self.clients:
                self.broadcast(json.dumps(self.status()))

    async def ws(self, req):
        ws = web.WebSocketResponse(heartbeat=20)
        await ws.prepare(req)
        q = asyncio.Queue()
        q.put_nowait((json.dumps({'t': 'hello', 'schema': SCHEMA, 'settings': dict(self.s)}), None))
        self.clients.add(q)

        async def writer():
            while True:
                text, binary = await q.get()
                await ws.send_str(text)
                if binary is not None:
                    await ws.send_bytes(binary)
        task = asyncio.ensure_future(writer())
        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    try:
                        self.on_msg(json.loads(msg.data))
                    except Exception as e:
                        log.exception('Nachricht %s', msg.data)
                        self.note('Error: %s' % e)
        finally:
            self.clients.discard(q)
            task.cancel()
            self.manual = (0.0, 0.0, 0.0)
        return ws

    def on_msg(self, m):
        t = m.get('t')
        if t == 'manual':
            self.manual = (max(-1.0, min(1.0, float(m.get('pan', 0)))),
                           max(-1.0, min(1.0, float(m.get('tilt', 0)))), time.time())
            s = self.s                    # sofort senden, auch wenn gerade kein Kamerabild kommt
            self.bridge.set_motion(self.manual[0] * s['man_pan'] * s['pan_sign'],
                                   self.manual[1] * s['man_tilt'] * s['tilt_sign'], False, 0)
        elif t == 'pulse':                # kurzer Drehimpuls (tools/pulsecal.py)
            self.bridge.set_motion(max(-20.0, min(20.0, float(m.get('pan', 0)))), 0.0, False, 0,
                                   max(0.0, min(0.35, float(m.get('s', 0)))))
        elif t == 'set':
            self.apply(m['k'], m['v'])
        elif t == 'cmd':
            self.command(m.get('c'), m.get('v'))

    def apply(self, key, value):
        self.s.set(key, value)
        if key.startswith('core.'):
            self.bridge.set_param(key[5:], self.s.core_value(key))
        elif key in ('cam.device', 'cam.res', 'cam.fps'):
            self.cam.restart()
        elif key.startswith('cam.'):
            threading.Thread(target=self.cam.apply_controls, daemon=True).start()
        elif key == 'model':
            threading.Thread(target=self.load_model, daemon=True).start()
        elif key == 'target':
            self.tracker.reset()
        self.broadcast(json.dumps({'t': 'settings', 'settings': dict(self.s)}))

    def command(self, c, v):
        b = self.bridge
        if c == 'arm':
            b.cease()
            b.set_param('armed', 1 if v else 0)
            self.note('Armed' if v else 'Safe')
        elif c == 'stop':
            b.cease()
            b.set_param('armed', 0)
            self.apply('target', 'off')
            self.note('Stop: safe, target off')
        elif c == 'fire':
            if b.armed:
                b.fire(self.s['burst_ms'])
                self.note('Fired (manual)')
            else:
                self.note('Not armed – no shot')
        elif c == 'tilt_home':
            b.send('X,%s' % self.s['core.tilt_home'])
        elif c == 'pan_zero':
            b.send('Z')
        elif c == 'trig' and not b.armed:
            b.send('T,%d' % int(v))       # ungesichert begrenzt der Core auf den Ruhebereich
        elif c == 'restart':
            subprocess.Popen(['sudo', '-n', 'systemctl', 'restart', 'turret'])

    async def index(self, req):
        return web.FileResponse(os.path.join(WEB, 'index.html'), headers={'Cache-Control': 'no-cache'})

    async def on_startup(self, app):
        self.loop = asyncio.get_event_loop()
        self.bridge.on_ready = lambda: self.note('Core restarted – safe')
        self.cam.start()
        self.bridge.start()
        threading.Thread(target=self.det_loop, daemon=True).start()
        asyncio.ensure_future(self.status_task())
        asyncio.ensure_future(self.watchdog_task())

    async def health(self, req):
        age = time.time() - self.det_beat
        ok = age < BEAT_MAX
        return web.json_response(dict(self.status(), ok=ok, det_age=round(age, 1)), status=200 if ok else 503)

    async def watchdog_task(self):
        """Meldet systemd, dass Web-Schleife und Erkennungsschleife leben (WatchdogSec im Dienst).
        Bleibt die Meldung aus (z. B. Edge TPU hängt), startet systemd den Dienst neu."""
        warned = False
        while True:
            await asyncio.sleep(5)
            if time.time() - self.det_beat < BEAT_MAX:
                sd_notify('WATCHDOG=1')
                warned = False
            elif not warned:
                warned = True
                log.error('Erkennungsschleife steht seit %.0f s – systemd startet den Dienst neu',
                          time.time() - self.det_beat)


def sd_notify(msg):
    addr = os.environ.get('NOTIFY_SOCKET')
    if not addr:
        return
    if addr[0] == '@':
        addr = '\0' + addr[1:]
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
            sock.sendto(msg.encode(), addr)
    except OSError:
        pass


def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(name)s %(levelname)s %(message)s')
    a = App()
    app = web.Application()
    app.on_startup.append(a.on_startup)
    app.router.add_get('/', a.index)
    app.router.add_get('/ws', a.ws)
    app.router.add_get('/health', a.health)
    app.router.add_static('/', WEB)

    # Browser sollen app.js/style.css nach einem Update nicht aus dem Zwischenspeicher nehmen
    async def no_cache(req, resp):
        resp.headers.setdefault('Cache-Control', 'no-cache')
    app.on_response_prepare.append(no_cache)
    loop = asyncio.get_event_loop()
    runner = web.AppRunner(app, access_log_format='%a "%r" %s %Tfs')
    loop.run_until_complete(runner.setup())
    for port in (PORT, 80):                   # 80 zusätzlich, damit die Adresse ohne :8080 geht
        try:
            loop.run_until_complete(web.TCPSite(runner, '0.0.0.0', port).start())
            log.info('Web-UI auf Port %d', port)
        except OSError as e:
            log.warning('Port %d nicht verfügbar: %s', port, e)
    loop.run_forever()


if __name__ == '__main__':
    main()
