"""
auto_shape.py — Gán nhãn 2D theo đúng KIỂU VẼ bạn chọn, giống các nút "Draw new ..." trên CVAT:
    rectangle | polygon | polyline | mask | skeleton

Tên nhãn lấy từ chính job trên CVAT. Chỉ gán những nhãn mà CVAT cho vẽ bằng kiểu đó
(kiểu của nhãn = kiểu đã chọn, hoặc "any"; skeleton thì chỉ nhãn skeleton).

  - rectangle / polygon / polyline / mask: YOLOE tìm vật theo chữ — mỗi nhãn có vài từ mô tả tiếng Anh,
    lấy từ labels/task<id>.json (tự tạo lần đầu theo tên nhãn, sửa tay được). Từ mask của vật:
        rectangle = khung bao | polygon = đường viền | mask = mask (RLE của CVAT)
        polyline  = đường tâm dọc theo vật (hợp với vật dài, mảnh: cột, lề đường, dây...)
  - skeleton: MediaPipe (keypoints.py) — mặt 50 điểm, người 17 điểm, bàn tay 21 điểm. Điểm con (sublabel)
    của nhãn skeleton trong job được khớp theo tên hoặc số thứ tự điểm. Điểm không thấy -> outside.

Mặc định chỉ XEM TRƯỚC: lưu ảnh vẽ sẵn + JSON vào preview_shape/. --push mới đẩy lên CVAT.

  python auto_shape.py 12345 --shape polygon                     # xem trước mọi frame của job
  python auto_shape.py 12345 --shape mask --frame 3 --push
  python auto_shape.py 12345 --shape rectangle --labels car,person --push --replace
"""
import argparse
import json
import os
import re
import sys
import tempfile
import time

import cv2
import numpy as np
from dotenv import load_dotenv

from cvat_client import CvatClient


def _imwrite(path, img, params=None):
    """cv2.imwrite khong ghi duoc duong dan co dau (Windows) -> encode roi ghi bang numpy."""
    ok, buf = cv2.imencode(os.path.splitext(path)[1] or ".jpg", img, params or [])
    if ok:
        buf.tofile(path)
    return ok

# Ban exe (PyInstaller): du lieu nam canh file exe
HERE = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__))
SHAPES = ("rectangle", "polygon", "polyline", "mask", "skeleton")
COLORS = [(230, 25, 75), (60, 180, 75), (255, 225, 25), (0, 130, 200), (245, 130, 48), (145, 30, 180),
          (70, 240, 240), (240, 50, 230), (210, 245, 60), (250, 190, 212), (0, 128, 128), (170, 110, 40)]
MIN_AREA = 60          # px: vat nho hon -> bo (nhieu)


def norm(s):
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def get_labels(client, job_id):
    r = client.session.get(f"{client.base_url}/api/labels", params={"job_id": job_id, "page_size": 500})
    r.raise_for_status()
    return r.json().get("results", [])


def target_labels(labels, shape, only=None):
    ok = ("skeleton",) if shape == "skeleton" else ("any", shape)
    out = [lb for lb in labels if (lb.get("type") or "any") in ok]
    if only:
        want = {norm(x) for x in only}
        out = [lb for lb in out if norm(lb["name"]) in want]
    return out


# -----------------------------------------------------------------------------
# Vat (rectangle / polygon / polyline / mask)
# -----------------------------------------------------------------------------

