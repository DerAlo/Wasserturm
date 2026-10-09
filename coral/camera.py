# USB-Kamera über ffmpeg (MJPEG wird durchgereicht, kein Umkodieren).
# Liefert immer nur das neueste Bild; startet ffmpeg neu, wenn 3 s nichts kommt.
import glob
import logging
import os
import select
import subprocess
import threading
import time

log = logging.getLogger('camera')

V4L2_CTRLS = ('brightness', 'contrast', 'gain')


def find_device():
    """Erste USB-Kamera (nicht die interne CSI-Schnittstelle des Boards)."""
    for d in sorted(glob.glob('/sys/class/video4linux/video*')):
        try:
            name = open(d + '/name').read()
            idx = open(d + '/index').read().strip()
        except OSError:
            continue
        if 'csi' in name.lower() or idx != '0':
            continue
        return '/dev/' + os.path.basename(d)
    return None


class Camera(threading.Thread):
    def __init__(self, settings):
        threading.Thread.__init__(self, daemon=True)
        self.s = settings
        self.cond = threading.Condition()
        self.jpeg = None
        self.seq = 0
        self.fps = 0.0
        self.ok = False
        self.device = None
        self.size = (640, 480)
        self._proc = None
        self._restart = False
        self._run = True

    def restart(self):
        self._restart = True

    def stop(self):
        self._run = False
        self._kill()

    def get(self, last_seq, timeout=1.0):
        """Wartet auf ein Bild, das neuer ist als last_seq. -> (jpeg, seq) oder (None, last_seq)"""
        with self.cond:
            if self.seq == last_seq:
                self.cond.wait(timeout)
            if self.seq == last_seq:
                return None, last_seq
            return self.jpeg, self.seq

    def apply_controls(self):
        dev = self.device
        if not dev:
            return
        s = self.s
        ctrls = ['exposure_auto=%d' % (3 if s['cam.exposure_auto'] else 1)]
        if not s['cam.exposure_auto']:
            ctrls.append('exposure_absolute=%d' % s['cam.exposure'])
        ctrls += ['%s=%d' % (c, s['cam.' + c]) for c in V4L2_CTRLS]
        for c in ctrls:
            subprocess.call(['v4l2-ctl', '-d', dev, '-c', c],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def _kill(self):
        p, self._proc = self._proc, None
        if p:
            try:
                p.kill()
                p.wait(timeout=2)
            except Exception:
                pass

    def _start(self):
        dev = self.s['cam.device']
        if dev == 'auto':
            dev = find_device()
        if not dev or not os.path.exists(dev):
            return False
        self.device = dev
        w, h = [int(v) for v in self.s['cam.res'].split('x')]
        self.size = (w, h)
        cmd = ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-f', 'v4l2',
               '-input_format', 'mjpeg', '-video_size', '%dx%d' % (w, h),
               '-framerate', str(self.s['cam.fps']), '-i', dev,
               '-c:v', 'copy', '-f', 'image2pipe', 'pipe:1']
        self._proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)
        log.info('Kamera %s %dx%d@%d gestartet', dev, w, h, self.s['cam.fps'])
        self.apply_controls()
        return True

    def run(self):
        while self._run:
            self._restart = False
            try:
                if not self._start():
                    self.ok = False
                    time.sleep(2)
                    continue
                self._read()
            except Exception:
                log.exception('Kamerafehler')
            self.ok = False
            self._kill()
            time.sleep(1)

    def _read(self):
        fd = self._proc.stdout.fileno()
        buf = b''
        n, t0 = 0, time.time()
        while self._run and not self._restart:
            r, _, _ = select.select([fd], [], [], 3.0)
            if not r:
                log.warning('Kamera liefert keine Bilder, Neustart')
                return
            chunk = os.read(fd, 131072)
            if not chunk:
                log.warning('ffmpeg beendet')
                return
            buf += chunk
            while True:
                a = buf.find(b'\xff\xd8')
                if a < 0:
                    buf = b''
                    break
                b = buf.find(b'\xff\xd9', a + 2)
                if b < 0:
                    buf = buf[a:]
                    break
                frame, buf = buf[a:b + 2], buf[b + 2:]
                with self.cond:
                    self.jpeg = frame
                    self.seq += 1
                    self.cond.notify_all()
                self.ok = True
                n += 1
            now = time.time()
            if now - t0 >= 1.0:
                self.fps = n / (now - t0)
                n, t0 = 0, now
