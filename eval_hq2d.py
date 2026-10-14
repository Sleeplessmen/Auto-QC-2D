"""
eval_hq2d.py — Do do chinh xac gan nhan 2D so voi dap an doi chieu bang mat.

  python eval_hq2d.py build --pred <out>/doi_chieu/v1_json --fix <out>/doi_chieu/sua.json --gt <out>/doi_chieu/gt
      -> tao dap an (gt/*.json) tu ket qua v1 + file sua (chi chay 1 lan)
  python eval_hq2d.py score --pred <out>/json --gt <out>/doi_chieu/gt [--list danh_sach.txt]

Mot box dung = cung vat (IoU >= 0.5) VA dung nhan. Do chinh xac tong = dung / (dung + sai nhan + sot + thua).
Vat 'ignore' / trong 'ignore_regions' khong tinh dung sai.
"""
import argparse
import glob
import json
import os
import sys

IOU_T = 0.5


def iou(a, b):
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / u if u > 0 else 0.0


def key_of(name):
    return os.path.splitext(name)[0].split("_")[0]


def build(args):
    fixes = json.load(open(args.fix, encoding="utf-8"))
    os.makedirs(args.gt, exist_ok=True)
    for fp in sorted(glob.glob(os.path.join(args.pred, "*.json"))):
        k = key_of(os.path.basename(fp))
        if k not in fixes:
            continue
        d = json.load(open(fp, encoding="utf-8"))
        fx = fixes[k]
        objs, ign = [], []
        for i, o in enumerate(d["objects"]):
            s = str(i)
            if i in fx.get("drop", []):
                continue
            box = fx.get("fix", {}).get(s, o["box"])
            cls = fx.get("relabel", {}).get(s, o["cls"])
            (ign if i in fx.get("ignore", []) else objs).append(dict(box=box, cls=cls))
        for s, cls in fx.get("accept", {}).items():
            objs.append(dict(box=d["rejected"][int(s)]["box"], cls=cls))
        for x1, y1, x2, y2, cls in fx.get("add", []):
            objs.append(dict(box=[x1, y1, x2, y2], cls=cls))
        json.dump(dict(image=d["image"], width=d["width"], height=d["height"], objects=objs, ignore=ign,
                       ignore_regions=fx.get("ignore_regions", [])),
                  open(os.path.join(args.gt, os.path.basename(fp)), "w", encoding="utf-8"), indent=1)
    print(f"Dap an: {len(glob.glob(os.path.join(args.gt, '*.json')))} anh -> {args.gt}")


def in_regions(box, regions):
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    return any(r[0] <= cx <= r[2] and r[1] <= cy <= r[3] for r in regions)


def score_image(pred, gt):
    P = [o for o in pred["objects"] if not in_regions(o["box"], gt["ignore_regions"])]
    G = [o for o in gt["objects"] if not in_regions(o["box"], gt["ignore_regions"])]
    pairs = sorted(((iou(p["box"], g["box"]), i, j) for i, p in enumerate(P) for j, g in enumerate(G)), reverse=True)
    mp, mg = {}, {}
    for v, i, j in pairs:
        if v < IOU_T:
            break
        if i in mp or j in mg:
            continue
        mp[i], mg[j] = j, i
    r = dict(gt=len(G), ok=0, wrong=0, miss=0, extra=0, errors=[])
    for j, g in enumerate(G):
        if j not in mg:
            r["miss"] += 1
            r["errors"].append(("sot", g["cls"], g["box"]))
        elif P[mg[j]]["cls"] == g["cls"]:
            r["ok"] += 1
        else:
            r["wrong"] += 1
            r["errors"].append((f"sai nhan {P[mg[j]]['cls']}->{g['cls']}", g["cls"], g["box"]))
    for i, p in enumerate(P):
        if i in mp:
            continue
        if any(iou(p["box"], q["box"]) >= 0.3 for q in gt["ignore"]):     # trung vat 'ignore' -> khong tinh
            continue
        r["extra"] += 1
        r["errors"].append(("thua", p["cls"], p["box"]))
    return r


def score(args):
    want = None
    groups = {}
    if args.list:
        cur = None
        want = []
        for line in open(args.list, encoding="utf-8"):
            line = line.strip()
            if line.startswith("#"):
                cur = line.lstrip("# ")
            elif line:
                want.append(key_of(line))
                groups[key_of(line)] = cur
    tot, per_group = {}, {}
    for gp in sorted(glob.glob(os.path.join(args.gt, "*.json"))):
        k = key_of(os.path.basename(gp))
        if want and k not in want:
            continue
        pp = os.path.join(args.pred, os.path.basename(gp))
        if not os.path.exists(pp):
            print(f"  thieu ket qua: {k}")
            continue
        pred, gt = json.load(open(pp, encoding="utf-8")), json.load(open(gp, encoding="utf-8"))
        if args.merge:              # vd "GreenSM:car,truck:car" khi dap an khong co cac lop nay (ExDark)
            mp = dict(x.split(":") for x in args.merge.split(","))
            for o in pred["objects"] + gt["objects"]:
                o["cls"] = mp.get(o["cls"], o["cls"])
        r = score_image(pred, gt)
        for t in (tot, per_group.setdefault(groups.get(k, "tat ca"), {})):
            for f in ("gt", "ok", "wrong", "miss", "extra"):
                t[f] = t.get(f, 0) + r[f]
        if args.verbose and r["errors"]:
            print(f"{k}: " + "; ".join(f"{e[0]} {e[1]} {[int(v) for v in e[2]]}" for e in r["errors"]))

    def line(name, t):
        acc = t["ok"] / max(1, t["ok"] + t["wrong"] + t["miss"] + t["extra"])
        rec = (t["ok"] + t["wrong"]) / max(1, t["gt"])
        prec = (t["ok"] + t["wrong"]) / max(1, t["ok"] + t["wrong"] + t["extra"])
        lab = t["ok"] / max(1, t["ok"] + t["wrong"])
        print(f"{name:16s} vat {t['gt']:4d} | dung {t['ok']:4d} sai_nhan {t['wrong']:3d} sot {t['miss']:3d} thua {t['extra']:3d}"
              f" | tim du {rec:6.1%}  khong thua {prec:6.1%}  dung nhan {lab:6.1%} | DO CHINH XAC {acc:6.1%}")
        return acc
    for g, t in per_group.items():
        line(g, t)
    return line("TONG", tot)


def main():
    for f in (sys.stdout, sys.stderr):
        try:
            f.reconfigure(encoding="utf-8")
        except Exception:
            pass
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["build", "score"])
    ap.add_argument("--pred", required=True)
    ap.add_argument("--gt", required=True)
    ap.add_argument("--fix")
    ap.add_argument("--list")
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--merge", help="gop nhan truoc khi cham, vd GreenSM:car,truck:car")
    args = ap.parse_args()
    build(args) if args.cmd == "build" else score(args)


if __name__ == "__main__":
    main()
