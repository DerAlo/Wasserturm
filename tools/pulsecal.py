#!/usr/bin/env python3
# Misst, wie weit ein kurzer Drehimpuls das Kamerabild verschiebt (Feinausrichtung).
#   pulsecal.py <pan%> <sekunden> [<sekunden> ...]
# Jeder Impuls wird nach rechts und links gefahren; Ausgabe: Verschiebung in Pixeln.
import asyncio
import json
import sys

import aiohttp
import cv2

from pancal import prep, frame


async def main():
    pan = float(sys.argv[1])
    win = None
    async with aiohttp.ClientSession() as s:
        async with s.ws_connect('http://localhost:8080/ws') as ws:
            for dur in [float(v) for v in sys.argv[2:]]:
                for sign in (1, -1):
                    fr = [await frame(ws, 15)]
                    await ws.send_str(json.dumps({'t': 'pulse', 'pan': pan * sign, 's': dur}))
                    loop = asyncio.get_event_loop()
                    t0 = loop.time()
                    while loop.time() - t0 < dur + 0.7:
                        try:
                            m = await ws.receive(timeout=0.03)
                        except asyncio.TimeoutError:
                            continue
                        if m.type == aiohttp.WSMsgType.BINARY:
                            fr.append(prep(m.data))
                    if win is None:
                        win = cv2.createHanningWindow((fr[0].shape[1], fr[0].shape[0]), cv2.CV_32F)
                    sx = sum(cv2.phaseCorrelate(p, q, win)[0][0] for p, q in zip(fr, fr[1:]))
                    print('pan %+3.0f %% %.3f s -> dx %+7.1f px  (%.0f px/s)' % (pan * sign, dur, sx, abs(sx) / dur))


asyncio.get_event_loop().run_until_complete(main())
