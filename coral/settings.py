# Alle Einstellungen an einer Stelle: Schema (für das Web-UI) + Speicherung in settings.json.
# Schlüssel mit "core." werden zusätzlich als K-Befehl an den Core geschickt,
# Schlüssel mit "cam." betreffen die Kamera.
# Bezeichnungen und Hinweise erscheinen im Web-UI und sind deshalb englisch.
import json
import logging
import os
import threading

log = logging.getLogger('settings')

SCHEMA = []


def F(sec, key, label, typ, default, lo=None, hi=None, step=None, opts=None, hint=''):
    SCHEMA.append({'sec': sec, 'key': key, 'label': label, 'type': typ, 'default': default,
                   'min': lo, 'max': hi, 'step': step, 'opts': opts, 'hint': hint})


SIGN = [[1, 'normal'], [-1, 'reversed']]

S = 'Operation'
F(S, 'target', 'Target', 'select', 'off',
  opts=[['off', 'Off (remote control / manual only)'], ['cat', 'Cat'], ['person', 'Person']])
F(S, 'auto_fire', 'Fire automatically', 'bool', False,
  hint='Only has an effect while "Armed" is switched on as well.')
F(S, 'protect_person', 'Do not fire while a person is in view', 'bool', True,
  hint='Applies to the target "Cat".')
F(S, 'man_pan', 'Manual: pan speed (%)', 'num', 10, 1, 100, 1)
F(S, 'man_tilt', 'Manual: tilt (°/s)', 'num', 120, 5, 180, 1)

S = 'Detection'
F(S, 'model', 'Model', 'select', 'yolo26n_448_int8_edgetpu.tflite', opts=[],
  hint='Larger = finds more, but slower: 320 ≈ 23 frames/s, 384 ≈ 17, 448 ≈ 12, 512 ≈ 10.')
F(S, 'det_fps_max', 'Detection: frames/s at most', 'num', 30, 2, 60, 1)
F(S, 'conf_cat', 'Threshold cat', 'num', 0.35, 0.05, 0.95, 0.01)
F(S, 'conf_person', 'Threshold person', 'num', 0.45, 0.05, 0.95, 0.01)
F(S, 'clahe', 'Contrast enhancement (costs ~15 ms per frame)', 'bool', False)
F(S, 'stream_fps', 'Frame rate in the browser', 'num', 15, 2, 30, 1)

S = 'Tracking'
F(S, 'lock_frames', 'Frames until a target counts', 'num', 3, 1, 20, 1)
F(S, 'lost_hold', 'Keep target after losing it (s)', 'num', 0.5, 0, 5, 0.1)
F(S, 'smooth', 'Smoothing (tilt only)', 'num', 0.15, 0, 0.9, 0.05)
F(S, 'deadzone', 'Dead zone (% of half the frame)', 'num', 6, 0, 40, 1)
F(S, 'kp_pan', 'Pan: gain (% at full error)', 'num', 40, 0, 200, 1)
F(S, 'kd_pan', 'Pan: damping', 'num', 0, -50, 50, 0.5)
F(S, 'pan_min', 'Pan: minimum speed (%)', 'num', 2, 0, 40, 1,
  hint='The dead band of the servo is already compensated on the Core (Servos > dead band).')
F(S, 'pan_track_max', 'Pan: maximum speed (%)', 'num', 30, 1, 100, 1)
F(S, 'pan_px_s', 'Pan: slowest speed of the servo (pixels/s)', 'num', 230, 0, 1000, 10,
  hint='The servo cannot turn any slower, so errors are corrected with short pulses. '
       '0 = no pulses, drive continuously.')
F(S, 'pan_pulse', 'Pan: pulse length (fraction of the distance)', 'num', 1.0, 0.1, 1.5, 0.05,
  hint='Smaller = more cautious, oscillates less.')
