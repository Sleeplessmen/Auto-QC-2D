"""
review_core.py — Review nhan 2D cua nguoi gan nhan (thay nguoi rev) va ghi chu loi len CVAT bang Issue.

Nguyen tac (KHONG doi):
  * Box dung -> khong ghi gi.
  * Chi ghi chu: sai kich thuoc, sai ten nhan, thieu vat, box thua, box trung.
  * KHONG tao / xoa / sua shape, track, nhan, thuoc tinh. Chi tao Issue (ghim vao vi tri tren frame).
  * Truoc khi day: luu ban sao annotation; sau khi day: tai lai va so sanh -> chung minh nhan goc khong doi.

Cach review: tool (label_hq_2d: 4 detector + SAM2 + CLIP) tu tim vat trong anh, roi so voi box nguoi gan.
Chi ghi "loi" khi tool chac chan; truong hop khong chac ghi "khong chac, nen kiem tra".
"""
import hashlib
import io
import json
import os
import re
import sys
import threading
import time
import xml.etree.ElementTree as ET
import zipfile

import cv2
import numpy as np
import requests
import torch

import area_check
import frame_check
import id_check
import rule_tier
import seg_check
import label_hq_2d as L
from label_mapping import norm


def _imwrite(path, img, params=None):
    """cv2.imwrite khong ghi duoc duong dan co dau (Windows) -> encode roi ghi bang numpy."""
    ok, buf = cv2.imencode(os.path.splitext(path)[1] or ".jpg", img, params or [])
    if ok:
        buf.tofile(path)
    return ok

HERE = L.HERE
CACHE = os.path.join(HERE, "cache_hq2d")
OUT_ROOT = os.path.join(HERE, "review_out")
PREFIX = "[Review tự động]"     # Issue kieu cu bat dau bang chu nay; Issue moi chi co ma [qc:...] o cuoi
QC_TAG = re.compile(r"\[qc:([^\]]+)\]\s*$")


def tool_issue(first):
    """Comment dau cua 1 Issue -> (ma qc, loi nhan sach) neu do tool tao, nguoc lai None."""
    m = QC_TAG.search(first)
    if not m and not first.startswith(PREFIX):
        return None
    text = first[:m.start()] if m else first
    text = re.sub(r"^\[Review tự động\]\s*(\[[^\]]+\]\s*)?", "", text).strip()
    return (m.group(1) if m else None), text

# ---------------------------------------------------------------------------
# Nguong (do tren 123 anh D:\DATA, xem review_eval.py)
# ---------------------------------------------------------------------------
MATCH_IOU = 0.5          # cung 1 vat
CROSS_IOU = 0.7          # khop khac nhom (vd box nguoi gan "motorcycle" dung tren nguoi) phai trung rat sat
NEAR_IOU = 0.25          # box lech nhieu (IoU 0.25-0.5) cung loai -> sai kich thuoc lon
EDGE_PX = 6              # sai lech mep cho phep: max(EDGE_PX, EDGE_REL * canh)
EDGE_REL = 0.10
SIZE_IOU = 0.85          # IoU >= muc nay coi nhu khit, khong bao
# Lech it (canh lech nhieu nhat < 20% canh vat) -> "Dang xem xet", khong phai loi chac: BDD100K 400 anh dung,
# 65/143 bao nham "sai kich thuoc" chac la lech < 20% (cach ve mep khac nhau / vat bi che), loi that thuong lech hon
SIZE_SURE_REL = 0.20
OCCLUDED_FRAC = 0.15     # >= 15% box nam trong box khac -> coi nhu bi che (guideline ve phan nhin thay: mep kho uoc luong)
DARK_MEAN = 30           # do sang trung binh vung box < muc nay -> anh qua toi, mep kho thay
# Nham giua cac loai xe (car / truck / bus): chi chac khi CLIP cung chac la loai tool noi (xe ban tai, van... de nham)
VEH_PROMPTS = {"car": ["a photo of a car", "a photo of a sedan", "a photo of an SUV"],
               "truck": ["a photo of a truck", "a photo of a lorry", "a photo of a delivery truck"],
               "bus": ["a photo of a bus", "a photo of a coach bus"]}
VEH_SURE_P = 0.80
# Vat bi thieu nam khuat >= 40% sau box da gan cung nhom: hay la tool tach doi 1 vat / vat bi che gan het -> khong chac
MISS_BEHIND = 0.40
MIN_CHECK_SIDE = 24      # vat nho hon (px) khong cham kich thuoc (nhieu qua)
MIN_MISS_SIDE = 14       # vat tool thay nho hon -> khong bao thieu
MIN_MISS_BY_LABEL = {}   # {ten nhan: px} — guideline bo qua vat nho hon muc nay (guideline.apply_to_core dat)
AMODAL = True            # guideline: ve toan bo vat (ca phan bi che); False = chi ve phan nhin thay
KIEU_NHAN = None         # guideline: "shape" (anh roi, moi vat 1 shape) | "track" (video, 1 vat 1 track) | None = tu doan
# ti le rong/cao hop ly theo nhom: (khong chac duoi, khong chac tren, chac duoi, chac tren)
SHAPE_RANGE = {"veh": (0.45, 4.5, 0.25, 7.0), "two": (0.25, 2.5, 0.12, 4.0), "person": (0.15, 1.6, 0.08, 3.0)}
SURE_SCORE = L.REVIEW_SCORE
UNSURE_SCORE = 0.36
MISS_UNSURE = 0.33      # tool thay (diem thap) ma nguoi gan khong co -> "co the thieu" (truoc 0.38)
# Vat tool da BO (diem 0.30-0.33, khong vao danh sach giu) nhung >= 3/4 model cung thay -> van "co the thieu".
# Do 400 anh BDD chinh: tim duoc vat bi thieu 73.4% -> 77.7%, them ~2.2 muc "dang xem xet" / 100 box (khong dong toi loi chac).
MISS_REJ_SCORE = 0.30
MISS_REJ_MODELS = 3
DUP_IOU = 0.85
NEAR_DUP_IOU = 0.60     # 2 box cung nhom de nhau 0.6-0.85, tool chi thay 1 vat -> "co the trung"

GROUP = dict(L.GROUP, GreenSM="veh")
SYN = {
    "GreenSM": ["greensm", "xanhsm", "greensmcar", "xesm", "taxixanh", "xanhsmtaxi"],
    "car": ["car", "cars", "oto", "xeoto", "xehoi", "sedan", "suv", "van", "automobile"],
    "truck": ["truck", "trucks", "xetai", "lorry", "pickup", "pickuptruck"],
    "bus": ["bus", "buses", "xebuyt", "xebus", "coach", "minibus"],
    "motorcycle": ["motorcycle", "motorcycles", "motorbike", "motorbikes", "motor", "moto", "xemay", "scooter"],
    "bicycle": ["bicycle", "bicycles", "bike", "xedap"],
    "person": ["person", "persons", "pedestrian", "pedestrians", "people", "human", "nguoi", "nguoidibo"],
}
# Nhan "di kem": job co nhan rieng cho 1 kieu vat ma tool gop chung lop (vd KITTI: Van, Person_sitting, Cyclist).
# ten (da norm) -> (nhom, cac lop tool chap nhan la DUNG nhan nay, co cham kich thuoc theo box tool khong).
# Cyclist (KITTI) = 1 box bao ca nguoi + xe dap -> khac cach ve cua tool (nguoi, xe rieng) -> khong cham kich thuoc.
ALT_SYN = {
    "van": ("veh", {"car", "truck", "bus", "GreenSM"}, True),
    "minivan": ("veh", {"car", "truck", "bus", "GreenSM"}, True),
    "personsitting": ("person", {"person"}, True),
    "sittingperson": ("person", {"person"}, True),
    "cyclist": ("person", {"person", "bicycle", "motorcycle"}, False),
    "motorcyclist": ("person", {"person", "bicycle", "motorcycle"}, False),
}
# BDD100K: nguoi dang lai / ngoi tren xe 2 banh la nhan rieng "rider" (khong phai pedestrian)
RIDER_SYN = ["rider", "riders", "nguoilai", "nguoilaixe", "nguoingoitrenxe", "nguoitrenxe"]
RIDER_ON = 0.25         # >= 25% box nguoi nam tren box xe 2 banh (va chan nguoi o tam xe) -> la rider
RIDER_SURE = 0.4        # >= 40% -> chac chan
GROUP_SYN = {
    "veh": ["vehicle", "vehicles", "xe4banh", "fourwheels", "4wheels", "fourwheeler", "xeoto4banh"],
    "two": ["twowheels", "twowheel", "2wheels", "xe2banh", "twowheeler", "twowheelers", "cycle", "cycles"],
    "person": ["human", "humans"],
}
NAME_VI = {"left": "trái", "top": "trên", "right": "phải", "bottom": "dưới"}


def log(msg, cb=None):
    print(msg, flush=True)
    if cb:
        cb(msg)


# ---------------------------------------------------------------------------
# Khop ten nhan cua job <-> lop cua tool
# ---------------------------------------------------------------------------

def build_label_map(job_labels):
    """job_labels: [ten nhan]. Tra ve (tool_cls -> ten nhan job | None, ten nhan job -> nhom, cac nhan khong danh gia duoc)"""
    by_norm = {_canon(n): n for n in job_labels}
    tool2job = {}
    for c in L.CLASSES:
        hit = next((by_norm[s] for s in SYN[c] if s in by_norm), None)
        if hit is None and c == "GreenSM":             # job khong co nhan Xanh SM -> xe Xanh SM tinh la car
            hit = next((by_norm[s] for s in SYN["car"] if s in by_norm), None)
        if hit is None:
            hit = next((by_norm[s] for s in GROUP_SYN[GROUP[c]] if s in by_norm), None)
        tool2job[c] = hit
    job_group = {}
    for c, j in tool2job.items():
        if j is not None:
            job_group[j] = GROUP[c]
    rider = rider_label(job_labels)
    if rider and rider not in job_group:
        job_group[rider] = "person"
    for n in job_labels:                              # nhan di kem (Van, Person_sitting, Cyclist...)
        a = ALT_SYN.get(norm(n))
        if a and n not in job_group:
            job_group[n] = a[0]
    skipped = [n for n in job_labels if n not in job_group]
    return tool2job, job_group, skipped


def _canon(name):
    """Ten nhan (da norm); go sai nhe (vd 'perdestrian') -> tu dong nghia gan nhat trong SYN."""
    n = norm(name)
    words = {w for ws in list(SYN.values()) + list(GROUP_SYN.values()) for w in ws} | set(RIDER_SYN) | set(ALT_SYN)
    if n in words or len(n) < 5:
        return n
    import difflib
    m = difflib.get_close_matches(n, [w for w in words if len(w) >= 5], n=1, cutoff=0.85)
    return m[0] if m else n


def alt_ok(label, t):
    """Nhan di kem 'label' chap nhan vat tool t (vd 'Van' <-> tool thay car) -> khong phai sai nhan."""
    a = ALT_SYN.get(norm(label))
    return bool(a) and t.get("cls") in a[1]


def rider_label(names):
    """Ten nhan 'rider' cua job (nguoi tren xe 2 banh), None neu job khong tach rider."""
    return next((n for n in names if norm(n) in RIDER_SYN), None)


def _on_two(p, bikes):
    """Muc do box nguoi p 'ngoi tren' 1 xe 2 banh: phan box nguoi nam trong box xe, tam ngang nguoi trong xe,
    chan nguoi khong thap hon day xe qua nhieu."""
    best = 0.0
    for b in bikes:
        cx = (p[0] + p[2]) / 2
        if not (b[0] <= cx <= b[2]) or p[3] > b[3] + 0.25 * (b[3] - b[1]) or p[3] < b[1]:
            continue
        best = max(best, _inside(p, b))
    return best


