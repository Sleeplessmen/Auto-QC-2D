"""
kiem_tra_chat_luong.py — Cong chat luong cho bo du lieu MOI: dam bao phan TU_DONG >= muc tieu (mac dinh 97%).

Cach dung:
  1. Chay tool:  python label_hq_2d.py --images <anh> --out <ket_qua>
  2. Gan tay / sua dung 20-30 anh bat ky (vd sua tren CVAT roi export) -> dap an dang eval_hq2d (thu muc gt/*.json),
     hoac sua file json/<anh>.json cua tool cho dung roi chep sang gt/.
  3. python kiem_tra_chat_luong.py --pred <ket_qua>/json --gt <thu muc gt> [--muc-tieu 0.97]
     -> do phan TU_DONG hien tai + goi y --review-score nho nhat de phan TU_DONG >= muc tieu
  4. Chay lai tool voi --review-score <goi y>.
"""
import argparse
import glob
import json
import os
import sys

import eval_hq2d as E
from label_hq_2d import iou


def load(pred_dir, gt_dir):
    boxes, miss, n_gt = [], 0, 0
    for gp in sorted(glob.glob(os.path.join(gt_dir, "*.json"))):
        pp = os.path.join(pred_dir, os.path.basename(gp))
        if not os.path.exists(pp):
            continue
        g, p = json.load(open(gp, encoding="utf-8")), json.load(open(pp, encoding="utf-8"))
        g.setdefault("ignore", [])
        g.setdefault("ignore_regions", [])
        P = [o for o in p["objects"] if not E.in_regions(o["box"], g["ignore_regions"])]
        r = E.score_image(dict(objects=P), g)
        miss += r["miss"]
        n_gt += r["gt"]
        bad = [e[2] for e in r["errors"] if e[0] != "sot"]
        for o in P:
            wrong = any(iou(o["box"], b) >= 0.9 for b in bad)
            if wrong and any(iou(o["box"], q["box"]) >= 0.3 for q in g["ignore"]):
                continue
            gsm_unsure = "GreenSM?" in o.get("can_xem", "") or "box?" in o.get("can_xem", "")
            boxes.append((o["score"], gsm_unsure, wrong, o.get("trang_thai") == "TU_DONG"))
    return boxes, miss, n_gt


def main():
    for f in (sys.stdout, sys.stderr):
        try:
            f.reconfigure(encoding="utf-8")
        except Exception:
            pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--pred", required=True)
    ap.add_argument("--gt", required=True)
    ap.add_argument("--muc-tieu", type=float, default=0.97)
    args = ap.parse_args()
    boxes, miss, n_gt = load(args.pred, args.gt)
    if not boxes:
        raise SystemExit("Khong co anh nao vua co ket qua vua co dap an")
    auto = [b for b in boxes if b[3]]
    acc = 1 - sum(b[2] for b in auto) / max(1, len(auto))
    print(f"{len(boxes)} box tren cac anh co dap an | TU_DONG {len(auto)} ({len(auto) / len(boxes):.0%}) dung {acc:.1%} "
          f"| sot {miss}/{n_gt} vat ({miss / max(1, n_gt):.1%})")
    print("Nguong | box TU_DONG | dung")
    best = None
    for t in [x / 100 for x in range(30, 96, 5)]:
        a = [b for b in boxes if b[0] >= t and not b[1]]
        if not a:
            continue
        ac = 1 - sum(b[2] for b in a) / len(a)
        print(f"  {t:.2f} | {len(a):4d} ({len(a) / len(boxes):3.0%}) | {ac:.1%}")
        if best is None and ac >= args.muc_tieu + 0.005 and len(a) >= 30:
            best = t
    if len(boxes) < 200:
        print(f"Canh bao: chi {len(boxes)} box co dap an -> con so chua chac; nen gan tay them anh (>= 300 box).")
    if best is None:
        print(f"KHONG nguong nao dat {args.muc_tieu:.0%} -> bo du lieu nay qua khac / qua kho: can them du lieu gan tay cho loai anh nay.")
    else:
        print(f"GOI Y: chay lai voi --review-score {best:.2f}  (phan TU_DONG >= {args.muc_tieu:.0%} + 0.5% du phong)")


if __name__ == "__main__":
    main()
