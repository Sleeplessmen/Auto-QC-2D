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
    ap.add_argument("--cond", default="goc", choices=["goc", "dem", "mua"], help="gia lap dieu kien anh")
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--dump", help="luu ghi chu bao nham ra file json de xem")
    ap.add_argument("--json", help="luu so lieu tung nhom ra file json")
    ap.add_argument("--visible", action="store_true", help="guideline: chi ve phan nhin thay (vd BDD100K), khong ve toan bo vat")
    ap.add_argument("--min-px", type=float, default=0, help="guideline: bo qua vat co canh ngan nho hon N px")
    args = ap.parse_args()

    meta = json.load(open(args.meta, encoding="utf-8")) if args.meta else {}
    runner = R.ToolRunner(args.mode)
    if args.visible:
        R.AMODAL = False
    if args.min_px:
        R.MIN_MISS_BY_LABEL.update({c: args.min_px for c in L.CLASSES})
    tiny = lambda b: args.min_px and min(b[2] - b[0], b[3] - b[1]) < args.min_px
    tool2job, job_group, _ = R.build_label_map(L.CLASSES)
    rng = random.Random(args.seed)
    G = {}
    dump, missed = [], {}
    gts = sorted(glob.glob(os.path.join(args.gt, "*.json")))[:args.limit]
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

        # 2) cai loi gia
        plab, errs = perturb(g["objects"], W, H, rng)
        errs = [e for e in errs if not (e[0] in ("thieu", "sai_nhan") and tiny(e[2]))]    # loi tren vat guideline bo qua
        pf = [f for f in R.compare(plab, tool, rej, W, H, tool2job, job_group, img=img, runner=runner) if not _ignored(f, ign)]
        used, res = set(), []
        for e in errs:
            f = hit(e, pf)
            res.append((e[0], None if f is None else f["sure"]))
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


if __name__ == "__main__":
    main()
