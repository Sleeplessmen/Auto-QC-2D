"""Review nhan vung (polygon / mask): vung duong (drivable area) va trung mask-box.

- Vung duong: so polygon nguoi gan voi mat duong do SegFormer (Cityscapes) tim ra
    * thua: polygon to len vung khong phai duong (via he, tuyet, co, nha...)
    * thieu: mat duong lon chua nam trong polygon nao
    * trung: 2 polygon cung nhan de len nhau
- Trung mask/polygon voi box cung nhan tren 1 vat (vd nguoi vua co mask vua co box)
Khong sua nhan, chi tra ve danh sach ghi chu giong review_core.compare.
"""
import threading

import cv2
import numpy as np
import torch

from label_mapping import norm

SEG_MODEL = "nvidia/segformer-b5-finetuned-cityscapes-1024-1024"
ROAD = 0
# lop Cityscapes co the nam tren mat duong (xe, nguoi, ...) -> khong tinh la "to sai"
ON_ROAD = {11, 12, 13, 14, 15, 16, 17, 18}
CS_VI = {1: "vỉa hè", 2: "nhà", 3: "tường", 4: "hàng rào", 5: "cột", 8: "cây cỏ", 9: "đất / tuyết / bãi cỏ", 10: "trời"}

ROAD_SYN = ["drivablearea", "drivable", "road", "roadarea", "freespace", "duong", "matduong", "vungduong",
            "landuong", "landuong", "vungdiduoc", "khudiduoc", "duongdiduoc"]

MIN_FRAC = 0.012        # vung loi nho hon (ti le dien tich anh) -> bo qua
SURE_FRAC = 0.03        # lon hon -> loi chac chan
DUP_AREA = 0.6          # 2 polygon cung nhan: phan giao / polygon nho >= muc nay -> trung
MASK_BOX_IOU = 0.7


def road_labels(label_names):
    return [n for n in label_names if norm(n) in ROAD_SYN or any(s in norm(n) for s in ("drivable", "road"))]


def areas_from_cvat(ann, id2label, frames, W_H):
    """{frame: [dict(id, label, kind, mask(bool HxW), box)]} — polygon + mask (shape, khong track)."""
    want = set(frames)
    per = {f: [] for f in frames}
    for s in ann.get("shapes", []):
        if s["frame"] not in want or s["label_id"] not in id2label or s.get("type") not in ("polygon", "mask"):
            continue
        W, H = W_H.get(s["frame"]) or (None, None)
        if not (W and H):
            continue
        m = _to_mask(s, W, H)
        if m is None or not m.any():
            continue
        ys, xs = np.nonzero(m)
        per[s["frame"]].append(dict(id=f"shape {s['id']}", label=id2label[s["label_id"]], kind=s["type"], mask=m,
                                    box=[float(xs.min()), float(ys.min()), float(xs.max() + 1), float(ys.max() + 1)]))
    return per


def _to_mask(s, W, H):
    p = s["points"]
    m = np.zeros((H, W), np.uint8)
    if s["type"] == "polygon":
        pts = np.round(np.array(p, np.float32).reshape(-1, 2)).astype(np.int32)
        if len(pts) < 3:
            return None
        cv2.fillPoly(m, [pts], 1)
    else:                       # mask: RLE (bat dau bang 0) theo hang trong khung [left, top, right, bottom]
        l, t, r, b = [int(round(v)) for v in p[-4:]]
        w, h = r - l + 1, b - t + 1
        flat = np.zeros(w * h, np.uint8)
        pos, val = 0, 0
        for c in p[:-4]:
            c = int(c)
            if val:
                flat[pos:pos + c] = 1
            pos += c
            val ^= 1
        sub = flat.reshape(h, w)
        y2, x2 = min(H, t + h), min(W, l + w)
        m[t:y2, l:x2] = sub[:y2 - t, :x2 - l]
    return m.astype(bool)


class RoadSeg:
    _lock = threading.Lock()

    def __init__(self):
        from transformers import SegformerForSemanticSegmentation, SegformerImageProcessor
        self.dev = "cuda" if torch.cuda.is_available() else "cpu"
        try:                    # da tai roi thi khong can mang
            self.proc = SegformerImageProcessor.from_pretrained(SEG_MODEL, local_files_only=True)
            model = SegformerForSemanticSegmentation.from_pretrained(SEG_MODEL, local_files_only=True)
        except OSError:
            self.proc = SegformerImageProcessor.from_pretrained(SEG_MODEL)
            model = SegformerForSemanticSegmentation.from_pretrained(SEG_MODEL)
        self.model = model.to(self.dev).eval()
        if self.dev == "cuda":
            self.model.half()

    @torch.no_grad()
    def __call__(self, img):
        """img RGB -> nhan lop Cityscapes tung pixel (HxW int)"""
        H, W = img.shape[:2]
        with self._lock:
            x = self.proc(images=img, return_tensors="pt")["pixel_values"].to(self.dev)
            if self.dev == "cuda":
                x = x.half()
            lo = self.model(pixel_values=x).logits
            lo = torch.nn.functional.interpolate(lo.float(), size=(H, W), mode="bilinear", align_corners=False)
            return lo.argmax(1)[0].cpu().numpy()


