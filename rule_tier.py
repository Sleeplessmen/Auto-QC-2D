"""Tang luat hinh hoc (chay TRUOC model, khong can GPU, luon bat) — gop tu LetmeQC (src/rules.py cua nhom).

Box     : ra ngoai anh, gan nhu khong co dien tich, qua nho (dien tich < MIN_BOX_AREA), ti le rong/cao cuc doan
          (bo qua vat bi mep anh cat), trung box cua nhan model KHONG cham (vd Tram, Misc, traffic sign)
Polygon : it hon 3 diem, tu cat (xoan), nam tran ra ngoai box cung vat (khi job ve ca box + polygon cho 1 vat)
Logic   : nguoi (pedestrian / person) nam trong box xe (car / truck / bus)
Trung box cua nhan model cham / box lech / thieu / thua do review_core.compare lo (khong lap 2 Issue cho 1 loi).
Moi finding giong review_core: kind, sure, label, box, ref, msg (+ tang=1 -> web hien nhan "luat").
"""
import numpy as np

from label_mapping import norm

BOX_TOL = 2.0            # px cho phep vuot mep anh
PAIR_TOL = (3.0, 0.03)   # polygon vuot box cua no: cho phep max(3px, 3% canh) (LetmeQC: 2px, qua chat voi viền ve tay)
PAIR_SURE = (8.0, 0.08)  # vuot qua max(8px, 8% canh) -> loi chac, giua 2 muc -> "khong chac"
MIN_BOX_AREA = 25.0      # px^2. LetmeQC dung 100, nhung BDD100K gan ca xe xa ~9x10px -> chi bat cu click nham (< 5x5)
MIN_POLY_POINTS = 3
MAX_ASPECT = 10.0        # rong/cao > 10 hoac < 0.1 -> phi ly (LetmeQC)
PAIR_IOU = 0.5           # polygon + box cung nhan, IoU box >= muc nay -> cung 1 vat
DUP_IOU = 0.85           # 2 box cung nhan de len nhau -> trung (nhu review_core.DUP_IOU)
PERSON = {"pedestrian", "person", "nguoi", "nguoidibo"}
VEHICLE = {"car", "truck", "bus", "oto", "xetai", "xebuyt"}


def _iou(a, b):
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))
    u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - ix
    return ix / u if u > 0 else 0.0