F(S, 'pan_settle', 'Pan: pause after a pulse (s)', 'num', 0.1, 0, 1, 0.05,
  hint='After each pulse the tracker waits this long until a frame taken after the movement has '
       'been evaluated. Too short = oscillates, too long = sluggish.')
F(S, 'dead_box', 'Pan: dead zone as a fraction of the target width', 'num', 0.12, 0, 0.5, 0.01,
  hint='Detections of close, large targets jitter more, so the dead zone grows with the box.')
F(S, 'pan_sign', 'Pan direction', 'select', 1, opts=SIGN)
F(S, 'kp_tilt', 'Tilt: gain (°/s at full error)', 'num', 350, 0, 400, 1)
F(S, 'tilt_rate_max', 'Tilt: maximum rate (°/s)', 'num', 180, 5, 180, 1)
F(S, 'tilt_sign', 'Tilt direction', 'select', -1, opts=SIGN)
F(S, 'aim_x', 'Aim point in the frame: X offset (%)', 'num', 0, -45, 45, 1)
F(S, 'aim_y', 'Aim point in the frame: Y offset (%)', 'num', 0, -45, 45, 1,
  hint='Where the jet hits in the frame (the camera sits above the barrel and looks higher). '
       'Quicker: double-click the spot in the video that the jet hits.')
F(S, 'box_aim', 'Aim point on the body (0 = top, 1 = bottom)', 'num', 0.5, 0, 1, 0.05)

S = 'Firing'
F(S, 'fire_zone', 'Fire window (% of half the frame)', 'num', 12, 2, 50, 1)
F(S, 'fire_frames', 'Frames inside the window before firing', 'num', 3, 1, 30, 1)
F(S, 'burst_ms', 'Burst length (ms)', 'num', 400, 100, 1500, 50)
F(S, 'cooldown_s', 'Pause between bursts (s)', 'num', 5, 0.5, 60, 0.5)
F(S, 'core.trig_park', 'Trigger servo safe (°)', 'num', 90, 0, 180, 1)
F(S, 'core.trig_rest', 'Trigger servo armed, waiting (°)', 'num', 20, 0, 180, 1)
F(S, 'core.trig_fire', 'Trigger servo firing (°)', 'num', 0, 0, 180, 1)
F(S, 'core.fire_max_ms', 'Maximum burst length on the Core (ms)', 'num', 1500, 100, 5000, 100)

S = 'Camera'
F(S, 'cam.device', 'Device', 'text', 'auto')
F(S, 'cam.res', 'Resolution', 'select', '640x480',
  opts=[[r, r] for r in ('320x240', '640x480', '800x600', '1280x720')])
F(S, 'cam.fps', 'Frame rate', 'num', 30, 5, 120, 1)
F(S, 'cam.exposure_auto', 'Automatic exposure', 'bool', True)
F(S, 'cam.exposure', 'Manual exposure', 'num', 157, 1, 5000, 1)
F(S, 'cam.gain', 'Gain', 'num', 0, 0, 100, 1)
F(S, 'cam.brightness', 'Brightness', 'num', 0, -64, 64, 1)
F(S, 'cam.contrast', 'Contrast', 'num', 32, 0, 64, 1)

S = 'Servos'
F(S, 'core.tilt_min', 'Tilt minimum (°)', 'num', 15, 0, 180, 1)
F(S, 'core.tilt_max', 'Tilt maximum (°)', 'num', 165, 0, 180, 1)
F(S, 'core.tilt_home', 'Tilt home position (°)', 'num', 90, 0, 180, 1)
F(S, 'core.pan_max', 'Pan: absolute maximum speed (%)', 'num', 40, 5, 100, 1)
F(S, 'core.pan_dead', 'Pan: dead band of the servo (%)', 'num', 18, 0, 50, 1,
  hint='The 360° servo stands still up to this value; the Core adds it to every drive command.')
F(S, 'core.pan_limit', 'Pan range ± (°, 0 = unlimited)', 'num', 0, 0, 720, 5,
  hint='From the pan centre, estimated from speed and time. The estimate drifts badly and then '
       'blocks at the wrong place (for the remote control too), so it is off. The turret has '
       'mechanical end stops; the tracker detects them itself and does not push against them.')
