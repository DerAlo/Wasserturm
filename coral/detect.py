# Katzen-/Mensch-Erkennung auf der Edge TPU.
# Zwei Modellfamilien, Auswahl über den Dateinamen:
#   *yolo*.tflite  -> YOLOv8/YOLO26 Rohausgabe [4+nc, N] (eine oder zwei Ausgaben, int8 oder float)
#   alles andere   -> SSD mit eingebautem Postprocessing (pycoral)
# Die YOLO-Auswertung stammt aus dem Katzenprojekt (dort auf diesem Board vermessen).
import threading
import time

import cv2
import numpy as np

YOLO_IDS = {0: 'person', 15: 'cat'}          # COCO-80
SSD_IDS = {0: 'person', 16: 'cat'}           # COCO-90 (coco_labels.txt)


def _nms(boxes, scores, iou_thr=0.45):
    order = scores.argsort()[::-1]
    keep = []
    area = (boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1])
    while order.size:
        i = order[0]
        keep.append(int(i))
        rest = order[1:]
        if not rest.size:
            break
        xx1 = np.maximum(boxes[i, 0], boxes[rest, 0])
        yy1 = np.maximum(boxes[i, 1], boxes[rest, 1])
        xx2 = np.minimum(boxes[i, 2], boxes[rest, 2])
        yy2 = np.minimum(boxes[i, 3], boxes[rest, 3])
        inter = np.clip(xx2 - xx1, 0, None) * np.clip(yy2 - yy1, 0, None)
        iou = inter / (area[i] + area[rest] - inter + 1e-6)
        order = rest[iou <= iou_thr]
    return keep


def _rows(a):
    # Ausgabe auf [N, C] drehen (N Anker ist immer die größere Dimension)
    return a.T if a.shape[0] < a.shape[1] else a


class Detector:
    def __init__(self):
        self._lock = threading.Lock()
        self._interp = None
        self.model = ''
        self.kind = ''
        self.infer_ms = 0.0
        self._clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))

    def load(self, path):
        from pycoral.utils.edgetpu import make_interpreter
        interp = make_interpreter(path)
        interp.allocate_tensors()
        inp = interp.get_input_details()[0]
        kind = 'yolo' if 'yolo' in path.rsplit('/', 1)[-1].lower() else 'ssd'
        with self._lock:
            self._interp = interp
            self._inp = inp
            self._h, self._w = int(inp['shape'][1]), int(inp['shape'][2])
            self._outs = interp.get_output_details()
            self._buf = np.full((self._h, self._w, 3), 114, dtype=np.uint8)
            self.kind = kind
            self.model = path

    def infer(self, frame, conf, clahe=False):
        """frame: BGR. conf: {'cat': x, 'person': y}. -> [(x1, y1, x2, y2, score, label)]"""
        with self._lock:
            if self._interp is None:
                return []
            t0 = time.time()
            if self.kind == 'yolo':
                res = self._yolo(frame, conf, clahe)
            else:
                res = self._ssd(frame, conf, clahe)
            self.infer_ms = 0.8 * self.infer_ms + 0.2 * (time.time() - t0) * 1000.0
            return res

    def _rgb(self, img, clahe):
        if clahe:
            lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
            lab[:, :, 0] = self._clahe.apply(lab[:, :, 0])
            return cv2.cvtColor(lab, cv2.COLOR_LAB2RGB)
        return cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

    def _set_input(self, img):
        if self._inp['dtype'] == np.int8:
            img = np.bitwise_xor(img, np.uint8(0x80)).view(np.int8)
        self._interp.set_tensor(self._inp['index'], img[np.newaxis, ...])

    # ---------------------------------------------------------------- SSD
    def _ssd(self, frame, conf, clahe):
        from pycoral.adapters import detect
        fh, fw = frame.shape[:2]
        small = cv2.resize(frame, (self._w, self._h), interpolation=cv2.INTER_LINEAR)
        self._set_input(self._rgb(small, clahe))
        self._interp.invoke()
        sx, sy = fw / float(self._w), fh / float(self._h)
        res = []
        for o in detect.get_objects(self._interp, min(conf.values())):
            label = SSD_IDS.get(o.id)
            if label is None or o.score < conf[label]:
                continue
            b = o.bbox
            res.append((max(0.0, b.xmin * sx), max(0.0, b.ymin * sy),
                        min(float(fw), b.xmax * sx), min(float(fh), b.ymax * sy),
                        float(o.score), label))
        return res

    # --------------------------------------------------------------- YOLO
    def _yolo(self, frame, conf, clahe):
        fh, fw = frame.shape[:2]
        tw, th = self._w, self._h
        scale = min(tw / float(fw), th / float(fh))
        nw, nh = int(fw * scale), int(fh * scale)
        px, py = (tw - nw) // 2, (th - nh) // 2
        small = cv2.resize(frame, (nw, nh), interpolation=cv2.INTER_LINEAR)
        self._buf[:] = 114
        self._buf[py:py + nh, px:px + nw] = self._rgb(small, clahe)
        self._set_input(self._buf)
        self._interp.invoke()

        ids = sorted(YOLO_IDS)
        cmin = min(conf.values())
        outs = [(d, _rows(self._interp.get_tensor(d['index'])[0])) for d in self._outs]

        def deq(d, a):
            s, zp = d.get('quantization', (0.0, 0))
            if d['dtype'] in (np.int8, np.uint8) and s:
                return (a.astype(np.float32) - zp) * s
            return a.astype(np.float32)

        def qthr(d):
            s, zp = d.get('quantization', (0.0, 0))
            if d['dtype'] in (np.int8, np.uint8) and s:
                return int(np.ceil(cmin / s + zp))
            return cmin

        if len(outs) == 2:
            (bd, braw), (sd, sraw) = sorted(outs, key=lambda o: o[1].shape[1])
            valid = (sraw[:, ids] >= qthr(sd)).any(axis=1)
            if not valid.any():
                return []
            boxes, scores = deq(bd, braw[valid]), deq(sd, sraw[valid])
        else:
            d, raw = outs[0]
            valid = (raw[:, [4 + i for i in ids]] >= qthr(d)).any(axis=1)
            if not valid.any():
                return []
            both = deq(d, raw[valid])
            boxes, scores = both[:, :4], both[:, 4:]

        cls = scores.argmax(axis=1)
        best = scores.max(axis=1)
        keep = np.array([c in YOLO_IDS and s >= conf[YOLO_IDS[c]]
                         for c, s in zip(cls.tolist(), best.tolist())], dtype=bool)
        if not keep.any():
            return []
        boxes, cls, best = boxes[keep], cls[keep], best[keep]
        if boxes.max() <= 2.0:                       # normierte Koordinaten
            boxes = boxes * np.array([tw, th, tw, th], dtype=np.float32)
        xyxy = np.stack([boxes[:, 0] - boxes[:, 2] / 2, boxes[:, 1] - boxes[:, 3] / 2,
                         boxes[:, 0] + boxes[:, 2] / 2, boxes[:, 1] + boxes[:, 3] / 2], axis=1)
        res = []
        for i in _nms(xyxy, best):
            x1, y1, x2, y2 = xyxy[i]
            res.append((float(np.clip((x1 - px) / scale, 0, fw)), float(np.clip((y1 - py) / scale, 0, fh)),
                        float(np.clip((x2 - px) / scale, 0, fw)), float(np.clip((y2 - py) / scale, 0, fh)),
                        float(best[i]), YOLO_IDS[int(cls[i])]))
        return res