# ---------------------------------------------------------------------------
# Tool: tim vat trong anh (dung lai label_hq_2d)
# ---------------------------------------------------------------------------

FAST_MODELS = [("yolo11x.pt", "yolo", 1280), ("rtdetr-x.pt", "rtdetr", 1280)]


# Phong to dai giua anh (quanh duong chan troi, noi co xe / nguoi nho o xa): cat 3 o chong nhau, model nhin moi o
# phong to ~2.4 lan. Chi lay vat NHO tu luot nay (vat lon da co tu anh nguyen, o cat co the lam lech box).
FAR_ZOOM = True
FAR_TILES = 3
FAR_BAND = (0.22, 0.72)  # tu 22% toi 72% chieu cao anh
FAR_TILE_W = 0.42        # moi o rong 42% anh, 3 o chong nhau
FAR_MAX_SIDE = 48        # px (anh goc): box tu luot phong to co canh ngan lon hon -> bo


def far_views(img):
    h, w = img.shape[:2]
    y0, y1 = int(h * FAR_BAND[0]), int(h * FAR_BAND[1])
    tw = int(w * FAR_TILE_W)
    for x0 in np.linspace(0, w - tw, FAR_TILES).astype(int):
        # canh cat: trai / phai (tru mep anh) va tren / duoi (luon la canh cat cua dai) -> bo box cham canh do
        yield img[y0:y1, x0:x0 + tw].copy(), int(x0), y0, (x0 > 0, True, x0 + tw < w, True)


def detect_far(models, img, mi, enh):
    """Luot phong to dai giua cho model mi. Anh dem / mua: dung ban da lam sang (giong L.views)."""
    src = L.enhance(img) if enh else img
    model, kind, imgsz = models[mi]
    out = []
    for sub, x0, y0, inner in far_views(src):
        sh, sw = sub.shape[:2]
        for (a, b, c, d), s, k in L.run_model(model, kind, imgsz, sub):
            if (inner[0] and a < 4) or (inner[1] and b < 4) or (inner[2] and c > sw - 4) or (inner[3] and d > sh - 4):
                continue                  # vat bi cat o canh o -> de anh nguyen lo
            if min(c - a, d - b) > FAR_MAX_SIDE:
                continue                  # vat lon: lay tu anh nguyen
            out.append((float(a + x0), float(b + y0), float(c + x0), float(d + y0), float(s), L.COCO[k], mi))
    return out


class ToolRunner:
    """mode 'chinh_xac' = y het label_hq_2d (4 model, nhieu goc nhin, SAM2). 'nhanh' = 2 model, anh nguyen + lat, khong SAM."""
    _lock = threading.Lock()

    def __init__(self, mode="chinh_xac", cb=None):
        self.mode = mode
        self.models = None
        log(f"Nạp model ({'GPU ' + torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU'}), chế độ {mode}...", cb)
        self.clf = L.GreenSMClassifier()
        self.sam = L.SamRefiner() if mode == "chinh_xac" else None
        os.makedirs(CACHE, exist_ok=True)

    @staticmethod
    def device():
        return f"GPU ({torch.cuda.get_device_name(0)})" if torch.cuda.is_available() else "CPU (không có GPU — sẽ chậm)"

    def _models(self):
        if self.models is None:
            if self.mode == "chinh_xac":
                self.models = L.load_models()
            else:
                from ultralytics import YOLO, RTDETR
                self.models = [((RTDETR if k == "rtdetr" else YOLO)(os.path.join(HERE, p)), k, s) for p, k, s in FAST_MODELS]
        return self.models

    def detect(self, img, key):
        """img RGB. key: ten cache (ten anh hoac hash). Tra ve (objs, rejected) — objs da qua toan bo hau xu ly."""
        spec = L.MODELS if self.mode == "chinh_xac" else FAST_MODELS
        dets = []
        enh = self.mode == "chinh_xac" and L.needs_enh(img)
        passes = [False, True] if self.mode == "chinh_xac" and FAR_ZOOM else [False]
        for mi, (p, _, _) in enumerate(spec):
            for far in passes:
                tag = re.sub(r"[^A-Za-z0-9.-]", "_", p) + ("" if self.mode == "chinh_xac" else "__fast") + \
                      (f"__far{FAR_TILES}" if far else "") + ("__enh" if enh else "")
                cp = os.path.join(CACHE, f"{key}__{tag}.json")
                if os.path.exists(cp):
                    part = [tuple(d[:6]) + (mi,) for d in json.load(open(cp))]
                else:
                    models = self._models()
                    if far:
                        part = detect_far(models, img, mi, enh)
                    elif self.mode == "chinh_xac":
                        part = L.detect_all(models, img, only={mi})
                    else:
                        m, kind, sz = models[mi]
                        part = []
                        w = img.shape[1]
                        for sub, flip in ((img, False), (img[:, ::-1].copy(), True)):
                            for (a, b, c, d), s, k in L.run_model(m, kind, sz, sub):
                                if flip:
                                    a, c = w - c, w - a
                                part.append((float(a), float(b), float(c), float(d), float(s), L.COCO[k], mi))
                    with open(cp + ".tmp", "w") as f:
                        json.dump(part, f)
                    os.replace(cp + ".tmp", cp)
                dets += part
        with self._lock:
            old_k, old_m = L.VOTE_K, L.MODELS
            if self.mode != "chinh_xac":
                L.VOTE_K, L.MODELS = 2, FAST_MODELS
            try:
                # mac dinh gan TOAN BO vat (ca phan bi che); guideline noi chi ve phan nhin thay thi AMODAL = False
                objs, rejected = L.postprocess(img, dets, self.clf, sam=self.sam, amodal=AMODAL)
            finally:
                L.VOTE_K, L.MODELS = old_k, old_m
        h, w = img.shape[:2]
        for o in objs:
            o["box"] = [max(0.0, min(float(w), o["box"][0])), max(0.0, min(float(h), o["box"][1])),
                        max(0.0, min(float(w), o["box"][2])), max(0.0, min(float(h), o["box"][3]))]
            o.pop("_mask", None)
        return objs, rejected

    def seg_sam(self, cb=None):
        """SAM2 de kiem tra vien polygon / mask tung vat (che do nhanh khong nap SAM luc detect -> nap rieng o day)."""
        if getattr(self, "_seg_sam", None) is None:
            if self.sam is None:
                log("Nạp SAM2 để kiểm tra viền polygon / mask...", cb)
            self._seg_sam = self.sam or L.SamRefiner()
        return self._seg_sam

    def road_seg(self, cb=None):
        """Model phan vung mat duong, nap 1 lan khi job co nhan vung duong."""
        if getattr(self, "_road", None) is None:
            import area_check
            log("Nạp model phân vùng mặt đường (SegFormer)...", cb)
            self._road = area_check.RoadSeg()
        return self._road

    def lookalike(self, img, box, grp):
        """Xac suat box KHONG phai vat (bien bao, quang cao, guong, than cay...)"""
        P = self.clf.probs(img, [box], L.OWN_PROMPTS[grp] + L.NEG_PROMPTS, pad=0.1)
        return float(P[0][len(L.OWN_PROMPTS[grp]):].sum())

    def vehicle_type(self, img, box):
        """CLIP: xac suat car / truck / bus cho 1 box xe (y kien thu 2 khi tool va nguoi gan khac loai xe)."""
        names = [c for c, ps in VEH_PROMPTS.items() for _ in ps]
        P = self.clf.probs(img, [box], [p for ps in VEH_PROMPTS.values() for p in ps], pad=0.05)[0]
        out = {c: 0.0 for c in VEH_PROMPTS}
        for c, p in zip(names, P):
            out[c] += float(p)
        return out


# ---------------------------------------------------------------------------
# So sanh box nguoi gan vs tool -> danh sach ghi chu
# ---------------------------------------------------------------------------

def _refs(t):
    """Cac uoc luong box cua tool cho 1 vat: box SAM + box tot nhat cua tung detector."""
    refs = [t["box"]]
    best = {}
    for m in t.get("_members") or []:
        if m[5] not in best or m[4] > best[m[5]][4]:
            best[m[5]] = m
    refs += [list(m[:4]) for m in best.values()]
    if t.get("box_detector"):
        refs.append(t["box_detector"])
    if t.get("box_nhin_thay"):          # vat bi che: box phan nhin thay cung la 1 cach ve chap nhan duoc
        refs.append(t["box_nhin_thay"])
    return refs


def _edges(lb, tb, W, H, refs=None):
    """mep nao lech: duong = box nguoi gan thua ra ngoai vat, am = cat mat vat.
    Co refs (nhieu uoc luong): chi tinh lech khi mep nguoi gan nam NGOAI khoang cua TAT CA uoc luong (cac model dong y)."""
    refs = refs or [tb]
    tw, th = tb[2] - tb[0], tb[3] - tb[1]
    idx = {"left": 0, "top": 1, "right": 2, "bottom": 3}
    at_border = {"left": tb[0] <= 2 and lb[0] <= 2, "top": tb[1] <= 2 and lb[1] <= 2,
                 "right": tb[2] >= W - 2 and lb[2] >= W - 2, "bottom": tb[3] >= H - 2 and lb[3] >= H - 2}
    off = {}
    for k, i in idx.items():
        tol = max(EDGE_PX, EDGE_REL * (tw if k in ("left", "right") else th))
        vals = [r[i] for r in refs]
        lo, hi = min(vals), max(vals)
        outward = -1 if i < 2 else 1          # trai/tren: nho hon la thua ra ngoai
        if lb[i] < lo - tol:
            v = (lo - lb[i]) * -outward
        elif lb[i] > hi + tol:
            v = (lb[i] - hi) * outward
        else:
            continue
        if not at_border[k]:
            off[k] = v
    return off


def _off_rel(off, tb):
    """Canh lech nhieu nhat, tinh theo % canh cua vat (trai/phai theo chieu rong, tren/duoi theo chieu cao)."""
    w, h = max(1.0, tb[2] - tb[0]), max(1.0, tb[3] - tb[1])
    return max((abs(v) / (w if k in ("left", "right") else h) for k, v in off.items()), default=0.0)


def _size_msg(off):
    parts = [f"cạnh {NAME_VI[k]} {'thừa' if v > 0 else 'thiếu'} {abs(v):.0f}px" for k, v in off.items()]
    return ", ".join(parts)


