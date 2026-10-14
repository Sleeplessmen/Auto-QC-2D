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

import label_hq_2d as L
from label_mapping import norm

HERE = L.HERE
CACHE = os.path.join(HERE, "cache_hq2d")
OUT_ROOT = os.path.join(HERE, "review_out")
PREFIX = "[Review tự động]"

# ---------------------------------------------------------------------------
# Nguong (do tren 123 anh D:\DATA, xem review_eval.py)
# ---------------------------------------------------------------------------
MATCH_IOU = 0.5          # cung 1 vat
CROSS_IOU = 0.7          # khop khac nhom (vd box nguoi gan "motorcycle" dung tren nguoi) phai trung rat sat
NEAR_IOU = 0.25          # box lech nhieu (IoU 0.25-0.5) cung loai -> sai kich thuoc lon
EDGE_PX = 6              # sai lech mep cho phep: max(EDGE_PX, EDGE_REL * canh)
EDGE_REL = 0.10
SIZE_IOU = 0.85          # IoU >= muc nay coi nhu khit, khong bao
MIN_CHECK_SIDE = 24      # vat nho hon (px) khong cham kich thuoc (nhieu qua)
MIN_MISS_SIDE = 14       # vat tool thay nho hon -> khong bao thieu
SURE_SCORE = L.REVIEW_SCORE
UNSURE_SCORE = 0.36
MISS_UNSURE = 0.38      # tool thay (diem thap) ma nguoi gan khong co -> "co the thieu"
DUP_IOU = 0.85

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
    by_norm = {norm(n): n for n in job_labels}
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
    skipped = [n for n in job_labels if n not in job_group]
    return tool2job, job_group, skipped


# ---------------------------------------------------------------------------
# Tool: tim vat trong anh (dung lai label_hq_2d)
# ---------------------------------------------------------------------------

FAST_MODELS = [("yolo11x.pt", "yolo", 1280), ("rtdetr-x.pt", "rtdetr", 1280)]


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
        for mi, (p, _, _) in enumerate(spec):
            tag = re.sub(r"[^A-Za-z0-9.-]", "_", p) + ("" if self.mode == "chinh_xac" else "__fast")
            cp = os.path.join(CACHE, f"{key}__{tag}.json")
            if os.path.exists(cp):
                part = [tuple(d[:6]) + (mi,) for d in json.load(open(cp))]
            else:
                models = self._models()
                if self.mode == "chinh_xac":
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
                # quy uoc du an: gan TOAN BO vat (ca phan bi che) -> tool cung uoc luong toan bo de so sanh
                objs, rejected = L.postprocess(img, dets, self.clf, sam=self.sam, amodal=True)
            finally:
                L.VOTE_K, L.MODELS = old_k, old_m
        h, w = img.shape[:2]
        for o in objs:
            o["box"] = [max(0.0, min(float(w), o["box"][0])), max(0.0, min(float(h), o["box"][1])),
                        max(0.0, min(float(w), o["box"][2])), max(0.0, min(float(h), o["box"][3]))]
            o.pop("_mask", None)
        return objs, rejected

    def lookalike(self, img, box, grp):
        """Xac suat box KHONG phai vat (bien bao, quang cao, guong, than cay...)"""
        P = self.clf.probs(img, [box], L.OWN_PROMPTS[grp] + L.NEG_PROMPTS, pad=0.1)
        return float(P[0][len(L.OWN_PROMPTS[grp]):].sum())


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


def _size_msg(off):
    parts = [f"cạnh {NAME_VI[k]} {'thừa' if v > 0 else 'thiếu'} {abs(v):.0f}px" for k, v in off.items()]
    return ", ".join(parts)


