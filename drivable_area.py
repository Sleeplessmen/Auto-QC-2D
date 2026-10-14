"""Drivable area theo TỪNG LÀN, đúng luật giao thông Việt Nam (QCVN 41:2019/BGTVT, xe đi bên phải).

1. Mặt đường = road (SegFormer) ∪ drivable (YOLOP), lấp lỗ nhỏ (vạch sơn, nắp cống...) cho kín, KHÔNG lấp
   chỗ xe đứng — polygon đi vòng quanh chân xe.
2. Các vạch chạy dọc đường (vạch làn, tim đường, lề đường) chia mặt đường thành từng làn; mỗi làn 1 polygon
   riêng, không gộp.
3. Làn xe mình đang đi (chứa tâm đáy ảnh) = "direct", dừng ở chân xe phía trước trong làn.
4. Làn bên cạnh = "alternative" CHỈ khi được phép chuyển sang theo luật:
   - vạch trắng nét đứt (vạch 2.x, phân chia làn cùng chiều, được đè/chuyển làn) -> sang được;
   - vạch trắng liền (không được đè vạch) -> KHÔNG (đổi ALLOW_CROSS_SOLID_WHITE nếu tài liệu cho phép);
   - vạch vàng (vạch 1.x, tim đường, phân chia 2 chiều ngược nhau) / vạch đôi -> làn bên kia là chiều
     ngược lại, KHÔNG gán;
   - lề đường -> hết đường.
5. Không chắc (đường không có vạch, làn chỉ có 1 bên vạch, vạch không rõ nét liền/đứt) -> needs_review=True.
"""
import cv2
import numpy as np

from lane_markings import SINGLE_WHITE, SINGLE_YELLOW, DOUBLE_WHITE, DOUBLE_YELLOW, CURB

DIRECT, ALTERNATIVE = "direct", "alternative"

BOUNDARY_TYPES = {SINGLE_WHITE, SINGLE_YELLOW, DOUBLE_WHITE, DOUBLE_YELLOW, CURB}
ALLOW_CROSS_SOLID_WHITE = False   # QCVN 41: vạch liền = không được đè/chuyển làn
# Vật cản chặn làn direct (diện tích lái được dừng ở chân vật cản gần nhất phía trước)
BLOCKING_LABELS = {"car", "truck", "bus", "train", "motorcycle", "bicycle", "rider", "pedestrian"}

MIN_BOUNDARY_SPAN_Y = 30   # px — vạch dọc đường phải trải ít nhất chừng này theo chiều dọc ảnh
EXTEND_UP_FRAC = 0.15      # kéo dài vạch lên phía xa thêm 15% chiều dài (khúc cuối hay bị YOLOP bỏ sót)
SAME_BOUNDARY_PX = 12      # 2 vạch trùng nhau cả ở đáy lẫn đỉnh -> là 1
LANE_MIN_WIDTH_RATIO = 0.4  # làn phải rộng >= 40% làn direct ở cùng độ cao — hẹp hơn là dải vụn do 2 vạch
                            # kéo dài cắt nhau, không phải làn thật
MIN_LANE_AREA = 1500       # px^2 — làn nhỏ hơn là mảnh vụn
FILL_HOLE_MAX_BOX_OVERLAP = 0.2  # lỗ trong mặt đường chồng box xe > 20% -> chỗ xe đứng, không lấp
POLY_EPS = 2.0             # px — sai số polygon: bám sát mép, không nới rộng


