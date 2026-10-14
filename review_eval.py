"""
review_eval.py — Do do tin cay cua review tu dong tren bo anh co dap an (mac dinh D:\\DATA, 123 anh).

  1. "Nguoi gan dung het" (nhan = dap an): moi ghi chu la BAO NHAM.
  2. Cai loi gia vao dap an (sai kich thuoc, sai nhan, xoa box, them box thua) -> do ty le BAT DUOC tung loai loi.

  python review_eval.py [--images D:/DATA] [--gt D:/DATA/ket_qua_gan_nhan/doi_chieu/gt] [--seed 0]
"""
import argparse
import glob
import json
import os
import random
import sys

import cv2
import numpy as np

import label_hq_2d as L
import review_core as R


def perturb(objs, W, H, rng):
    """tra ve (box nguoi gan gia, danh sach loi da cai: (loai, id))"""
    out, errs = [], []
    for k, o in enumerate(objs):
        b = list(o["box"])
        bid = f"g{k}"
        w, h = b[2] - b[0], b[3] - b[1]
        r = rng.random()
        if r < 0.07:                      # xoa -> thieu
            errs.append(("thieu", bid, o["box"], o["cls"]))
            continue
        if r < 0.15 and min(w, h) >= R.MIN_CHECK_SIDE:     # sai kich thuoc: 1-2 canh lech 25-40%
            for e in rng.sample([0, 1, 2, 3], rng.choice([1, 2])):
                side = w if e in (0, 2) else h
                d = max(10, rng.uniform(0.25, 0.4) * side) * rng.choice([-1, 1])
                b[e] += -d if e in (0, 1) else d
            b = [max(0, min(W, b[0])), max(0, min(H, b[1])), max(0, min(W, b[2])), max(0, min(H, b[3]))]
            if b[2] - b[0] > 4 and b[3] - b[1] > 4:
                errs.append(("sai_kich_thuoc", bid, b, o["cls"]))
                out.append(dict(id=bid, label=o["cls"], box=b, occluded=False))
                continue
            b = list(o["box"])
        cls = o["cls"]
        if 0.15 <= r < 0.20:              # sai nhan
            alt = {"car": ["truck", "GreenSM"], "GreenSM": ["car"], "truck": ["car", "bus"], "bus": ["truck"],
                   "motorcycle": ["bicycle", "person"], "bicycle": ["motorcycle"], "person": ["motorcycle"]}[cls]
            cls = rng.choice(alt)
            errs.append(("sai_nhan", bid, b, cls))
        out.append(dict(id=bid, label=cls, box=b, occluded=False))
    # box thua: o ngau nhien khong de len vat nao
    for _ in range(1 if rng.random() < 0.4 else 0):
        for _try in range(30):
            bw, bh = rng.uniform(40, 160), rng.uniform(40, 120)
            x, y = rng.uniform(0, W - bw), rng.uniform(H * 0.2, H - bh)
            fb = [x, y, x + bw, y + bh]
            if all(L.iou(fb, o["box"]) < 0.05 for o in objs):
                bid = f"fake{len(errs)}"
                cls = rng.choice(["car", "person", "motorcycle"])
                out.append(dict(id=bid, label=cls, box=fb, occluded=False))
                errs.append(("thua", bid, fb, cls))
                break
    return out, errs


def hit(err, finds):
    kind, bid, box, _ = err
    for f in finds:
        if f["kind"] != kind:
            continue
        if kind == "thieu":
            if L.iou(f["box"], box) >= 0.5:
                return f
        elif f["ref"] == bid:
            return f
    return None