def compare(lab, tool, rejected, W, H, tool2job, job_group, img=None, runner=None, rider_person=True):
    """lab: [dict(id, label, box, occluded)] (chi nhan danh gia duoc). tool: objs cua ToolRunner.
    Tra ve [dict(kind, sure, label, box, msg, ref)]"""
    out = []
    T = []
    for o in tool:
        j = tool2job.get(o["cls"])
        if j is None:
            continue
        T.append(dict(o, label=j, grp=GROUP[o["cls"]],
                      sure=o.get("trang_thai") == "TU_DONG" and o["score"] >= SURE_SCORE,
                      box_ok=isinstance(o.get("box_sam"), float)))
    if not rider_person:      # quy uoc job: nguoi lai xe may KHONG co box rieng
        two = [t["box"] for t in T if t["grp"] == "two"] + [l["box"] for l in lab if job_group.get(l["label"]) == "two"]
        T = [t for t in T if not (t["grp"] == "person" and any(_inside(t["box"], b) > 0.5 for b in two))]

    ml, mt = {}, {}
    pairs = sorted(((L.iou(l["box"], t["box"]), i, k) for i, l in enumerate(lab) for k, t in enumerate(T)), reverse=True)
    # khop theo do trung + uu tien nhe cung nhan / cung nhom. Khac nhom (nguoi <-> xe may) phai trung rat sat,
    # vi box nguoi lai va box xe may hay chong nhau ~0.5 (nguoi gan dan nhan "motorcycle" len nguoi -> van bat duoc)
    cand = []
    for v, i, k in pairs:
        if v < MATCH_IOU:
            break
        same = lab[i]["label"] == T[k]["label"]
        same_grp = job_group.get(lab[i]["label"]) == T[k]["grp"]
        if same_grp or v >= CROSS_IOU:
            cand.append((v + (0.15 if same else 0.08 if same_grp else 0.0), i, k))
    for _, i, k in sorted(cand, reverse=True):
        if i not in ml and k not in mt:
            ml[i], mt[k] = k, i

    for i, k in ml.items():
        l, t = lab[i], T[k]
        if l["label"] != t["label"]:
            if t["sure"] and "GreenSM?" not in t.get("can_xem", ""):
                out.append(dict(kind="sai_nhan", sure=True, label=l["label"], box=l["box"], ref=l["id"],
                                msg=f"Sai nhãn: đang gán '{l['label']}', vật này là '{t['label']}'."))
            elif t["score"] >= UNSURE_SCORE:
                out.append(dict(kind="sai_nhan", sure=False, label=l["label"], box=l["box"], ref=l["id"],
                                msg=f"Nhãn '{l['label']}' có thể sai, có vẻ là '{t['label']}'."))
            continue
        _check_size(out, l, t, W, H)

    # box lech nhieu (IoU 0.25-0.5) cung nhan: thuong la ve sai kich thuoc lon
    for v, i, k in pairs:
        if v < NEAR_IOU:
            break
        if i in ml or k in mt or lab[i]["label"] != T[k]["label"]:
            continue
        l, t = lab[i], T[k]
        lc = ((l["box"][0] + l["box"][2]) / 2, (l["box"][1] + l["box"][3]) / 2)
        tc = ((t["box"][0] + t["box"][2]) / 2, (t["box"][1] + t["box"][3]) / 2)
        if not (_contains(t["box"], lc) or _contains(l["box"], tc)):
            continue
        ml[i], mt[k] = k, i
        off = _edges(l["box"], t["box"], W, H, _refs(t))
        sure = t["sure"] and t["box_ok"] and not l.get("occluded")
        out.append(dict(kind="sai_kich_thuoc", sure=sure, label=l["label"], box=l["box"], ref=l["id"],
                        msg=f"Sai kích thước nhiều: box '{l['label']}' lệch xa vật thật (IoU {v:.2f}); "
                            f"{_size_msg(off) or 'lệch vị trí'}. Box đúng khoảng {_fmt(t['box'])}."))

    # thieu: tool thay chac chan, nguoi gan khong co box nao
    for k, t in enumerate(T):
        if k in mt:
            continue
        x1, y1, x2, y2 = t["box"]
        if min(x2 - x1, y2 - y1) < MIN_MISS_SIDE:
            continue
        if any(L.iou(t["box"], l["box"]) >= 0.5 and job_group.get(l["label"]) == t["grp"] for l in lab):
            continue          # da co box cung nhom de len (lech / khac nhan, da xu ly o tren)
        if t["sure"]:
            out.append(dict(kind="thieu", sure=True, label=t["label"], box=t["box"], ref=None,
                            msg=f"Thiếu nhãn: có 1 '{t['label']}' ở đây chưa được gán."))
        elif t["score"] >= MISS_UNSURE:
            out.append(dict(kind="thieu", sure=False, label=t["label"], box=t["box"], ref=None,
                            msg=f"Có thể thiếu 1 '{t['label']}' ở đây."))

    # thua: nguoi gan co box ma tool khong thay gi (ca box diem thap)
    cand = [o["box"] for o in tool] + [o["box"] for o in rejected]
    for i, l in enumerate(lab):
        if i in ml:
            continue
        x1, y1, x2, y2 = l["box"]
        if min(x2 - x1, y2 - y1) < 20 or any(L.iou(l["box"], b) >= 0.3 for b in cand):
            continue
        p_neg = runner.lookalike(img, l["box"], job_group[l["label"]]) if runner is not None and img is not None else 0.0
        if p_neg >= L.NEG_P:
            out.append(dict(kind="thua", sure=True, label=l["label"], box=l["box"], ref=l["id"],
                            msg=f"Box thừa: trong box '{l['label']}' không có vật thể (giống biển báo / quảng cáo / bóng phản chiếu)."))
        else:
            out.append(dict(kind="thua", sure=False, label=l["label"], box=l["box"], ref=l["id"],
                            msg=f"Tool không thấy '{l['label']}' nào trong box này, kiểm tra lại xem có phải box thừa."))

    # box trung: 2 box cung nhan tren 1 vat
    for i in range(len(lab)):
        for j in range(i + 1, len(lab)):
            if lab[i]["label"] == lab[j]["label"] and L.iou(lab[i]["box"], lab[j]["box"]) >= DUP_IOU:
                out.append(dict(kind="trung", sure=True, label=lab[i]["label"], box=lab[j]["box"], ref=lab[j]["id"],
                                msg=f"Box trùng: 2 box '{lab[i]['label']}' chồng lên nhau trên cùng 1 vật."))
    return out


