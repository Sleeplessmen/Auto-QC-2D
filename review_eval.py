"""
review_eval.py — Do do tin cay cua review tu dong tren bo anh co dap an (mac dinh D:\\DATA, 123 anh).

  1. "Nguoi gan dung het" (nhan = dap an): moi ghi chu la BAO NHAM.
  2. Cai loi gia vao dap an (sai kich thuoc, sai nhan, xoa box, them box thua) -> do ty le BAT DUOC tung loai loi.

  python review_eval.py [--images D:/DATA] [--gt D:/DATA/ket_qua_gan_nhan/doi_chieu/gt] [--seed 0]

  3. SEGMENTATION (--seg): polygon nguoi ve that (COCO val2017, tao bang tao_bo_seg_eval.py). Do bao nham tren polygon dung,
     roi cai loi polygon (co / phinh / lech / mat 1 phan / ve tho) va do ty le bat duoc:
  python review_eval.py --seg D:/DATA_EXT/coco_seg_eval
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
import seg_check as S


def degrade(img, cond, seed):
    """Gia lap dieu kien xau tren anh ban ngay: 'dem' (toi, nhieu hat), 'mua' (vet mua, mo, suong)."""
    if cond == "goc":
        return img
    r = np.random.default_rng(seed)
    f = img.astype(np.float32) / 255
    if cond == "dem":
        f = (f ** 2.2) * 0.6
        f += r.normal(0, 0.025, f.shape).astype(np.float32)
    elif cond == "mua":
        f = f * 0.75 + 0.18
        H, W = f.shape[:2]
        rain = np.zeros((H, W), np.float32)
        for _ in range(int(W * H / 900)):
            x, y = int(r.integers(0, W)), int(r.integers(0, H))
            ln = int(r.integers(10, 30))
            cv2.line(rain, (x, y), (x + ln // 4, y + ln), float(r.uniform(0.25, 0.6)), 1)
        rain = cv2.GaussianBlur(rain, (3, 3), 0)
        f = cv2.GaussianBlur(f, (5, 5), 1.2)
        f = f * (1 - rain[..., None]) + rain[..., None] * 0.9
    return (np.clip(f, 0, 1) * 255).astype(np.uint8)


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
    # box trung: chep 1 box co san, lech nhe
    if objs and rng.random() < 0.25:
        o = rng.choice(objs)
        b = o["box"]
        w, h = b[2] - b[0], b[3] - b[1]
        if min(w, h) >= 20:
            j = [rng.uniform(-0.03, 0.03) * (w if i % 2 == 0 else h) for i in range(4)]
            db = [b[0] + j[0], b[1] + j[1], b[2] + j[2], b[3] + j[3]]
            bid = f"dup{len(errs)}"
            out.append(dict(id=bid, label=o["cls"], box=db, occluded=False))
            errs.append(("trung", bid, db, o["cls"]))
    # box det phi ly (keo nham): rong 250-900px, cao 5-15px
    if rng.random() < 0.15:
        bw, bh = rng.uniform(250, min(900, W - 1)), rng.uniform(5, 15)
        x, y = rng.uniform(0, W - bw), rng.uniform(H * 0.3, H * 0.7)
        fb = [x, y, x + bw, y + bh]
        bid = f"flat{len(errs)}"
        out.append(dict(id=bid, label="car", box=fb, occluded=False))
        errs.append(("sai_kich_thuoc", bid, fb, "car"))
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


def _new_group():
    return dict(img=0, boxes=0, cl_sure=0, cl_unsure=0, inj={}, fp_s=0, fp_u=0,
                fr_ok=0, fr_strict=0, verdict=0, verdict_n=0, auto=0, auto_clean=0, clean_n=0)


def _ignored(f, ign):
    return any(L.iou(f["box"], q["box"]) >= 0.3 or R._inside(f["box"], q["box"]) > 0.7 for q in ign)


def main():
    for f in (sys.stdout, sys.stderr):
        try:
            f.reconfigure(encoding="utf-8")
        except Exception:
            pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--images", default="D:/DATA")
    ap.add_argument("--gt", default="D:/DATA/ket_qua_gan_nhan/doi_chieu/gt")
    ap.add_argument("--meta", help="json {ten anh: {timeofday, weather}} de chia ket qua theo dieu kien (BDD100K)")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--mode", default="chinh_xac")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--skip", type=int, default=0, help="bo qua N anh dau (vd anh da dung de chinh nguong)")
    ap.add_argument("--cond", default="goc", choices=["goc", "dem", "mua"], help="gia lap dieu kien anh")
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--dump", help="luu ghi chu bao nham ra file json de xem")
    ap.add_argument("--json", help="luu so lieu tung nhom ra file json")
    ap.add_argument("--rows", help="luu TUNG loi cai vao (loai, canh ngan vat, bat chac / khong chac / bo lot) + bao nham "
                                   "ra file json -> tinh lai ti le bat theo kich thuoc toi thieu ma khong can chay lai")
    ap.add_argument("--visible", action="store_true", help="guideline: chi ve phan nhin thay (vd BDD100K), khong ve toan bo vat")
    ap.add_argument("--min-px", type=float, default=0, help="guideline: bo qua vat co canh ngan nho hon N px")
    ap.add_argument("--no-far", action="store_true", help="tat luot phong to dai giua anh (de so sanh)")
    args = ap.parse_args()

    meta = json.load(open(args.meta, encoding="utf-8")) if args.meta else {}
    runner = R.ToolRunner(args.mode)
    if args.visible:
        R.AMODAL = False
    if args.no_far:
        R.FAR_ZOOM = False
    if args.min_px:                     # = guideline "vat duoi N px khong bat buoc gan" (khong_bat_buoc_duoi_px)
        R.MIN_MISS_BY_LABEL.update({c: args.min_px for c in L.CLASSES})
        R.MIN_MISS_SIDE = args.min_px
    tiny = lambda b: args.min_px and min(b[2] - b[0], b[3] - b[1]) < args.min_px
    tool2job, job_group, _ = R.build_label_map(L.CLASSES)
    rng = random.Random(args.seed)
    G = {}
    dump, missed, per_err = [], {}, dict(loi=[], bao_nham=[])
    side_of = lambda b: round(min(b[2] - b[0], b[3] - b[1]), 1)
    gts = sorted(glob.glob(os.path.join(args.gt, "*.json")))[args.skip:][:args.limit]
    for n, gp in enumerate(gts, 1):
        g = json.load(open(gp, encoding="utf-8"))
        ip = os.path.join(args.images, g["image"])
        img = cv2.imdecode(np.fromfile(ip, np.uint8), cv2.IMREAD_COLOR)[:, :, ::-1].copy()
        m = meta.get(g["image"], {})
        groups = ["tat ca"]
        if m:
            groups += [f"luc: {m.get('timeofday')}", f"troi: {m.get('weather')}"]
        else:
            groups.append("anh toi" if img.mean() < 60 or args.cond == "dem" else "anh sang")
        img = degrade(img, args.cond, n)
        H, W = img.shape[:2]
        ign = g.get("ignore", []) + [dict(box=r) for r in g.get("ignore_regions", [])]
        # guideline bo qua vat nho: vat nho trong dap an khong bat buoc gan -> ghi chu tren do khong tinh bao nham
        ign += [dict(box=o["box"]) for o in g["objects"] if tiny(o["box"])]
        tool, rej = runner.detect(img, os.path.splitext(g["image"])[0] + ("" if args.cond == "goc" else "__" + args.cond))

        # 1) nguoi gan dung het: moi ghi chu la bao nham
        lab = [dict(id=f"g{k}", label=o["cls"], box=o["box"], occluded=False) for k, o in enumerate(g["objects"])]
        finds = [f for f in R.compare(lab, tool, rej, W, H, tool2job, job_group, img=img, runner=runner) if not _ignored(f, ign)]
        cs, cu = sum(f["sure"] for f in finds), sum(not f["sure"] for f in finds)
        for f in finds:
            dump.append(dict(image=g["image"], **f))
            per_err["bao_nham"].append(dict(anh=g["image"], loai=f["kind"], chac=f["sure"], canh=side_of(f["box"])))
        per_err.setdefault("box_theo_canh", []).extend(side_of(o["box"]) for o in g["objects"])

        # 2) cai loi gia
        plab, errs = perturb(g["objects"], W, H, rng)
        errs = [e for e in errs if not (e[0] in ("thieu", "sai_nhan") and tiny(e[2]))]    # loi tren vat guideline bo qua
        pf = [f for f in R.compare(plab, tool, rej, W, H, tool2job, job_group, img=img, runner=runner) if not _ignored(f, ign)]
        used, res = set(), []
        for e in errs:
            f = hit(e, pf)
            res.append((e[0], None if f is None else f["sure"]))
            # canh ngan cua VAT THAT (loi kich thuoc / trung: box goc trong dap an), khong phai box da lam sai
            src = next((o["box"] for k_, o in enumerate(g["objects"]) if f"g{k_}" == e[1]), e[2])
            per_err["loi"].append(dict(anh=g["image"], loai=e[0], canh=side_of(src), kq="chac" if f and f["sure"] else "kc" if f else "lot",
                                    dem=m.get("timeofday") == "night" if m else None))
            if f is not None:
                used.add(id(f))
            else:
                bt = max(tool, key=lambda o: L.iou(o["box"], e[2]), default=None)
                v = L.iou(bt["box"], e[2]) if bt else 0
                side = min(e[2][2] - e[2][0], e[2][3] - e[2][1])
                missed.setdefault(e[0], []).append((round(side), "tool khong thay" if v < 0.5 else
                                                    f"tool {bt['cls']} {bt['score']:.2f} {bt.get('trang_thai')}", e[3], g["image"]))
        bad_ids = {e[1] for e in errs}
        fps = [f for f in pf if id(f) not in used and f["ref"] not in bad_ids]
        fp_s, fp_u = sum(f["sure"] for f in fps), sum(not f["sure"] for f in fps)
        caught = sum(r is not None for _, r in res)
        caught_sure = sum(r is True for _, r in res)

        for gr in groups:
            s = G.setdefault(gr, _new_group())
            s["img"] += 1
            s["boxes"] += len(lab)
            s["cl_sure"] += cs
            s["cl_unsure"] += cu
            for kind, r in res:
                t = s["inj"].setdefault(kind, [0, 0, 0])
                t[0] += 1
                t[1] += r is True
                t[2] += r is False
            s["fp_s"] += fp_s
            s["fp_u"] += fp_u
            # khung co loi: review dung = bat du moi loi (chac hoac khong chac), khong bao nham chac chan
            s["fr_ok"] += caught == len(errs) and fp_s == 0
            s["fr_strict"] += caught_sure == len(errs) and fp_s == 0 and fp_u == 0
            # phan dung "khung co loi / sach" tren ca 2 ban (dung het, co cai loi)
            s["verdict"] += (cs == 0) + (bool(errs) == bool(caught_sure + fp_s))
            s["verdict_n"] += 2
            # tool noi "sach" (khong ghi chu nao) -> cho qua tu dong. Do: trong so do bao nhieu thuc su sach
            s["clean_n"] += 1 + (not errs)
            for has_err, fl in ((False, finds), (bool(errs), pf)):
                if not fl:
                    s["auto"] += 1
                    s["auto_clean"] += not has_err
        if n % 50 == 0:
            print(f"  {n}/{len(gts)}", flush=True)

    out = {}
    print(f"\n######## {len(gts)} anh · dieu kien gia lap: {args.cond}")
    for gr in sorted(G, key=lambda k: (k != "tat ca", k)):
        s = G[gr]
        t = [sum(v[i] for v in s["inj"].values()) for i in range(3)]
        rec = (t[1] + t[2]) / t[0] if t[0] else 0
        auto_p = s["auto_clean"] / s["auto"] if s["auto"] else 0
        auto_c = s["auto_clean"] / s["clean_n"] if s["clean_n"] else 0
        out[gr] = dict(anh=s["img"], box=s["boxes"], bat_loi=rec, bat_chac=t[1] / t[0] if t[0] else 0,
                       bao_nham_chac_100box=s["cl_sure"] / max(1, s["boxes"]) * 100,
                       bao_nham_kc_100box=s["cl_unsure"] / max(1, s["boxes"]) * 100,
                       khung_review_dung=s["fr_ok"] / s["img"], khung_hoan_hao=s["fr_strict"] / s["img"],
                       phan_dung_co_khong_loi=s["verdict"] / s["verdict_n"],
                       cho_qua_tu_dong_dung=auto_p, cho_qua_tu_dong_phu=auto_c,
                       theo_loai={R.KIND_VI[k]: dict(tong=v[0], chac=v[1] / v[0], khong_chac=v[2] / v[0]) for k, v in s["inj"].items()})
        o = out[gr]
        print(f"\n== {gr}: {s['img']} anh, {s['boxes']} box")
        print(f"  Bat loi cai vao     : {o['bat_loi']:6.1%} (chac {o['bat_chac']:.1%}) tren {t[0]} loi")
        for k, v in sorted(o["theo_loai"].items()):
            print(f"      {k:15s} {v['tong']:4d} | chac {v['chac']:6.1%} | khong chac {v['khong_chac']:6.1%} | bo lot {1 - v['chac'] - v['khong_chac']:6.1%}")
        print(f"  Bao nham / 100 box dung: chac {o['bao_nham_chac_100box']:.1f} · khong chac {o['bao_nham_kc_100box']:.1f}")
        print(f"  Khung co loi review dung (bat du, khong bao nham chac): {o['khung_review_dung']:6.1%} · hoan hao {o['khung_hoan_hao']:6.1%}")
        print(f"  Phan dung khung co loi / sach : {o['phan_dung_co_khong_loi']:6.1%}")
        print(f"  Tool noi 'sach' -> dung {auto_p:6.1%} ({s['auto']} khung) · cho qua duoc {auto_c:6.1%} so khung sach")
    print("\n=== Loi bo lot (theo co vat) ===")
    for k, rows in sorted(missed.items()):
        small = sum(1 for r in rows if r[0] < 30)
        notool = sum(1 for r in rows if r[1] == "tool khong thay")
        print(f"  {R.KIND_VI[k]:15s} {len(rows):3d} | vat < 30px: {small} | tool khong thay: {notool}")
        if args.verbose:
            for r in rows[:25]:
                print("     ", r)
    if args.json:
        json.dump(out, open(args.json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    if args.dump:
        json.dump(dump, open(args.dump, "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=float)
    if args.rows:
        json.dump(per_err, open(args.rows, "w", encoding="utf-8"), ensure_ascii=False, default=float)


# ---------------------------------------------------------------------------
# 3) segmentation: loi polygon / mask tung vat
# ---------------------------------------------------------------------------
SEG_KINDS = ["co", "phinh", "lech", "mat_phan", "tho"]
SEG_VI = {"co": "co lem vien", "phinh": "phinh ra nen", "lech": "lech vi tri", "mat_phan": "mat 1 phan vat", "tho": "ve tho (it diem)"}


def _poly_mask(polys, W, H):
    m = np.zeros((H, W), np.uint8)
    for p in polys:
        if len(p) >= 6:
            cv2.fillPoly(m, [np.round(np.array(p, np.float32).reshape(-1, 2)).astype(np.int32)], 1)
    return m.astype(bool)


def _box(m):
    ys, xs = np.nonzero(m)
    return [float(xs.min()), float(ys.min()), float(xs.max() + 1), float(ys.max() + 1)]


def perturb_mask(M, kind, rng):
    """Loi labeler hay gap tren polygon. Tra ve mask moi (hoac None neu khong tao duoc)."""
    A = M.sum()
    u8 = M.astype(np.uint8)
    k3 = np.ones((3, 3), np.uint8)
    if kind == "co":                      # ve lem vao trong toan vien: mat 20-35% dien tich
        r, m = rng.uniform(0.2, 0.35), u8
        for _ in range(200):
            m = cv2.erode(m, k3)
            if m.sum() <= (1 - r) * A:
                break
        return m.astype(bool)
    if kind == "phinh":                   # to ra nen quanh vien: them 20-40%
        r, m = rng.uniform(0.2, 0.4), u8
        for _ in range(200):
            m = cv2.dilate(m, k3)
            if m.sum() >= (1 + r) * A:
                break
        return m.astype(bool)
    x1, y1, x2, y2 = _box(M)
    w, h = x2 - x1, y2 - y1
    if kind == "lech":                    # dat lech 20-30% chieu rong / cao
        if rng.random() < 0.6:
            dx, dy = rng.uniform(0.2, 0.3) * w * rng.choice([-1, 1]), 0
        else:
            dx, dy = 0, rng.uniform(0.2, 0.3) * h * rng.choice([-1, 1])
        T = np.float32([[1, 0, dx], [0, 1, dy]])
        return cv2.warpAffine(u8, T, (M.shape[1], M.shape[0]), flags=cv2.INTER_NEAREST).astype(bool)
    if kind == "mat_phan":                # bo quen 1 dau vat (25-40% theo 1 chieu)
        c, m = rng.uniform(0.25, 0.4), M.copy()
        side = rng.choice(["left", "right", "top", "bottom"])
        if side == "left":
            m[:, :int(x1 + c * w)] = False
        elif side == "right":
            m[:, int(x2 - c * w):] = False
        elif side == "top":
            m[:int(y1 + c * h)] = False
        else:
            m[int(y2 - c * h):] = False
        return m
    if kind == "tho":                     # ve qua it diem (4-6 dinh), cat goc / lem nhieu
        cs, _ = cv2.findContours(u8, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        c = max(cs, key=cv2.contourArea)
        n = rng.choice([4, 5, 6])
        eps = 0.01 * cv2.arcLength(c, True)
        p = cv2.approxPolyDP(c, eps, True)
        while len(p) > n:
            eps *= 1.3
            p = cv2.approxPolyDP(c, eps, True)
        m = np.zeros_like(u8)
        cv2.fillPoly(m, [p], 1)
        return m.astype(bool)
    return None


def _miou(a, b):
    u = (a | b).sum()
    return float((a & b).sum() / u) if u else 1.0


def main_seg(args):
    root = args.seg
    gts = json.load(open(os.path.join(root, "gt_seg.json"), encoding="utf-8"))[args.skip:][:args.limit]
    runner = R.ToolRunner(args.mode)
    sam = runner.seg_sam()
    tool2job, job_group, _ = R.build_label_map(L.CLASSES)
    rng = random.Random(args.seed)
    n_clean = cs = cu = 0
    inj = {k: [0, 0, 0] for k in SEG_KINDS}       # tong, chac, khong chac
    by_size = {}
    fp_s = fp_u = n_ok_pert = 0
    sam_iou, dump = [], []
    miss_cmp = dict(thieu_s=0, thieu_u=0, thua_s=0, thua_u=0)
    for n, g in enumerate(gts, 1):
        ip = os.path.join(root, "images", g["image"])
        img = cv2.imdecode(np.fromfile(ip, np.uint8), cv2.IMREAD_COLOR)[:, :, ::-1].copy()
        H, W = img.shape[:2]
        areas = []
        for k, o in enumerate(g["objects"]):
            m = _poly_mask(o["polys"], W, H)
            if m.any():
                areas.append(dict(id=f"g{k}", label=o["cls"], kind="polygon", mask=m, box=_box(m)))
        tool, rej = runner.detect(img, "coco_" + os.path.splitext(g["image"])[0])
        ign = [dict(box=b) for b in g.get("ignore", [])]

        # a) polygon dung het: moi ghi chu sai_vien la bao nham
        ref = {}
        finds = S.check(areas, tool, img, sam, job_group, R.GROUP.get, keep_ref=ref)
        checked = [a for a in areas if a["id"] in ref]
        n_clean += len(checked)
        for a in checked:
            sam_iou.append(_miou(a["mask"], ref[a["id"]]["mask"]))
        cs += sum(f["sure"] for f in finds)
        cu += sum(not f["sure"] for f in finds)
        dump += [dict(image=g["image"], loai="bao_nham", **{k: v for k, v in f.items() if k != "poly"}) for f in finds]
        # job chi ve polygon (khong box): polygon co duoc tinh la nhan cua vat khong (khong bao thieu / thua oan)
        lab = [dict(id=a["id"], label=a["label"], box=a["box"], occluded=False, seg="polygon") for a in areas]
        for f in R.compare(lab, tool, rej, W, H, tool2job, job_group, img=img, runner=runner):
            if f["kind"] in ("thieu", "thua") and not _ignored(f, ign):
                miss_cmp[f["kind"] + ("_s" if f["sure"] else "_u")] += 1

        # b) cai loi polygon vao ~40% vat du lon
        pert, errs = [], {}
        for a in areas:
            b = a["box"]
            side = min(b[2] - b[0], b[3] - b[1])
            if side >= S.MIN_SIDE and rng.random() < 0.4:
                kind = rng.choice(SEG_KINDS)
                m2 = perturb_mask(a["mask"], kind, rng)
                if m2 is not None and m2.any():
                    v = _miou(m2, a["mask"])
                    if v < S.IOU_OK:          # chi tinh la loi khi thuc su lech (IoU voi dap an < muc khit cua tool)
                        errs[a["id"]] = (kind, v, side)
                        pert.append(dict(a, mask=m2, box=_box(m2)))
                        continue
            pert.append(a)
        pf = S.check(pert, tool, img, sam, job_group, R.GROUP.get)
        got = {f["ref"]: f for f in pf}
        for aid, (kind, v, side) in errs.items():
            f = got.get(aid)
            t = inj[kind]
            t[0] += 1
            t[1] += bool(f and f["sure"])
            t[2] += bool(f and not f["sure"])
            sz = "nho <64px" if side < 64 else "vua 64-160px" if side < 160 else "lon >=160px"
            z = by_size.setdefault(sz, [0, 0])
            z[0] += 1
            z[1] += f is not None
            if f is None:
                dump.append(dict(image=g["image"], loai="bo_lot", ref=aid, kind=kind, iou_dap_an=round(v, 3)))
        for f in pf:
            if f["ref"] not in errs:
                fp_s += f["sure"]
                fp_u += not f["sure"]
        n_ok_pert += sum(1 for a in pert if a["id"] not in errs and a["id"] in ref)
        if n % 25 == 0:
            print(f"  {n}/{len(gts)}", flush=True)

    t = [sum(v[i] for v in inj.values()) for i in range(3)]
    sam_iou = np.array(sam_iou)
    out = dict(anh=len(gts), polygon_cham=n_clean,
               bao_nham_chac_100=cs / max(1, n_clean) * 100, bao_nham_kc_100=cu / max(1, n_clean) * 100,
               bat_loi=(t[1] + t[2]) / max(1, t[0]), bat_chac=t[1] / max(1, t[0]), loi_cai=t[0],
               theo_loai={SEG_VI[k]: dict(tong=v[0], chac=v[1] / max(1, v[0]), khong_chac=v[2] / max(1, v[0]))
                          for k, v in inj.items()},
               theo_co={k: dict(tong=v[0], bat=v[1] / max(1, v[0])) for k, v in by_size.items()},
               bao_nham_tren_vat_khong_loi_100=dict(chac=fp_s / max(1, n_ok_pert) * 100, kc=fp_u / max(1, n_ok_pert) * 100),
               sam_vs_dap_an_iou=dict(trung_vi=float(np.median(sam_iou)) if len(sam_iou) else None,
                                      duoi_0_8=float((sam_iou < 0.8).mean()) if len(sam_iou) else None),
               job_chi_polygon=miss_cmp)
    print(f"\n######## SEGMENTATION · {len(gts)} anh COCO val2017 · {n_clean} polygon nguoi ve that duoc cham")
    print(f"  SAM2 so voi dap an: IoU trung vi {out['sam_vs_dap_an_iou']['trung_vi']:.3f}, "
          f"{out['sam_vs_dap_an_iou']['duoi_0_8']:.1%} polygon co IoU < 0.8")
    print(f"  Bao nham / 100 polygon dung: chac {out['bao_nham_chac_100']:.1f} · khong chac {out['bao_nham_kc_100']:.1f}")
    print(f"  Bat loi cai vao: {out['bat_loi']:.1%} (chac {out['bat_chac']:.1%}) tren {t[0]} loi")
    for k, v in out["theo_loai"].items():
        print(f"      {k:18s} {v['tong']:4d} | chac {v['chac']:6.1%} | khong chac {v['khong_chac']:6.1%} "
              f"| bo lot {1 - v['chac'] - v['khong_chac']:6.1%}")
    for k, v in sorted(out["theo_co"].items()):
        print(f"      vat {k:14s} {v['tong']:4d} | bat {v['bat']:6.1%}")
    print(f"  Bao nham tren vat khong loi (cung anh co loi) / 100: chac {out['bao_nham_tren_vat_khong_loi_100']['chac']:.1f} "
          f"· khong chac {out['bao_nham_tren_vat_khong_loi_100']['kc']:.1f}")
    print(f"  Job chi ve polygon: thieu (chac/kc) {miss_cmp['thieu_s']}/{miss_cmp['thieu_u']}, "
          f"thua (chac/kc) {miss_cmp['thua_s']}/{miss_cmp['thua_u']}")
    if args.json:
        json.dump(out, open(args.json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    if args.dump:
        json.dump(dump, open(args.dump, "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=float)


if __name__ == "__main__":
    if "--seg" in sys.argv:
        for f in (sys.stdout, sys.stderr):
            try:
                f.reconfigure(encoding="utf-8")
            except Exception:
                pass
        ap = argparse.ArgumentParser()
        ap.add_argument("--seg", required=True, help="thu muc tao_bo_seg_eval.py (images/ + gt_seg.json)")
        ap.add_argument("--seed", type=int, default=0)
        ap.add_argument("--mode", default="chinh_xac")
        ap.add_argument("--limit", type=int)
        ap.add_argument("--skip", type=int, default=0, help="bo qua N anh dau (vd anh da dung de chinh nguong)")
        ap.add_argument("--json")
        ap.add_argument("--dump")
        main_seg(ap.parse_args())
    else:
        main()