def compare(lab, tool, rejected, W, H, tool2job, job_group, img=None, runner=None, rider_person=True):
    """lab: [dict(id, label, box, occluded)] (chi nhan danh gia duoc). tool: objs cua ToolRunner.
    Tra ve [dict(kind, sure, label, box, msg, ref)]"""
    out = []
    T = []
    rider = rider_label(job_group)
    bikes = [o["box"] for o in tool if GROUP.get(o["cls"]) == "two"] + \
            [l["box"] for l in lab if job_group.get(l["label"]) == "two"] if rider else []
    for o in tool:
        j = tool2job.get(o["cls"])
        on = _on_two(o["box"], bikes) if rider and o["cls"] == "person" else 0.0
        if on >= RIDER_ON:                 # nguoi tren xe 2 banh -> job tach rider
            j = rider
        if j is None:
            continue
        T.append(dict(o, label=j, grp=GROUP[o["cls"]], on_two=on,
                      sure=o.get("trang_thai") == "TU_DONG" and o["score"] >= SURE_SCORE,
                      box_ok=isinstance(o.get("box_sam"), float)))
    if not rider_person:      # quy uoc job: nguoi lai xe may KHONG co box rieng
        two = [t["box"] for t in T if t["grp"] == "two"] + [l["box"] for l in lab if job_group.get(l["label"]) == "two"]
        T = [t for t in T if not (t["grp"] == "person" and any(_inside(t["box"], b) > 0.5 for b in two))]

    # box hinh dang phi ly (dep / manh bat thuong): bao ngay, khong dem khop voi tool
    bad = set()
    for i, l in enumerate(lab):
        # Cyclist bao ca nguoi + xe -> dang box nhu xe 2 banh, khong nhu nguoi dung
        shape_grp = "two" if norm(l["label"]) in ("cyclist", "motorcyclist") else job_group.get(l["label"])
        f = None if l.get("seg") else _check_shape(l, shape_grp, W, H)
        if f:
            out.append(f)
            bad.add(i)

    ml, mt = {}, {}
    pairs = sorted(((L.iou(l["box"], t["box"]), i, k) for i, l in enumerate(lab) if i not in bad
                    for k, t in enumerate(T)), reverse=True)
    # khop theo do trung + uu tien nhe cung nhan / cung nhom. Khac nhom (nguoi <-> xe may) phai trung rat sat,
    # vi box nguoi lai va box xe may hay chong nhau ~0.5 (nguoi gan dan nhan "motorcycle" len nguoi -> van bat duoc)
    cand = []
    for v, i, k in pairs:
        if v < MATCH_IOU:
            break
        same = lab[i]["label"] == T[k]["label"] or alt_ok(lab[i]["label"], T[k])
        same_grp = job_group.get(lab[i]["label"]) == T[k]["grp"]
        if same_grp or v >= CROSS_IOU:
            cand.append((v + (0.15 if same else 0.08 if same_grp else 0.0), i, k))
    for _, i, k in sorted(cand, reverse=True):
        if i not in ml and k not in mt:
            ml[i], mt[k] = k, i

    for i, k in ml.items():
        l, t = lab[i], T[k]
        if alt_ok(l["label"], t):          # nhan di kem dung (vd 'Van' tren vat tool thay la car)
            if ALT_SYN[norm(l["label"])][2]:
                _check_size(out, l, t, W, H)
            continue
        if l["label"] != t["label"]:
            if rider and t["grp"] == "person" and job_group.get(l["label"]) == "person":
                # rider <-> pedestrian: phan theo vi tri so voi xe 2 banh (xe co the bi che / tool khong thay -> it khi chac)
                sure = t["sure"] and t["label"] == rider and t["on_two"] >= RIDER_SURE
                why = "người đang ở trên xe 2 bánh" if t["label"] == rider else "không thấy xe 2 bánh dưới người này"
                out.append(dict(kind="sai_nhan", sure=sure, label=l["label"], box=l["box"], ref=l["id"],
                                msg=f"{'' if sure else 'Có thể '}{'Sai' if sure else 'sai'} nhãn: {why}, "
                                    f"nên là '{t['label']}', không phải '{l['label']}'."))
                continue
            sure = t["sure"] and "GreenSM?" not in t.get("can_xem", "")
            if sure and t["cls"] in VEH_PROMPTS and job_group.get(l["label"]) == "veh":
                # car <-> truck <-> bus: hoi them CLIP; khong co CLIP thi khong chac
                vt = runner.vehicle_type(img, l["box"]) if runner is not None and img is not None else {}
                sure = vt.get(t["cls"], 0.0) >= VEH_SURE_P
            if sure:
                out.append(dict(kind="sai_nhan", sure=True, label=l["label"], box=l["box"], ref=l["id"],
                                msg=f"Sai nhãn: đây là '{t['label']}', không phải '{l['label']}'."))
            elif t["score"] >= UNSURE_SCORE:
                out.append(dict(kind="sai_nhan", sure=False, label=l["label"], box=l["box"], ref=l["id"],
                                msg=f"Có thể sai nhãn: giống '{t['label']}' hơn '{l['label']}'."))
            continue
        _check_size(out, l, t, W, H)

    # box lech nhieu (IoU 0.25-0.5) cung nhan: thuong la ve sai kich thuoc lon
    for v, i, k in pairs:
        if v < NEAR_IOU:
            break
        if i in ml or k in mt:
            continue
        if lab[i]["label"] != T[k]["label"] and not (alt_ok(lab[i]["label"], T[k]) and ALT_SYN[norm(lab[i]["label"])][2]):
            continue
        l, t = lab[i], T[k]
        if l.get("seg"):            # polygon cua vat: vien do seg_check cham bang SAM, o day chi danh dau la co nhan
            ml[i], mt[k] = k, i
            continue
        lc = ((l["box"][0] + l["box"][2]) / 2, (l["box"][1] + l["box"][3]) / 2)
        tc = ((t["box"][0] + t["box"][2]) / 2, (t["box"][1] + t["box"][3]) / 2)
        if not (_contains(t["box"], lc) or _contains(l["box"], tc)):
            continue
        ml[i], mt[k] = k, i
        off = _edges(l["box"], t["box"], W, H, _refs(t))
        sure = t["sure"] and t["box_ok"] and not l.get("occluded") and _off_rel(off, t["box"]) >= SIZE_SURE_REL
        out.append(dict(kind="sai_kich_thuoc", sure=sure, label=l["label"], box=l["box"], ref=l["id"], off=off,
                        msg=f"Box lệch nhiều so với vật: {_size_msg(off) or 'sai vị trí'}."))

    # thieu: tool thay chac chan, nguoi gan khong co box nao
    for k, t in enumerate(T):
        if k in mt:
            continue
        x1, y1, x2, y2 = t["box"]
        if min(x2 - x1, y2 - y1) < max(MIN_MISS_SIDE, MIN_MISS_BY_LABEL.get(t["label"], 0)):
            continue          # vat qua nho (hoac guideline khong bat gan vat nho nhu vay)
        if any(L.iou(t["box"], l["box"]) >= 0.5 and job_group.get(l["label"]) == t["grp"] for l in lab):
            continue          # da co box cung nhom de len (lech / khac nhan, da xu ly o tren)
        if any(alt_ok(l["label"], t) and _inside(t["box"], l["box"]) >= 0.8 for l in lab):
            continue          # nam trong box nhan di kem (vd nguoi tren xe dap trong box 'Cyclist')
        where = _miss_where(t, lab, bad)
        what = "box / polygon" if any(l.get("seg") for l in lab) else "box"
        behind = any(job_group.get(l["label"]) == t["grp"] and _inside(t["box"], l["box"]) >= MISS_BEHIND for l in lab)
        if t["sure"] and not behind:
            out.append(dict(kind="thieu", sure=True, label=t["label"], box=t["box"], ref=None,
                            msg=f"Thiếu {what} '{t['label']}' ở đây{where}."))
        elif t["score"] >= MISS_UNSURE:
            out.append(dict(kind="thieu", sure=False, label=t["label"], box=t["box"], ref=None,
                            msg=f"Có thể thiếu {what} '{t['label']}' ở đây{where}."))

    # vat tool da bo vi diem thap nhung nhieu model cung thay (thuong la vat nho / xa / toi) -> "co the thieu"
    two_boxes = [t["box"] for t in T if t["grp"] == "two"] + [l["box"] for l in lab if job_group.get(l["label"]) == "two"]
    for o in rejected:
        j = tool2job.get(o.get("cls"))
        if j is None or o.get("score", 0) < MISS_REJ_SCORE or o.get("n_models", 0) < MISS_REJ_MODELS:
            continue
        g_ = GROUP.get(o["cls"])
        x1, y1, x2, y2 = o["box"]
        if min(x2 - x1, y2 - y1) < max(MIN_MISS_SIDE, MIN_MISS_BY_LABEL.get(j, 0)):
            continue
        if any(L.iou(o["box"], t["box"]) >= 0.5 for t in T) or \
                any(L.iou(o["box"], l["box"]) >= 0.5 or (job_group.get(l["label"]) == g_ and _inside(o["box"], l["box"]) >= MISS_BEHIND) for l in lab):
            continue          # da co vat tool giu / box nguoi gan o day
        if any(f["kind"] == "thieu" and L.iou(o["box"], f["box"]) >= 0.5 for f in out):
            continue          # da bao thieu o cho nay (vd 2 ung vien car / truck chong nhau)
        if g_ == "person" and not rider_person and any(_inside(o["box"], b) > 0.5 for b in two_boxes):
            continue          # quy uoc job: nguoi lai xe khong co box rieng
        what = "box / polygon" if any(l.get("seg") for l in lab) else "box"
        out.append(dict(kind="thieu", sure=False, label=j, box=list(o["box"]), ref=None,
                        msg=f"Có thể thiếu {what} '{j}' ở đây (vật mờ / nhỏ, nhiều model cùng thấy, xem kỹ)."))

    # thua: nguoi gan co box ma tool khong thay gi (ca box diem thap)
    cand = [o["box"] for o in tool] + [o["box"] for o in rejected]
    for i, l in enumerate(lab):
        if i in ml or i in bad:
            continue
        x1, y1, x2, y2 = l["box"]
        if min(x2 - x1, y2 - y1) < 20 or any(L.iou(l["box"], b) >= 0.3 for b in cand):
            continue
        p_neg = runner.lookalike(img, l["box"], job_group[l["label"]]) if runner is not None and img is not None else 0.0
        what = {"polygon": "Polygon", "mask": "Mask"}.get(l.get("seg"), "Box")
        if p_neg >= L.NEG_P:
            out.append(dict(kind="thua", sure=True, label=l["label"], box=l["box"], ref=l["id"],
                            msg=f"{what} thừa: không có '{l['label']}' ở đây (biển báo / quảng cáo / bóng phản chiếu?)."))
        else:
            out.append(dict(kind="thua", sure=False, label=l["label"], box=l["box"], ref=l["id"],
                            msg=f"Có thể {what.lower()} thừa: không thấy '{l['label']}' ở đây."))

    # box trung: 2 box cung nhom tren 1 vat. Bao tren box ve SAU (j). Khac nhan (vd car + truck) cung la trung.
    # De nhau vua (IoU 0.6-0.85) ma tool chi thay DUNG 1 vat o do -> "dang xem xet" (box chep roi keo lech / 2 vat sat).
    for i in range(len(lab)):
        for j in range(i + 1, len(lab)):
            a, b = lab[i], lab[j]
            if job_group.get(a["label"]) != job_group.get(b["label"]):
                continue
            v = L.iou(a["box"], b["box"])
            two = f"2 box '{a['label']}'" if a["label"] == b["label"] else f"2 box '{a['label']}' và '{b['label']}'"
            if v >= DUP_IOU:
                out.append(dict(kind="trung", sure=True, label=b["label"], box=b["box"], ref=b["id"],
                                msg=f"Trùng: {two} cho cùng 1 vật, xoá 1 box."))
            elif v >= NEAR_DUP_IOU and sum(1 for t in T if max(L.iou(t["box"], a["box"]), L.iou(t["box"], b["box"])) >= MATCH_IOU) == 1:
                out.append(dict(kind="trung", sure=False, label=b["label"], box=b["box"], ref=b["id"],
                                msg=f"Có thể trùng: {two} đè nhau mà ở đó chỉ thấy 1 vật, xoá box thừa."))

    # kich thuoc / hinh dang cua vat bi box khac che, hoac vung anh qua toi: tool uoc luong mep kem
    # (BDD100K: 1/3 bao nham kich thuoc la vat bi che, 1/3 la anh dem / mo) -> "dang xem xet", ghi ro ly do
    byid = {l["id"]: l for l in lab}
    for f in out:
        l = byid.get(f.get("ref"))
        if f["kind"] != "sai_kich_thuoc" or not f["sure"] or l is None or min(l["box"][2] - l["box"][0], l["box"][3] - l["box"][1]) < 3:
            continue
        why = _shaky(l, lab, img, f.get("off"))
        if why:
            f["sure"] = False
            f["msg"] = f["msg"].rstrip(".") + f" ({why} nên chưa chắc)."
    return out


