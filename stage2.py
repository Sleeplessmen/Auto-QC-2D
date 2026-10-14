"""
stage2.py — Buoc loc thu 2 cho label_hq_2d: hoc tu anh da co dap an (doi_chieu/gt) de
  (1) quyet dinh GIU / BO tung box ung vien (box thua: trung lap, bong guong, bien bao, tay tai xe...)
  (2) gan lai nhan xe 4 banh: GreenSM / car / truck / bus

Dac trung moi box: diem tung model, so model thay, kich thuoc / vi tri, do chong voi box khac,
mau xanh ngoc, va xac suat CLIP theo ~20 cau mo ta (nguoi, xe, bong guong, taplo, bien bao...).

  python stage2.py train --gt D:/DATA/ket_qua_gan_nhan/doi_chieu/gt --images D:/DATA      -> models/stage2.pkl
  (label_hq_2d.py tu dung models/stage2.pkl neu co)
"""
import argparse
import glob
import json
import os
import pickle
import re
import sys

import cv2
import numpy as np

import label_hq_2d as L

HERE = L.HERE
MODEL_PATH = os.path.join(HERE, "models", "stage2.pkl")
CAND_MIN = 0.12            # ung vien: diem WBF toi thieu
VEH_CLASSES = ["GreenSM", "car", "truck", "bus"]
PROMPTS = ["a photo of a person", "a photo of a person riding a motorbike", "a photo of a pedestrian",
           "a photo of a motorbike", "a photo of a parked motorbike", "a photo of a bicycle",
           "a photo of a car", "a photo of a taxi", "a photo of a turquoise taxi car", "a photo of a truck",
           "a photo of a bus", "a photo of a golf cart",
           "a reflection in a rear-view mirror", "a car side mirror", "a car dashboard", "a human hand",
           "a car seat", "a traffic sign", "a poster on a wall", "a tree trunk", "a building", "an empty road",
           "a blurry dark image", "rain drops on glass"]


def candidates(img, dets):
    """Ung vien = cum WBF diem >= CAND_MIN, sau loc kich thuoc / xe minh (luat cung)."""
    allc = [o for o in L.wbf(dets, len(L.MODELS)) if o["score"] >= CAND_MIN]
    return L.ego_filter(allc, img)


def _contain(a, b):
    """phan dien tich a nam trong b"""
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0])) * max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    return ix / max(1e-6, (a[2] - a[0]) * (a[3] - a[1]))


def _wide_cyan(img, box):
    x1, y1, x2, y2 = [int(round(v)) for v in box]
    c = img[max(0, y1):y2, max(0, x1):x2]
    if c.size == 0:
        return 0.0
    f = img.reshape(-1, 3).astype(np.float32).mean(0)
    c = np.clip(c.astype(np.float32) * (f.mean() / f), 0, 255).astype(np.uint8)       # can bang trang
    hsv = cv2.cvtColor(c[:, :, ::-1], cv2.COLOR_BGR2HSV)
    return float((cv2.inRange(hsv, (75, 40, 40), (105, 255, 255)) > 0).mean())


def features(img, cands, clf):
    h, w = img.shape[:2]
    if not cands:
        return np.zeros((0, 1))
    P = clf.probs(img, [o["box"] for o in cands], PROMPTS, pad=0.12)
    pg = clf.prob(img, [o["box"] for o in cands])
    bright = float(img.mean()) / 255
    order = sorted(range(len(cands)), key=lambda i: -cands[i]["score"])
    rank = {i: r for r, i in enumerate(order)}
    rows = []
    for i, o in enumerate(cands):
        x1, y1, x2, y2 = o["box"]
        bw, bh = max(1.0, x2 - x1), max(1.0, y2 - y1)
        g = L.GROUP[o["cls"]]
        pm = [o["per_model"].get(m, 0.0) for m in range(len(L.MODELS))]
        higher = [cands[j] for j in order if rank[j] < rank[i]]
        same_hi = [k for k in higher if L.GROUP[k["cls"]] == g]
        f_iou_hi = max([L.iou(o["box"], k["box"]) for k in same_hi] + [0])
        f_in_hi = max([_contain(o["box"], k["box"]) for k in same_hi] + [0])
        f_hi_in = max([_contain(k["box"], o["box"]) for k in same_hi] + [0])
        strong = [k for k in cands if k is not o and k["score"] >= 0.3]
        ov = {gg: max([L.iou(o["box"], k["box"]) for k in strong if L.GROUP[k["cls"]] == gg] + [0])
              for gg in ("veh", "two", "person")}
        rows.append([
            g == "veh", g == "two", g == "person",
            *[o["cls"] == c for c in ("car", "truck", "bus", "motorcycle", "bicycle", "person")],
            *pm, o["score"], o["n_models"], o["max_score"], o.get("n_members", 0),
            np.log(bw * bh / (w * h)), bw / w, bh / h, bh / bw, (x1 + x2) / 2 / w, (y1 + y2) / 2 / h, y2 / h,
            x1 < 2, y1 < 2, x2 > w - 2, y2 > h - 2,
            f_iou_hi, f_in_hi, f_hi_in, ov["veh"], ov["two"], ov["person"],
            bright, L.cyan_ratio(img, o["box"]), _wide_cyan(img, o["box"]), pg[i],
            *P[i],
        ])
    return np.array(rows, dtype=np.float32)


