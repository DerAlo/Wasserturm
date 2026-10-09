# Kleine Turret – Wasserwerfer gegen Katzen/Menschen

Sprache: Deutsch. Bei Unklarheiten nachfragen.

## Regeln
- **Nie selbst schießen / scharf schalten** ohne ausdrückliche Erlaubnis (Wasserschaden). Tests nur
  ungesichert; Abzug-Servo nur zwischen „gesichert“ (90°) und „wartend“ (20°), nie Richtung 0°.
- **Core NIE mit Fremdtools flashen** (laut Hersteller dauerhaft kaputt), nur Dateien kopieren (mpremote).
- Keine SSD-Modelle wieder in `models/` legen (gelöscht), siehe „Bekannte Probleme“.
- `tools/mp` auf dem Coral nie ohne Argumente und nie ohne `timeout` aufrufen (hängt sonst endlos).

## Ziel
Umgebauter MakerWorld „Remote Controlled Water Turret“ (CyberBrick, Assembly V1.5) sichert einen
Durchgang. Ziel wählbar: **Aus / Katze / Mensch**, Umschalten im Web-UI auf dem Coral.
Original-Fernbedienung soll weiter gehen. Akkus sollen später raus, alles über Netzteil.

## Hardware (Ist)
- CyberBrick Core (ESP32-C3, MicroPython) + Receiver Shield X11 im drehenden Teil.
  - **S1 / GPIO3 = Drehen** (360°-Servo, keine Positionsrückmeldung)
  - **S2 / GPIO2 = Neigen** (größerer Winkel = Kamera schaut höher; ~1,8 Bildpunkte je Servograd)
  - **S3 / GPIO1 = Abzug** (90° gesichert/geparkt, 20° scharf-wartend, 0° Schuss)
  - Der Schalter zwischen Akku und Core muss an sein, sonst bewegen sich die Servos kaum.
- Coral Dev Board 4 GB (Mendel, Python 3.7, pycoral, OpenCV 3.2, aiohttp 3.8).
  - `ssh mendel@192.168.178.110` (Schlüssel-Login, `sudo -n` geht). Keine Echtzeituhr, Journal flüchtig.
  - USB-A: IR-Kamera („HD USB Camera“, `/dev/video1`, MJPEG 640x480, ~99 B/s; `/dev/video0` ist die
    Board-CSI-Schnittstelle).
  - USB-C: Core als `/dev/ttyACM0`. Dafür muss der Port auf Host-Rolle stehen
    (`deploy/usb-host-role.service`).
- Kamera sitzt mit Kabelbindern auf dem Lauf; die Pistole reflektiert viel IR (heller Fleck unten im
  Bild) – Kamera soll noch umgesetzt werden (höher winkeln oder näher zur Mündung).
- Tank ist undicht (Ursache offen).

## Software
| Ort | Inhalt |
|---|---|
| `turret_main.py` | Core-Firmware -> Core `/app/turret_main.py`. `boot.py` -> Core `/` (Datei `/turret_off` auf dem Core = Original-RC-Firmware). `core_backup/` = Originalzustand des Core. |
| `coral/` | App -> Coral `~/turret/app/`: `camera.py` (ffmpeg MJPEG), `detect.py` (Edge TPU, YOLO), `tracker.py` (Zielwahl, Regelung), `bridge.py` (Serial zum Core, 20 Hz), `settings.py` (Schema aller Einstellungen), `main.py` (aiohttp, Port 8080, WebSocket `/ws`). |
| `web/` | Web-UI -> `~/turret/web/`. Einstellungen werden aus dem Schema gebaut. |
| `deploy/deploy.ps1` | Aufspielen und Dienst neu starten; mit `-Core` auch die Core-Firmware. |
| `tools/` | Liegen auch unter `~/turret/tools/` (siehe unten). |

- Web-UI: **http://192.168.178.110:8080** – Dienst `turret` (systemd, Autostart an).
- Einstellungen: `~/turret/settings.json` (entsteht erst beim ersten Ändern; ohne Datei gelten die
  Vorgaben aus `settings.py`). Schlüssel mit `core.` werden an den Core weitergereicht.