def _shaky(l, lab, img, off=None):
    """Ly do tool khong chac mep cua vat: bi box khac che mot phan, hoac vung anh qua toi. None neu khong.
    off (canh lech, tu _edges): chi tinh 'bi che' khi MOI canh bi bao lech deu nam sau vat che (vat bi che thi
    nguoi gan dung o mep vat che, tool uoc luong qua). Khong co off (vd box dep / manh) -> bi che la du."""
    b = l["box"]
    others = [o["box"] for o in lab if o is not l and _inside(b, o["box"]) >= OCCLUDED_FRAC]
    if others:
        mid = {"left": (b[0], (b[1] + b[3]) / 2), "right": (b[2], (b[1] + b[3]) / 2),
               "top": ((b[0] + b[2]) / 2, b[1]), "bottom": ((b[0] + b[2]) / 2, b[3])}
        if not off or all(any(_contains(o, mid[k]) for o in others) for k in off):
            return "vật bị vật khác che một phần"
    if img is not None:
        x1, y1, x2, y2 = (int(max(0, v)) for v in b)
        crop = img[y1:max(y1 + 1, y2), x1:max(x1 + 1, x2)]
        if crop.size and float(crop.mean()) < DARK_MEAN:
            return "vùng ảnh quá tối"
    return None


def _check_size(out, l, t, W, H):
    x1, y1, x2, y2 = t["box"]
    if min(x2 - x1, y2 - y1) < MIN_CHECK_SIDE or l.get("occluded") or l.get("seg"):
        return
    v = L.iou(l["box"], t["box"])
    if v >= SIZE_IOU:
        return
    off = _edges(l["box"], t["box"], W, H, _refs(t))
    if not off:
        return
    sure = t["sure"] and t["box_ok"] and _off_rel(off, t["box"]) >= SIZE_SURE_REL
    out.append(dict(kind="sai_kich_thuoc", sure=sure, label=l["label"], box=l["box"], ref=l["id"], off=off,
                    msg=f"Box chưa khít: {_size_msg(off)}."))


def _check_shape(l, grp, W, H):
    """Box co ti le rong/cao phi ly voi loai vat (vd car rong 912px cao 14px). Bo qua chieu bi cat o mep anh."""
    rng = SHAPE_RANGE.get(grp)
    x1, y1, x2, y2 = l["box"]
    w, h = x2 - x1, y2 - y1
    if rng is None or w <= 0 or h <= 0:
        return None
    r = w / h
    if (r > 1 and (y1 <= 2 or y2 >= H - 2)) or (r < 1 and (x1 <= 2 or x2 >= W - 2)):
        return None           # vat bi mep anh cat -> dep / manh la binh thuong
    u_lo, u_hi, s_lo, s_hi = rng
    sure = r > s_hi or r < s_lo or min(w, h) < 3
    if not (sure or r > u_hi or r < u_lo):
        return None
    shape = "quá dẹt" if r > 1 else "quá mảnh"
    return dict(kind="sai_kich_thuoc", sure=sure, label=l["label"], box=l["box"], ref=l["id"],
                msg=f"Box '{l['label']}' {shape} ({w:.0f}×{h:.0f}px), không đúng 1 vật. Xoá và vẽ lại.")


def _miss_where(t, lab, bad):
    """Mo ta cho vat bi thieu: vi tri, co, va box da gan nam sat ben (de labeler khong nham la box do sai)."""
    x1, y1, x2, y2 = t["box"]
    s = []
    if max(x2 - x1, y2 - y1) < 40:
        s.append("vật nhỏ ở xa, phóng to để thấy")
    if any(i not in bad and _inside(t["box"], l["box"]) > 0 for i, l in enumerate(lab)):
        s.append("nằm sát box khác, cần box riêng")
    return f" ({', '.join(s)})" if s else ""


def analysis_data(lab, areas, tool, tool2job, job_group, finds, road_cls, road_names, W, H, seg_ref=None):
    """Du lieu cho che do xem 'Phan tich' tren web: nhan cua labeler, vat tool thay, mat duong model to, va doi chieu."""
    level, msgs = {}, {}
    for f in finds:
        if f.get("ref"):
            level[f["ref"]] = max(level.get(f["ref"], 0), 2 if f["sure"] else 1)
            msgs.setdefault(f["ref"], []).append(f["msg"])
    status = ("dung", "nghi", "loi")
    rd = lambda b: [round(float(v), 1) for v in b]
    T = [dict(box=rd(o["box"]), label=tool2job.get(o["cls"]) or o["cls"], cls=o["cls"], score=round(float(o["score"]), 2),
              sure=o.get("trang_thai") == "TU_DONG" and o["score"] >= SURE_SCORE) for o in tool]
    labs = []
    for l in lab:
        g = job_group.get(l["label"])
        best = max(((L.iou(l["box"], t["box"]), k) for k, t in enumerate(T) if GROUP.get(t["cls"]) == g), default=(0.0, None))
        labs.append(dict(id=l["id"], label=l["label"], box=rd(l["box"]), occluded=bool(l.get("occluded")),
                         status=status[level.get(l["id"], 0)], msgs=msgs.get(l["id"], []),
                         match=best[1] if best[0] >= NEAR_IOU else None, iou=round(best[0], 2)))
    used = {x["match"] for x in labs if x["match"] is not None}
    for k, t in enumerate(T):
        t["matched"] = k in used
    seg_ref = seg_ref or {}
    out_areas = [dict(id=a["id"], label=a["label"], kind=a["kind"], polys=area_check.outlines(a["mask"], 20, 1.5),
                      road=a["label"] in road_names, status=status[level.get(a["id"], 0)], msgs=msgs.get(a["id"], []),
                      ref_polys=area_check.outlines(seg_ref[a["id"]]["mask"], 20, 1.5) if a["id"] in seg_ref else None,
                      ref_iou=seg_ref[a["id"]]["iou"] if a["id"] in seg_ref else None)
                 for a in areas]
    road = None
    if road_cls is not None:
        rm = road_cls == area_check.ROAD
        lab_m = np.zeros_like(rm)
        for a in areas:
            if a["label"] in road_names:
                lab_m |= a["mask"]
        n = float(rm.size)
        road = dict(polys=area_check.outlines(rm), model_pct=round(rm.sum() / n * 100, 1), label_pct=round(lab_m.sum() / n * 100, 1),
                    both_pct=round((rm & lab_m).sum() / n * 100, 1))
    missing = [dict(label=f["label"], box=rd(f["box"]), sure=f["sure"], msg=f["msg"], kind=f["kind"],
                    poly=f.get("poly")) for f in finds if not f.get("ref")]
    return dict(W=W, H=H, labels=labs, tool=T, areas=out_areas, road=road, missing=missing)


def _inside(a, b):
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))
    return ix / max(1e-6, (a[2] - a[0]) * (a[3] - a[1]))


def _contains(b, p):
    return b[0] <= p[0] <= b[2] and b[1] <= p[1] <= b[3]


def _fmt(b):
    return f"({b[0]:.0f},{b[1]:.0f})-({b[2]:.0f},{b[3]:.0f})"


# ---------------------------------------------------------------------------
# CVAT API
# ---------------------------------------------------------------------------

class Cvat:
    def __init__(self, url, token, org=None):
        self.url = url.rstrip("/")
        self.s = requests.Session()
        if org:                                    # CVAT co to chuc: thieu header nay se bi 401/403 hoac khong thay job
            self.s.headers["X-Organization"] = org
        self.s.headers["Authorization"] = f"Bearer {token}"
        r = self.s.get(f"{self.url}/api/users/self", timeout=20)
        if r.status_code == 401:                   # token kieu cu (Token ...)
            self.s.headers["Authorization"] = f"Token {token}"
            r = self.s.get(f"{self.url}/api/users/self", timeout=20)
        if r.status_code == 401:
            raise RuntimeError("Token sai hoặc đã hết hạn (CVAT trả 401).")
        r.raise_for_status()
        self.user = r.json()

    def get(self, path, **params):
        for k in range(4):
            r = self.s.get(f"{self.url}{path}", params=params, timeout=120)
            if r.status_code < 500:
                break
            time.sleep(2 * (k + 1))
        if r.status_code == 403:
            raise RuntimeError(f"Tài khoản '{self.user.get('username')}' không có quyền vào {path}.")
        if r.status_code == 404:
            raise RuntimeError(f"Không tìm thấy {path} trên CVAT (sai số job/task?).")
        r.raise_for_status()
        return r

    def job(self, job_id):
        return self.get(f"/api/jobs/{job_id}").json()

    def frames(self, job_id, job):
        """[(so frame tuyet doi, ten file, w, h)] cua job"""
        m = self.get(f"/api/jobs/{job_id}/data/meta").json()
        start, stop = m.get("start_frame", job["start_frame"]), m.get("stop_frame", job["stop_frame"])
        step = 1
        mm = re.search(r"step\s*=\s*(\d+)", m.get("frame_filter") or "")
        if mm:
            step = int(mm.group(1))
        deleted = set(m.get("deleted_frames") or [])
        nums = m.get("included_frames") or list(range(start, stop + 1, step))
        fr = m["frames"]
        out = []
        for i, n in enumerate(nums):
            info = fr[i] if len(fr) == len(nums) else fr[min(len(fr) - 1, n - start)] if fr else {}
            if n in deleted:
                continue
            out.append((n, info.get("name", f"frame_{n:06d}"), info.get("width"), info.get("height")))
        return out, start

    def labels(self, job_id, task_id):
        res = self.get("/api/labels", job_id=job_id, page_size=500).json()["results"]
        if not res:
            res = self.get("/api/labels", task_id=task_id, page_size=500).json()["results"]
        return res

    def annotations(self, job_id):
        return self.get(f"/api/jobs/{job_id}/annotations").json()

    def image(self, job_id, frame, start):
        last = None
        for number in (frame, frame - start):       # CVAT moi: so tuyet doi; ban cu: so trong job
            for q in ("original", "compressed"):
                r = self.s.get(f"{self.url}/api/jobs/{job_id}/data",
                               params=dict(type="frame", number=number, quality=q), timeout=120)
                if r.ok:
                    a = cv2.imdecode(np.frombuffer(r.content, np.uint8), cv2.IMREAD_COLOR)
                    if a is not None:
                        return a[:, :, ::-1].copy()
                last = r
        raise RuntimeError(f"Không tải được ảnh frame {frame}: {last.status_code if last is not None else '?'}")

    def issues(self, job_id):
        out, page = [], 1
        while True:
            r = self.get("/api/issues", job_id=job_id, page=page, page_size=100).json()
            out += r["results"]
            if not r.get("next"):
                return out
            page += 1

    def first_comment(self, issue_id):
        r = self.get("/api/comments", issue_id=issue_id, page_size=1, sort="id").json()["results"]
        return r[0]["message"] if r else ""

    def create_issue(self, job_id, frame, box, message, poly=None):
        """poly: [x1, y1, x2, y2, ...] — ghim theo dung hinh vung (vd mat duong), khong co thi ghim theo box."""
        if poly and len(poly) >= 6:
            pos = [round(float(v), 2) for v in poly]
        else:
            x1, y1, x2, y2 = [round(float(v), 2) for v in box]
            pos = [x1, y1, x2, y1, x2, y2, x1, y2]
        payload = dict(job=job_id, frame=frame, position=pos, message=message)
        for k in range(4):
            r = self.s.post(f"{self.url}/api/issues", json=payload, timeout=60)
            if r.status_code < 500:
                break
            time.sleep(2 * (k + 1))
        if not r.ok:
            raise RuntimeError(f"Tạo Issue lỗi {r.status_code}: {r.text[:300]}")
        return r.json()

    def comment_count(self, issue_id):
        return self.get("/api/comments", issue_id=issue_id, page_size=1).json().get("count", 0)

    def resolve_issue(self, issue_id):
        r = self.s.patch(f"{self.url}/api/issues/{issue_id}", json=dict(resolved=True), timeout=60)
        if not r.ok:
            raise RuntimeError(f"Đóng Issue {issue_id} lỗi {r.status_code}: {r.text[:200]}")

    def delete_issue(self, issue_id):
        r = self.s.delete(f"{self.url}/api/issues/{issue_id}", timeout=60)
        if r.status_code not in (204, 404):
            raise RuntimeError(f"Xoá Issue {issue_id} lỗi {r.status_code}: {r.text[:200]}")


