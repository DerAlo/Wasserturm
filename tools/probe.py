#!/usr/bin/env python3
# Prüft die laufende App über den WebSocket: Status, Erkennungen, optional Befehle.
#   probe.py [sekunden] [bild.jpg] ['{"t":"cmd",...}' ...]
# Befehle werden nach 1 s der Reihe nach im Abstand von 0,1 s gesendet.
import asyncio
import json
import sys

import aiohttp


async def main():
    secs = float(sys.argv[1]) if len(sys.argv) > 1 else 3
    out = sys.argv[2] if len(sys.argv) > 2 and sys.argv[2] != '-' else None
    cmds = sys.argv[3:]
    frames, labels, last, logs, cs = 0, {}, None, [], []
    loop = asyncio.get_event_loop()
    t0 = loop.time()
    async with aiohttp.ClientSession() as s:
        async with s.ws_connect('http://localhost:8080/ws') as ws:
            sent = 0
            while loop.time() - t0 < secs:
                if sent < len(cmds) and loop.time() - t0 > 1 + 0.1 * sent:
                    await ws.send_str(cmds[sent])
                    sent += 1
                try:
                    m = await ws.receive(timeout=0.1)
                except asyncio.TimeoutError:
                    continue
                if m.type == aiohttp.WSMsgType.TEXT:
                    d = json.loads(m.data)
                    if d['t'] == 'f':
                        frames += 1
                        for x in d['dets']:
                            labels[x[5]] = labels.get(x[5], 0) + 1
                        meta = d
                    elif d['t'] == 'status':
                        last = d
                        c = d.get('core_status')
                        if c and (not cs or cs[-1] != c):
                            cs.append(c)
                    elif d['t'] == 'log':
                        logs.append(d['msg'])
                    elif d['t'] == 'hello':
                        print('schema', len(d['schema']), 'settings', len(d['settings']))
                elif m.type == aiohttp.WSMsgType.BINARY and out:
                    open(out, 'wb').write(m.data)
    print('frames %d in %.1fs, Treffer je Bild: %s' % (
        frames, secs, {k: round(v / max(frames, 1), 2) for k, v in labels.items()}))
    if frames:
        print('letztes Bild:', meta)
    print('status:', last)
    print('core-Verlauf:', cs[:40])
    print('log:', logs)


asyncio.get_event_loop().run_until_complete(main())