- Protokoll Coral -> Core: `C,<mode>,<pan%>,<dtilt°>,<fire>`, `K,<name>,<wert>`, `X,<winkel>`,
  `T,<winkel>` (nur ungesichert, begrenzt auf gesichert..wartend), `Z`, `?`.
  Core -> Coral alle 200 ms: `S,<src>,<pan%>,<pan_est>,<tilt>,<trig>,<armed>,<rc>`.
- WebSocket: Server `hello{schema,settings}`, `settings`, `f{…}` + JPEG, `status`, `log`;
  Client `{t:'set',k,v}`, `{t:'manual',pan,tilt}`, `{t:'pulse',pan,s}`,
  `{t:'cmd',c:'arm'|'stop'|'fire'|'tilt_home'|'pan_zero'|'trig'|'restart',v}`.

## Werkzeuge (auf dem Coral in `~/turret/tools/`)
- `probe.py [s] [bild|-] [json-befehle…]` – Status/Erkennungen mitlesen, Befehle schicken.
- `servotest.sh tilt|pan|trig` – jede Achse kurz bewegen (ungesichert, kein Schuss).
- `pancal.py pan|tilt <dauer> <wert…>` – Bildverschiebung je Fahrbefehl (px/s).
- `pulsecal.py <pan%> <s…>` – Bildverschiebung je kurzem Drehimpuls.
- `bench.py`, `evalset.py` – Modellvergleich (Dienst vorher stoppen, TPU sonst belegt).
  Testdaten: `~/turret/test/{media,cats,eval,snapshots_alt}`.
- `watch.sh <s>` – dmesg/Temperatur/Last mit sync nach `~/turret/test/watch.log`.

## Messwerte (07.10.2026)
- Dreh-Servo: Totbereich ±~17 % (wird am Core ausgeglichen, `core.pan_dead` 18), danach sofort
  ~220–250 px/s – langsamer geht nicht. Kleine Abweichungen fährt der Tracker deshalb mit kurzen
  Impulsen an (`pan_px_s`, `pan_pulse`); 30 ms ≈ 11–19 px, 100 ms ≈ 25–33 px.
  1 % ≈ 250 px/s, 6 % ≈ 340, 10 % ≈ 410 px/s. `core.pan_trim_us` −20 gleicht links/rechts an.
- `core.deg_s` (Grad/s bei 100 %, für die Kabel-Drehgrenze) ist geschätzt, nicht gemessen.
- Modelle (Edge TPU, Tageslicht-Testsatz, Schwelle 0,35): yolo26n 320 – 36 ms, Katzen 65 %;
  384 – 50 ms, 70 %; **448 – 65 ms, 80 % (Vorgabe, ~13 Erkennungen/s)**; 512 – 85 ms, 84 %.
  Menschen 84–97 %. Auf Wärmebild-Testdaten finden alle Modelle Katzen kaum (≤ 18 %); wie gut es
  mit dieser NIR-Kamera nachts klappt, ist noch nicht live geprüft.

## Bekannte Probleme / offen
- **Harter Neustart des Coral** binnen 2–70 s, wenn ein SSD-Modell (ssdlite_mobiledet,
  ssd_mobilenet) auf der TPU läuft, während die USB-Kamera streamt. Keine Kernelmeldung; Ursache
  unklar (Verdacht: Stromversorgung). YOLO-Modelle laufen stabil. SSD-Modelle sind gelöscht.
- **Core startet neu, wenn er nur am USB des Coral hängt** (Akku leer/ab): gemessen 08.10.2026,
  Kamera-Stream + TPU-Inferenz gleichzeitig -> Core-Reset alle paar Sekunden bis Minuten
  (jede Last einzeln: keiner). Meldung im Journal: `Core: MPY: soft_reset` / „Core neu gestartet“.
  Die App fängt das ab (Parameter neu, immer gesichert). Abhilfe ist Hardware: Core über X11
  versorgen (Akku bzw. Netzteil/Buck), Netzteil + Kabel des Coral prüfen. Firmware lässt deshalb
  die Servos nach dem Start stromlos, bis ein Befehl kommt (`core.idle_off_s`, 0 = immer halten).