class ObjectFinder:
    def __init__(self, task_id, names, conf):
        from ultralytics import YOLOE
        import torch
        from vision_labels import load_prompts
        prompts = load_prompts(task_id, names)
        self.texts, self.text_label = [], []
        for lab in names:
            for w in prompts.get(lab, []):
                if w not in self.texts:
                    self.texts.append(w)
                    self.text_label.append(lab)
        skipped = [n for n in names if not prompts.get(n)]
        if skipped:
            print(f"  Bo qua (khong co tu mo ta trong labels/task{task_id}.json): {', '.join(skipped)}")
        if not self.texts:
            raise SystemExit("Khong co nhan nao de tim")
        self.device = 0 if torch.cuda.is_available() else "cpu"
        path = os.path.join(HERE, "yoloe-11l-seg.pt")
        self.model = YOLOE(path if os.path.exists(path) else "yoloe-11l-seg.pt")
        self.model.set_classes(self.texts, self.model.get_text_pe(self.texts))
        self.conf = conf
        print(f"  YOLOE: {len(self.texts)} tu mo ta cho {len(names)} nhan ({'GPU' if self.device == 0 else 'CPU - cham'})")
        for lab in names:
            if prompts.get(lab):
                print(f"    {lab}: {', '.join(prompts[lab])}")

    def find(self, img):
        r = self.model.predict(np.ascontiguousarray(img[:, :, ::-1]), conf=self.conf, imgsz=1280, device=self.device,
                               retina_masks=True, agnostic_nms=True, verbose=False)[0]
        out = []
        if r.boxes is None or len(r.boxes) == 0:
            return out
        masks = r.masks.data.cpu().numpy() > 0.5 if r.masks is not None else [None] * len(r.boxes)
        for box, c, s, m in zip(r.boxes.xyxy.cpu().numpy(), r.boxes.cls.cpu().numpy(), r.boxes.conf.cpu().numpy(), masks):
            if m is not None and m.shape != img.shape[:2]:
                m = cv2.resize(m.astype(np.uint8), (img.shape[1], img.shape[0]), interpolation=cv2.INTER_NEAREST) > 0
            out.append(dict(label=self.text_label[int(c)], conf=float(s), box=[float(v) for v in box], mask=m))
        return out


def to_polygons(mask):
    cnts, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cnts:
        return []
    big = max(cv2.contourArea(c) for c in cnts)
    polys = []
    for c in sorted(cnts, key=cv2.contourArea, reverse=True):
        if cv2.contourArea(c) < max(MIN_AREA, 0.15 * big):      # manh nho -> nhieu
            continue
        c = cv2.approxPolyDP(c, max(1.0, 0.002 * cv2.arcLength(c, True)), True).reshape(-1, 2)
        if len(c) >= 3:
            polys.append([float(v) for v in c.flatten()])
    return polys


def to_polyline(mask):
    """Duong tam doc truc chinh cua mask: chia vat thanh cac doan doc truc, lay tam moi doan."""
    ys, xs = np.nonzero(mask)
    if len(xs) < MIN_AREA:
        return None
    P = np.c_[xs, ys].astype(float)
    c = P.mean(0)
    _, V = np.linalg.eigh(np.cov((P - c).T))
    t = (P - c) @ V[:, 1]
    n = int(np.clip(np.ptp(t) / 25, 2, 40))
    edges = np.linspace(t.min(), t.max(), n + 1)
    pts = []
    for i, (a, b) in enumerate(zip(edges[:-1], edges[1:])):
        sel = (t >= a) & (t <= b)
        if not sel.any():
            continue
        q = P[sel].mean(0)
        if i == 0:                       # keo 2 dau ra toi mep vat
            q = P[sel][np.argmin(t[sel])] * 0.5 + q * 0.5
        elif i == n - 1:
            q = P[sel][np.argmax(t[sel])] * 0.5 + q * 0.5
        pts.append(q)
    return [float(v) for v in np.array(pts).flatten()] if len(pts) >= 2 else None


def mask_to_cvat_rle(mask, bbox):
    """Mask CVAT: points = [do dai cac doan 0/1 lien tiep (doan dau la 0)..., left, top, right, bottom]
    (giong semantic_segmentation.mask_to_cvat_rle)."""
    x0, y0, x1, y1 = bbox
    flat = mask[y0:y1 + 1, x0:x1 + 1].astype(np.uint8).flatten()
    change = np.flatnonzero(np.diff(flat)) + 1
    runs = np.diff(np.concatenate(([0], change, [flat.size]))).tolist()
    if flat.size and flat[0] == 1:
        runs = [0] + runs
    return runs + [int(x0), int(y0), int(x1), int(y1)]


