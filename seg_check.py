"""Review polygon / mask cua TUNG VAT (xe, nguoi, xe may...): viền có ôm đúng vật không.

Cach lam: lay box cua vat (box detector cua tool neu khop, khong thi box cua polygon noi rong ra) lam prompt cho SAM2
-> mask "chuan" cua vat. So voi mask labeler ve (bo qua 1 dai mep vai px vi viền tay khong the khit tung px):
    * lem   : phan vat SAM thay ma polygon khong phu (ve lem / bo mat 1 phan vat)
    * thua  : phan polygon to ra nen, SAM khong coi la vat
    * lech  : ca 2 deu lon -> polygon dat lech / ve nham vat
Chi bao khi phan sai du lon (ti le dien tich + so px) va SAM tu tin. Khong sua nhan.
Vung duong (drivable area) do area_check lo, khong xet o day.
"""
import cv2
import numpy as np

# nguong: chinh tren 120 anh COCO val2017 (polygon nguoi ve that + 5 kieu loi cai vao), kiem lai tren 80 anh con lai
# (review_eval.py --seg). Tren tap chinh: bao nham chac 1.4 / 100 polygon dung, bat 75% loi.
MIN_SIDE = 24           # vat nho hon (canh ngan, px) -> SAM va polygon deu khong du chi tiet, bo qua
BAND_REL = 0.02         # dai mep bo qua: max(BAND_MIN, BAND_REL * sqrt(dien tich vat))
BAND_MIN = 2
PART_SURE = 0.22        # phan sai >= 22% dien tich vat -> du nang de "chac"
PART_UNSURE = 0.15      # >= 15% -> co the loi
MIN_PART_PX = 150       # phan sai nho hon so px nay -> bo qua (vat nho, nhieu)
RING_REL = 0.03         # vien polygon lech DEU ca vong (lem vao / to ra) >= 3% * sqrt(dien tich) ...
RING_PX = 1.5           # ... va >= 1.5 px (trung vi khoang cach co dau tu vien polygon toi mask SAM)
RING_FRAC = 0.6         # ... tren >= 60% chieu dai vien
IOU_OK = 0.80           # IoU >= muc nay -> coi nhu khit, khong bao
ALT_K = 1.5             # prompt thu 2 thay polygon on -> chi bao khi loi o prompt 1 nang gap 1.5 lan nguong
SAM_SURE = 0.85         # diem SAM thap hon -> chi "khong chac"
SURE_SIDE = 40          # vat nho hon (canh ngan) -> toi da "khong chac" (polygon vat nho ve tho, SAM cung kem)
WRONG_OBJ_IOU = 0.2     # mask SAM tu box tool gan nhu khong cham polygon -> box tool la vat khac, bo
MATCH_IOU = 0.3         # khop polygon voi vat tool thay (box)
EXPAND = 0.08           # box polygon noi rong 8% moi chieu (prompt thu 2)
CLIP = 0.15             # mask SAM chi duoc vuot box prompt 15% moi chieu (tranh lan sang vat ben canh)
WHERE_VI = {"left": "bên trái", "right": "bên phải", "top": "phía trên", "bottom": "phía dưới"}


def _iou_box(a, b):
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))
    u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - ix
    return ix / u if u > 0 else 0.0


def _inside(a, b):
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))
    return ix / max(1e-6, (a[2] - a[0]) * (a[3] - a[1]))


def _expand(b, r, W, H):
    dx, dy = (b[2] - b[0]) * r, (b[3] - b[1]) * r
    return [max(0.0, b[0] - dx), max(0.0, b[1] - dy), min(float(W), b[2] + dx), min(float(H), b[3] + dy)]


def object_areas(areas, road_names, job_group):
    """Polygon / mask cua nhan vat (tool nhan ra loai), khong phai vung duong."""
    road = set(road_names)
    return [a for a in areas if a["label"] not in road and a["label"] in job_group]