- Härtung (08.10.2026, `deploy/harden.sh`, wiederholbar): Web-UI auf Port 80 **und** 8080,
  `/health`, systemd-Watchdog für die App (60 s), Hardware-Watchdog (30 s), `kernel.panic=10`,
  Journal persistent, WLAN-Stromsparen aus, Dienst `netwatch` (WLAN neu verbinden / Neustart),
  unnötige Dienste aus (weston, bluetooth, usb-gadget, unattended-upgrades, haveged).
  Der Coral selbst lief 9,4 h ohne Neustart, WLAN ohne Abbrüche.
- Mit vollem Akku am X11 (08.10.2026, 09:44): keine Core-Neustarts mehr. Coral-Netzteil und
  -Kabel stammen von der Quest 3.
- **Der Turm hat mechanische Anschläge**: gemessen 09.10.2026 mit `tools/turnstep.py` von Anschlag
  zu Anschlag 1250 Bildpunkte (laut Nutzer etwa 180°, also ~7 Bildpunkte/°, nicht nachgemessen).
  Volle 360° gehen nicht; am Anschlag blockiert das Servo, solange der Fahrbefehl anliegt.
  `core.pan_limit` steht seit 09.10.2026 auf **0 (aus)**: die Schätzung driftet im Impulsbetrieb
  binnen Minuten um zig Grad und sperrte dann mitten im Bereich eine Richtung – auch für die
  Fernbedienung (Nutzer: „Totpunkte“). Stattdessen erkennt der Tracker den Anschlag am Bild
  (5 Impulse ohne kleineren Fehler -> 3 s Pause in diese Richtung, `STALL_N`/`STALL_PAUSE`).
  Nicht wieder einschalten, solange es keine echte Positionsmessung gibt. Mitte finden: an einen
  Anschlag fahren, dann `turnstep.py <richtung> 10 0.3 625`, dann nullen – dabei Fernbedienung
  nicht benutzen (sie hat Vorrang und überstimmt die Fahrbefehle).
  Schätzung am Core: `core.deg_s0` 38 °/s sobald das Servo dreht + `core.deg_s` 260 °/s je 100 %
  (vorher 400 °/s·Anteil: lief um ein Mehrfaches falsch und sperrte dadurch scheinbar grundlos).
  Die Schätzung liegt in `~/turret/pan_est` und wird dem Core nach
  jedem Core-Neustart zurückgegeben (`U` = Start-Kennung, `Z,<grad>`). Sie ist nur Koppelnavigation
  (`core.deg_s` geschätzt) – von Hand verdrehen oder Drift bemerkt sie nicht.
- `tools/probe.py` sendet Befehle erst nach 1 s: Dauer mindestens 3 s angeben.
- Live-Test mit echter Katze/Person vor der Kamera und geschlossener Regelkreis stehen aus.
- Fernbedienung: Kanäle nicht kalibriert (`core.debug_rc`), `rc_fire_en` ist aus.
- Geplant: 12-V-Netzteil -> Sicherung 5 A -> Buck 8,0 V -> X11 und Pistole; Coral eigenes
  5-V/3-A-Netzteil; Drehbereich per Software begrenzt (Kabel); Wetterschutz, Tank abdichten.

- Kamera wurde höher gewinkelt (sieht den Lauf gerade nicht mehr). Deshalb `core.tilt_home` 88 und
  `aim_x` −3 / `aim_y` 16 (09.10.2026 nach Testschuss des Nutzers, Treffer bei Bildpunkt ca. 300/318, auf den Treffpunkt gesetzt, gilt für
  diese Entfernung; Schuss über das Web-Protokoll danach vom Nutzer als Treffer bestätigt). Nachstellen: Doppelklick ins Bild im
  Web-UI setzt `aim_x`/`aim_y` auf die Stelle, die der Strahl trifft.
