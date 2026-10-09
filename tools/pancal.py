#!/usr/bin/env python3
# Misst über die laufende App, wie weit sich das Kamerabild je Fahrbefehl verschiebt.
#   pancal.py pan|tilt <dauer_s> <wert> [<wert> ...]     wert = -1..1 (Anteil von man_pan / man_tilt)
# Jeder Wert wird hin und zurück gefahren; Ausgabe: Bildverschiebung in Pixeln (dx, dy).
import asyncio
import json
import sys

import aiohttp
import cv2
import numpy as np

CLAHE = cv2.createCLAHE(3.0, (8, 8))


def prep(jpeg):
    g = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_GRAYSCALE)
    g = CLAHE.apply(g[:300])               # unten blendet der Lauf
    return np.float32(cv2.GaussianBlur(g, (5, 5), 0))


async def frame(ws, n=4):
    """n-tes Bild ab jetzt (ältere im Puffer überspringen)."""
    got = None
    while n > 0:
        m = await ws.receive(timeout=5)
        if m.type == aiohttp.WSMsgType.BINARY:
            got = m.data
            n -= 1
    return prep(got)


async def drive(ws, axis, val, dur):
    loop = asyncio.get_event_loop()
    t0 = loop.time()
    msg = json.dumps({'t': 'manual', 'pan': val if axis == 'pan' else 0, 'tilt': val if axis == 'tilt' else 0})
    frames, sent, stopped = [], 0.0, False
    while loop.time() - t0 < dur + 0.8:           # Nachlauf mitmessen
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
            frames.append(prep(m.data))
    return frames


async def main():
    axis, dur = sys.argv[1], float(sys.argv[2])
    vals = [float(v) for v in sys.argv[3:]]
    win = None
    async with aiohttp.ClientSession() as s:
        async with s.ws_connect('http://localhost:8080/ws') as ws:
            for v in vals:
                for sign in (1, -1):
                    a = await frame(ws, 20)
                    fr = [a] + await drive(ws, axis, v * sign, dur)
                    if win is None:
                        win = cv2.createHanningWindow((a.shape[1], a.shape[0]), cv2.CV_32F)
                    sx = sy = 0.0
                    worst = 1.0
                    for p, q in zip(fr, fr[1:]):       # Bild für Bild aufsummieren
                        (dx, dy), resp = cv2.phaseCorrelate(p, q, win)
                        sx += dx
                        sy += dy
                        worst = min(worst, resp)
                    print('%s %+.2f %.1fs -> dx %+7.1f dy %+7.1f  %5.0f px/s  (%d Bilder, Güte min %.2f)' % (
                        axis, v * sign, dur, sx, sy, (sx if axis == 'pan' else sy) / dur, len(fr), worst))


if __name__ == '__main__':
    asyncio.get_event_loop().run_until_complete(main())
