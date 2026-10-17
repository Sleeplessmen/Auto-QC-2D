"""
label_hq_2d.py — Gan nhan 2D (rectangle) do chinh xac cao cho anh giao thong VN, nhan:
    GreenSM (xe Xanh SM) | car | truck | bus | motorcycle | bicycle | person

Cach lam:
  1. 3 detector COCO (YOLO11x, RT-DETR-x, YOLOv8x) x nhieu goc nhin (anh nguyen, lat ngang, cat o 2x2 phong to
     -> bat xe nho o xa). Gop bang WBF: box chi 1 model thay phai rat chac moi giu.
  2. Quy uoc COCO/BDD: nguoi lai xe may cung la person (box rieng), box xe may chi bao chiec xe.
  3. Xe o to -> CLIP (anh vung xe) + ty le mau xanh ngoc -> GreenSM hay xe thuong.
  4. Bo vat cua chinh xe dang quay (taplo, nguoi lai trong cabin, tay lai xe may).
  5. SAM2 large thu tung box ve dung mep vat (xe re / nghieng van om sat); SAM lech xa -> giu box cu, danh dau "box?".

  python label_hq_2d.py --images D:/DATA --out D:/DATA/ket_qua_gan_nhan [--names a.jpg,b.jpg]
  python label_hq_2d.py ... --day-du     anh duong pho dong xe / chup tu cau vuot (KHONG dung cho camera hanh trinh):
      them luoi 3x3 + box 2 model thay + khong bo theo luat taplo; xe bi che mep -> CAN_XEM "mep bi che".
      Do tren 123 anh camera hanh trinh: sot 9 (nhu mac dinh), thua ~10 lan nhieu hon nhung gan het nam o CAN_XEM,
      box TU_DONG van dung ~98%.
Ket qua: <out>/labels/*.txt (YOLO), <out>/json/*.json, <out>/preview/*.jpg, <out>/classes.txt
"""
import argparse
import glob
import json
import os
import re
import sys

import cv2
import numpy as np
import torch


def _imwrite(path, img, params=None):
    """cv2.imwrite khong ghi duoc duong dan co dau (Windows) -> encode roi ghi bang numpy."""
    ok, buf = cv2.imencode(os.path.splitext(path)[1] or ".jpg", img, params or [])
    if ok:
        buf.tofile(path)
    return ok

HERE = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__))
CLASSES = ["GreenSM", "car", "truck", "bus", "motorcycle", "bicycle", "person"]
COCO = {0: "person", 1: "bicycle", 2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}
GROUP = {"car": "veh", "truck": "veh", "bus": "veh", "motorcycle": "two", "bicycle": "two", "person": "person"}
COLORS = {"GreenSM": (200, 210, 0), "car": (60, 60, 255), "truck": (0, 140, 255), "bus": (0, 220, 255),
          "motorcycle": (255, 80, 200), "bicycle": (255, 160, 80), "person": (80, 255, 80)}
MODELS = [("yolo11x.pt", "yolo", 1280), ("rtdetr-x.pt", "rtdetr", 1280), ("yolov8x-seg.pt", "yolo", 1280),
          ("ustc-community/dfine-xlarge-obj2coco", "dfine", 640)]   # D-FINE-X: hoc truoc Objects365 -> ben hon
DET_CONF = 0.12        # nguong tho cua tung model (gop xong moi loc)
VOTE_K = 3             # so model tinh diem (trong 4)
KEEP_SCORE = 0.33      # diem sau gop de giu box (do tren 30 anh doi chieu: tot nhat 0.33)
REVIEW_SCORE = 0.55    # box diem < muc nay -> CAN_XEM. Do tren 123 anh: box TU_DONG (con lai) dung 99.0%, dem 97.7%
SINGLE_KEEP = 0.80     # box chi 1 model thay: diem goc phai >= muc nay
MIN_SIDE = 10          # px: vat nho hon -> bo (qua xa, khong nhan ra)
MIN_PERSON_H = 15      # px: nguoi thap hon -> bo (chi con vai cham)
# Che do --day-du (anh duong pho dong xe, khong phai camera hanh trinh): bat them vat nho / bi che, moi box them -> CAN_XEM
FINE_GRID = 3          # cat them anh thanh luoi 3x3 o chong nhau 25% -> vat nho duoc phong to ~3 lan
FINE_OVL = 0.25
PAIR_KEEP = 0.35       # box chi 2 model thay: trung binh 2 diem >= muc nay -> giu (CAN_XEM)
OCCL_IOA = 0.12        # xe bi nguoi / xe may che >= 12% dien tich o nua duoi -> CAN_XEM "mep bi che"
# Quy uoc gan nhan TOAN BO vat (amodal): vat bi che van ve box uoc luong ca phan bi che (vd banh xe, can sau bi nguoi che)
AMODAL_BAND = 0.15     # dai 15% sat moi canh cua box
AMODAL_COVER = 0.25    # vat gan camera hon phu >= 25% dai do -> coi la canh bi che
AMODAL_PCT = 15        # canh bi che: lay mep NGOAI (phan vi 15 / 85) cua cac box model tu tin, thay cho trung binh
AMODAL_MAX = 0.15      # noi toi da 15% kich thuoc moi canh


# -----------------------------------------------------------------------------
# Detect
# -----------------------------------------------------------------------------