def match_tool(a, tool, grp_of, job_group):
    """Vat tool thay khop voi polygon (cung nhom, box trung / polygon nam trong box tool). None neu khong co."""
    g = job_group.get(a["label"])
    best, bv = None, 0.0
    for t in tool:
        if grp_of(t["cls"]) != g:
            continue
        v = _iou_box(a["box"], t["box"])
        if v < MATCH_IOU and not (_inside(a["box"], t["box"]) > 0.85 and v > 0.15):
            continue
        if v > bv:
            best, bv = t, v
    return best


def _clean(mk, box, W, H):
    """Cat mask SAM trong box prompt noi rong, bo dom nho."""
    x1, y1, x2, y2 = _expand(box, CLIP, W, H)
    lim = np.zeros_like(mk)
    lim[int(y1):int(np.ceil(y2)), int(x1):int(np.ceil(x2))] = True
    mk = mk & lim
    n, lab, st, _ = cv2.connectedComponentsWithStats(mk.astype(np.uint8), connectivity=8)
    if n > 2:
        a = st[1:, cv2.CC_STAT_AREA]
        mk = np.isin(lab, [i + 1 for i, v in enumerate(a) if v >= 0.1 * a.max()])
    return mk


def measure(M, S, others=None):
    """M: mask labeler, S: mask SAM (bool HxW). others: mask cac vat khac da gan (vat che phia truoc) -> khong tinh lem.
    Tra ve dict(iou, lem, thua, lem_mask, thua_mask) — lem / thua la ti le so voi dien tich vat."""
    area = max(1, int(S.sum()), int(M.sum()))
    band = max(BAND_MIN, int(round(BAND_REL * np.sqrt(area))))
    k = np.ones((2 * band + 1, 2 * band + 1), np.uint8)
    Md = cv2.dilate(M.astype(np.uint8), k).astype(bool)
    Sd = cv2.dilate(S.astype(np.uint8), k).astype(bool)
    lem = S & ~Md
    if others is not None:
        lem &= ~others
    thua = M & ~Sd
    lem = cv2.morphologyEx(lem.astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8)).astype(bool)
    thua = cv2.morphologyEx(thua.astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8)).astype(bool)
    inter, uni = (M & S).sum(), (M | S).sum()
    # khoang cach co dau tu vien polygon toi mask SAM: + = vien nam ngoai vat (to thua), - = nam trong (lem)
    sd, out_f, in_f = 0.0, 0.0, 0.0
    cs, _ = cv2.findContours(M.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if cs:
        pts = np.concatenate([c.reshape(-1, 2) for c in cs])
        x, y = pts[:, 0], pts[:, 1]
        dout = cv2.distanceTransform((~S).astype(np.uint8), cv2.DIST_L2, 3)
        din = cv2.distanceTransform(S.astype(np.uint8), cv2.DIST_L2, 3)
        d = np.where(S[y, x], -din[y, x], dout[y, x])
        sd, out_f, in_f = float(np.median(d)), float((d > 2).mean()), float((d < -2).mean())
    return dict(iou=float(inter / uni) if uni else 1.0, lem=float(lem.sum() / max(1, S.sum())),
                thua=float(thua.sum() / max(1, M.sum())), lem_px=int(lem.sum()), thua_px=int(thua.sum()),
                lem_mask=lem, thua_mask=thua, ring_px=sd, ring=sd / np.sqrt(max(1, S.sum())), out_frac=out_f, in_frac=in_f)


def _where(part, box):
    """Phan sai nam o phia nao cua vat: 'bên trái', 'phía dưới bên phải'..."""
    ys, xs = np.nonzero(part)
    if not len(xs):
        return ""
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    w, h = max(1.0, box[2] - box[0]), max(1.0, box[3] - box[1])
    dx, dy = (xs.mean() - cx) / w, (ys.mean() - cy) / h
    s = []
    if dy < -0.15:
        s.append(WHERE_VI["top"])
    elif dy > 0.15:
        s.append(WHERE_VI["bottom"])
    if dx < -0.15:
        s.append(WHERE_VI["left"])
    elif dx > 0.15:
        s.append(WHERE_VI["right"])
    return " ".join(s) if s else "giữa / dọc viền"


def _outline(mask, max_pts=60):
    cs, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cs:
        return None
    c = max(cs, key=cv2.contourArea)
    eps = 0.003 * cv2.arcLength(c, True)
    p = cv2.approxPolyDP(c, eps, True)
    while len(p) > max_pts:
        eps *= 1.5
        p = cv2.approxPolyDP(c, eps, True)
    return [float(v) for v in p.reshape(-1)] if len(p) >= 3 else None


def _area_bad(m, k=1.0):
    return (m["lem"] >= PART_UNSURE * k and m["lem_px"] >= MIN_PART_PX) or (m["thua"] >= PART_UNSURE * k and m["thua_px"] >= MIN_PART_PX)


def _ring_bad(m, k=1.0):
    """vien lech deu ca vong (ve co vao / phinh ra), kho thay bang dien tich khi vat nho"""
    if abs(m["ring_px"]) < RING_PX * k or abs(m["ring"]) < RING_REL * k:
        return False
    return (m["out_frac"] if m["ring"] > 0 else m["in_frac"]) >= RING_FRAC


def _bad(m, k=1.0):
    return m is not None and m["iou"] < IOU_OK and (_area_bad(m, k) or _ring_bad(m, k))


def judge(a, m, score, alt=None):
    """Tu so do -> finding (hoac None). a: area dict, m: measure() voi mask SAM chinh, score: diem SAM.
    alt: measure() voi mask SAM tu prompt thu 2 (box cua polygon). Prompt 2 thay polygon on -> chi bao khi loi nang;
    "chac" khi loi nang, SAM tu tin, vat du lon va ca 2 prompt cung thay sai."""
    if not _bad(m):
        return None
    if alt is not None and not _bad(alt) and not _bad(m, ALT_K):
        return None
    side = min(a["box"][2] - a["box"][0], a["box"][3] - a["box"][1])
    heavy = max(m["lem"], m["thua"]) >= PART_SURE or _ring_bad(m, 1.5)
    sure = heavy and score >= SAM_SURE and side >= SURE_SIDE and (alt is None or _bad(alt))
    what = "Mask" if a["kind"] == "mask" else "Polygon"
    big_lem = m["lem"] >= PART_UNSURE and m["lem_px"] >= MIN_PART_PX
    big_thua = m["thua"] >= PART_UNSURE and m["thua_px"] >= MIN_PART_PX
    if big_lem and big_thua and m["iou"] < 0.5:
        part = m["lem_mask"] | m["thua_mask"]
        msg = (f"{what} '{a['label']}' lệch khỏi vật (chỉ trùng {m['iou'] * 100:.0f}%): "
               f"thiếu {m['lem'] * 100:.0f}% vật {_where(m['lem_mask'], a['box'])}, "
               f"tô ra nền {m['thua'] * 100:.0f}% {_where(m['thua_mask'], a['box'])}. Vẽ lại sát viền vật.")
        sub = "lech"
    elif big_lem and (m["lem"] >= m["thua"] or not big_thua):
        part = m["lem_mask"]
        msg = (f"{what} '{a['label']}' vẽ lẹm: thiếu ~{m['lem'] * 100:.0f}% vật ở {_where(part, a['box'])}, "
               f"kéo viền ra sát mép vật.")
        sub = "lem"
    elif big_thua:
        part = m["thua_mask"]
        msg = (f"{what} '{a['label']}' tô thừa ra nền ~{m['thua'] * 100:.0f}% ở {_where(part, a['box'])}, "
               f"kéo viền vào sát mép vật.")
        sub = "thua"
    elif m["ring"] < 0:
        part = m["lem_mask"] if m["lem_mask"].any() else a["mask"]
        msg = (f"{what} '{a['label']}' vẽ co vào trong: viền nằm lẹm vào vật ~{abs(m['ring_px']):.0f}px "
               f"gần như cả vòng, kéo viền ra sát mép vật.")
        sub = "co"
    else:
        part = m["thua_mask"] if m["thua_mask"].any() else a["mask"]
        msg = (f"{what} '{a['label']}' vẽ phình ra nền: viền nằm ngoài vật ~{m['ring_px']:.0f}px "
               f"gần như cả vòng, kéo viền vào sát mép vật.")
        sub = "phinh"
    if not sure:
        msg = "Có thể " + msg[0].lower() + msg[1:]
    return dict(kind="sai_vien", sub=sub, sure=bool(sure), label=a["label"], box=a["box"], ref=a["id"],
                poly=_outline(part), msg=msg, iou=round(m["iou"], 3), sam=round(float(score), 3))


def check(areas, tool, img, sam, job_group, grp_of, road_names=(), keep_ref=None):
    """areas: [dict(id,label,kind,mask,box)] cua 1 frame. tool: vat tool thay (ToolRunner.detect). sam: L.SamRefiner.
    grp_of(cls) -> nhom ('veh' / 'two' / 'person'). keep_ref: dict de luu mask SAM (ve tren web).
    Tra ve [finding] giong review_core.compare (kind = 'sai_vien')."""
    areas = [a for a in areas if a.get("mask") is not None]     # track: chi cham vien o keyframe
    objs = [a for a in object_areas(areas, road_names, job_group)
            if min(a["box"][2] - a["box"][0], a["box"][3] - a["box"][1]) >= MIN_SIDE]
    if not objs or sam is None:
        return []
    H, W = img.shape[:2]
    # 2 prompt cho moi vat: box tool (neu khop, thay duoc ca phan polygon bo quen) + box cua chinh polygon noi rong
    tb = []
    for a in objs:
        t = match_tool(a, tool, grp_of, job_group)
        tb.append(list(t["box"]) if t is not None else None)
    pb = [_expand(a["box"], EXPAND, W, H) for a in objs]
    prompts = [b for b in tb if b is not None] + pb
    masks, scores = sam.predict_boxes(img, prompts)
    k = sum(b is not None for b in tb)
    tmask, it = [], iter(range(k))
    for b in tb:
        tmask.append(next(it) if b is not None else None)
    out = []
    for i, a in enumerate(objs):
        # vat khac da gan (box / polygon khac) de len vung SAM: thuong la vat che phia truoc -> phan do khong tinh lem
        others = np.zeros_like(a["mask"])
        for b in areas:
            if b is not a and b["label"] not in road_names:
                others |= b["mask"]
        others &= ~a["mask"]
        Sp = _clean(masks[k + i], pb[i], W, H)
        mp = measure(a["mask"], Sp, others) if Sp.any() else None
        main, alt, sc, S, pr = mp, None, float(scores[k + i]), Sp, pb[i]
        if tmask[i] is not None:
            St = _clean(masks[tmask[i]], tb[i], W, H)
            if St.any():
                mt = measure(a["mask"], St, others)
                if mt["iou"] >= WRONG_OBJ_IOU:      # box tool dung la vat nay -> dung lam mask chinh
                    main, alt, sc, S, pr = mt, mp, float(scores[tmask[i]]), St, tb[i]
        if main is None:
            continue
        if keep_ref is not None:
            keep_ref[a["id"]] = dict(mask=S, iou=round(main["iou"], 3), sam=round(sc, 3))
        f = judge(a, main, sc, alt)
        if f and f["sure"] and f["sub"] in ("thua", "phinh", "lech"):
            # SAM hay chi lay 1 phan vat (ao, nua nguoi...). 1 trong 3 phuong an mask cua SAM khop polygon
            # -> co the polygon dung (ca vat), ha xuong "khong chac"
            mm, _ = sam.predict_boxes(img, [pr], multimask=True)
            for cand in mm[0]:
                c = _clean(cand, pr, W, H)
                if c.any() and not _bad(measure(a["mask"], c, others)):
                    f["sure"] = False
                    f["msg"] = "Có thể " + f["msg"][0].lower() + f["msg"][1:]
                    break
        if f:
            out.append(f)
    return out
