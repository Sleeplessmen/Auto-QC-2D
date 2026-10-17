"""Thu dac trung (polygon vs mask SAM) cho tung vat: ban dung + 5 kieu loi. Dung de chinh nguong seg_check offline.
    venv\\Scripts\\python cvat_2d\\kiem_thu\\seg_thu_dac_trung.py <tu anh> <den anh> <out.json>    (vd 0 120 feats.json)
roi chinh nguong: python seg_chinh_nguong.py feats.json"""
import json, os, sys, random
HERE = os.path.dirname(os.path.abspath(__file__))
D = os.path.dirname(HERE)                                                     # cvat_2d
SEG = os.path.join(D, "du_lieu_danh_gia", "coco_seg_eval")   # anh + gt_seg.json
if not os.path.isdir(SEG):
    SEG = os.path.join(os.path.dirname(D), "du_lieu_danh_gia", "coco_seg_eval")
sys.path.insert(0, D); os.chdir(D)
import cv2, numpy as np
import review_core as R, seg_check as S, label_hq_2d as L, review_eval as E

a0, a1, outp = int(sys.argv[1]), int(sys.argv[2]), os.path.abspath(sys.argv[3])
gts = json.load(open(os.path.join(SEG, "gt_seg.json")))[a0:a1]
runner = R.ToolRunner("chinh_xac")
sam = runner.seg_sam()
_, job_group, _ = R.build_label_map(L.CLASSES)
rng = random.Random(1)


def sdist(M, Sm):
    """khoang cach co dau tu vien M toi mask S: + = vien M nam ngoai S (to thua), - = nam trong (lem)."""
    cs, _ = cv2.findContours(M.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not cs:
        return None
    pts = np.concatenate([c.reshape(-1, 2) for c in cs])
    dout = cv2.distanceTransform((~Sm).astype(np.uint8), cv2.DIST_L2, 3)
    din = cv2.distanceTransform(Sm.astype(np.uint8), cv2.DIST_L2, 3)
    x, y = pts[:, 0], pts[:, 1]
    d = np.where(Sm[y, x], -din[y, x], dout[y, x])
    return d


def feats(M, Sm, others, sc):
    m = S.measure(M, Sm, others)
    d = sdist(M, Sm)
    r = float(np.sqrt(max(1, Sm.sum())))
    return dict(iou=m["iou"], lem=m["lem"], thua=m["thua"], lem_px=m["lem_px"], thua_px=m["thua_px"], sc=float(sc),
                sd_med=float(np.median(d)) / r if d is not None else 0.0,
                sd_med_px=float(np.median(d)) if d is not None else 0.0,
                out_frac=float((d > 2).mean()) if d is not None else 0.0,
                in_frac=float((d < -2).mean()) if d is not None else 0.0)


rows = []
for n, g in enumerate(gts, 1):
    img = cv2.imdecode(np.fromfile(os.path.join(SEG, "images", g["image"]), np.uint8), cv2.IMREAD_COLOR)[:, :, ::-1].copy()
    H, W = img.shape[:2]
    areas = []
    for k, o in enumerate(g["objects"]):
        m = E._poly_mask(o["polys"], W, H)
        if m.any():
            areas.append(dict(id=f"g{k}", label=o["cls"], kind="polygon", mask=m, box=E._box(m)))
    tool, _ = runner.detect(img, "coco_" + os.path.splitext(g["image"])[0])
    for a in areas:
        side = min(a["box"][2] - a["box"][0], a["box"][3] - a["box"][1])
        if side < S.MIN_SIDE:
            continue
        others = np.zeros_like(a["mask"])
        for b in areas:
            if b is not a:
                others |= b["mask"]
        others &= ~a["mask"]
        t = S.match_tool(a, tool, R.GROUP.get, job_group)
        variants = [("dung", a["mask"])]
        for kind in E.SEG_KINDS:
            m2 = E.perturb_mask(a["mask"], kind, rng)
            if m2 is not None and m2.any() and E._miou(m2, a["mask"]) < S.IOU_OK:
                variants.append((kind, m2))
        for kind, M in variants:
            box = E._box(M)
            pb = S._expand(box, S.EXPAND, W, H)
            prompts = [pb] + ([list(t["box"])] if t is not None else [])
            masks, scores = sam.predict_boxes(img, prompts)
            row = dict(image=g["image"], id=a["id"], cls=a["label"], kind=kind, side=float(side),
                       true_iou=E._miou(M, a["mask"]))
            Sp = S._clean(masks[0], pb, W, H)
            row["p"] = feats(M, Sp, others, scores[0]) if Sp.any() else None
            if t is not None:
                St = S._clean(masks[1], prompts[1], W, H)
                row["t"] = feats(M, St, others, scores[1]) if St.any() else None
            rows.append(row)
    if n % 20 == 0:
        print(n, flush=True)
json.dump(rows, open(outp, "w"))
print("xong", len(rows))