def _fmt(b):
    return f"({b[0]:.0f},{b[1]:.0f})-({b[2]:.0f},{b[3]:.0f})"


def _blobs(mask, min_px):
    """Cac vung lien thong lon: [(so px, box, mask vung)] lon truoc"""
    m = cv2.morphologyEx(mask.astype(np.uint8), cv2.MORPH_OPEN, np.ones((7, 7), np.uint8))
    n, lab, st, _ = cv2.connectedComponentsWithStats(m, 8)
    out = [(int(st[i, 4]), [float(st[i, 0]), float(st[i, 1]), float(st[i, 0] + st[i, 2]), float(st[i, 1] + st[i, 3])], lab == i)
           for i in range(1, n) if st[i, 4] >= min_px]
    return sorted(out, key=lambda x: -x[0])


def outline(mask, max_pts=60):
    """Duong vien vung lon nhat -> [x1, y1, x2, y2, ...] de ghim Issue dung hinh vung (khong trum sang xe ben canh)."""
    cs, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cs:
        return None
    c = max(cs, key=cv2.contourArea)
    eps = 0.003 * cv2.arcLength(c, True)
    p = cv2.approxPolyDP(c, eps, True)
    while len(p) > max_pts:
        eps *= 1.5
        p = cv2.approxPolyDP(c, eps, True)
    if len(p) < 3:
        return None
    return [float(v) for v in p.reshape(-1)]


def check(areas, boxes, img, seg, road_names):
    """areas: [dict(id,label,kind,mask,box)] cua 1 frame. boxes: box nguoi gan (dict id,label,box). seg: RoadSeg | None."""
    out = []
    H, W = img.shape[:2]
    N = H * W
    road_set = set(road_names)
    roads = [a for a in areas if a["label"] in road_set]

    # trung: 2 vung cung nhan de len nhau (vd tam giac nam trong polygon lon)
    dup = set()
    for i in range(len(areas)):
        for j in range(i + 1, len(areas)):
            a, b = areas[i], areas[j]
            if a["label"] != b["label"]:
                continue
            inter = np.logical_and(a["mask"], b["mask"]).sum()
            small = b if b["mask"].sum() <= a["mask"].sum() else a
            big = a if small is b else b
            if inter and inter / small["mask"].sum() >= DUP_AREA:
                dup.add(small["id"])
                out.append(dict(kind="trung", sure=True, label=small["label"], box=small["box"], ref=small["id"],
                                poly=outline(small["mask"]),
                                msg=f"Trùng: vùng '{small['label']}' này nằm đè lên vùng khác, xoá vùng này."))

    # trung: mask / polygon va box cung nhan tren 1 vat
    for a in areas:
        if a["label"] in road_set:
            continue
        for b in boxes:
            if b["label"] == a["label"] and _iou(a["box"], b["box"]) >= MASK_BOX_IOU:
                out.append(dict(kind="trung", sure=True, label=a["label"], box=b["box"], ref=a["id"],
                                msg=f"Trùng: '{a['label']}' này vừa có {'mask' if a['kind'] == 'mask' else 'polygon'} "
                                    f"vừa có box, xoá 1 cái."))
                break

    if seg is None or not road_names:
        return out
    cls = seg(img)
    road = cls == ROAD
    neutral = np.isin(cls, list(ON_ROAD))
    hood = np.zeros_like(road)
    hood[int(H * 0.9):] = True          # nap capo xe minh o day anh -> khong xet
    union = np.zeros_like(road)
    for a in roads:
        if a["id"] not in dup:
            union |= a["mask"]

    # thua: polygon to len cho khong phai duong
    for a in roads:
        if a["id"] in dup:
            continue
        wrong = a["mask"] & ~road & ~neutral & ~hood
        for px, box, comp in _blobs(wrong, MIN_FRAC * N):
            what = np.bincount(cls[comp], minlength=19)
            top = [CS_VI[k] for k in np.argsort(-what)[:2] if what[k] > 0.2 * px and k in CS_VI]
            out.append(dict(kind="thua", sure=px >= SURE_FRAC * N, label=a["label"], box=box, ref=a["id"],
                            poly=outline(comp),
                            msg=f"Tô thừa '{a['label']}' lên {' / '.join(top) if top else 'chỗ không phải đường'}, "
                                f"kéo viền vào sát mép đường."))

    # thieu: mat duong chua duoc to
    miss = road & ~union & ~hood
    for px, box, comp in _blobs(miss, MIN_FRAC * N):
        out.append(dict(kind="thieu", sure=px >= SURE_FRAC * N, label=road_names[0], box=box, ref=None,
                        poly=outline(comp),
                        msg=f"Thiếu '{road_names[0]}': phần đường này chưa tô."))
    return out


def _iou(a, b):
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))
    u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - ix
    return ix / u if u > 0 else 0.0