def load_dets(name, cache):
    dets = []
    for mi, (p, _, _) in enumerate(L.MODELS):
        cp = os.path.join(cache, f"{name}__{re.sub(r'[^A-Za-z0-9.-]', '_', p)}.json")
        dets += [tuple(d[:6]) + (mi,) for d in json.load(open(cp))]
    return dets


def label_candidates(cands, gt):
    """keep: 1 trung vat that / 0 thua / -1 bo qua (vung ignore); cls: nhan dung neu keep=1"""
    import eval_hq2d as E
    G = [o for o in gt["objects"]]
    pairs = sorted(((L.iou(c["box"], g["box"]), i, j) for i, c in enumerate(cands) for j, g in enumerate(G)
                    if L.GROUP.get(c["cls"]) == L.GROUP.get(g["cls"], "veh" if g["cls"] == "GreenSM" else None)),
                   reverse=True)
    mc, mg = {}, {}
    for v, i, j in pairs:
        if v < 0.5:
            break
        if i in mc or j in mg:
            continue
        mc[i], mg[j] = j, i
    keep, cls = [], []
    for i, c in enumerate(cands):
        if i in mc:
            keep.append(1)
            cls.append(G[mc[i]]["cls"])
        elif E.in_regions(c["box"], gt["ignore_regions"]) or any(L.iou(c["box"], q["box"]) >= 0.3 for q in gt["ignore"]):
            keep.append(-1)
            cls.append(None)
        else:
            keep.append(0)
            cls.append(None)
    return keep, cls


def build_dataset(gt_dir, images, cache, clf):
    data = []          # (ten anh, cands, X, keep, cls)
    for gp in sorted(glob.glob(os.path.join(gt_dir, "*.json"))):
        gt = json.load(open(gp, encoding="utf-8"))
        name = os.path.splitext(gt["image"])[0]
        img = cv2.imdecode(np.fromfile(os.path.join(images, gt["image"]), np.uint8), 1)[:, :, ::-1].copy()
        cands = candidates(img, load_dets(name, cache))
        X = features(img, cands, clf)
        keep, cls = label_candidates(cands, gt)
        data.append((name, cands, X, np.array(keep), cls))
    return data


def fit(data):
    from sklearn.ensemble import HistGradientBoostingClassifier
    X = np.vstack([d[2] for d in data if len(d[1])])
    y = np.concatenate([d[3] for d in data if len(d[1])])
    m = y >= 0
    keep_m = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.05, max_leaf_nodes=15,
                                            l2_regularization=1.0, random_state=0).fit(X[m], y[m])
    cl = [c for d in data for c in d[4]]
    vm = np.array([c in VEH_CLASSES for c in cl])
    yv = np.array([VEH_CLASSES.index(c) for c in cl if c in VEH_CLASSES])
    veh_m = HistGradientBoostingClassifier(max_iter=200, learning_rate=0.05, max_leaf_nodes=7,
                                           l2_regularization=1.0, random_state=0).fit(X[vm], yv)
    return dict(keep=keep_m, veh=veh_m)


def apply(models, cands, X, thr=0.5):
    """-> danh sach vat cuoi (dict nhu label_hq_2d) da gan nhan, bo trung lap"""
    if not cands:
        return []
    pk = models["keep"].predict_proba(X)[:, 1]
    out = []
    for o, p, x in zip(cands, pk, X):
        if p < thr:
            continue
        o = dict(o, p_keep=round(float(p), 3))
        if L.GROUP[o["cls"]] == "veh":
            pv = models["veh"].predict_proba(x[None])[0]
            o["cls"] = VEH_CLASSES[int(models["veh"].classes_[np.argmax(pv)])]
            o["p_cls"] = round(float(pv.max()), 3)
        out.append(o)
    # trung lap con sot: cung nhom, IoU > 0.6 -> giu p_keep cao hon
    out.sort(key=lambda o: -o["p_keep"])
    final = []
    for o in out:
        go = "veh" if o["cls"] in VEH_CLASSES else L.GROUP[o["cls"]]
        if any(("veh" if k["cls"] in VEH_CLASSES else L.GROUP[k["cls"]]) == go and L.iou(o["box"], k["box"]) > 0.6
               for k in final):
            continue
        final.append(o)
    return final


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["train"])
    ap.add_argument("--gt", required=True)
    ap.add_argument("--images", required=True)
    ap.add_argument("--cache", default=os.path.join(HERE, "cache_hq2d"))
    args = ap.parse_args()
    clf = L.GreenSMClassifier()
    data = build_dataset(args.gt, args.images, args.cache, clf)
    models = fit(data)
    os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)
    pickle.dump(models, open(MODEL_PATH, "wb"))
    print(f"Da hoc tu {len(data)} anh -> {MODEL_PATH}")


if __name__ == "__main__":
    main()
