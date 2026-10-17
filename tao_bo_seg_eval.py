"""
tao_bo_seg_eval.py — Tao bo anh co dap an SEGMENTATION (polygon nguoi ve that) tu COCO val2017 de do review_eval.py --seg.

  1. Tai annotations_trainval2017.zip (http://images.cocodataset.org/annotations/), giai nen instances_val2017.json
  2. python tao_bo_seg_eval.py --ann <instances_val2017.json> --out D:/DATA_EXT/coco_seg_eval --n 200

Chon anh duong pho: co it nhat 1 xe (car / bus / truck) du lon. Lay moi vat thuoc 6 loai tool nhan ra
(car, truck, bus, motorcycle, bicycle, person); vung iscrowd -> vung bo qua.
Ra: <out>/images/*.jpg + <out>/gt_seg.json [{image, W, H, objects: [{cls, box, polys}], ignore: [box]}]
"""
import argparse
import json
import os
import random
import urllib.request

CLS = {"car", "truck", "bus", "motorcycle", "bicycle", "person"}
VEH = {"car", "truck", "bus"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ann", required=True)
    ap.add_argument("--out", default="D:/DATA_EXT/coco_seg_eval")
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    d = json.load(open(args.ann, encoding="utf-8"))
    cats = {c["id"]: c["name"] for c in d["categories"]}
    ims = {i["id"]: i for i in d["images"]}
    per = {}
    for a in d["annotations"]:
        if cats[a["category_id"]] in CLS:
            per.setdefault(a["image_id"], []).append(a)
    cand = [i for i, aa in per.items()
            if any(cats[a["category_id"]] in VEH and not a["iscrowd"] and a["area"] >= 3000 for a in aa)
            and sum(not a["iscrowd"] for a in aa) >= 2]
    random.Random(args.seed).shuffle(cand)
    os.makedirs(os.path.join(args.out, "images"), exist_ok=True)
    out = []
    for iid in sorted(cand[:args.n]):
        im = ims[iid]
        p = os.path.join(args.out, "images", im["file_name"])
        if not os.path.exists(p):
            urllib.request.urlretrieve(im["coco_url"], p + ".tmp")
            os.replace(p + ".tmp", p)
        objs, ign = [], []
        for a in per[iid]:
            x, y, w, h = a["bbox"]
            box = [x, y, x + w, y + h]
            if a["iscrowd"] or not isinstance(a["segmentation"], list):
                ign.append(box)
                continue
            objs.append(dict(cls=cats[a["category_id"]], box=box, polys=a["segmentation"]))
        out.append(dict(image=im["file_name"], W=im["width"], H=im["height"], objects=objs, ignore=ign))
        if len(out) % 25 == 0:
            print(f"  {len(out)}/{args.n}", flush=True)
    json.dump(out, open(os.path.join(args.out, "gt_seg.json"), "w", encoding="utf-8"))
    print(f"Xong: {len(out)} anh, {sum(len(g['objects']) for g in out)} vat -> {args.out}")


if __name__ == "__main__":
    main()