F(S, 'core.idle_off_s', 'Release servos after idle time (s)', 'num', 30, 0, 600, 5,
  hint='Only while safe: tilt and trigger servo are released after this time without movement, '
       'which saves battery. 0 = always hold (needed if the barrel sags otherwise).')
F(S, 'core.deg_s0', 'Pan: °/s at the smallest command (for the estimate)', 'num', 38, 0, 300, 1,
  hint='The servo immediately turns this fast, slower is not possible. Measured ~230 pixels/s, '
       'calculated with ~7 pixels per degree (stop to stop 1250 pixels ≈ 180°).')
F(S, 'core.deg_s', 'Pan: additional °/s at 100 % (for the estimate)', 'num', 260, 0, 1500, 5)
F(S, 'core.pan_trim_us', 'Pan: stop correction (µs)', 'num', -20, -100, 100, 1)
F(S, 'core.cmd_timeout_ms', 'Stop without a command after (ms)', 'num', 300, 100, 2000, 50)

S = 'Remote control'
F(S, 'core.rc_en', 'Remote control enabled', 'bool', True)
F(S, 'core.rc_fire_en', 'Fire button of the remote control enabled', 'bool', False,
  hint='Needs "Armed" as well. Only switch on once "Value while pressed" is correct.')
F(S, 'core.rc_hold_ms', 'Priority after stick movement (ms)', 'num', 3000, 0, 20000, 100)
F(S, 'core.tilt_rc_rate', 'Tilt by stick (°/s)', 'num', 150, 5, 180, 1)
F(S, 'core.rc_pan', 'Channel pan (0–9)', 'num', 1, 0, 9, 1)
F(S, 'core.rc_tilt', 'Channel tilt (0–9)', 'num', 2, 0, 9, 1)
F(S, 'core.rc_fire', 'Channel fire (0–9)', 'num', 6, 0, 9, 1)
F(S, 'core.rc_pan_sign', 'Stick pan', 'select', 1, opts=SIGN)
F(S, 'core.rc_tilt_sign', 'Stick tilt', 'select', 1, opts=SIGN)
F(S, 'core.rc_pressed', 'Value while the fire button is pressed', 'num', 0, 0, 4095, 1)
F(S, 'core.debug_rc', 'Show raw values of the remote control', 'bool', False)

BY_KEY = {f['key']: f for f in SCHEMA}


class Settings(dict):
    def __init__(self, path):
        dict.__init__(self, {f['key']: f['default'] for f in SCHEMA})
        self.path = path
        self._lock = threading.Lock()
        try:
            with open(path) as fh:
                for k, v in json.load(fh).items():
                    if k in BY_KEY:
                        self[k] = self.coerce(k, v)
        except (OSError, ValueError):
            pass

    def coerce(self, key, v):
        f = BY_KEY[key]
        t = f['type']
        if t == 'bool':
            return bool(v)
        if t == 'text':
            return str(v)[:64]
        if t == 'select':
            for o in f['opts']:
                if str(o[0]) == str(v):
                    return o[0]
            return v if not f['opts'] else self.get(key, f['default'])
        v = float(v)
        v = max(f['min'], min(f['max'], v))
        whole = all(float(x).is_integer() for x in (f['step'], f['min'], f['default']))
        return int(round(v)) if whole else v

    def set(self, key, v):
        if key not in BY_KEY:
            raise KeyError(key)
        self[key] = self.coerce(key, v)
        self.save()
        return self[key]

    def core_value(self, key):
        v = self[key]
        return int(v) if isinstance(v, bool) else v

    def save(self):
        with self._lock:
            tmp = self.path + '.tmp'
            with open(tmp, 'w') as fh:
                json.dump(dict(self), fh, indent=1, sort_keys=True)
            os.replace(tmp, self.path)