LOW_LIGHT = 75         # do sang trung binh < muc nay (anh dem) -> them goc nhin anh da lam sang
LOW_CONTRAST = 42      # do lech chuan do sang < muc nay (mua, suong, mo) -> cung them


def needs_enh(img):
    # Do tren 735 anh BDD100K: dem bat loi +1.7%, nhung bao nham dem tang 3.8 -> 4.7 / 100 box -> mac dinh TAT.
    # Bat bang bien moi truong QC_ENH=1 (vd du an toan anh dem rat toi).
    if not os.environ.get("QC_ENH"):
        return False
    g = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
    return g.mean() < LOW_LIGHT or g.std() < LOW_CONTRAST


def enhance(img):
    """Lam ro anh toi / mo: CLAHE tren kenh sang + gamma keo do sang trung binh ve ~115."""
    lab = cv2.cvtColor(img, cv2.COLOR_RGB2LAB)
    lab[..., 0] = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8)).apply(lab[..., 0])
    out = cv2.cvtColor(lab, cv2.COLOR_LAB2RGB)
    m = max(1.0, float(out.mean()))
    if m < 100:
        gamma = np.log(115 / 255) / np.log(m / 255)
        out = cv2.LUT(out, ((np.arange(256) / 255) ** gamma * 255).clip(0, 255).astype(np.uint8))
    return out


def views(img):
    """(anh con, offset x, offset y, lat?, canh trong (de bo box bi cat))"""
    h, w = img.shape[:2]
    out = [(img, 0, 0, False, None), (img[:, ::-1].copy(), 0, 0, True, None)]
    if needs_enh(img):        # anh dem / mua: model nhin them ban da lam sang (moi model van chi 1 phieu)
        e = enhance(img)
        out += [(e, 0, 0, False, None), (e[:, ::-1].copy(), 0, 0, True, None)]
    tw, th = int(w * 0.6), int(h * 0.6)
    for x0 in (0, w - tw):
        for y0 in (0, h - th):
            inner = (x0 > 0, y0 > 0, x0 + tw < w, y0 + th < h)       # trai, tren, phai, duoi la canh cat
            out.append((img[y0:y0 + th, x0:x0 + tw].copy(), x0, y0, False, inner))
    return out


def fine_views(img):
    """Luoi FINE_GRID x FINE_GRID o chong nhau (che do --day-du): vat nho / xa duoc phong to khi dua vao model."""
    h, w = img.shape[:2]
    k = FINE_GRID - (FINE_GRID - 1) * FINE_OVL
    tw, th = int(w / k), int(h / k)
    out = []
    for y0 in np.linspace(0, h - th, FINE_GRID).astype(int):
        for x0 in np.linspace(0, w - tw, FINE_GRID).astype(int):
            inner = (x0 > 0, y0 > 0, x0 + tw < w, y0 + th < h)
            out.append((img[y0:y0 + th, x0:x0 + tw].copy(), int(x0), int(y0), False, inner))
    return out


class DFine:
    """D-FINE (transformers) voi giao dien giong ultralytics: tra ve (box xyxy, diem, lop COCO)."""

    def __init__(self, name):
        from transformers import AutoImageProcessor, DFineForObjectDetection
        self.dev = "cuda" if torch.cuda.is_available() else "cpu"
        self.proc = AutoImageProcessor.from_pretrained(name)
        self.model = DFineForObjectDetection.from_pretrained(name).to(self.dev).eval()

    def boxes(self, rgb, conf):
        from PIL import Image
        with torch.no_grad():
            x = self.proc(images=Image.fromarray(rgb), return_tensors="pt").to(self.dev)
            r = self.proc.post_process_object_detection(self.model(**x), target_sizes=[rgb.shape[:2]], threshold=conf)[0]
        return r["boxes"].cpu().numpy(), r["scores"].cpu().numpy(), r["labels"].cpu().numpy().astype(int)


def load_models():
    from ultralytics import YOLO, RTDETR
    out = []
    for p, kind, size in MODELS:
        if kind == "dfine":
            m = DFine(p)
        else:
            m = (RTDETR if kind == "rtdetr" else YOLO)(os.path.join(HERE, p) if os.path.exists(os.path.join(HERE, p)) else p)
        out.append((m, kind, size))
    return out


def run_model(model, kind, imgsz, rgb):
    if kind == "dfine":
        b, s, k = model.boxes(rgb, DET_CONF)
    else:
        r = model.predict(np.ascontiguousarray(rgb[:, :, ::-1]), conf=DET_CONF, imgsz=imgsz, verbose=False,
                          classes=list(COCO), device=0 if torch.cuda.is_available() else "cpu")[0]
        if r.boxes is None:
            return []
        b, s, k = r.boxes.xyxy.cpu().numpy(), r.boxes.conf.cpu().numpy(), r.boxes.cls.cpu().numpy().astype(int)
    return [(bb, ss, kk) for bb, ss, kk in zip(b, s, k) if kk in COCO]


def detect_all(models, img, only=None, fine=False):
    dets = []                 # (x1, y1, x2, y2, score, cls_name, model_idx)
    for mi, (model, kind, imgsz) in enumerate(models):
        if only is not None and mi not in only:
            continue
        for sub, x0, y0, flip, inner in (fine_views(img) if fine else views(img)):
            sh, sw = sub.shape[:2]
            for (a, b, c, d), s, k in run_model(model, kind, imgsz, sub):
                if inner is not None:          # box cham canh cat cua o -> vat bi cat, de anh nguyen lo
                    if (inner[0] and a < 4) or (inner[1] and b < 4) or (inner[2] and c > sw - 4) or (inner[3] and d > sh - 4):
                        continue
                if flip:
                    a, c = sw - c, sw - a
                dets.append((float(a + x0), float(b + y0), float(c + x0), float(d + y0), float(s), COCO[k], mi))
    return dets