def object_shapes(dets, shape, label_ids, frame):
    shapes, group = [], 0
    for d in dets:
        base = dict(type=shape, frame=frame, label_id=label_ids[d["label"]], occluded=False, z_order=0,
                    group=0, source="auto", attributes=[])
        m = d["mask"]
        if shape == "rectangle":
            shapes.append(dict(base, points=d["box"]))
            continue
        if m is None or m.sum() < MIN_AREA:
            continue
        if shape == "polygon":
            polys = to_polygons(m)
            if len(polys) > 1:          # vat bi che thanh nhieu manh -> cung 1 nhom
                group += 1
            for p in polys:
                shapes.append(dict(base, points=p, group=group if len(polys) > 1 else 0))
        elif shape == "polyline":
            p = to_polyline(m)
            if p:
                shapes.append(dict(base, points=p))
        elif shape == "mask":
            ys, xs = np.nonzero(m)
            shapes.append(dict(base, points=mask_to_cvat_rle(m, (xs.min(), ys.min(), xs.max(), ys.max()))))
    return shapes


# -----------------------------------------------------------------------------
# Skeleton
# -----------------------------------------------------------------------------
HINTS = {"hand": ("hand", "finger", "bantay", "ngon"),
         "person": ("person", "human", "pose", "body", "nguoi", "pedestrian"),
         "face": ("face", "mat", "mui", "moi", "longmay", "eye", "nose", "lip", "brow", "mouth")}


def _keys(p):
    k = {norm(p["id"])}
    if p.get("name"):
        k |= {norm(p["name"]), norm(re.sub(r"\(.*?\)", "", p["name"])), norm(p["name"].replace("_", " "))}
    return k


def _template(kind):
    import keypoints as kp
    if kind == "face":
        return [dict(id=i) for i in range(50)]
    if kind == "person":
        return [dict(id=i, name=n) for i, n in kp.POSE17_NAMES.items()]
    return [dict(id=i, name=n) for i, n in enumerate(kp.HAND_NAMES)]


def skeleton_kind(lb):
    """Nhan skeleton nay ung voi mat / nguoi / ban tay? Theo ten nhan, khong ro thi theo ten cac diem con."""
    subs = [norm(s["name"]) for s in lb.get("sublabels", [])]
    if not subs:
        return None
    match = {}
    for kind in ("person", "hand", "face"):
        keys = set().union(*(_keys(p) for p in _template(kind)))
        match[kind] = np.mean([s in keys for s in subs])
    n = norm(lb["name"])
    for kind in ("hand", "person", "face"):
        if any(h in n for h in HINTS[kind]) and match[kind] >= 0.5:
            return kind
    best = max(match, key=lambda k: (match[k], {"person": 17, "hand": 21}.get(k, 0) == len(subs)))
    return best if match[best] >= 0.5 else None


def skeleton_shapes(det, lbs, frame):
    shapes = []
    for lb, kind in lbs:
        for inst in det[{"face": "faces", "person": "persons", "hand": "hands"}[kind]]:
            pts = {}
            for p in inst["points"]:
                for k in _keys(p):
                    pts.setdefault(k, p)
            found = [(s, pts[norm(s["name"])]) for s in lb["sublabels"] if norm(s["name"]) in pts]
            if len(found) < max(2, 0.3 * len(lb["sublabels"])):
                continue
            cx, cy = np.mean([p["xy"] for _, p in found], axis=0)
            have = {s["id"] for s, _ in found}
            els = [dict(type="points", frame=frame, label_id=s["id"], points=[float(v) for v in p["xy"]],
                        occluded=not p.get("visible", True), outside=False, source="auto", attributes=[])
                   for s, p in found]
            els += [dict(type="points", frame=frame, label_id=s["id"], points=[float(cx), float(cy)],
                         occluded=False, outside=True, source="auto", attributes=[])
                    for s in lb["sublabels"] if s["id"] not in have]
            shapes.append(dict(type="skeleton", frame=frame, label_id=lb["id"], points=[], occluded=False, z_order=0,
                               group=0, source="auto", attributes=[], elements=els))
    return shapes


# -----------------------------------------------------------------------------
# Xem truoc
# -----------------------------------------------------------------------------