def _seg_cross(p1, p2, p3, p4):
    """2 doan thang cat nhau (khong tinh cham dau mut)."""
    def orient(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    d1, d2 = orient(p3, p4, p1), orient(p3, p4, p2)
    d3, d4 = orient(p1, p2, p3), orient(p1, p2, p4)
    return d1 * d2 < 0 and d3 * d4 < 0


def self_intersects(pts):
    """pts [(x,y)...] polygon kin. True neu co 2 canh khong ke nhau cat nhau."""
    n = len(pts)
    if n < 4:
        return False
    edges = [(pts[i], pts[(i + 1) % n]) for i in range(n)]
    for i in range(n):
        for j in range(i + 2, n):
            if i == 0 and j == n - 1:
                continue            # 2 canh ke nhau qua diem dau
            if _seg_cross(*edges[i], *edges[j]):
                return True
    return False


def _fmt(b):
    return f"({b[0]:.0f},{b[1]:.0f})-({b[2]:.0f},{b[3]:.0f})"


def check(boxes, areas, W, H, pair_mode=False, shape_known=(), job_group=None):
    """boxes: [dict(id,label,box,rotation?)]. areas: [dict(id,label,kind,box,points?)] (polygon/mask, ca vung duong).
    pair_mode: job ve ca box + polygon cho 1 vat (instance segmentation) -> polygon phai nam trong box cua no.
    shape_known: nhan ma review_core da cham ti le theo loai vat (_check_shape, chinh hon) -> khong cham ti le o day.
    job_group: {nhan job: nhom 'veh'/'two'/'person'} — co nhan rider thi kiem rider / pedestrian theo box xe 2 banh."""
    out = []

    def add(kind, sure, obj, msg, box=None):
        out.append(dict(kind=kind, sure=sure, label=obj["label"], box=box or obj["box"], ref=obj["id"], msg=msg, tang=1))

    for b in boxes:
        x1, y1, x2, y2 = b["box"]
        w, h = x2 - x1, y2 - y1
        if w < 1 or h < 1:
            add("sai_kich_thuoc", True, b, f"Box '{b['label']}' gần như không có diện tích ({w:.0f}×{h:.0f}px), xoá hoặc vẽ lại.")
            continue
        if W and H and (x1 < -BOX_TOL or y1 < -BOX_TOL or x2 > W + BOX_TOL or y2 > H + BOX_TOL):
            add("ngoai_anh", True, b, f"Box '{b['label']}' vượt ra ngoài ảnh, kéo mép vào trong khung ảnh.",
                box=[max(0, x1), max(0, y1), min(W, x2), min(H, y2)])
        if w * h < MIN_BOX_AREA:
            add("sai_kich_thuoc", False, b, f"Box '{b['label']}' rất nhỏ ({w:.0f}×{h:.0f}px), kiểm tra có đúng là 1 vật không.")
        ar = w / h
        # vat bi mep anh cat thi dep / manh la binh thuong (vd box 'Van' rong 6px o mep phai) -> khong cham ti le
        cut = W and H and ((ar < 1 and (x1 <= BOX_TOL or x2 >= W - BOX_TOL)) or (ar > 1 and (y1 <= BOX_TOL or y2 >= H - BOX_TOL)))
        if b["label"] not in shape_known and not cut and not abs(b.get("rotation") or 0) > 0.5 \
                and (ar > MAX_ASPECT or ar < 1 / MAX_ASPECT):
            add("sai_kich_thuoc", True, b, f"Box '{b['label']}' có tỉ lệ rộng/cao {ar:.2f} phi lý, không đúng 1 vật.")

    # trung: nhan model KHONG cham (vd Van, Tram, Misc, traffic sign) -> review_core.compare khong xet, xet o day.
    # Nhan model cham da co compare bao trung (khong lap 2 Issue).
    known = set(job_group or ()) | set(shape_known or ())
    rest = [b for b in boxes if b["label"] not in known]
    for i in range(len(rest)):
        for j in range(i + 1, len(rest)):
            if rest[i]["label"] == rest[j]["label"] and _iou(rest[i]["box"], rest[j]["box"]) >= DUP_IOU:
                add("trung", True, rest[j], f"Trùng: 2 box '{rest[j]['label']}' cho cùng 1 vật, xoá 1 box.")

    for a in areas:
        pts = a.get("points")
        if a["kind"] == "polygon" and pts is not None:
            P = [(float(pts[i]), float(pts[i + 1])) for i in range(0, len(pts) - 1, 2)]
            if len(P) < MIN_POLY_POINTS:
                add("polygon_hong", True, a, f"Polygon '{a['label']}' chỉ có {len(P)} điểm, cần ít nhất {MIN_POLY_POINTS}.")
                continue
            if self_intersects(P):
                add("polygon_hong", True, a, f"Polygon '{a['label']}' bị xoắn (viền tự cắt nhau), sửa lại thứ tự điểm.")
        if W and H:
            x1, y1, x2, y2 = a["box"]
            if x1 < -BOX_TOL or y1 < -BOX_TOL or x2 > W + BOX_TOL or y2 > H + BOX_TOL:
                add("ngoai_anh", True, a, f"{'Mask' if a['kind'] == 'mask' else 'Polygon'} '{a['label']}' vượt ra ngoài ảnh.")

    if pair_mode:
        for a in areas:
            pair = max((b for b in boxes if b["label"] == a["label"]), key=lambda b: _iou(a["box"], b["box"]), default=None)
            if pair is None or _iou(a["box"], pair["box"]) < PAIR_IOU:
                continue
            ab, pb = a["box"], pair["box"]
            w, h = pb[2] - pb[0], pb[3] - pb[1]
            d = [pb[0] - ab[0], pb[1] - ab[1], ab[2] - pb[2], ab[3] - pb[3]]      # px polygon vuot ra ngoai box moi canh
            side = [w, h, w, h]
            over = [v > max(PAIR_TOL[0], PAIR_TOL[1] * sd) for v, sd in zip(d, side)]
            if any(over):
                sure = any(v > max(PAIR_SURE[0], PAIR_SURE[1] * sd) for v, sd in zip(d, side))
                sides = [f"{s} {v:.0f}px" for s, o, v in zip(("trái", "trên", "phải", "dưới"), over, d) if o]
                what = "mask" if a["kind"] == "mask" else "polygon"
                add("sai_vien", sure, a, f"{what.capitalize() if sure else 'Có thể ' + what} '{a['label']}' tràn ra ngoài box "
                                         f"của nó ({', '.join(sides)}): polygon và box phải khớp nhau.")

    # rider / pedestrian theo box xe 2 banh cua chinh labeler (khong can model: vat nho tool khong thay van bat duoc)
    if job_group:
        import review_core as R
        rider = R.rider_label(job_group)
        if rider:
            bikes = [b["box"] for b in boxes if job_group.get(b["label"]) == "two"]
            for b in boxes:
                if job_group.get(b["label"]) != "person":
                    continue
                on = R._on_two(b["box"], bikes)
                if b["label"] != rider and on >= R.RIDER_ON:
                    sure = on >= R.RIDER_SURE
                    add("sai_nhan", sure, b, f"{'Sai' if sure else 'Có thể sai'} nhãn: '{b['label']}' này đang ở trên xe 2 bánh, "
                                             f"nên là '{rider}'.")
                elif b["label"] == rider and on < 0.1:
                    add("thieu", False, b, f"'{rider}' này không có box xe máy / xe đạp bên dưới: thiếu box xe, "
                                           f"hoặc đây là người đi bộ.")

    # nguoi nam trong box xe (LetmeQC label_consistency): thuong la gan nham nguoi ngoi trong xe / gan nham nhan
    people = [b for b in boxes if norm(b["label"]) in PERSON]
    cars = [b for b in boxes if norm(b["label"]) in VEHICLE]
    for p in people:
        for c in cars:
            if _iou(p["box"], c["box"]) > 0.5:
                add("sai_nhan", False, p, f"Box '{p['label']}' gần như trùng box '{c['label']}' {_fmt(c['box'])}: "
                                          f"người trong xe không gán riêng, hoặc gán nhầm nhãn.")
                break
    return out


def raw_areas(shapes, id2label):
    """shape polygon / mask kieu CVAT API (ca polygon hong < 3 diem) -> [dict(id,label,kind,box,points)]"""
    out = []
    for s in shapes:
        if s.get("type") not in ("polygon", "mask") or s.get("label_id") not in id2label:
            continue
        p = [float(v) for v in s["points"]]
        if s["type"] == "mask":
            box = p[-4:]
            box = [box[0], box[1], box[2] + 1, box[3] + 1]
        elif len(p) >= 2:
            xs, ys = p[0::2], p[1::2]
            box = [min(xs), min(ys), max(xs), max(ys)]
        else:
            continue
        out.append(dict(id=s.get("_ref") or f"shape {s['id']}", label=id2label[s["label_id"]], kind=s["type"], box=box,
                        points=p if s["type"] == "polygon" else None))
    return out