def iou(a, b):
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / u if u > 0 else 0.0


def wbf(dets, n_models, thr=0.55):
    """Weighted box fusion theo nhom (xe 4 banh / 2 banh / nguoi). Diem = trung binh diem cao nhat cua tung model."""
    out = []
    for grp in ("veh", "two", "person"):
        ds = sorted([d for d in dets if GROUP[d[5]] == grp], key=lambda d: -d[4])
        clusters = []
        for d in ds:
            best, bi = thr, -1
            for i, c in enumerate(clusters):
                v = iou(d, c["box"])
                if v > best:
                    best, bi = v, i
            if bi < 0:
                clusters.append(dict(members=[d], box=list(d[:4])))
            else:
                c = clusters[bi]
                c["members"].append(d)
                ws = np.array([m[4] for m in c["members"]])
                c["box"] = list((np.array([m[:4] for m in c["members"]]) * ws[:, None]).sum(0) / ws.sum())
        for c in clusters:
            per_model = {}
            for m in c["members"]:
                per_model[m[6]] = max(per_model.get(m[6], 0), m[4])
            top = sorted(per_model.values(), reverse=True)[:VOTE_K]
            score = sum(top) / VOTE_K          # trung binh VOTE_K model tu tin nhat: 1 model khong thay khong keo diem xuong
            votes = {}
            for m in c["members"]:
                votes[m[5]] = votes.get(m[5], 0) + m[4]
            out.append(dict(box=[float(v) for v in c["box"]], score=float(score), n_models=len(per_model),
                            max_score=float(max(per_model.values())), cls=max(votes, key=votes.get), votes=votes,
                            per_model=per_model, n_members=len(c["members"]),
                            _members=[list(m[:5]) + [m[6]] for m in c["members"]]))
    return out


def dedup(objs, thr=0.6):
    """Bo box trung (cung nhom) hoac box nam gon trong box khac cung loai (vd 1 xe bi tach 2 box)."""
    objs = sorted(objs, key=lambda o: -o["score"])
    keep = []
    for o in objs:
        dup = False
        for k in keep:
            if GROUP[k["cls"]] != GROUP[o["cls"]]:
                continue
            a, b = o["box"], k["box"]
            ix = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))
            ao = (a[2] - a[0]) * (a[3] - a[1])
            if iou(a, b) > thr or (ao > 0 and ix / ao > 0.85 and GROUP[o["cls"]] == "veh"):
                dup = True
                break
        if not dup:
            keep.append(o)
    return keep


def drop_artifacts(objs, w):
    """Box sai hay gap: manh mong o mep anh nam trong box cung loai; 'xe' dung dung trung nguoi (nguoi ao do bi goi la car)."""
    def inside(a, b):
        ix = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))
        return ix / max(1e-6, (a[2] - a[0]) * (a[3] - a[1]))
    out = []
    for o in objs:
        x1, y1, x2, y2 = o["box"]
        same = [k for k in objs if k is not o and GROUP[k["cls"]] == GROUP[o["cls"]]]
        if o["cls"] == "person" and (x1 < 2 or x2 > w - 2) and x2 - x1 < 40 and any(inside(o["box"], k["box"]) > 0.7 for k in same):
            continue
        if GROUP[o["cls"]] == "veh" and (y2 - y1) > 1.1 * (x2 - x1) and any(
                k["cls"] == "person" and k["score"] > o["score"] and iou(o["box"], k["box"]) > 0.5 for k in objs):
            continue
        out.append(o)
    return out


# -----------------------------------------------------------------------------
# Xanh SM
# -----------------------------------------------------------------------------

def cyan_ratio(img, box):
    x1, y1, x2, y2 = [int(round(v)) for v in box]
    crop = img[max(0, y1):y2, max(0, x1):x2]
    if crop.size == 0:
        return 0.0
    hsv = cv2.cvtColor(crop[:, :, ::-1], cv2.COLOR_BGR2HSV)
    m = cv2.inRange(hsv, (78, 60, 50), (100, 255, 255)) | cv2.inRange(hsv, (68, 90, 50), (78, 255, 220))
    return float((m > 0).mean())


