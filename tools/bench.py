#!/usr/bin/env python3
# Vergleicht die Modelle auf Testmaterial (Dienst vorher stoppen, die Edge TPU ist sonst belegt).
#   bench.py <ordner mit .mp4/.jpg> [modellfilter]
# Ausgabe je Modell: Anteil der Bilder mit Katze / Mensch, mittlere Sicherheit, ms je Bild.
import glob
import os
import sys
import time

import cv2

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'app'))
from detect import Detector

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


STEP = int(os.environ.get('STEP', 10))
CONF_CAT = float(os.environ.get('CONF_CAT', 0.35))


def frames(folder, step=STEP, limit=400 // STEP):
    out = []
    for p in sorted(glob.glob(os.path.join(folder, '*'))):
        if p.lower().endswith(('.jpg', '.jpeg', '.png')):
            img = cv2.imread(p)
            if img is not None:
                out.append((os.path.basename(p), img))
        elif p.lower().endswith('.mp4'):
            cap = cv2.VideoCapture(p)
            i = n = 0
            while n < limit:
                ok, img = cap.read()
                if not ok:
                    break
                if i % step == 0:
                    out.append((os.path.basename(p), img))
                    n += 1
                i += 1
            cap.release()
    return out


def main():
    fr = frames(sys.argv[1])
    flt = sys.argv[2] if len(sys.argv) > 2 else ''
    key = lambda n: n[4:19] if n.endswith('.mp4') else n
    groups = sorted(set(key(n) for n, _ in fr))
    print('%d Bilder, Gruppen: %s' % (len(fr), groups))
    for m in sorted(glob.glob(os.path.join(BASE, 'models', '*edgetpu*.tflite'))):
        if flt not in m:
            continue
        d = Detector()
        try:
            d.load(m)
        except Exception as e:
            print('%-52s FEHLER %s' % (os.path.basename(m), e))
            continue
        for clahe in (False, True):
            stat = {}
            t0 = time.time()
            for name, img in fr:
                g = key(name)
                st = stat.setdefault(g, {'n': 0, 'cat': 0, 'person': 0, 'cs': 0.0, 'ps': 0.0})
                st['n'] += 1
                dets = d.infer(img, {'cat': CONF_CAT, 'person': 0.45}, clahe)
                for lab, k in (('cat', 'cs'), ('person', 'ps')):
                    sc = [x[4] for x in dets if x[5] == lab]
                    if sc:
                        st[lab] += 1
                        st[k] += max(sc)
            ms = (time.time() - t0) * 1000 / max(len(fr), 1)
            parts = []
            for g, st in sorted(stat.items()):
                parts.append('%s[%d]: Katze %3.0f%% (%.2f) Mensch %3.0f%% (%.2f)' % (
                    g[9:15] if len(g) == 15 else g[:8], st['n'], 100.0 * st['cat'] / st['n'], st['cs'] / max(st['cat'], 1),
                    100.0 * st['person'] / st['n'], st['ps'] / max(st['person'], 1)))
            print('%-46s clahe=%d %5.1f ms (Netz %4.1f) | %s' % (
                os.path.basename(m).replace('_edgetpu.tflite', ''), clahe, ms, d.infer_ms, ' | '.join(parts)))


main()
