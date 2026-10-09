#!/usr/bin/env python3
# Dreht über die laufende App in kurzen Stücken, bis das Startbild wieder erscheint (= 360°),
# und misst dabei die Bildverschiebung. Läuft nie weiter als max_stuecke.
#   turnstep.py <richtung -1|1> [max_stuecke=16] [stueck_s=0.45] [ziel_px]
# Mit ziel_px: nur so weit drehen (z. B. vom Anschlag zur Mitte: 625).
# Ausgabe je Stück: Summe px und Vergleich mit dem Startbild. Die Drehgrenze ist währenddessen aus.
import asyncio
import json
import sys

import aiohttp
import cv2
import numpy as np

CLAHE = cv2.createCLAHE(3.0, (8, 8))
WIN = None
SRC = set()         # was der Core während eines Stücks als Befehlsquelle meldet


def prep(jpeg):
    g = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_GRAYSCALE)
    g = CLAHE.apply(g[:300])
    return np.float32(cv2.GaussianBlur(g, (5, 5), 0))


def shift(p, q):
    global WIN
    if WIN is None:
        WIN = cv2.createHanningWindow((p.shape[1], p.shape[0]), cv2.CV_32F)
    (dx, _), resp = cv2.phaseCorrelate(p, q, WIN)
    return dx, resp


async def still(ws, n=8):
    got = None
    while n > 0:
        m = await ws.receive(timeout=5)
        if m.type == aiohttp.WSMsgType.BINARY:
            got = m.data
            n -= 1
    return got


async def chunk(ws, val, dur):
    """Fährt dur Sekunden und sammelt die Bilder (ausgewertet wird erst danach)."""
    loop = asyncio.get_event_loop()
    t0 = loop.time()
    msg = json.dumps({'t': 'manual', 'pan': val, 'tilt': 0})
    frames, sent, stopped = [], 0.0, False
    while loop.time() - t0 < dur + 0.7:
        now = loop.time()
        if now - t0 < dur:
            if now - sent > 0.08:
                sent = now
                await ws.send_str(msg)
        elif not stopped:
            stopped = True
            await ws.send_str(json.dumps({'t': 'manual', 'pan': 0, 'tilt': 0}))
        try:
            m = await ws.receive(timeout=0.03)
        except asyncio.TimeoutError:
            continue
        if m.type == aiohttp.WSMsgType.BINARY:
            frames.append(m.data)
        elif m.type == aiohttp.WSMsgType.TEXT and '"status"' in m.data:
            c = json.loads(m.data).get('core_status') or {}
            SRC.add('%s%s' % (c.get('src'), '+rc' if c.get('rc') else ''))
            SRC.add('est %s' % c.get('pan_est'))
    return frames


async def main():
    val = float(sys.argv[1])
    max_n = int(sys.argv[2]) if len(sys.argv) > 2 else 16
    dur = float(sys.argv[3]) if len(sys.argv) > 3 else 0.45
    goal = float(sys.argv[4]) if len(sys.argv) > 4 else 0      # nach so vielen px aufhören
    async with aiohttp.ClientSession() as s:
        async with s.ws_connect('http://localhost:8080/ws') as ws:
            hello = json.loads((await ws.receive(timeout=5)).data)
            limit = hello['settings']['core.pan_limit']
            await ws.send_str(json.dumps({'t': 'set', 'k': 'core.pan_limit', 'v': 0}))
            try:
                j = await still(ws, 20)
                open('/tmp/turn_start.jpg', 'wb').write(j)
                a = prev = prep(j)
                acc = acc0 = 0.0
                stalled = 0
                for i in range(max_n):
                    worst = 1.0
                    for f in await chunk(ws, val, dur):
                        cur = prep(f)
                        dx, r = shift(prev, cur)
                        acc += dx
                        worst = min(worst, r)
                        prev = cur
                    j = await still(ws, 4)
                    prev2 = prep(j)
                    dx, r = shift(prev, prev2)
                    acc += dx
                    prev = prev2
                    d, resp = shift(a, prev)
                    print('%2d: summe %+7.0f px (Güte min %.2f)  zum Startbild %+6.0f px, Güte %.2f  %s'
                          % (i + 1, acc, worst, d, resp, ' '.join(sorted(SRC))))
                    SRC.clear()
                    # steht der Turm trotz Fahrbefehl, nicht weiter gegen den Anschlag drücken
                    stalled = stalled + 1 if abs(acc - acc0) < 10 else 0
                    acc0 = acc
                    if stalled >= 2:
                        print('steht -> Abbruch')
                        break
                    if goal and abs(acc) >= goal - 50:
                        print('Ziel erreicht')
                        break
                    if abs(acc) > 600 and resp > 0.25 and abs(d) < 200:
                        print('360° = %.0f px -> %.2f px/°' % (abs(acc - d), abs(acc - d) / 360))
                        break
                open('/tmp/turn_end.jpg', 'wb').write(j)
            finally:
                await ws.send_str(json.dumps({'t': 'manual', 'pan': 0, 'tilt': 0}))
                await ws.send_str(json.dumps({'t': 'set', 'k': 'core.pan_limit', 'v': limit}))
                await asyncio.sleep(0.3)


if __name__ == '__main__':
    asyncio.get_event_loop().run_until_complete(main())