class GreenSMClassifier:
    POS = ["a photo of a turquoise cyan Xanh SM electric taxi car",
           "a photo of a teal mint green VinFast taxi car with Xanh SM logo",
           "a photo of a light blue-green taxi car at night"]
    NEG = ["a photo of a white car", "a photo of a black car", "a photo of a silver grey car",
           "a photo of a red car", "a photo of a dark blue car", "a photo of a yellow car",
           "a photo of a dark green car", "a photo of a brown car", "a photo of a truck", "a photo of a bus"]

    def __init__(self):
        from transformers import CLIPModel, CLIPProcessor
        name = "openai/clip-vit-large-patch14"
        self.dev = "cuda" if torch.cuda.is_available() else "cpu"
        self.model = CLIPModel.from_pretrained(name, torch_dtype=torch.float16 if self.dev == "cuda" else torch.float32).to(self.dev).eval()
        self.proc = CLIPProcessor.from_pretrained(name)
        self._cache = {}

    def _text(self, prompts):
        key = tuple(prompts)
        if key not in self._cache:
            with torch.no_grad():
                t = self.proc(text=list(prompts), return_tensors="pt", padding=True).to(self.dev)
                f = self.model.get_text_features(**t)
                f = f.pooler_output if hasattr(f, "pooler_output") else f
                self._cache[key] = f / f.norm(dim=-1, keepdim=True)
        return self._cache[key]

    def probs(self, img, boxes, prompts, pad=0.08):
        """softmax tren bo cau `prompts` cho tung box -> mang (so box, so cau)"""
        if not boxes:
            return np.zeros((0, len(prompts)))
        with torch.no_grad():
            f = self._image(img, boxes, pad)
            return (100 * f @ self._text(prompts).T).float().softmax(-1).cpu().numpy()

    def _image(self, img, boxes, pad):
        crops = []
        h, w = img.shape[:2]
        for b in boxes:
            x1, y1, x2, y2 = b
            pd = pad * max(x2 - x1, y2 - y1)
            x1, y1, x2, y2 = int(max(0, x1 - pd)), int(max(0, y1 - pd)), int(min(w, x2 + pd)), int(min(h, y2 + pd))
            c = img[y1:y2, x1:x2]
            s = max(c.shape[:2])                      # dem vuong -> CLIP khong cat mat 2 dau xe
            sq = np.full((s, s, 3), 114, np.uint8)
            sq[(s - c.shape[0]) // 2:(s - c.shape[0]) // 2 + c.shape[0], (s - c.shape[1]) // 2:(s - c.shape[1]) // 2 + c.shape[1]] = c
            crops.append(sq)
        x = self.proc(images=crops, return_tensors="pt").to(self.dev)
        f = self.model.get_image_features(pixel_values=x["pixel_values"].to(self.model.dtype))
        f = f.pooler_output if hasattr(f, "pooler_output") else f
        return f / f.norm(dim=-1, keepdim=True)

    def prob(self, img, boxes):
        return self.probs(img, boxes, self.POS + self.NEG)[:, :len(self.POS)].sum(1).tolist()


def is_greensm(p_clip, cyan):
    # mau xanh ngoc la dau hieu bat buoc (CLIP de nham xe dien trang / xe co logo V)
    return (p_clip >= 0.5 and cyan >= 0.05) or (cyan >= 0.15 and p_clip >= 0.25)


# -----------------------------------------------------------------------------
# Xe van / cuu thuong: COCO hay goi la truck -> CLIP phan lai (quy uoc BDD: van = car)
# -----------------------------------------------------------------------------

VAN = ["a photo of a van", "a photo of a minivan", "a photo of an ambulance", "a photo of a car", "a photo of a pickup truck"]
TRUCK = ["a photo of a cargo truck", "a photo of a lorry", "a photo of a semi-trailer truck", "a photo of a dump truck"]


def fix_vans(clf, img, objs):
    trucks = [o for o in objs if o["cls"] == "truck"]
    for o, p in zip(trucks, clf.probs(img, [o["box"] for o in trucks], VAN + TRUCK)):
        if p[:len(VAN)].sum() > 0.5:
            o["cls"] = "car"


# -----------------------------------------------------------------------------
# Loc vat cua chinh xe dang quay
# -----------------------------------------------------------------------------

def ego_filter(objs, img, ego=True):
    """ego=False (anh khong quay tu xe, vd chup tu cau vuot): chi bo vat qua nho, khong bo theo vi tri taplo / tay lai."""
    h, w = img.shape[:2]
    out = []
    for o in objs:
        x1, y1, x2, y2 = o["box"]
        bw, bh = x2 - x1, y2 - y1
        if min(bw, bh) < MIN_SIDE or (o["cls"] == "person" and bh < MIN_PERSON_H):
            continue
        if not ego:
            out.append(o)
            continue
        # xe/nguoi chiem gan het chieu ngang va cham day anh -> thuong la taplo / mui xe minh
        if GROUP[o["cls"]] == "veh" and bw > 0.85 * w and y2 > 0.97 * h:
            continue
        # nguoi cao gan het anh, cham mep tren -> tai xe / khach trong cabin (quay tu trong xe)
        if o["cls"] == "person" and y1 < 0.03 * h and bh > 0.6 * h:
            continue
        # tay lai / dau xe may cua nguoi quay (camera gan tren xe may): box det, giua anh, cham day
        if GROUP[o["cls"]] in ("veh", "two") and y2 > 0.95 * h and bh < 0.25 * h and bw > 0.25 * w \
                and 0.25 * w < (x1 + x2) / 2 < 0.75 * w:
            continue
        # tai xe ngoi canh camera: cham mep trai/phai + mep tren, to
        if o["cls"] == "person" and y1 < 0.03 * h and bh > 0.45 * h and bw > 0.2 * w and (x1 < 2 or x2 > w - 2):
            continue
        # tay / ghe tren taplo: nam o nua duoi, cham day anh, khong co xe may ben duoi
        if o["cls"] == "person" and y1 > 0.5 * h and y2 > 0.97 * h and not any(
                GROUP[k["cls"]] == "two" and iou(o["box"], k["box"]) > 0.2 for k in objs):
            continue
        out.append(o)
    return out


# -----------------------------------------------------------------------------

def draw(img, objs, path):
    out = img[:, :, ::-1].copy()
    for i, o in enumerate(objs):
        x1, y1, x2, y2 = [int(round(v)) for v in o["box"]]
        col = COLORS[o["cls"]]
        cv2.rectangle(out, (x1, y1), (x2, y2), col, 2)
        txt = f"{i} {o['cls']}" + (" ?" if o.get("can_xem") else "")
        if o.get("can_xem"):
            cv2.rectangle(out, (x1, y1), (x2, y2), (255, 255, 255), 1)
        (tw, th), _ = cv2.getTextSize(txt, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
        ty = y1 - 3 if y1 > th + 4 else y1 + th + 3
        cv2.rectangle(out, (x1, ty - th - 2), (x1 + tw + 2, ty + 2), col, -1)
        cv2.putText(out, txt, (x1 + 1, ty), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 1, cv2.LINE_AA)
    _imwrite(path, out, [cv2.IMWRITE_JPEG_QUALITY, 92])


def draw_debug(img, objs, rejected, path):
    """Anh doi chieu: box giu (mau, so thu tu + diem) va box bi loai (xam, 'r' + diem). Phong to 1.5x cho de nhin."""
    k = 1.5
    out = cv2.resize(img[:, :, ::-1], None, fx=k, fy=k, interpolation=cv2.INTER_CUBIC)
    for j, o in enumerate(rejected):
        x1, y1, x2, y2 = [int(round(v * k)) for v in o["box"]]
        cv2.rectangle(out, (x1, y1), (x2, y2), (170, 170, 170), 1)
        cv2.putText(out, f"r{j} {o['cls'][:3]} {o['score']:.2f}", (x1 + 2, y2 - 3), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (255, 255, 255), 1, cv2.LINE_AA)
    for i, o in enumerate(objs):
        x1, y1, x2, y2 = [int(round(v * k)) for v in o["box"]]
        col = COLORS[o["cls"]]
        cv2.rectangle(out, (x1, y1), (x2, y2), col, 2)
        extra = f" g{o['p_greensm']:.2f}c{o['cyan']:.2f}" if "p_greensm" in o else ""
        txt = f"{i} {o['cls'][:5]} {o['score']:.2f}{extra}"
        (tw, th), _ = cv2.getTextSize(txt, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
        ty = y1 - 3 if y1 > th + 4 else y1 + th + 3
        cv2.rectangle(out, (x1, ty - th - 2), (x1 + tw + 2, ty + 2), col, -1)
        cv2.putText(out, txt, (x1 + 1, ty), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 1, cv2.LINE_AA)
    _imwrite(path, out, [cv2.IMWRITE_JPEG_QUALITY, 90])


# -----------------------------------------------------------------------------
# SAM2: thu box ve dung mep vat (do tren 37 vat doi chieu: lech mep trung vi 5.6 -> 4.0 px)
# -----------------------------------------------------------------------------

SAM_MIN_IOU = 0.6       # box SAM lech qua xa box detector -> SAM tach sai vat, giu box detector
SAM_MIN_SCORE = 0.5
SAM_EXPAND = 0.15       # mask chi duoc vuot box detector toi da 15% moi chieu (tranh lan sang vat ben canh)


class SamRefiner:
    def __init__(self):
        root = os.path.dirname(HERE)
        if root not in sys.path:
            sys.path.insert(0, root)
        from sam2.build_sam import build_sam2
        from sam2.sam2_image_predictor import SAM2ImagePredictor
        dev = "cuda" if torch.cuda.is_available() else "cpu"
        ckpt = os.path.join(root, "checkpoints", "sam2.1_hiera_large.pt")
        self.dev = dev
        self.pred = SAM2ImagePredictor(build_sam2("configs/sam2.1/sam2.1_hiera_l.yaml", ckpt, device=dev))

    def _set(self, img):
        """Tinh embedding anh 1 lan; goi lai cung anh (refine roi seg_check) thi dung lai."""
        key = (img.__array_interface__["data"][0], img.shape, img[::53, ::53].tobytes())
        if getattr(self, "_key", None) != key:
            self.pred.set_image(img)
            self._key = key

    def predict_boxes(self, img, boxes, multimask=False):
        """boxes [[x1,y1,x2,y2]] -> (masks bool NxHxW, scores N). multimask: 3 phuong an moi box (Nx3xHxW, Nx3)"""
        if not len(boxes):
            return np.zeros((0,) + img.shape[:2], bool), np.zeros(0)
        b = np.array(boxes, np.float32)
        with torch.inference_mode(), torch.autocast(self.dev, dtype=torch.bfloat16, enabled=self.dev == "cuda"):
            self._set(img)
            masks, scores, _ = self.pred.predict(point_coords=None, point_labels=None, box=b, multimask_output=multimask)
        masks = np.asarray(masks).reshape(len(b), -1, *np.asarray(masks).shape[-2:]) > 0
        scores = np.asarray(scores, np.float32).reshape(len(b), -1)
        return (masks, scores) if multimask else (masks[:, 0], scores[:, 0])

    def refine(self, img, objs):
        if not objs:
            return
        masks, scores = self.predict_boxes(img, [o["box"] for o in objs])
        H, W = img.shape[:2]
        for o, mk, sc in zip(objs, masks, scores):
            x1, y1, x2, y2 = o["box"]
            mk = (mk > 0).astype(np.uint8)
            dx, dy = (x2 - x1) * SAM_EXPAND, (y2 - y1) * SAM_EXPAND
            lim = np.zeros_like(mk)
            lim[max(0, int(y1 - dy)):min(H, int(np.ceil(y2 + dy))), max(0, int(x1 - dx)):min(W, int(np.ceil(x2 + dx)))] = 1
            mk &= lim
            n, lab, st, _ = cv2.connectedComponentsWithStats(mk, connectivity=8)
            if n > 2:                       # bo dom nhieu nho (lam box phinh ra)
                a = st[1:, cv2.CC_STAT_AREA]
                mk = np.isin(lab, [i + 1 for i, v in enumerate(a) if v >= 0.1 * a.max()]).astype(np.uint8)
            o["_mask"] = mk.astype(bool)
            ys, xs = np.nonzero(mk)
            if len(xs) == 0 or sc < SAM_MIN_SCORE:
                o["box_sam"] = "khong dung (mask kem)"
                continue
            tight = [float(xs.min()), float(ys.min()), float(xs.max() + 1), float(ys.max() + 1)]
            if iou(tight, o["box"]) < SAM_MIN_IOU:
                o["box_sam"] = "khong dung (lech xa)"
                o["can_xem"] = (o.get("can_xem", "") + ", box?").strip(", ")
                continue
            o["box_detector"] = [round(v, 1) for v in o["box"]]
            o["box"] = tight
            o["box_sam"] = round(float(sc), 3)


# Loc box thua co chu dich: CLIP rat chac (>= NEG_P) la bien bao / quang cao / guong / than cay / loa den
# VA detector khong chac (diem < NEG_MAX_SCORE). Do tren 123 anh: bo 7 box thua, khong mat vat that nao.
NEG_P = 0.9
NEG_MAX_SCORE = 0.5
OWN_PROMPTS = {"person": ["a photo of a person", "a photo of a person riding a motorbike", "a photo of a pedestrian walking"],
               "veh": ["a photo of a car", "a photo of a truck", "a photo of a bus", "a photo of a taxi"],
               "two": ["a photo of a motorbike", "a photo of a scooter", "a photo of a bicycle"]}
NEG_PROMPTS = ["a blue traffic sign with a white car symbol", "a road sign", "a billboard advertisement",
               "a poster of a man on a building", "a reflection in a rear-view mirror", "a tree trunk",
               "bright lens flare at night", "a car dashboard", "a windshield wiper", "a shop sign"]


def drop_lookalikes(img, objs, clf):
    out = []
    for grp in ("person", "veh", "two"):
        idx = [i for i, o in enumerate(objs) if GROUP.get(o["cls"], "veh") == grp]
        if not idx:
            continue
        P = clf.probs(img, [objs[i]["box"] for i in idx], OWN_PROMPTS[grp] + NEG_PROMPTS, pad=0.1)
        for i, pp in zip(idx, P):
            objs[i]["p_khong_phai_vat"] = round(float(pp[len(OWN_PROMPTS[grp]):].sum()), 3)
    for o in objs:
        if o.get("p_khong_phai_vat", 0) >= NEG_P and o["score"] < NEG_MAX_SCORE:
            continue
        out.append(o)
    return out


GSM_VETO_P = 0.02      # CLIP chi nhin than xe (nen xam) < muc nay
GSM_VETO_CYAN = 0.30   # va mau xanh ngoc tren than xe < muc nay -> khong phai Xanh SM (mau lan tu xe ben canh)


def greensm_mask_check(img, objs, clf):
    """Box GreenSM: do lai tren DUNG than xe (mask SAM). Xe thuong dung canh xe Xanh SM hay bi lan mau -> ha ve car.
    Kiem tra cheo: anh cu 10->8 loi, anh moi 14->12 loi."""
    hsv = cv2.cvtColor(img[:, :, ::-1], cv2.COLOR_BGR2HSV)
    cy = (cv2.inRange(hsv, (78, 60, 50), (100, 255, 255)) | cv2.inRange(hsv, (68, 90, 50), (78, 255, 220))) > 0
    for o in objs:
        m = o.get("_mask")
        if o["cls"] != "GreenSM" or m is None or not m.any():
            continue
        im2 = img.copy()
        im2[~m] = 114
        o["p_greensm_mask"] = round(clf.prob(im2, [o["box"]])[0], 3)
        o["cyan_mask"] = round(float((cy & m).sum() / m.sum()), 3)
        if o["p_greensm_mask"] < GSM_VETO_P and o["cyan_mask"] < GSM_VETO_CYAN:
            o["cls"] = "car"


def contained(a, b):
    """Ti le dien tich box a nam trong box b."""
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))
    return ix / max(1e-6, (a[2] - a[0]) * (a[3] - a[1]))


def occluded_bottom(o, objs):
    """Xe bi nguoi / xe may phia truoc che nua duoi -> mep box (banh, can sau) de bi hut."""
    x1, y1, x2, y2 = o["box"]
    low = [x1, (y1 + y2) / 2, x2, y2]
    area = max(1e-6, (x2 - x1) * (y2 - y1))
    cov = sum(contained(k["box"], low) * (k["box"][2] - k["box"][0]) * (k["box"][3] - k["box"][1])
              for k in objs if GROUP.get(k["cls"], "veh") in ("person", "two"))
    return cov / area >= OCCL_IOA


def amodal_extend(objs, w, h):
    """Canh bi vat khac che: noi box ra mep ngoai ma cac model tu tin da uoc luong (WBF lay trung binh nen hay hut
    phan bi che, SAM chi om phan nhin thay). Canh khong bi che giu nguyen (van sat mep)."""
    for o in objs:
        mem = o.get("_members") or []
        if len(mem) < 2:
            continue
        top = max(m[4] for m in mem)
        good = [m for m in mem if m[4] >= 0.5 * top]
        if len(good) < 2:
            continue
        x1, y1, x2, y2 = o["box"]
        bw, bh = x2 - x1, y2 - y1
        bands = [[x1, y1, x1 + AMODAL_BAND * bw, y2], [x1, y1, x2, y1 + AMODAL_BAND * bh],
                 [x2 - AMODAL_BAND * bw, y1, x2, y2], [x1, y2 - AMODAL_BAND * bh, x2, y2]]
        box, sides = list(o["box"]), []
        for s, band in enumerate(bands):
            # vat che phai o GAN camera hon (day box thap hon trong anh) va phu dang ke dai sat canh
            if not any(k is not o and k["box"][3] > y2 + 0.02 * bh and contained(band, k["box"]) > AMODAL_COVER
                       for k in objs):
                continue
            vals = [m[s] for m in good]
            lim = AMODAL_MAX * (bw if s in (0, 2) else bh)
            if s < 2:           # trai / tren: mep ngoai = gia tri nho
                new = max(float(np.percentile(vals, AMODAL_PCT)), box[s] - lim)
                grow = new < box[s] - 1
            else:               # phai / duoi: mep ngoai = gia tri lon
                new = min(float(np.percentile(vals, 100 - AMODAL_PCT)), box[s] + lim)
                grow = new > box[s] + 1
            if grow:
                box[s] = new
                sides.append(("trai", "tren", "phai", "duoi")[s])
        if sides:
            o["box_nhin_thay"] = [round(v, 1) for v in o["box"]]
            o["box"] = [max(0.0, box[0]), max(0.0, box[1]), min(float(w), box[2]), min(float(h), box[3])]
            o["uoc_luong_canh_bi_che"] = ",".join(sides)


def postprocess(img, dets, clf, keep_score=None, sam=None, day_du=False, amodal=False):
    """detect tho (moi model) -> danh sach vat cuoi + cac box bi loai (de doi chieu)"""
    keep_score = KEEP_SCORE if keep_score is None else keep_score
    allc = wbf(dets, len(MODELS))
    objs = [o for o in allc if o["score"] >= keep_score or (o["n_models"] == 1 and o["max_score"] >= SINGLE_KEEP)]
    if day_du:                  # vat nho / bi che thuong chi 2 model thay -> van giu, cho nguoi xem
        for o in allc:
            if o not in objs and o["n_models"] >= 2 and sum(sorted(o["per_model"].values())[-2:]) / 2 >= PAIR_KEEP:
                o["_pair"] = True
                objs.append(o)
    rejected = [o for o in allc if o not in objs and o["score"] >= 0.12]
    objs = dedup(objs)
    objs = ego_filter(objs, img, ego=not day_du)
    objs = drop_artifacts(objs, img.shape[1])
    # (Khong bo box nguoi nam trong box nguoi khac: do tren 123 anh lam mat ~67 nguoi ngoi sau xe may)
    fix_vans(clf, img, objs)
    cars = [o for o in objs if GROUP[o["cls"]] == "veh"]
    for o, p in zip(cars, clf.prob(img, [o["box"] for o in cars])):
        o["p_greensm"], o["cyan"] = round(p, 3), round(cyan_ratio(img, o["box"]), 3)
        if o["cls"] == "car" and is_greensm(p, o["cyan"]):
            o["cls"] = "GreenSM"
    for o in objs:              # cho nguoi duyet: box diem thap, Xanh SM / xe thuong khong chac
        why = []
        if o["score"] < REVIEW_SCORE:
            why.append("diem thap")
        if "p_greensm" in o and o["cls"] in ("car", "GreenSM") and (
                0.15 <= o["p_greensm"] <= 0.9 or (o["cls"] == "car" and o["cyan"] >= 0.1)):
            why.append("GreenSM?")
        if o.get("_pair"):
            why.append("co the sot (2 model)")
        if day_du and GROUP.get(o["cls"], "veh") == "veh" and occluded_bottom(o, objs):     # GreenSM cung la xe
            why.append("mep bi che")
        if why:
            o["can_xem"] = ", ".join(why)
    if sam is not None:
        sam.refine(img, objs)
        greensm_mask_check(img, objs, clf)
    objs = drop_lookalikes(img, objs, clf)
    if amodal:
        amodal_extend(objs, img.shape[1], img.shape[0])
    for o in objs:
        o["trang_thai"] = "CAN_XEM" if o.get("can_xem") else "TU_DONG"
    objs.sort(key=lambda o: (o["box"][0], o["box"][1]))
    return objs, rejected


def main():
    for f in (sys.stdout, sys.stderr):
        try:
            f.reconfigure(encoding="utf-8")
        except Exception:
            pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--images", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--names", help="file chua danh sach ten anh (moi dong 1 ten) hoac ten cach nhau dau phay")
    ap.add_argument("--review-score", type=float, default=None,
                    help="box diem < muc nay -> CAN_XEM (mac dinh 0.55). Bo du lieu moi: lay goi y tu kiem_tra_chat_luong.py")
    ap.add_argument("--bat-sot", type=float, default=None,
                    help="giu ca box diem >= muc nay (vd 0.2) duoi dang CAN_XEM de giam vat bi sot (nguoi phai xem nhieu hon)")
    ap.add_argument("--day-du", action="store_true",
                    help="anh duong pho dong xe / chup tu tren cao (KHONG phai camera hanh trinh): cat anh 3x3 bat vat nho, "
                         "giu box 2 model thay, khong bo theo luat taplo / tay lai; box them + xe bi che mep -> CAN_XEM. Cham hon ~2 lan")
    ap.add_argument("--toan-bo", action="store_true",
                    help="quy uoc gan TOAN BO vat (amodal): canh bi vat khac che -> uoc luong ca phan bi che (tu bat khi --day-du)")
    ap.add_argument("--no-sam", action="store_true", help="khong thu box bang SAM2 (nhanh hon, box kem sat)")
    ap.add_argument("--debug", action="store_true", help="them anh debug/ ve ca box bi loai (xam) + diem")
    ap.add_argument("--cache", default=os.path.join(HERE, "cache_hq2d"), help="luu ket qua detect tho (chay lai nhanh)")
    args = ap.parse_args()

    files = sorted(glob.glob(os.path.join(args.images, "*.jpg")) + glob.glob(os.path.join(args.images, "*.png")))
    if args.names:
        want = [l.strip() for l in (open(args.names, encoding="utf-8").read().split("\n") if os.path.exists(args.names)
                                    else args.names.split(",")) if l.strip()]
        files = [f for f in files if os.path.basename(f) in want or os.path.splitext(os.path.basename(f))[0] in want]
    for d in ("labels", "json", "preview"):
        os.makedirs(os.path.join(args.out, d), exist_ok=True)
    os.makedirs(args.cache, exist_ok=True)
    with open(os.path.join(args.out, "classes.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(CLASSES) + "\n")

    models = None
    if args.review_score is not None:
        globals()["REVIEW_SCORE"] = args.review_score
    clf = GreenSMClassifier()
    sam = None if args.no_sam else SamRefiner()
    for fp in files:
        name = os.path.splitext(os.path.basename(fp))[0]
        img = cv2.imdecode(np.fromfile(fp, np.uint8), cv2.IMREAD_COLOR)[:, :, ::-1].copy()      # RGB
        h, w = img.shape[:2]
        # cache theo tung model: them / bot model khong phai detect lai cac model cu
        dets = []
        for mi, (p, _, _) in enumerate(MODELS):
            for fine in ((False, True) if args.day_du else (False,)):
                tag = f"__fine{FINE_GRID}" if fine else ""
                cp = os.path.join(args.cache, f"{name}__{re.sub(r'[^A-Za-z0-9.-]', '_', p)}{tag}.json")
                if os.path.exists(cp):
                    part = [tuple(d[:6]) + (mi,) for d in json.load(open(cp))]
                else:
                    if models is None:
                        models = load_models()
                    part = detect_all(models, img, only={mi}, fine=fine)
                    with open(cp + ".tmp", "w") as f:
                        json.dump(part, f)
                    os.replace(cp + ".tmp", cp)
                dets += part
        objs, rejected = postprocess(img, dets, clf, sam=sam, day_du=args.day_du, amodal=args.day_du or args.toan_bo)
        if args.bat_sot is not None:      # giu ca box diem thap (model co thay) -> CAN_XEM "co the sot"
            extra = [o for o in rejected if o["score"] >= args.bat_sot]
            for o in extra:
                o["trang_thai"] = "CAN_XEM"
                o["can_xem"] = "co the sot (diem thap)"
            rejected = [o for o in rejected if o not in extra]
            objs = objs + extra
        for o in objs:
            o["box"] = [round(max(0.0, min(float(w), o["box"][0])), 1), round(max(0.0, min(float(h), o["box"][1])), 1),
                        round(max(0.0, min(float(w), o["box"][2])), 1), round(max(0.0, min(float(h), o["box"][3])), 1)]
        with open(os.path.join(args.out, "labels", name + ".txt"), "w") as f:
            for o in objs:
                x1, y1, x2, y2 = o["box"]
                f.write(f"{CLASSES.index(o['cls'])} {(x1 + x2) / 2 / w:.6f} {(y1 + y2) / 2 / h:.6f} {(x2 - x1) / w:.6f} {(y2 - y1) / h:.6f}\n")
        json.dump(dict(image=os.path.basename(fp), width=w, height=h,
                       objects=[{k: v for k, v in o.items() if k != "votes" and not k.startswith("_")} for o in objs],
                       rejected=[dict(box=[round(v, 1) for v in o["box"]], cls=o["cls"], score=round(o["score"], 3)) for o in rejected]),
                  open(os.path.join(args.out, "json", name + ".json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        draw(img, objs, os.path.join(args.out, "preview", name + ".jpg"))
        if args.debug:
            os.makedirs(os.path.join(args.out, "debug"), exist_ok=True)
            draw_debug(img, objs, rejected, os.path.join(args.out, "debug", name + ".jpg"))
        cnt = {}
        for o in objs:
            cnt[o["cls"]] = cnt.get(o["cls"], 0) + 1
        print(f"{name[:24]:24s} {len(objs):3d} vat: " + ", ".join(f"{k} {v}" for k, v in sorted(cnt.items())), flush=True)


if __name__ == "__main__":
    main()