- 08.10.2026, 13:18 UTC: Kamera fiel vom USB (`usb 1-1: USB disconnect`), danach meldete der Kernel
  dauernd `failed to scale arm_reg up: -11` (füllte das Journal). Neustart beseitigt die
  Reglerfehler. Die Kamera blieb weg, bis sie am 09.10. neu eingesteckt wurde (danach stabil
  ~99 B/s) -> Wackelkontakt an Stecker/Kabel, bei Ausfall zuerst dort prüfen. Kernelprotokoll: `~/turret/test/kernel_2026-10-08_1318_kamera_weg.log`.
- Tracker seit 09.10.2026: verfolgt und zeigt nur noch **eine** Erkennung (die sicherste der
  gewählten Zielklasse, bisheriges Ziel +0,1 Bonus; ohne Ziel wird die sicherste im Bild gezeigt,
  `n` im Bild-Telegramm = Anzahl aller). Drehen: ein Impuls wird zu Ende gefahren, danach
  `pan_settle` (0,2 s) Pause, erst dann zählt wieder ein Bild; keine Glättung mehr beim Drehen;
  Totzone wächst mit der Boxbreite (`dead_box`). Wirkung auf das Pendeln noch nicht live bewertet.
- `/health` meldet „ok“, auch wenn die Kamera fehlt (`cam_ok` false) – noch nicht behoben.

- Repos seit 09.10.2026: **öffentlich** https://github.com/DerAlo/Wasserturm (Remote `origin`,
  Zweig `main`, Verlauf beginnt neu ohne `core_backup/`; Commits dort mit der GitHub-noreply-Adresse,
  nicht mit der privaten Mail). **Privat** https://github.com/DerAlo/Wasserturm-privat (Remote
  `archiv`, lokaler Zweig `v1-archiv`, Tag `v1`, enthält `core_backup/` und den alten Verlauf) –
  den Tag `v1` und `v1-archiv` nie nach `origin` pushen. `core_backup/` (Herstellerfirmware,
  Geräteprotokolle) liegt nur lokal und im Archiv, steht in `.gitignore`.
  Für MakerWorld gedacht: `README.md`, Web-UI-Texte und Meldungen der App sind deshalb **englisch** (Bezeichnungen
  in `coral/settings.py`, `web/`), Code-Kommentare und diese Datei deutsch. Vor dem Öffentlichmachen
  prüfen: `docs/webui.png` (Zimmer ist weichgezeichnet, nur die Box mit dem Nutzer scharf – so
  gewollt; die unverwischte erste Fassung wurde am 09.10.2026 aus dem Verlauf entfernt – nie ein
  Bild mit erkennbarem Zimmer committen), `core_backup/` ist Herstellerfirmware, diese
  Datei nennt IP/Host.
- `deploy.ps1 -Core` hatte bis 09.10.2026 einen Tippfehler (`cpturret_main.py`) und kopierte die
  Core-Firmware nicht; der Tag `v1` enthält ihn noch. Seit 09.10. (09:20 UTC) läuft auf dem Core
  wirklich die Firmware mit `deg_s0`. Nach `-Core` immer prüfen: `grep -c deg_s0` in der Datei auf dem Core.
- 09.10.2026: Kamera fiel wieder aus, als der Coral ein paar Zentimeter verschoben wurde
  (Wackelkontakt USB-A bzw. Kamerakabel, Nutzer prüft am Laptop).
- Bildschirmfoto des Web-UI: Headless-Chrome über das DevTools-Protokoll (Seite braucht echte Zeit
  für den WebSocket, `--screenshot` allein zeigt ein schwarzes Bild).

## Quellen
- CyberBrick API: https://makerworld.com/en/cyberbrick/api-doc/
- Offizieller RC-Code: https://github.com/CyberBrick-Official/CyberBrick_Controller_Core
- Coral Dev Board: https://gweb-coral-full.uc.r.appspot.com/docs/dev-board/datasheet/