def main():
    for f in (sys.stdout, sys.stderr):
        try:
            f.reconfigure(encoding="utf-8")
        except Exception:
            pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--images", default="D:/DATA")
    ap.add_argument("--gt", default="D:/DATA/ket_qua_gan_nhan/doi_chieu/gt")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--mode", default="chinh_xac")
    ap.add_argument("--limit", type=int)
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--dump", help="luu ghi chu bao nham ra file json de xem")
    args = ap.parse_args()

    runner = R.ToolRunner(args.mode)
    tool2job, job_group, _ = R.build_label_map(L.CLASSES)
    rng = random.Random(args.seed)
    clean = dict(boxes=0, sure=0, unsure=0, by_kind={})
    inj = {}
    fp_pert = dict(sure=0, unsure=0)
    dump = []
    missed = {}
    gts = sorted(glob.glob(os.path.join(args.gt, "*.json")))[:args.limit]
    for n, gp in enumerate(gts, 1):
        g = json.load(open(gp, encoding="utf-8"))
        ip = os.path.join(args.images, g["image"])
        img = cv2.imdecode(np.fromfile(ip, np.uint8), cv2.IMREAD_COLOR)[:, :, ::-1].copy()
        H, W = img.shape[:2]
        ign = g.get("ignore", []) + [dict(box=r) for r in g.get("ignore_regions", [])]
        tool, rej = runner.detect(img, os.path.splitext(g["image"])[0])
        # vat 'ignore' trong dap an (mo, khong ro) -> khong tinh bao nham
        lab = [dict(id=f"g{k}", label=o["cls"], box=o["box"], occluded=False) for k, o in enumerate(g["objects"])]
        finds = R.compare(lab, tool, rej, W, H, tool2job, job_group, img=img, runner=runner)
        finds = [f for f in finds if not any(L.iou(f["box"], q["box"]) >= 0.3 or R._inside(f["box"], q["box"]) > 0.7 for q in ign)]
        clean["boxes"] += len(lab)
        for f in finds:
            clean["sure" if f["sure"] else "unsure"] += 1
            kk = clean["by_kind"].setdefault(f["kind"], [0, 0])
            kk[0 if f["sure"] else 1] += 1
            dump.append(dict(image=g["image"], **{k: v for k, v in f.items()}))

        plab, errs = perturb(g["objects"], W, H, rng)
        pf = R.compare(plab, tool, rej, W, H, tool2job, job_group, img=img, runner=runner)
        pf = [f for f in pf if not any(L.iou(f["box"], q["box"]) >= 0.3 or R._inside(f["box"], q["box"]) > 0.7 for q in ign)]
        used = set()
        for e in errs:
            f = hit(e, pf)
            st = inj.setdefault(e[0], [0, 0, 0])      # tong, bat chac, bat khong chac
            st[0] += 1
            if f is not None:
                st[1 if f["sure"] else 2] += 1
                used.add(id(f))
            else:
                bt = max(tool, key=lambda o: L.iou(o["box"], e[2]), default=None)
                v = L.iou(bt["box"], e[2]) if bt else 0
                side = min(e[2][2] - e[2][0], e[2][3] - e[2][1])
                why = ("tool khong thay" if v < 0.5 else f"tool {bt['cls']} {bt['score']:.2f} {bt.get('trang_thai')}")
                missed.setdefault(e[0], []).append((round(side), why, e[3]))
        bad_ids = {e[1] for e in errs}
        for f in pf:
            if id(f) in used or (f["ref"] in bad_ids):
                continue
            fp_pert["sure" if f["sure"] else "unsure"] += 1
        if n % 20 == 0:
            print(f"  {n}/{len(gts)}", flush=True)

    B = clean["boxes"]
    print(f"\n=== 1) Nguoi gan DUNG HET ({len(gts)} anh, {B} box) — moi ghi chu la bao nham ===")
    print(f"  ghi 'loi' (chac): {clean['sure']}  = {clean['sure'] / B * 100:.1f} / 100 box")
    print(f"  ghi 'khong chac': {clean['unsure']} = {clean['unsure'] / B * 100:.1f} / 100 box")
    for k, (a, b) in sorted(clean["by_kind"].items()):
        print(f"    {R.KIND_VI[k]:15s} chac {a:3d}  khong chac {b:3d}")
    print("\n=== 2) Cai loi gia ===")
    tot = [0, 0, 0]
    for k, (t, a, b) in sorted(inj.items()):
        print(f"  {R.KIND_VI[k]:15s} {t:4d} loi | bat 'loi' {a / t:6.1%} | bat 'khong chac' {b / t:6.1%} | bo lot {(t - a - b) / t:6.1%}")
        tot = [x + y for x, y in zip(tot, (t, a, b))]
    print(f"  {'TONG':15s} {tot[0]:4d} loi | bat 'loi' {tot[1] / tot[0]:6.1%} | bat 'khong chac' {tot[2] / tot[0]:6.1%} | "
          f"bo lot {(tot[0] - tot[1] - tot[2]) / tot[0]:6.1%}")
    print(f"  bao nham tren box dung: chac {fp_pert['sure']}, khong chac {fp_pert['unsure']}")
    print("\n=== Loi bo lot (theo co vat) ===")
    for k, rows in sorted(missed.items()):
        small = sum(1 for r in rows if r[0] < 30)
        notool = sum(1 for r in rows if r[1] == "tool khong thay")
        print(f"  {R.KIND_VI[k]:15s} {len(rows):3d} | vat < 30px: {small} | tool khong thay: {notool}")
        if args.verbose:
            for r in rows[:25]:
                print("     ", r)
    if args.dump:
        json.dump(dump, open(args.dump, "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=float)


if __name__ == "__main__":
    main()