def boxes_from_cvat(ann, id2label, frames):
    """{frame: [dict(id, label, box, occluded)]} — rectangle cua shape + track (noi suy giua cac keyframe)."""
    want = set(frames)
    per = {f: [] for f in frames}
    for s in ann.get("shapes", []):
        if s.get("type") == "rectangle" and s["frame"] in want and s["label_id"] in id2label:
            per[s["frame"]].append(dict(id=f"shape {s['id']}", label=id2label[s["label_id"]], box=_rect(s["points"]),
                                        occluded=bool(s.get("occluded")), rotation=s.get("rotation", 0)))
    for t in ann.get("tracks", []):
        if t["label_id"] not in id2label:
            continue
        ks = sorted([k for k in t["shapes"] if k.get("type", "rectangle") == "rectangle"], key=lambda k: k["frame"])
        if not ks:
            continue
        for f in frames:
            prev = [k for k in ks if k["frame"] <= f]
            if not prev or prev[-1].get("outside"):
                continue
            a = prev[-1]
            nxt = [k for k in ks if k["frame"] > f]
            box = _rect(a["points"])
            if nxt and a["frame"] != f and not nxt[0].get("outside"):
                b = nxt[0]
                r = (f - a["frame"]) / (b["frame"] - a["frame"])
                box = [p + r * (q - p) for p, q in zip(_rect(a["points"]), _rect(b["points"]))]
            per[f].append(dict(id=f"track {t['id']}", label=id2label[t["label_id"]], box=box,
                               occluded=bool(a.get("occluded")), rotation=a.get("rotation", 0), keyframe=a["frame"] == f))
    return per


def shape_track_check(ann, id2label, frames, task_mode=None, cb=None):
    """Kieu nhan dung chua: guideline (KIEU_NHAN) yeu cau shape ma labeler dung track (hoac nguoc lai).
    Khong co guideline: task anh roi (mode 'annotation', vd BDD100K) ma co track -> "khong chac".
    Tra ve {frame: [finding]} — ghi chu dat o keyframe dau tien cua track / shape trong job."""
    want = KIEU_NHAN or ("shape" if task_mode == "annotation" else None)
    if want is None:
        return {}
    sure = KIEU_NHAN is not None
    in_job = {n for n, _, _, _ in frames}
    out = {}
    ref = " (theo guideline)" if sure else " (task là ảnh rời)"
    if want == "shape":
        for t in ann.get("tracks", []):
            ks = sorted([k for k in t.get("shapes", []) if not k.get("outside") and k["frame"] in in_job], key=lambda k: k["frame"])
            if not ks or t["label_id"] not in id2label:
                continue
            k = ks[0]
            p = [float(v) for v in k["points"]]
            box = _rect(p) if k.get("type", "rectangle") == "rectangle" else [min(p[0::2]), min(p[1::2]), max(p[0::2]), max(p[1::2])]
            out.setdefault(k["frame"], []).append(dict(
                kind="sai_kieu", sure=sure, label=id2label[t["label_id"]], box=box, ref=f"track {t['id']}", tang=1,
                msg=f"'{id2label[t['label_id']]}' đang gán bằng Track ({len(ks)} khung), cần gán bằng Shape{ref}: "
                    f"mỗi ảnh là 1 ảnh riêng, vật không nối qua các khung."))
    elif want == "track" and len(in_job) > 1:
        for sh in ann.get("shapes", []):
            if sh["frame"] in in_job and sh["label_id"] in id2label and sh.get("type") in ("rectangle", "polygon", "mask"):
                p = [float(v) for v in sh["points"]]
                box = _rect(p) if sh["type"] == "rectangle" else [min(p[0::2]), min(p[1::2]), max(p[0::2]), max(p[1::2])]
                out.setdefault(sh["frame"], []).append(dict(
                    kind="sai_kieu", sure=sure, label=id2label[sh["label_id"]], box=box, ref=f"shape {sh['id']}", tang=1,
                    msg=f"'{id2label[sh['label_id']]}' đang gán bằng Shape, cần gán bằng Track{ref} để nối vật qua các khung."))
    n = sum(len(v) for v in out.values())
    if n:
        log(f"  Kiểu nhãn: cần {want.upper()}{ref} — {n} {'track' if want == 'shape' else 'shape'} gán sai kiểu.", cb)
    return out


ID_VI = {"doi_vat": "đổi vật (ID switch)", "trao_id": "tráo ID", "mot_vat_2_id": "1 vật 2 ID", "hai_id_1_vat": "2 ID 1 vật",
         "ket_thuc_som": "track kết thúc sớm", "kich_thuoc": "kích thước không đồng bộ",
         "kich_thuoc_nhay": "kích thước nhảy ở 1 keyframe"}
TRACK_GAP = 3            # track B bat dau trong vong 3 khung sau khi track A ket thuc, cung cho -> co the dut track
TRACK_JOIN_IOU = 0.4
TRACK_JUMP = 1.0         # tam box nhay xa hon 1.0 lan canh dai cua box giua 2 keyframe gan nhau -> nghi nham vat


def _kbox(k):
    p = [float(v) for v in k["points"]]
    t = k.get("type", "rectangle")
    if t == "rectangle":
        return _rect(p)
    if t == "mask":
        return [p[-4], p[-3], p[-2] + 1, p[-1] + 1]
    return [min(p[0::2]), min(p[1::2]), max(p[0::2]), max(p[1::2])]


def track_check(ann, id2label, frames, cb=None):
    """Loi rieng cua track (job video / guideline dung track). Tra ve {frame: [finding]} (deu 'khong chac', nguoi xem lai):
      - dut track: 1 vat bi tach thanh 2 track noi tiep (A het o khung f, B cung nhan bat dau ngay sau, cung cho)
      - nhay vi tri: giua 2 keyframe gan nhau box nhay xa -> co the track chuyen nham sang vat khac"""
    in_job = sorted({n for n, _, _, _ in frames})
    if len(in_job) < 2:
        return {}
    last = in_job[-1]
    segs = []                                  # (track, nhan, khung dau, box dau, khung cuoi, box cuoi)
    out = {}
    for t in ann.get("tracks", []):
        if t["label_id"] not in id2label:
            continue
        ks = sorted(t.get("shapes", []), key=lambda k: k["frame"])
        vis = [k for k in ks if not k.get("outside")]
        if not vis:
            continue
        lb = id2label[t["label_id"]]
        end_k = vis[-1]
        after = [k for k in ks if k["frame"] > end_k["frame"] and k.get("outside")]
        end_f = (after[0]["frame"] - 1) if after else last
        segs.append((t, lb, vis[0]["frame"], _kbox(vis[0]), end_f, _kbox(end_k)))
        jumped_from = None                     # box truoc cu nhay: nhay di roi nhay ve cho cu chi bao 1 lan
        for a, b in zip(vis, vis[1:]):
            if b["frame"] - a["frame"] > TRACK_GAP or any(k.get("outside") and a["frame"] < k["frame"] < b["frame"] for k in ks):
                jumped_from = None
                continue
            ba, bb = _kbox(a), _kbox(b)
            if jumped_from is not None and L.iou(jumped_from, bb) >= 0.5:
                jumped_from = None
                continue
            ca, cb_ = ((ba[0] + ba[2]) / 2, (ba[1] + ba[3]) / 2), ((bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2)
            size = max(ba[2] - ba[0], ba[3] - ba[1], 1.0)
            moved = ((ca[0] - cb_[0]) ** 2 + (ca[1] - cb_[1]) ** 2) ** 0.5
            if moved > TRACK_JUMP * size * (b["frame"] - a["frame"]) and L.iou(ba, bb) < 0.1:
                out.setdefault(b["frame"], []).append(dict(
                    kind="track", sure=False, label=lb, box=bb, ref=f"track {t['id']}", tang=1,
                    msg=f"Track '{lb}' nhảy xa {moved:.0f}px từ khung {a['frame']} sang {b['frame']}: "
                        f"có thể đã chuyển nhầm sang vật khác, kiểm tra lại."))
                jumped_from = ba
            else:
                jumped_from = None
    for A in segs:
        for B in segs:
            if A is B or A[1] != B[1]:
                continue
            if A[4] < B[2] <= A[4] + TRACK_GAP and B[2] in set(in_job) and L.iou(A[5], B[3]) >= TRACK_JOIN_IOU:
                out.setdefault(B[2], []).append(dict(
                    kind="track", sure=False, label=B[1], box=B[3], ref=f"track {B[0]['id']}", tang=1,
                    msg=f"Có thể đứt track: track '{B[1]}' này bắt đầu ở khung {B[2]}, ngay sau khi track {A[0]['id']} "
                        f"(cùng nhãn, cùng chỗ) kết thúc ở khung {A[4]}. Nếu là 1 vật thì nối thành 1 track."))
    n = sum(len(v) for v in out.values())
    if n:
        log(f"  Track: {n} chỗ nghi đứt track / nhảy vị trí (đang xem xét, cần người xem).", cb)
    return out


def _rect(p):
    x1, y1, x2, y2 = [float(v) for v in p[:4]]
    return [min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)]


def canon(ann):
    """Ban rut gon de so sanh truoc/sau (bo 'version' — CVAT tang version moi khi co thay doi)."""
    def strip(x):
        return {k: v for k, v in x.items() if k not in ("version",)}
    return json.dumps(dict(tags=sorted([json.dumps(strip(x), sort_keys=True) for x in ann.get("tags", [])]),
                           shapes=sorted([json.dumps(strip(x), sort_keys=True) for x in ann.get("shapes", [])]),
                           tracks=sorted([json.dumps(strip(x), sort_keys=True) for x in ann.get("tracks", [])])), sort_keys=True)


# ---------------------------------------------------------------------------
# Doc file export (CVAT for images 1.1 / YOLO 1.1 / COCO 1.0 / chi anh)
# ---------------------------------------------------------------------------

IMG_EXT = (".jpg", ".jpeg", ".png", ".bmp", ".webp")