class _Boundary:
    def __init__(self, name, style, pts, max_y):
        self.name, self.style = name, style
        ys, xs = pts[:, 1], pts[:, 0]
        self.y_top = float(ys.min() - EXTEND_UP_FRAC * np.ptp(ys))
        self.y_low, self.y_high = float(ys.min()), float(ys.max())
        span = np.ptp(ys)
        deg = 2 if span > 150 and len(pts) >= 5 else 1
        self.mid = np.polyfit(ys, xs, deg)
        # ngoài đoạn nhìn thấy thì kéo dài THẲNG theo hướng của khúc gần nhất (đa thức bậc 2 ngoại suy dễ cong bậy)
        order = np.argsort(ys)
        k = max(2, len(pts) // 3)
        lo, hi = order[:k], order[-k:]
        self.top = np.polyfit(ys[lo], xs[lo], 1) if np.ptp(ys[lo]) > 3 else self.mid[-2:]
        self.bot = np.polyfit(ys[hi], xs[hi], 1) if np.ptp(ys[hi]) > 3 else self.mid[-2:]

    def x_at(self, y):
        y = np.asarray(y, float)
        return np.where(y < self.y_low, np.polyval(self.top, y),
                        np.where(y > self.y_high, np.polyval(self.bot, y), np.polyval(self.mid, y)))

    def crossable(self):
        """Có được chuyển làn qua vạch này không (QCVN 41:2019)."""
        if self.name != SINGLE_WHITE:
            return False           # vạch vàng / vạch đôi / lề đường
        return self.style == "dashed" or (ALLOW_CROSS_SOLID_WHITE and self.style == "solid")


def build_road_mask(seg_road, yolop_drivable, vehicle_boxes, max_y):
    """Mặt đường kín: hợp 2 model, lấp lỗ nhỏ, giữ nguyên chỗ xe đứng."""
    road = seg_road.astype(bool)
    if yolop_drivable is not None:
        road |= yolop_drivable.astype(bool)
    h, w = road.shape
    road = cv2.morphologyEx(road.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    if max_y is not None:
        road[int(max_y):] = 0

    box_mask = np.zeros((h, w), np.uint8)
    for x1, y1, x2, y2 in vehicle_boxes:
        box_mask[max(0, int(y1)):int(np.ceil(y2)), max(0, int(x1)):int(np.ceil(x2))] = 1
    # lỗ = vùng không phải road bị road bao kín
    inv = (1 - road).astype(np.uint8)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(inv, connectivity=4)
    for i in range(1, n):
        x, y, bw, bh, area = stats[i]
        if x == 0 or y == 0 or x + bw >= w or y + bh >= (int(max_y) if max_y else h):
            continue   # chạm mép ảnh / ca-pô -> không phải lỗ
        comp = labels == i
        if (box_mask[comp] > 0).mean() <= FILL_HOLE_MAX_BOX_OVERLAP:
            road[comp] = 1
    return road.astype(bool)


def split_drivable(road, lane_details, vehicle_dets, max_y):
    """road: mask mặt đường (build_road_mask). lane_details: LaneMarkingDetector.details.
    vehicle_dets: [(cvat_name, [xtl,ytl,xbr,ybr])]. Trả về list dict(area_type, points, needs_review, note)."""
    h, w = road.shape
    y_bottom = int(max_y) - 1 if max_y else h - 1
    if not road.any():
        return []

    bounds = []
    for d in lane_details:
        if d["name"] not in BOUNDARY_TYPES or not d["along"]:
            continue
        pts = np.asarray(d["pts"], float)
        if np.ptp(pts[:, 1]) < MIN_BOUNDARY_SPAN_Y:
            continue
        bounds.append(_Boundary(d["name"], d["style"], pts, max_y))
    bounds = _dedupe_bounds(bounds, y_bottom)
    bounds.sort(key=lambda b: float(b.x_at(y_bottom)))

    ys = np.arange(h)
    cols = np.arange(w)[None, :]
    xs = [b.x_at(ys) for b in bounds]
    ego_x = w / 2.0
    ego = int(np.searchsorted([float(x[y_bottom]) for x in xs], ego_x))  # làn thứ ego nằm giữa bound ego-1 và ego

    def lane_mask(k):
        left = bounds[k - 1] if k - 1 >= 0 else None
        right = bounds[k] if k < len(bounds) else None
        xl = xs[k - 1] if left else np.full(h, -1.0)
        xr = xs[k] if right else np.full(h, float(w))
        top = max(left.y_top if left else 0, right.y_top if right else 0)
        m = (cols > xl[:, None]) & (cols < xr[:, None]) & road
        m[:int(max(0, top))] = False
        return m, left, right

    out = []
    if not bounds:
        out.append(_polygon(road, DIRECT, True, "không thấy vạch chia làn — cả mặt đường là direct, kiểm tra xem đường 2 chiều không"))
        return [o for o in out if o]

    # làn direct + đi dần sang 2 bên chừng nào còn được chuyển làn hợp pháp
    reach = {ego: DIRECT}
    for step in (-1, 1):
        k = ego
        while True:
            b_idx = k - 1 if step < 0 else k       # vạch giữa làn k và làn k+step
            if b_idx < 0 or b_idx >= len(bounds) or not bounds[b_idx].crossable():
                break
            k += step
            reach[k] = ALTERNATIVE

    ego_w = lane_mask(ego)[0].sum(axis=1)
    for k, kind in sorted(reach.items()):
        m, left, right = lane_mask(k)
        if kind == ALTERNATIVE:
            # chỉ so ở những hàng làn KHÔNG chạm mép ảnh (làn bị khung ảnh cắt thì trông hẹp nhưng vẫn là làn thật)
            rows = (ego_w > 0) & (m.sum(axis=1) > 0) & ~m[:, 0] & ~m[:, -1]
            if rows.any() and np.median(m.sum(axis=1)[rows] / ego_w[rows]) < LANE_MIN_WIDTH_RATIO:
                continue
        review, notes = False, []
        if left is None or right is None:
            review = True
            notes.append("làn chỉ có vạch 1 bên — bên kia lấy theo mép mặt đường")
        for b in (left, right):
            if b is not None and b.name != CURB and b.style is None:
                review = True
                notes.append("vạch không rõ nét liền/đứt")
        if kind == DIRECT:
            m = _cut_at_leading_vehicle(m, vehicle_dets, y_bottom)
        poly = _polygon(m, kind, review, "; ".join(notes))
        if poly:
            out.append(poly)
    return out


def _dedupe_bounds(bounds, y_bottom):
    kept = []
    for b in sorted(bounds, key=lambda b: -(b.y_high - b.y_low)):
        top = max(b.y_low, 0)
        if any(abs(float(b.x_at(y_bottom) - k.x_at(y_bottom))) < SAME_BOUNDARY_PX
               and abs(float(b.x_at(top) - k.x_at(top))) < SAME_BOUNDARY_PX for k in kept):
            continue
        kept.append(b)
    return kept


def _cut_at_leading_vehicle(m, vehicle_dets, y_bottom):
    """Làn direct dừng ở chân xe/người gần nhất phía trước nằm trong làn."""
    best = None
    for name, (x1, y1, x2, y2) in vehicle_dets:
        if name not in BLOCKING_LABELS:
            continue
        yb = int(min(y2, y_bottom))
        below = m[yb:yb + 8]   # mặt đường ngay dưới chân xe
        if below.size == 0 or not below[:, max(0, int(x1)):int(np.ceil(x2))].any():
            continue
        cols = np.where(below.any(axis=0))[0]
        center = (cols.min() + cols.max()) / 2   # tâm làn ngay dưới chân xe
        if not (x1 <= center <= x2):
            continue   # xe đỗ ven lề / lấn một phần: không chắn giữa làn -> polygon đi vòng qua chân xe
        if best is None or yb > best:
            best = yb
    if best is not None:
        m = m.copy()
        m[:best] = False
    return m


def _polygon(mask, kind, review, note):
    """Mảnh gần xe nhất (thấp nhất trong ảnh) của làn -> polygon bám sát mép."""
    mask = mask.astype(np.uint8)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    comps = [i for i in range(1, n) if stats[i, cv2.CC_STAT_AREA] >= MIN_LANE_AREA]
    if not comps:
        return None
    best = max(comps, key=lambda i: stats[i, cv2.CC_STAT_TOP] + stats[i, cv2.CC_STAT_HEIGHT])
    cnts, _ = cv2.findContours((labels == best).astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    cnt = max(cnts, key=cv2.contourArea)
    approx = cv2.approxPolyDP(cnt, POLY_EPS, True).reshape(-1, 2)
    if len(approx) < 3:
        return None
    return dict(area_type=kind, points=approx.astype(float).flatten().tolist(), needs_review=review, note=note)