def draw_preview(img, shapes, id2name, path):
    out = img[:, :, ::-1].copy()
    names = sorted(set(id2name.values()))
    color = {n: COLORS[i % len(COLORS)][::-1] for i, n in enumerate(names)}
    for s in shapes:
        name = id2name.get(s["label_id"], "?")
        col = color.get(name, (255, 255, 255))
        p = np.array(s["points"], float)
        if s["type"] == "rectangle":
            x0, y0, x1, y1 = p.astype(int)
            cv2.rectangle(out, (x0, y0), (x1, y1), col, 2)
            anchor = (x0, y0)
        elif s["type"] in ("polygon", "polyline"):
            q = p.reshape(-1, 2).astype(np.int32)
            cv2.polylines(out, [q], s["type"] == "polygon", col, 2)
            anchor = tuple(q[0])
        elif s["type"] == "mask":
            runs, (x0, y0, x1, y1) = p[:-4].astype(int), p[-4:].astype(int)
            flat = np.repeat(np.arange(len(runs)) % 2, runs).astype(bool)
            crop = flat.reshape(y1 - y0 + 1, x1 - x0 + 1)
            reg = out[y0:y1 + 1, x0:x1 + 1]
            reg[crop] = (0.5 * reg[crop] + 0.5 * np.array(col)).astype(np.uint8)
            anchor = (x0, y0)
        else:   # skeleton
            anchor = None
            for e in s["elements"]:
                if not e["outside"]:
                    x, y = int(e["points"][0]), int(e["points"][1])
                    cv2.circle(out, (x, y), 3, col if not e["occluded"] else (128, 128, 128), -1)
                    anchor = anchor or (x, y)
            if anchor is None:
                continue
        cv2.putText(out, name, (int(anchor[0]), max(12, int(anchor[1]) - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, col, 1,
                    cv2.LINE_AA)
    _imwrite(path, out)


# -----------------------------------------------------------------------------

def main():
    for f in (sys.stdout, sys.stderr):
        try:
            f.reconfigure(encoding="utf-8")
        except Exception:
            pass
    ap = argparse.ArgumentParser(description="Gan nhan 2D theo kieu ve da chon (giong nut Draw new ... tren CVAT)")
    ap.add_argument("job", type=int, nargs="?", help="Job (mac dinh CVAT_JOB_ID trong .env)")
    ap.add_argument("--shape", choices=SHAPES, required=True)
    ap.add_argument("--frame", type=int, help="Chi 1 frame (mac dinh: moi frame cua job)")
    ap.add_argument("--labels", help="Chi cac nhan nay, cach nhau dau phay (mac dinh: moi nhan hop kieu)")
    ap.add_argument("--push", action="store_true", help="Day len CVAT (mac dinh chi xem truoc)")
    ap.add_argument("--replace", action="store_true",
                    help="Khi --push: sao luu roi xoa box AUTO cu cung kieu + cung nhan o cac frame nay (nhan ve tay giu nguyen)")
    ap.add_argument("--conf", type=float, default=0.3, help="Do tin cay toi thieu cua YOLOE (mac dinh 0.3)")
    ap.add_argument("--out-dir", default="preview_shape")
    ap.add_argument("--env", default=os.path.join(HERE, ".env"))
    args = ap.parse_args()

    os.chdir(HERE)
    load_dotenv(args.env, override=True)
    client = CvatClient(os.environ["CVAT_URL"], os.environ["CVAT_TOKEN"])
    job_id = args.job or int(os.environ["CVAT_JOB_ID"])
    r = client.session.get(f"{client.base_url}/api/jobs/{job_id}")
    r.raise_for_status()
    meta = r.json()
    if (meta.get("dimension") or "2d").lower() == "3d":
        raise SystemExit(f"Job {job_id} la 3D -> chi ve duoc cuboid (dung autolabel.bat / menu muc 1)")
    labels = get_labels(client, job_id)
    targets = target_labels(labels, args.shape, args.labels.split(",") if args.labels else None)
    if not targets:
        kinds = ", ".join(f"{lb['name']} ({lb.get('type') or 'any'})" for lb in labels)
        raise SystemExit(f"Job {job_id} khong co nhan nao ve duoc bang '{args.shape}'. Nhan cua job: {kinds}")
    label_ids = {lb["name"]: lb["id"] for lb in targets}
    id2name = {lb["id"]: lb["name"] for lb in targets}
    for lb in targets:
        for s in lb.get("sublabels", []):
            id2name.setdefault(s["id"], f"{lb['name']}.{s['name']}")
    frames = [args.frame] if args.frame is not None else list(range(meta["start_frame"], meta["stop_frame"] + 1))
    print(f"Job {job_id} (task {meta['task_id']}) | kieu '{args.shape}' | {len(frames)} frame | "
          f"nhan: {', '.join(lb['name'] for lb in targets)}")

    if args.shape == "skeleton":
        sk = [(lb, skeleton_kind(lb)) for lb in targets]
        for lb, kind in sk:
            print(f"  {lb['name']} ({len(lb.get('sublabels', []))} diem) -> "
                  f"{ {'face': 'mat', 'person': 'nguoi', 'hand': 'ban tay'}.get(kind, 'KHONG nhan ra, bo qua') }")
        sk = [(lb, k) for lb, k in sk if k]
        if not sk:
            raise SystemExit("Khong nhan skeleton nao khop mat / nguoi / ban tay (xem ten cac diem con tren CVAT)")
        import keypoints
        kinds = tuple({k for _, k in sk})
    else:
        finder = ObjectFinder(meta["task_id"], list(label_ids), args.conf)

    os.makedirs(args.out_dir, exist_ok=True)
    existing = None
    if args.push and args.replace:
        r = client.session.get(f"{client.base_url}/api/jobs/{job_id}/annotations")
        r.raise_for_status()
        existing = r.json().get("shapes", [])
    total = 0
    for fr in frames:
        img = np.asarray(client.get_frame_image(job_id, fr))
        if args.shape == "skeleton":
            fd, tmp = tempfile.mkstemp(suffix=".jpg")
            os.close(fd)
            try:
                _imwrite(tmp, img[:, :, ::-1])
                det = keypoints.detect(tmp, kinds=kinds)
            finally:
                os.remove(tmp)
            shapes = skeleton_shapes(det, sk, fr)
        else:
            dets = finder.find(img)
            shapes = object_shapes(dets, args.shape, label_ids, fr)
        cnt = {}
        for s in shapes:
            cnt[id2name[s["label_id"]]] = cnt.get(id2name[s["label_id"]], 0) + 1
        base = os.path.join(args.out_dir, f"job{job_id}_f{fr}_{args.shape}")
        draw_preview(img, shapes, id2name, base + ".jpg")
        json.dump(shapes, open(base + ".json", "w", encoding="utf-8"))
        print(f"[frame {fr}] {len(shapes)} {args.shape}: {', '.join(f'{k} {v}' for k, v in sorted(cnt.items())) or '-'}"
              f"  -> {base}.jpg")
        total += len(shapes)
        if not args.push:
            continue
        if existing is not None:
            old = [s for s in existing if s["frame"] == fr and s["type"] == args.shape
                   and s["label_id"] in label_ids.values() and s.get("source") in ("auto", "semi-auto")]
            if old:
                os.makedirs(os.path.join(HERE, "backup_2d"), exist_ok=True)
                bk = os.path.join(HERE, "backup_2d", f"job{job_id}_f{fr}_{args.shape}_{time.strftime('%Y%m%d_%H%M%S')}.json")
                json.dump(old, open(bk, "w", encoding="utf-8"))
                client.delete_shapes(job_id, old)
                print(f"  Xoa {len(old)} {args.shape} auto cu (sao luu {bk})")
        if shapes:
            client.push_annotations(job_id, shapes)
            print(f"  Da day {len(shapes)} {args.shape} len CVAT")
    print(f"\nTong: {total} {args.shape} tren {len(frames)} frame" + ("" if args.push else
          f" (chi xem truoc, anh trong {args.out_dir}/ — them --push de day len CVAT)"))


if __name__ == "__main__":
    main()