def read_export(path):
    """Tra ve dict(images={ten goc: bytes}, ann={ten goc: [dict(id,label,box,occluded)]} | None, fmt, labels)"""
    z = zipfile.ZipFile(path)
    names = z.namelist()
    images = {os.path.basename(n): n for n in names if n.lower().endswith(IMG_EXT)}
    res = dict(images={k: z.read(v) for k, v in images.items()}, ann=None, fmt="chỉ có ảnh", labels=[],
               areas={}, raw_areas={}, has_seg=False)
    xmls = [n for n in names if n.lower().endswith("annotations.xml")]
    cocos = [n for n in names if n.lower().endswith(".json") and "instances" in os.path.basename(n).lower()]
    yolo_names = [n for n in names if os.path.basename(n) in ("obj.names", "classes.txt")]
    if xmls:
        root = ET.fromstring(z.read(xmls[0]))
        res["fmt"] = "CVAT for images 1.1"
        res["labels"] = [e.findtext("name") for e in root.iter("label") if e.findtext("name")]
        ann = {}
        res["has_seg"] = True           # file CVAT co the chua polygon / mask -> review ca nhan vung
        for im in root.iter("image"):
            nm = os.path.basename(im.get("name"))
            ann[nm] = [dict(id=f"box {k}", label=b.get("label"), occluded=b.get("occluded") == "1",
                            box=[float(b.get("xtl")), float(b.get("ytl")), float(b.get("xbr")), float(b.get("ybr"))])
                       for k, b in enumerate(im.findall("box"))]
            W, H = int(float(im.get("width") or 0)), int(float(im.get("height") or 0))
            for k, e in enumerate(im.findall("polygon")):
                pts = [float(v) for xy in (e.get("points") or "").split(";") if xy for v in xy.split(",")]
                _add_area(res, nm, f"polygon {k}", e.get("label"), "polygon", pts, W, H)
            for k, e in enumerate(im.findall("mask")):
                l, t = int(float(e.get("left"))), int(float(e.get("top")))
                w, h = int(float(e.get("width"))), int(float(e.get("height")))
                rle = [int(v) for v in (e.get("rle") or "").replace(" ", "").split(",") if v]
                _add_area(res, nm, f"mask {k}", e.get("label"), "mask", rle + [l, t, l + w - 1, t + h - 1], W, H)
        if not ann:     # export dang video (track)
            raise RuntimeError("File XML là dạng 'CVAT for video'. Hãy export 'CVAT for images 1.1'.")
        res["ann"] = ann
    elif cocos:
        d = json.loads(z.read(cocos[0]))
        res["fmt"] = "COCO 1.0"
        cats = {c["id"]: c["name"] for c in d["categories"]}
        res["labels"] = list(cats.values())
        ims = {i["id"]: os.path.basename(i["file_name"]) for i in d["images"]}
        size = {i["id"]: (int(i.get("width") or 0), int(i.get("height") or 0)) for i in d["images"]}
        ann = {n: [] for n in ims.values()}
        for a in d["annotations"]:
            seg = a.get("segmentation")
            if seg:                     # co segmentation -> la polygon / mask (CVAT export box voi segmentation rong)
                res["has_seg"] = True
                W, H = size[a["image_id"]]
                if isinstance(seg, list):
                    parts = [p for p in seg if len(p) >= 2]
                    _add_area(res, ims[a["image_id"]], f"ann {a['id']}", cats[a["category_id"]], "polygon",
                              max(parts, key=len) if parts else [], W, H, extra=parts[1:] if len(parts) > 1 else None)
                elif isinstance(seg, dict) and isinstance(seg.get("counts"), list):
                    m = np.zeros(W * H, np.uint8)        # RLE COCO khong nen: dem theo COT
                    pos, val = 0, 0
                    for c in seg["counts"]:
                        if val:
                            m[pos:pos + c] = 1
                        pos += c
                        val ^= 1
                    _add_area(res, ims[a["image_id"]], f"ann {a['id']}", cats[a["category_id"]], "mask", None, W, H,
                              mask=m.reshape(W, H).T.astype(bool))
                continue
            x, y, w, h = a["bbox"]
            ann[ims[a["image_id"]]].append(dict(id=f"ann {a['id']}", label=cats[a["category_id"]], box=[x, y, x + w, y + h],
                                                occluded=bool(a.get("attributes", {}).get("occluded"))))
        res["ann"] = ann
    elif yolo_names:
        cls = [l.strip() for l in z.read(yolo_names[0]).decode("utf-8").splitlines() if l.strip()]
        res["fmt"] = "YOLO 1.1"
        res["labels"] = cls
        txt = {os.path.splitext(os.path.basename(n))[0]: n for n in names if n.lower().endswith(".txt")
               and os.path.basename(n) not in ("obj.names", "classes.txt", "train.txt", "valid.txt", "obj.data")}
        ann = {}
        for nm, data in res["images"].items():
            im = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
            h, w = im.shape[:2]
            rows = []
            st = os.path.splitext(nm)[0]
            if st in txt:
                for k, line in enumerate(z.read(txt[st]).decode("utf-8").splitlines()):
                    p = line.split()
                    if len(p) >= 5:
                        c, cx, cy, bw, bh = int(p[0]), *map(float, p[1:5])
                        rows.append(dict(id=f"dòng {k + 1}", label=cls[c], occluded=False,
                                         box=[(cx - bw / 2) * w, (cy - bh / 2) * h, (cx + bw / 2) * w, (cy + bh / 2) * h]))
            ann[nm] = rows
        res["ann"] = ann
    return res


def _add_area(res, name, oid, label, kind, points, W, H, extra=None, mask=None):
    """Them 1 polygon / mask doc tu file vao res['areas'] (co mask de review) va res['raw_areas'] (cho tang luat)."""
    if kind == "polygon":
        xs, ys = (points or [])[0::2], (points or [])[1::2]
        box = [min(xs), min(ys), max(xs), max(ys)] if xs else None
    elif mask is None:
        box = [float(points[-4]), float(points[-3]), float(points[-2]) + 1, float(points[-1]) + 1]
    else:
        box = None
    if mask is None and W and H and points:
        mask = area_check._to_mask(dict(type=kind, points=points), W, H)
        if mask is not None and extra:      # polygon COCO nhieu manh
            for p in extra:
                if len(p) >= 6:
                    mask |= area_check._to_mask(dict(type="polygon", points=p), W, H)
    if mask is not None and mask.any():
        ys, xs = np.nonzero(mask)
        mb = [float(xs.min()), float(ys.min()), float(xs.max() + 1), float(ys.max() + 1)]
        res["areas"].setdefault(name, []).append(dict(id=oid, label=label, kind=kind, mask=mask, box=mb,
                                                      points=points if kind == "polygon" else None))
        box = box or mb
    if box is not None:
        res["raw_areas"].setdefault(name, []).append(dict(id=oid, label=label, kind=kind, box=box,
                                                          points=points if kind == "polygon" else None))


# ---------------------------------------------------------------------------
# Ve anh xem truoc: box nguoi gan (trang mong) + ghi chu (do = loi, vang = khong chac)
# ---------------------------------------------------------------------------