def _check_size(out, l, t, W, H):
    x1, y1, x2, y2 = t["box"]
    if min(x2 - x1, y2 - y1) < MIN_CHECK_SIDE or l.get("occluded"):
        return
    v = L.iou(l["box"], t["box"])
    if v >= SIZE_IOU:
        return
    off = _edges(l["box"], t["box"], W, H, _refs(t))
    if not off:
        return
    sure = t["sure"] and t["box_ok"]
    out.append(dict(kind="sai_kich_thuoc", sure=sure, label=l["label"], box=l["box"], ref=l["id"],
                    msg=f"Box '{l['label']}' chưa khít: {_size_msg(off)} (IoU {v:.2f}). Box đúng khoảng {_fmt(t['box'])}."))


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

    def create_issue(self, job_id, frame, box, message):
        x1, y1, x2, y2 = [round(float(v), 2) for v in box]
        payload = dict(job=job_id, frame=frame, position=[x1, y1, x2, y1, x2, y2, x1, y2], message=message)
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
                               occluded=bool(a.get("occluded")), rotation=a.get("rotation", 0)))
    return per


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
    res = dict(images={k: z.read(v) for k, v in images.items()}, ann=None, fmt="chỉ có ảnh", labels=[])
    xmls = [n for n in names if n.lower().endswith("annotations.xml")]
    cocos = [n for n in names if n.lower().endswith(".json") and "instances" in os.path.basename(n).lower()]
    yolo_names = [n for n in names if os.path.basename(n) in ("obj.names", "classes.txt")]
    if xmls:
        root = ET.fromstring(z.read(xmls[0]))
        res["fmt"] = "CVAT for images 1.1"
        res["labels"] = [e.findtext("name") for e in root.iter("label") if e.findtext("name")]
        ann = {}
        for im in root.iter("image"):
            nm = os.path.basename(im.get("name"))
            ann[nm] = [dict(id=f"box {k}", label=b.get("label"), occluded=b.get("occluded") == "1",
                            box=[float(b.get("xtl")), float(b.get("ytl")), float(b.get("xbr")), float(b.get("ybr"))])
                       for k, b in enumerate(im.findall("box"))]
        if not ann:     # export dang video (track)
            raise RuntimeError("File XML là dạng 'CVAT for video'. Hãy export 'CVAT for images 1.1'.")
        res["ann"] = ann
    elif cocos:
        d = json.loads(z.read(cocos[0]))
        res["fmt"] = "COCO 1.0"
        cats = {c["id"]: c["name"] for c in d["categories"]}
        res["labels"] = list(cats.values())
        ims = {i["id"]: os.path.basename(i["file_name"]) for i in d["images"]}
        ann = {n: [] for n in ims.values()}
        for a in d["annotations"]:
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
        txt = str(n)
        (tw, th), _ = cv2.getTextSize(txt, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
        ty = y1 - 4 if y1 > th + 6 else y2 + th + 4
        cv2.rectangle(out, (x1, ty - th - 3), (x1 + tw + 4, ty + 3), col, -1)
        cv2.putText(out, txt, (x1 + 2, ty), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2, cv2.LINE_AA)
    cv2.imwrite(path, out, [cv2.IMWRITE_JPEG_QUALITY, 88])


KIND_VI = {"sai_kich_thuoc": "Sai kích thước", "sai_nhan": "Sai nhãn", "thieu": "Thiếu", "thua": "Thừa", "trung": "Trùng",
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
        os.makedirs(os.path.join(self.out_dir, "preview"), exist_ok=True)

        export = read_export(zip_path) if zip_path else None
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
            n_other = sum(1 for s in self.before.get("shapes", []) if s.get("type") != "rectangle")
            if n_other:
                log(f"  Lưu ý: {n_other} shape không phải hình chữ nhật (polygon, point...) — không review.", cb)
            per = boxes_from_cvat(self.before, id2label, [f[0] for f in frames])
            if export and export["ann"] is not None:
                log("  Dùng nhãn trong file tải lên (ảnh khớp theo tên với frame của job).", cb)
            for n, name, w, h in frames:
                base = os.path.basename(name)
                if export and export["ann"] is not None:
                    if base not in export["ann"]:
                        continue
                    boxes = export["ann"][base]
                else:
                    boxes = per[n]
                if export and base in export["images"]:
                    data = export["images"][base]
                    loader = (lambda d=data: cv2.imdecode(np.frombuffer(d, np.uint8), cv2.IMREAD_COLOR)[:, :, ::-1].copy())
                else:
                    loader = (lambda n=n: self.cvat.image(self.job_id, n, start))
                items.append((n, base, loader, boxes))
        else:
            if not export or export["ann"] is None:
                raise RuntimeError("Không có số job thì phải tải lên file export có nhãn (CVAT for images / COCO / YOLO).")
            label_names = export["labels"]
            for base in sorted(export["ann"]):
                if base not in export["images"]:
                    continue
                data = export["images"][base]
                items.append((None, base, (lambda d=data: cv2.imdecode(np.frombuffer(d, np.uint8), cv2.IMREAD_COLOR)[:, :, ::-1].copy()),
                              export["ann"][base]))
            log("Không có số job: chỉ đánh giá, không đẩy lên CVAT.", cb)
        if max_frames:
            items = items[:int(max_frames)]

        tool2job, job_group, self.skipped_labels = build_label_map(label_names)
        log("Khớp nhãn: " + ", ".join(f"{c}→{j}" for c, j in tool2job.items() if j), cb)
        if self.skipped_labels:
            log(f"  Tool KHÔNG đánh giá được các nhãn: {', '.join(self.skipped_labels)} (bỏ qua, không ghi chú).", cb)
        if not job_group:
            raise RuntimeError("Không nhãn nào của job khớp với loại tool nhận ra (xe, xe máy, người...).")

        runner = runner or ToolRunner(mode, cb)
        st = dict(frames=0, boxes=0, ok=0, sure=0, unsure=0)
        for idx, (n, base, loader, boxes) in enumerate(items, 1):
            img = loader()
            H, W = img.shape[:2]
            lab = [b for b in boxes if b["label"] in job_group]
            rot = [b for b in lab if abs(b.get("rotation") or 0) > 0.5]
            key = hashlib.sha1(img.tobytes()).hexdigest()[:20]
            tool, rejected = runner.detect(img, key)
            finds = compare(lab, tool, rejected, W, H, tool2job, job_group, img=img, runner=runner, rider_person=rider_person)
            for b in rot:
                finds.append(dict(kind="sai_kich_thuoc", sure=False, label=b["label"], box=b["box"], ref=b["id"],
                                  msg=f"Box '{b['label']}' bị xoay {b['rotation']:.0f}°, tool chỉ kiểm tra được box không xoay."))
            bad_refs = {f["ref"] for f in finds if f["ref"] and f["sure"]}
            st["frames"] += 1
            st["boxes"] += len(lab)
            st["ok"] += len(lab) - len(bad_refs & {b["id"] for b in lab})
            st["sure"] += sum(f["sure"] for f in finds)
            st["unsure"] += sum(not f["sure"] for f in finds)
            for f in finds:
                f.update(frame=n, name=base)
            pv = os.path.join(self.out_dir, "preview", f"{idx:04d}_{os.path.splitext(base)[0][:40]}.jpg")
            draw_review(img, lab, finds, pv)
            self.findings += finds
            self.frames.append((n, base, len(lab), pv, finds))
            el = time.time() - t0
            log(f"[{idx}/{len(items)}] frame {n if n is not None else '-'} {base[:40]}: {len(lab)} box, "
                f"{sum(f['sure'] for f in finds)} lỗi, {sum(not f['sure'] for f in finds)} không chắc "
                f"(còn ~{el / idx * (len(items) - idx) / 60:.1f} phút)", cb)
        st["giay"] = round(time.time() - t0, 1)
        self.stats = st
        self.save_report()
        return st

    def save_report(self):
        import csv
        with open(os.path.join(self.out_dir, "ket_qua_review.csv"), "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["frame", "anh", "so", "loai", "muc", "nhan", "x1", "y1", "x2", "y2", "ghi_chu"])
            for n, base, _, _, finds in self.frames:
                for k, x in enumerate(finds, 1):
                    w.writerow([n, base, k, KIND_VI[x["kind"]], "lỗi" if x["sure"] else "không chắc", x["label"],
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

    def push(self, include_unsure=True, replace_old=True, cb=None):
        """Day ghi chu len CVAT bang Issue. KHONG dung toi annotation.
        replace_old: doi chieu voi Issue tu dong lan truoc theo dau van tay:
          - loi van con + Issue cu dang mo -> giu Issue cu, khong tao trung
          - loi da het -> Issue cu chua ai tra loi thi xoa, da co tra loi thi danh dau resolved (giu lich su)
          - Issue cu da resolved, hoac do nguoi that tao -> khong dung toi."""
        if not self.cvat or not self.job_id:
            raise RuntimeError("Lần review này không gắn với job CVAT nào (chỉ đánh giá file).")
        todo = [f for f in self.findings if f["frame"] is not None and (f["sure"] or include_unsure)]
        want = {self.fingerprint(f): f for f in todo}
        removed = resolved = kept = 0
        keep_fp = set()
        if replace_old:
            me = self.cvat.user.get("id")
            for it in self.cvat.issues(self.job_id):
                owner = (it.get("owner") or {}).get("id")
                if owner != me or it.get("resolved"):
                    continue
                first = self.cvat.first_comment(it["id"])
                if not first.startswith(PREFIX):
                    continue
                m = re.search(r"\[qc:([^\]]+)\]\s*$", first)
                fp = m.group(1) if m else None
                if fp and fp in want:
                    keep_fp.add(fp)
                    kept += 1
                    continue
                if self.cvat.comment_count(it["id"]) > 1:
                    self.cvat.resolve_issue(it["id"])
                    resolved += 1
                else:
                    self.cvat.delete_issue(it["id"])
                    removed += 1
            log(f"Issue tự động cũ: giữ {kept} (lỗi vẫn còn), đóng {resolved} (đã có trả lời), xoá {removed}.", cb)
        made = []
        new = [f for fp, f in want.items() if fp not in keep_fp]
        for k, f in enumerate(new, 1):
            msg = f"{PREFIX} {f['msg']}" + ("" if f["sure"] else " (không chắc — nên kiểm tra lại)")
            if f["ref"]:
                msg += f" [{f['ref']}]"
            msg += f" [qc:{self.fingerprint(f)}]"
            r = self.cvat.create_issue(self.job_id, f["frame"], f["box"], msg)
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
