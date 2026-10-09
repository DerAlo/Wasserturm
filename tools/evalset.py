#!/usr/bin/env python3
# Trefferquote der Modelle auf beschrifteten Bildern (YOLO-Format, Klasse 0 = Katze, 1 = Mensch).
# Dienst vorher stoppen, die Edge TPU ist sonst belegt.
#   evalset.py <ordner mit images/ und labels/> [modellfilter] [clahe 0|1]
# Ausgabe je Modell und Schwelle: gefunden / vorhanden (Trefferquote) und Fehlalarme.
import glob
import os
import sys

import cv2

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'app'))
from detect import Detector

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NAMES = {0: 'cat', 1: 'person'}
THRESH = (0.25, 0.35, 0.45)


def iou(a, b):
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    if w <= 0 or h <= 0:
        return 0.0
    i = w * h
    return i / ((a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - i)


def load(folder):
    data = []
    for p in sorted(glob.glob(os.path.join(folder, 'images', '*'))):
        img = cv2.imread(p)
        if img is None:
            continue
        h, w = img.shape[:2]
        gt = []
        lab = os.path.join(folder, 'labels', os.path.splitext(os.path.basename(p))[0] + '.txt')
        if os.path.exists(lab):
            for line in open(lab):
                v = line.split()
                if len(v) == 5 and int(v[0]) in NAMES:
                    cx, cy, bw, bh = [float(x) for x in v[1:]]
                    gt.append(((cx - bw / 2) * w, (cy - bh / 2) * h, (cx + bw / 2) * w, (cy + bh / 2) * h,
                               NAMES[int(v[0])]))
        data.append((img, gt))
    return data


def main():
    data = load(sys.argv[1])
    flt = sys.argv[2] if len(sys.argv) > 2 else ''
    clahe = len(sys.argv) > 3 and sys.argv[3] == '1'
    print('%s: %d Bilder, %d Katzen, %d Menschen, clahe=%d' % (
        os.path.basename(sys.argv[1].rstrip('/')), len(data),
        sum(g[4] == 'cat' for _, gt in data for g in gt),
        sum(g[4] == 'person' for _, gt in data for g in gt), clahe))
    for m in sorted(glob.glob(os.path.join(BASE, 'models', '*edgetpu*.tflite'))):
        if flt not in m:
            continue
        d = Detector()
        try:
            d.load(m)
        except Exception as e:
            print('%-40s FEHLER %s' % (os.path.basename(m), e))
            continue
        res = {(t, c): [0, 0, 0] for t in THRESH for c in NAMES.values()}     # gefunden, vorhanden, falsch
        ms = 0.0
        for img, gt in data:
            dets = d.infer(img, {'cat': THRESH[0], 'person': THRESH[0]}, clahe)
            ms += d.infer_ms
            for t in THRESH:
                for c in NAMES.values():
                    g = [x for x in gt if x[4] == c]
                    dd = [x for x in dets if x[5] == c and x[4] >= t]
                    used = set()
                    for x in g:
                        best = max(((iou(x, y), i) for i, y in enumerate(dd) if i not in used), default=(0, -1))
                        if best[0] >= 0.4:
                            used.add(best[1])
                    r = res[(t, c)]
                    r[0] += len(used)
                    r[1] += len(g)
                    r[2] += len(dd) - len(used)
        out = []
        for c in NAMES.values():
            out.append(c + ' ' + '  '.join('%.2f: %3.0f%% +%d' % (
                t, 100.0 * res[(t, c)][0] / max(res[(t, c)][1], 1), res[(t, c)][2]) for t in THRESH))
        print('%-36s %5.1f ms | %s' % (os.path.basename(m).replace('_edgetpu.tflite', '')[:36],
                                      ms / max(len(data), 1), ' | '.join(out)))


main()