def draw_review(img, lab, finds, path):
    out = img[:, :, ::-1].copy()
    for l in lab:
        x1, y1, x2, y2 = [int(round(v)) for v in l["box"]]
        cv2.rectangle(out, (x1, y1), (x2, y2), (235, 235, 235), 1)
    for n, f in enumerate(finds, 1):
        x1, y1, x2, y2 = [int(round(v)) for v in f["box"]]
        col = (40, 40, 255) if f["sure"] else (0, 210, 255)
        if f["kind"] == "thieu":
            for i in range(x1, x2, 12):
                cv2.line(out, (i, y1), (min(i + 6, x2), y1), col, 2)
                cv2.line(out, (i, y2), (min(i + 6, x2), y2), col, 2)
            for i in range(y1, y2, 12):
                cv2.line(out, (x1, i), (x1, min(i + 6, y2)), col, 2)
                cv2.line(out, (x2, i), (x2, min(i + 6, y2)), col, 2)
        else:
            cv2.rectangle(out, (x1, y1), (x2, y2), col, 2)
        if f.get("poly"):                   # vung (mat duong): to theo dung hinh
            pts = np.round(np.array(f["poly"]).reshape(-1, 2)).astype(np.int32)
            ov = out.copy()
            cv2.fillPoly(ov, [pts], col)
            out = cv2.addWeighted(ov, 0.25, out, 0.75, 0)
            cv2.polylines(out, [pts], True, col, 2)
        txt = str(n)
        (tw, th), _ = cv2.getTextSize(txt, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
        ty = y1 - 4 if y1 > th + 6 else y2 + th + 4
        cv2.rectangle(out, (x1, ty - th - 3), (x1 + tw + 4, ty + 3), col, -1)
        cv2.putText(out, txt, (x1 + 2, ty), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2, cv2.LINE_AA)
    _imwrite(path, out, [cv2.IMWRITE_JPEG_QUALITY, 88])


KIND_VI = {"sai_kich_thuoc": "Sai kích thước", "sai_nhan": "Sai nhãn", "thieu": "Thiếu", "thua": "Thừa", "trung": "Trùng",
           "sai_vien": "Sai viền", "ngoai_anh": "Ra ngoài ảnh", "polygon_hong": "Polygon hỏng", "sai_kieu": "Sai kiểu (shape/track)", "track": "Track bất thường",
           "ghi_chu": "Ghi chú người review", "tong_ket": "Tổng kết",
           "guideline": "Vi phạm guideline"}


# ---------------------------------------------------------------------------
# Chay review
# ---------------------------------------------------------------------------

class Review:
    """Mot lan review. Giu lai ket qua de day len CVAT sau."""

    def __init__(self):
        self.findings = []      # dict(frame, name, kind, sure, label, box, msg, ref)
        self.frames = []        # (frame, name, n_boxes, preview_path)
        self.stats = {}
        self.job_id = None
        self.cvat = None
        self.before = None
        self.out_dir = None
        self.skipped_labels = []

    def run(self, url=None, token=None, task_id=None, job_id=None, zip_path=None, mode="chinh_xac", org=None,
            rider_person=True, cb=None, runner=None, max_frames=None):
        t0 = time.time()
        ts = time.strftime("%Y%m%d_%H%M%S")
        self.job_id = int(job_id) if job_id else None
        self.out_dir = os.path.join(OUT_ROOT, f"job{self.job_id or 'file'}_{ts}")
        for sub in ("preview", "analysis", "goc"):
            os.makedirs(os.path.join(self.out_dir, sub), exist_ok=True)

        export = read_export(zip_path) if zip_path else None
        areas = {}                         # {frame: [polygon / mask]} — chi co khi doc tu CVAT
        extra = {}                         # {frame: [ghi chu]} — loi cap job (vd dung track thay vi shape)
        mode = None                        # 'annotation' (anh roi) / 'interpolation' (video) — doc tu task CVAT
        labels, tags = [], {}              # dinh nghia nhan + tag (nhan cho ca anh) theo frame — chi co khi doc tu CVAT
        from_cvat = False
        if export:
            log(f"File: {export['fmt']}, {len(export['images'])} ảnh", cb)
        items = []                         # (frame | None, name, loader, boxes)
        if self.job_id:
            if not (url and token):
                raise RuntimeError("Có số job thì phải có CVAT_URL và CVAT_TOKEN.")
            self.cvat = Cvat(url, token, org)
            log(f"Đã kết nối CVAT {url} (tài khoản {self.cvat.user.get('username')})", cb)
            job = self.cvat.job(self.job_id)
            if task_id and int(task_id) != job["task_id"]:
                raise RuntimeError(f"Job {self.job_id} thuộc task {job['task_id']}, không phải task {task_id}. Kiểm tra lại số.")
            if job.get("dimension") == "3d":
                raise RuntimeError("Đây là job 3D. Trang này hiện chỉ review job 2D.")
            labels = self.cvat.labels(self.job_id, job["task_id"])
            id2label = {lb["id"]: lb["name"] for lb in labels}
            label_names = [lb["name"] for lb in labels]
            frames, start = self.cvat.frames(self.job_id, job)
            self.before = self.cvat.annotations(self.job_id)
            json.dump(self.before, open(os.path.join(self.out_dir, "annotations_truoc_review.json"), "w", encoding="utf-8"),
                      ensure_ascii=False)
            log(f"Job {self.job_id} (task {job['task_id']}): {len(frames)} frame, "
                f"{len(self.before.get('shapes', []))} shape, {len(self.before.get('tracks', []))} track. Đã lưu bản sao.", cb)
            n_area = sum(1 for s in self.before.get("shapes", []) if s.get("type") in ("polygon", "mask"))
            n_other = sum(1 for s in self.before.get("shapes", []) if s.get("type") not in ("rectangle", "polygon", "mask"))
            if n_area:
                log(f"  {n_area} polygon / mask: kiểm tra trùng, và so với mặt đường nếu là nhãn vùng đường.", cb)
            if n_other:
                log(f"  Lưu ý: {n_other} shape dạng khác (point, polyline...) — không review.", cb)
            per = boxes_from_cvat(self.before, id2label, [f[0] for f in frames])
            areas = area_check.areas_from_cvat(self.before, id2label, [f[0] for f in frames],
                                               {n: (w, h) for n, _, w, h in frames})
            raw = {}
            for sh in self.before.get("shapes", []):
                raw.setdefault(sh["frame"], []).append(sh)
            for t in self.before.get("tracks", []):        # keyframe polygon / mask cua track cung qua tang luat
                for k in t.get("shapes", []):
                    if k.get("type") in ("polygon", "mask") and not k.get("outside"):
                        raw.setdefault(k["frame"], []).append(dict(k, id=t["id"], label_id=t["label_id"], _ref=f"track {t['id']}"))
            raw = {n: rule_tier.raw_areas(v, id2label) for n, v in raw.items()}
            mode = self._task_mode(job)
            extra = shape_track_check(self.before, id2label, frames, mode, cb)
            if (KIEU_NHAN or ("shape" if mode == "annotation" else None)) != "shape":
                for n, fs in track_check(self.before, id2label, frames, cb).items():
                    extra.setdefault(n, []).extend(fs)
            for t in self.before.get("tags", []):
                tags.setdefault(t["frame"], []).append(t)
            from_cvat = not (export and export["ann"] is not None)
            if export and export["ann"] is not None:
                log("  Dùng nhãn trong file tải lên (ảnh khớp theo tên với frame của job).", cb)
            for n, name, w, h in frames:
                base = os.path.basename(name)
                if export and export["ann"] is not None:
                    if base not in export["ann"]:
                        continue
                    boxes = export["ann"][base]
                    alist, rlist = export["areas"].get(base, []), export["raw_areas"].get(base, [])
                else:
                    boxes = per[n]
                    alist, rlist = areas.get(n, []), raw.get(n, [])
                if export and base in export["images"]:
                    data = export["images"][base]
                    loader = (lambda d=data: cv2.imdecode(np.frombuffer(d, np.uint8), cv2.IMREAD_COLOR)[:, :, ::-1].copy())
                else:
                    loader = (lambda n=n: self.cvat.image(self.job_id, n, start))
                items.append((n, base, loader, boxes, alist, rlist))
        else:
            if not export or export["ann"] is None:
                raise RuntimeError("Không có số job thì phải tải lên file export có nhãn (CVAT for images / COCO / YOLO).")
            label_names = export["labels"]
            for base in sorted(export["ann"]):
                if base not in export["images"]:
                    continue
                data = export["images"][base]
                items.append((None, base, (lambda d=data: cv2.imdecode(np.frombuffer(d, np.uint8), cv2.IMREAD_COLOR)[:, :, ::-1].copy()),
                              export["ann"][base], export["areas"].get(base, []), export["raw_areas"].get(base, [])))
            log("Không có số job: chỉ đánh giá, không đẩy lên CVAT.", cb)
        if max_frames:
            items = items[:int(max_frames)]

        tool2job, job_group, self.skipped_labels = build_label_map(label_names)
        # review DU moi nhan cua task tren moi anh: vung duong cham ca khi labeler chua ve polygon nao,
        # nhan cho ca anh (tag, vd image_info / weather) cham ca khi anh chua gan
        seg_ok = from_cvat or bool(export and export.get("has_seg"))
        road_names = area_check.road_labels(label_names) if seg_ok else []
        used = {x["label_id"] for x in (self.before or {}).get("shapes", []) + (self.before or {}).get("tracks", [])}
        flabels = frame_check.frame_labels(labels, set(job_group) | set(road_names), used) if from_cvat else []
        done = set(road_names) | {f["name"] for f in flabels}
        self.skipped_labels = [n for n in self.skipped_labels if n not in done]
        log("Khớp nhãn: " + ", ".join(f"{c}→{j}" for c, j in tool2job.items() if j), cb)
        if road_names:
            log(f"  Nhãn vùng đường: {', '.join(road_names)} — so với model phân vùng mặt đường.", cb)
        for fl in flabels:
            log(f"  Nhãn cho cả ảnh: {fl['name']}" + (f" ({', '.join(a['name'] for a in fl['attrs'])})" if fl["attrs"] else "")
                + " — kiểm tra mỗi ảnh có gán chưa và giá trị có hợp với ảnh không.", cb)
        if self.skipped_labels:
            log(f"  Tool KHÔNG đánh giá được các nhãn: {', '.join(self.skipped_labels)} (bỏ qua, không ghi chú).", cb)
        if not job_group:
            raise RuntimeError("Không nhãn nào của job khớp với loại tool nhận ra (xe, xe máy, người...).")

        n_obj = sum(len(seg_check.object_areas(it[4], road_names, job_group)) for it in items)
        if n_obj:
            log(f"  {n_obj} polygon / mask của vật: so viền với mask SAM2 (vẽ lẹm, tô thừa ra nền, lệch vật).", cb)
        pair = area_check.MASK_WITH_BOX == "cap"
        runner = runner or ToolRunner(mode, cb)
        seg = runner.road_seg(cb) if road_names else None
        sam = runner.seg_sam(cb) if n_obj else None
        # job anh roi (guideline / task la shape): track da bi bao "can Shape", khong cham ID them cho do nhieu
        has_tracks = bool((self.before or {}).get("tracks")) and from_cvat and             (KIEU_NHAN or ("shape" if mode == "annotation" else None)) != "shape"
        idc = id_check.Collector(runner.clf, job_group) if has_tracks else None
        if idc:
            log("  Job có track: kiểm tra ID (đổi vật, tráo ID, 1 vật 2 ID, 2 ID 1 vật, track kết thúc sớm).", cb)
        st = dict(frames=0, boxes=0, ok=0, sure=0, unsure=0)
        from concurrent.futures import ThreadPoolExecutor
        pool = ThreadPoolExecutor(max_workers=4)
        futs = {}

        def prefetch(i):
            if i < len(items) and i not in futs:
                futs[i] = pool.submit(items[i][2])

        for i in range(4):
            prefetch(i)
        for idx, (n, base, loader, boxes, alist, rlist) in enumerate(items, 1):
            prefetch(idx + 3)
            img = futs.pop(idx - 1).result()
            H, W = img.shape[:2]
            lab = [b for b in boxes if b["label"] in job_group]
            rot = [b for b in lab if abs(b.get("rotation") or 0) > 0.5]
            # polygon / mask cua vat chua co box di kem cung la 1 nhan cua vat (khong thi tool bao "thieu" oan)
            lab += [dict(id=a["id"], label=a["label"], box=a["box"], occluded=False, seg=a["kind"])
                    for a in seg_check.object_areas(alist, road_names, job_group)
                    if not any(b["label"] == a["label"] and L.iou(b["box"], a["box"]) >= 0.5 for b in boxes)]
            # tang luat hinh hoc (nhanh, khong can model) chay truoc
            finds = list(extra.get(n, [])) + rule_tier.check(boxes, rlist, W, H, pair_mode=pair, shape_known=job_group, job_group=job_group)
            key = hashlib.sha1(img.tobytes()).hexdigest()[:20]
            tool, rejected = runner.detect(img, key)
            finds += compare(lab, tool, rejected, W, H, tool2job, job_group, img=img, runner=runner, rider_person=rider_person)
            for b in rot:
                finds.append(dict(kind="sai_kich_thuoc", sure=False, label=b["label"], box=b["box"], ref=b["id"],
                                  msg=f"Box bị xoay {b['rotation']:.0f}°, tool không kiểm tra được, xem lại."))
            seg_ref = {}
            if sam is not None and alist:
                finds += seg_check.check(alist, tool, img, sam, job_group, GROUP.get, road_names, keep_ref=seg_ref)
            if any(a.get("mask") is not None for a in alist) or seg is not None:
                finds += area_check.check(alist, boxes, img, seg, road_names)
            if idc:
                idc.add(n, img, tool, lab, GROUP.get)
            seen, uniq = set(), []          # 1 vat 1 loai loi chi giu 1 ghi chu (luat va model cung bat)
            for f in finds:
                k = (f["kind"], f["ref"]) if f.get("ref") else id(f)
                if k not in seen:
                    seen.add(k)
                    uniq.append(f)
            finds = uniq
            if flabels:
                finds += frame_check.check(img, tags.get(n, []), flabels, runner.clf)
            bad_refs = {f["ref"] for f in finds if f["ref"] and f["sure"]}
            st["frames"] += 1
            st["boxes"] += len(lab)
            st["ok"] += len(lab) - len(bad_refs & {b["id"] for b in lab})
            st["sure"] += sum(f["sure"] for f in finds)
            st["unsure"] += sum(not f["sure"] for f in finds)
            for f in finds:
                f.update(frame=n, name=base)
            stem = f"{idx:04d}_{os.path.splitext(base)[0][:40]}"
            pv = os.path.join(self.out_dir, "preview", stem + ".jpg")
            draw_review(img, lab, finds, pv)
            # du lieu cho che do "Phan tich": anh goc + nhung gi tool thay + doi chieu
            an = analysis_data(lab, [a for a in alist if a.get("mask") is not None], tool, tool2job, job_group, finds,
                               seg(img) if seg is not None else None, road_names, W, H, seg_ref)
            json.dump(an, open(os.path.join(self.out_dir, "analysis", stem + ".json"), "w", encoding="utf-8"), ensure_ascii=False)
            _imwrite(os.path.join(self.out_dir, "goc", stem + ".jpg"), img[:, :, ::-1], [cv2.IMWRITE_JPEG_QUALITY, 88])
            self.findings += finds
            self.frames.append((n, base, len(lab), pv, finds))
            el = time.time() - t0
            log(f"[{idx}/{len(items)}] frame {n if n is not None else '-'} {base[:40]}: {len(lab)} box, "
                f"{sum(f['sure'] for f in finds)} lỗi, {sum(not f['sure'] for f in finds)} đang xem xét "
                f"(còn ~{el / idx * (len(items) - idx) / 60:.1f} phút)", cb)
        pool.shutdown(wait=False, cancel_futures=True)
        if idc:
            self._id_findings(idc, cb)
        self._merge_track_repeats(st)
        st["sure"] = sum(f["sure"] for f in self.findings)
        st["unsure"] = sum(not f["sure"] for f in self.findings)
        st["giay"] = round(time.time() - t0, 1)
        self.stats = st
        self.save_report()
        return st

    def _id_findings(self, idc, cb=None):
        """Them loi ID (id_check) vao ket qua; bo ghi chu tho trung voi loi ID cu the hon; gop 'thieu' cung 1 vat."""
        found = idc.analyze()
        self.idc = idc
        name_of = {n: b for n, b, *_ in self.frames}
        new = []
        for n, fs in found.items():
            for f in fs:
                f.update(frame=n, name=name_of.get(n, ""))
                new.append(f)
        refs_switch = {r for f in new if f["sub"] in ("doi_vat", "trao_id") for r in (f.get("refs") or [f["ref"]])}
        refs_join = {f["ref"] for f in new if f["sub"] == "mot_vat_2_id"}
        size_at = {(f["ref"], n) for f in new if f["sub"] in ("kich_thuoc", "kich_thuoc_nhay") for n in f.get("frames", [])}
        drop = set()
        for f in self.findings:
            m = f["msg"]
            if f["kind"] == "track" and f.get("ref") in refs_switch and "nhảy" in m:
                drop.add(id(f))             # nhay xa: da co loi doi vat / trao ID cu the hon
            if f["kind"] == "track" and f.get("ref") in refs_join and "đứt track" in m:
                drop.add(id(f))
            if f["kind"] == "sai_kich_thuoc" and (f.get("ref"), f["frame"]) in size_at:
                drop.add(id(f))
        # 'thieu' lap lai tren cung 1 vat qua nhieu khung -> 1 ghi chu; vat cua track ket thuc som -> da co ghi chu do
        early = {f.get("end_tid") for f in new if f["sub"] == "ket_thuc_som"}
        groups = {}
        for f in self.findings:
            if f["kind"] == "thieu" and not f.get("ref") and f["frame"] is not None:
                tid = idc.missing_tid(f["frame"], f["box"])
                if tid in early:
                    drop.add(id(f))
                elif tid is not None:
                    groups.setdefault(tid, []).append(f)
        for fs in groups.values():
            if len(fs) < 2:
                continue
            fs.sort(key=lambda f: f["frame"])
            fs[0]["sure"] = any(f["sure"] for f in fs)
            fs[0]["msg"] = fs[0]["msg"].rstrip(".") + f" (thiếu ở {len(fs)} khung: {fs[0]['frame']}–{fs[-1]['frame']}, " \
                                                      f"cùng 1 vật: gán 1 track cho cả đoạn)."
            drop |= {id(f) for f in fs[1:]}
        self.findings = [f for f in self.findings if id(f) not in drop] + new
        by = {}
        for f in new:
            by.setdefault(f["frame"], []).append(f)
        self.frames = [(n, b, k, pv, [f for f in fs if id(f) not in drop] + by.get(n, [])) for n, b, k, pv, fs in self.frames]
        if new:
            c = {}
            for f in new:
                c[f["sub"]] = c.get(f["sub"], 0) + 1
            log("  Lỗi ID track: " + ", ".join(f"{ID_VI.get(k, k)} {v}" for k, v in c.items()), cb)

    def _merge_track_repeats(self, st):
        """Cung 1 loi tren cung 1 track lap lai o nhieu khung (thuong la khung noi suy) -> giu 1 ghi chu o khung dau,
        ghi them 'lap o khung a-b', de annotator sua 1 lan (khong ra N Issue cho 1 loi)."""
        groups = {}
        for f in self.findings:
            if str(f.get("ref") or "").startswith("track ") and f["kind"] != "track":
                groups.setdefault((f["kind"], f["ref"]), []).append(f)
        drop = set()
        for fs in groups.values():
            if len(fs) < 2:
                continue
            fs.sort(key=lambda f: f["frame"] if f["frame"] is not None else -1)
            first = fs[0]
            first["sure"] = any(f["sure"] for f in fs)
            first["msg"] = first["msg"].rstrip(".") + f" (lặp ở {len(fs)} khung: {fs[0]['frame']}–{fs[-1]['frame']})."
            drop |= {id(f) for f in fs[1:]}
        if not drop:
            return
        self.findings = [f for f in self.findings if id(f) not in drop]
        self.frames = [(n, b, k, pv, [f for f in fs if id(f) not in drop]) for n, b, k, pv, fs in self.frames]
        st["sure"] = sum(f["sure"] for f in self.findings)
        st["unsure"] = sum(not f["sure"] for f in self.findings)

    def _task_mode(self, job):
        """'annotation' = task anh roi, 'interpolation' = video. None neu khong doc duoc."""
        try:
            return self.cvat.get(f"/api/tasks/{job['task_id']}").json().get("mode")
        except Exception:
            return None

    def save_report(self):
        import csv
        with open(os.path.join(self.out_dir, "ket_qua_review.csv"), "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["frame", "anh", "so", "loai", "muc", "nhan", "x1", "y1", "x2", "y2", "ghi_chu"])
            for n, base, _, _, finds in self.frames:
                for k, x in enumerate(finds, 1):
                    w.writerow([n, base, k, KIND_VI[x["kind"]], "lỗi" if x["sure"] else "đang xem xét", x["label"],
                                *[round(v) for v in x["box"]], x["msg"]])
        json.dump(dict(stats=self.stats, skipped_labels=self.skipped_labels,
                       findings=[dict(x, box=[round(v, 1) for v in x["box"]]) for x in self.findings]),
                  open(os.path.join(self.out_dir, "ket_qua_review.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    @staticmethod
    def fingerprint(f):
        """Ma on dinh cua 1 loi giua cac lan chay: frame + loai + box nguoi gan (hoac vi tri vat bi thieu)."""
        if f.get("ref"):
            return f"{f['frame']}|{f['kind']}|{f['ref']}"
        x1, y1, x2, y2 = f["box"]
        return f"{f['frame']}|{f['kind']}|@{round((x1 + x2) / 40)},{round((y1 + y2) / 40)}"

    @staticmethod
    def issue_text(f):
        """Loi chac: ghi thang loi. Khong chac: 'Đang xem xét' + ly do, de annotator kiem chung."""
        if f["sure"]:
            return f["msg"]
        m = f["msg"].rstrip(".")
        m = m[0].lower() + m[1:] if m else m
        if not m.startswith("có thể"):
            m = "có thể " + m
        return f"Đang xem xét — {m}. Kiểm tra lại: nhãn đúng thì giữ nguyên và trả lời Issue này, sai thì sửa."

    @classmethod
    def issue_groups(cls, todo):
        """Moi VAT 1 Issue: cac loi cung frame + cung shape/track (ref) gop lai, ghim vao box cua chinh vat do.
        Vat bi thieu (khong co ref) moi cai 1 Issue o dung cho vat. Ma qc = cac dau van tay noi bang ';'."""
        groups = {}
        for f in todo:
            key = (f["frame"], f["ref"]) if f.get("ref") else ("@", cls.fingerprint(f))
            groups.setdefault(key, []).append(f)
        out = []
        for fs in groups.values():
            fs = sorted(fs, key=lambda f: (not f["sure"], f["kind"]))
            # ghim vao box cua chinh vat; vat ra ngoai anh -> dung box da cat vao trong anh (CVAT can vi tri trong anh)
            pin = next((f for f in fs if f["kind"] == "ngoai_anh"), fs[0])
            if len(fs) == 1:
                text = cls.issue_text(fs[0])
            else:
                # moi dong ghi ro TEN loi truoc (vd "Sai kích thước", "Lỗi ID: tráo ID") roi moi toi mo ta
                name = lambda f: f"Lỗi ID: {ID_VI[f['sub']]}" if f["kind"] == "track" and f.get("sub") in ID_VI \
                    else KIND_VI.get(f["kind"], f["kind"])
                what = f"'{fs[0]['label']}' này" if fs[0].get("label") else "Vật này"
                text = (f"{what} có {len(fs)} lỗi: {', '.join(name(f) for f in fs)}.\n"
                        + "\n".join(f"{k}. [{name(f)}] {cls.issue_text(f)}" for k, f in enumerate(fs, 1)))
            out.append(dict(fp=";".join(sorted({cls.fingerprint(f) for f in fs})), frame=fs[0]["frame"], box=pin["box"],
                            poly=next((f["poly"] for f in fs if f.get("poly")), None), text=text,
                            sure=any(f["sure"] for f in fs), n=len(fs)))
        return out

    def push(self, include_unsure=True, replace_old=True, cb=None):
        """Day ghi chu len CVAT bang Issue. KHONG dung toi annotation.
        replace_old: doi chieu voi Issue tu dong lan truoc theo dau van tay:
          - loi van con + Issue cu dang mo -> giu Issue cu, khong tao trung
          - loi da het -> danh dau resolved (giu lich su: hieu_qua.py dung de do % Issue dung)
          - loi van con nhung loi nhan doi (vd annotator sua 1 phan) -> dong Issue cu, tao Issue moi voi loi nhan moi
          - Issue cu da resolved, hoac do nguoi that tao -> khong dung toi."""
        if not self.cvat or not self.job_id:
            raise RuntimeError("Lần review này không gắn với job CVAT nào (chỉ đánh giá file).")
        todo = [f for f in self.findings if f["frame"] is not None and (f["sure"] or include_unsure)]
        want = {g["fp"]: g for g in self.issue_groups(todo)}
        removed = resolved = kept = 0
        keep_fp = set()
        if replace_old:
            me = self.cvat.user.get("id")
            for it in self.cvat.issues(self.job_id):
                owner = (it.get("owner") or {}).get("id")
                if owner != me or it.get("resolved"):
                    continue
                ti = tool_issue(self.cvat.first_comment(it["id"]))
                if ti is None:
                    continue
                fp = ti[0]
                replies = self.cvat.comment_count(it["id"]) > 1
                # loi van con: giu Issue cu. Rieng Issue chua ai tra loi ma loi nhan da doi (vd kieu cu co
                # "[Review tu dong]") thi xoa di tao lai voi loi nhan moi.
                if fp and fp in want and (replies or ti[1] == want[fp]["text"]):
                    keep_fp.add(fp)
                    kept += 1
                    continue
                # loi da het, hoac con nhung loi nhan doi: dong (khong xoa) de giu lich su do % Issue dung
                self.cvat.resolve_issue(it["id"])
                if fp and fp in want:
                    removed += 1
                else:
                    resolved += 1
            log(f"Issue tự động cũ: giữ {kept} (lỗi vẫn còn), đóng {resolved} (lỗi đã hết), "
                f"đóng {removed} (lỗi đổi, tạo Issue mới).", cb)
        made = []
        new = [g for fp, g in want.items() if fp not in keep_fp]
        for k, g in enumerate(new, 1):
            msg = g["text"] + f"\n\n[qc:{g['fp']}]"   # ma de lan sau khong tao trung, labeler bo qua
            r = self.cvat.create_issue(self.job_id, g["frame"], g["box"], msg, g["poly"])
            made.append(r["id"])
            if k % 20 == 0:
                log(f"  đã tạo {k}/{len(new)} Issue", cb)
        json.dump(made, open(os.path.join(self.out_dir, "issue_ids.json"), "w"))
        after = self.cvat.annotations(self.job_id)
        json.dump(after, open(os.path.join(self.out_dir, "annotations_sau_review.json"), "w", encoding="utf-8"), ensure_ascii=False)
        same = canon(after) == canon(self.before)
        log(f"Đã tạo {len(made)} Issue mới trên job {self.job_id}. Kiểm tra nhãn gốc: "
            f"{'KHÔNG thay đổi ✔' if same else 'CÓ THAY ĐỔI ✘ (có người đang sửa job?) — xem annotations_truoc/sau_review.json'}", cb)
        return dict(created=len(made), removed=removed, resolved=resolved, kept=kept, unchanged=same)
