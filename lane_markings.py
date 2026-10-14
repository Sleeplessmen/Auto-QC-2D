"""Tự phát hiện vạch sơn kẻ đường (Lane marking -> Polyline) bằng xử lý ảnh, không cần model riêng.

Chỉ tìm vạch BÊN TRONG vùng mặt đường (mask "road" của SegFormer) và NGOÀI box xe/người:
  1. Vạch sơn = pixel sáng hơn hẳn mặt đường xung quanh (white top-hat trên kênh V).
  2. Phân màu: trắng (độ bão hoà thấp) / vàng (hue vàng, bão hoà cao).
  3. Lọc hình dạng: vạch sơn là mảng dài, đặc (loại chữ "STOP", mũi tên, vệt đèn pha, lá cây...).
  4. Nhiều sọc dày song song cùng hàng ngang, cách đều -> lane/crosswalk (2 polyline mép gần + mép xa).
  5. Các đoạn nét đứt thẳng hàng -> nối thành 1 polyline (1 vạch = 1 đường, không vẽ từng khúc).
  6. 2 vạch cùng màu chạy song song sát nhau -> lane/double white|yellow, còn lại -> lane/single white|yellow.

Mảng nghi là vạch nhưng không chắc (màu lạ -> có thể là "single other", frame quá tối...) KHÔNG được
gán nhãn tự động mà trả về trong danh sách cảnh báo để kiểm tra tay — tránh sinh nhãn sai.
"""
import os
import sys

import cv2
import numpy as np

SINGLE_WHITE = "lane/single white"
SINGLE_YELLOW = "lane/single yellow"
DOUBLE_WHITE = "lane/double white"
DOUBLE_YELLOW = "lane/double yellow"
CROSSWALK = "lane/crosswalk"
CURB = "lane/road curb"

ROAD_GROW_PX = 7           # nới nhẹ vùng road để không cắt cụt vạch sát mép đường
MIN_ON_ROAD = 0.6          # >= 60% pixel của mảng phải nằm trên mặt đường (Cityscapes xếp vạch sơn vào "road")
TOPHAT_KERNEL = 51         # lớn hơn bề rộng vạch/sọc crosswalk gần xe nhất (px)
WHITE_TOPHAT_MIN = 30      # vạch trắng phải sáng hơn nền đường ít nhất chừng này (thang 0-255)
WHITE_MAX_SAT = 70
YELLOW_TOPHAT_MIN = 20
YELLOW_HUE = (12, 38)      # thang hue OpenCV 0-180
YELLOW_SAT_ABOVE_ROAD = 60 # vàng phải đậm hơn hẳn màu nền đường (đèn đường/đèn pha vàng nhuộm cả mặt đường)
OTHER_SAT_ABOVE_ROAD = 90  # sáng + rất đậm màu mà không phải vàng -> có thể "single other", chỉ cảnh báo

MIN_AREA = 30              # px — bỏ đốm nhiễu
MIN_SOLIDITY = 0.75        # diện tích / diện tích bao lồi — vạch/sọc là hình lồi đặc; chữ, mũi tên thì không
LINE_MIN_ELONGATION = 2.5  # dài / rộng — vạch làn phải là mảng dài
STRIPE_MIN_ELONGATION = 1.3  # sọc crosswalk nhìn nghiêng có thể gần vuông
STRIPE_MIN_SOLIDITY = 0.85  # sọc crosswalk là hình bình hành đặc (loại mảnh chữ "STOP")
RIDGE_MIN_CONTRAST = 18    # vạch phải sáng hơn mặt đường ở CẢ HAI bên (loại mép sáng/tối: ca-pô, bóng râm)
EDGE_MIN_GRAD = 10         # độ sắc mép tối thiểu — loại vệt đèn pha loang mờ
MIN_LINE_LEN = 30          # px — polyline cuối cùng ngắn hơn -> bỏ

CROSSWALK_MIN_STRIPES = 3
CROSSWALK_MAX_GAP_RATIO = 2.5   # khe giữa 2 sọc <= tỉ lệ này * bề sọc (vạch làn thường cách xa hơn nhiều)
CROSSWALK_SIZE_RATIO = 2.0      # các sọc trong 1 dải có kích thước tương đương nhau

DASH_MAX_GAP = 250         # px — khe tối đa giữa 2 khúc nét đứt để nối
DASH_MAX_ANGLE = 15        # độ
DASH_LATERAL_TOL = 6       # px + 0.15 * khe

DOUBLE_MAX_GAP_WIDTHS = 4.0    # 2 vạch song song cách nhau <= chừng này lần bề rộng vạch -> vạch đôi
DOUBLE_MIN_OVERLAP = 0.5
DOUBLE_AS_CENTER = True    # True: vạch đôi vẽ 1 polyline ở giữa 2 vạch; False: vẽ cả 2 vạch, cùng nhãn double

# --- Nhánh YOLOP ---
YOLOP_MIN_LINE_LEN = 40    # px — đường ngắn hơn (mảnh chữ số, mũi tên YOLOP lỡ bắt) -> bỏ
PROFILE_BASE = 6           # nửa bề rộng mặt cắt ngang vạch (px) = PROFILE_BASE + PROFILE_PER_Y * y
PROFILE_PER_Y = 0.03       # vạch càng gần xe (y lớn) càng to
PAINT_TOPHAT_MIN = 20      # gờ sáng tối thiểu để coi là có sơn tại vị trí YOLOP chỉ ra
YELLOW_PIXEL_SAT_ABOVE_ROAD = 25  # pixel sơn đậm màu vàng hơn nền đường chừng này -> pixel vàng
YELLOW_MIN_FRAC = 0.4      # >= 40% pixel sơn là vàng -> vạch vàng (vạch vàng cũ/mờ vẫn nhận được)
DOUBLE_WIDTH_RATIO = 2.5   # 2 dải của vạch đôi rộng tương đương nhau
PAINT_MIN_FRAC = 0.15      # >= 15% điểm mẫu thấy sơn -> vạch sơn (nét đứt chỉ ~25% chiều dài là sơn)
DOUBLE_MIN_FRAC = 0.5      # >= 50% mặt cắt có sơn thấy 2 dải sơn tách rời -> vạch đôi
DOUBLE_MAX_RUN_FRAC = 0.45 # 1 dải sơn chiếm gần hết mặt cắt thì không phải 2 vạch mảnh song song
CURB_SIDE_MIN_FRAC = 0.5   # không có sơn nhưng >= 50% điểm mẫu giáp vỉa hè/cỏ/cây -> lề đường
ZEBRA_MIN_RATE = 2.5       # mép crosswalk: 1 bên vạch có sơn bật/tắt >= chừng này lần / 100 px (sọc, ô cờ)
ZEBRA_FILL = (0.25, 0.85)  # và sơn chiếm 25-85% chiều dài bên đó (1 vạch liền bên cạnh thì ~100%)
ZEBRA_MAX_CV = 0.5         # độ lệch chuẩn / trung bình của độ dài sọc và khe — sọc thật đều đặn
ON_ROAD_MARGIN = 15        # px — vạch sơn phải nằm trong vùng road (nới chừng này), trừ lề đường
ALONG_MIN_SLOPE = 0.15     # vạch dọc đường: dốc >= 0.15 (vạch làn ở rìa ảnh nhìn phối cảnh rất thoải);
                           # thoải hơn là vạch ngang đường (vạch dừng, mép crosswalk) -> Direction vertical
SOLID_MIN_FRAC = 0.75      # >= 75% chiều dài nhìn thấy có sơn -> nét liền, ít hơn -> nét đứt
STYLE_EXTEND_NEAR = 1.0    # kéo dài vạch về phía gần xe thêm chừng này lần chiều dài để xét nét liền/đứt
STYLE_FAR_SKIP = 0.15      # bỏ 15% phần xa nhất của vạch khi tìm khe: vạch liền mờ dần về phía chân trời,
                           # KHÔNG kéo dài về phía xa — chỗ vạch liền hết thấy sẽ bị tưởng là khe nét đứt
STYLE_TOPHAT_MIN = 40      # xét nét liền/đứt dùng ngưỡng sơn chặt (mặt đường nắng, vệt sáng không tính là sơn)
DASH_GAP_MIN_SAMPLES = 6   # nét đứt phải có khe liên tục >= 6 điểm mẫu (~24 px) — vài điểm lẻ mất sơn
                           # (vạch mòn, bóng râm) không đủ để kết luận nét đứt -> tránh gán alternative trái luật
STYLE_MIN_SAMPLES = 12     # cần ít nhất chừng này điểm mẫu nhìn thấy mới kết luận được
BRIDGE_MAX_GAP = 700       # px — nối vạch xuyên qua xe (khe nằm trong box xe) tối đa chừng này
BRIDGE_IN_BOX = 0.6        # >= 60% khe phải nằm trong box xe mới được nối xa
DEDUPE_DIST = 8            # px — 2 đường trùng nhau (>= 70% điểm cách nhau dưới mức này) -> giữ 1

DARK_ROAD_V = 70           # độ sáng trung vị của mặt đường thấp hơn -> frame tối, cảnh báo dễ sót vạch


class _Seg:
    """1 mảng vạch sơn đã trích đường tâm."""

    def __init__(self, color, pts, width, bbox):
        self.color = color          # "white" | "yellow"
        self.pts = pts              # (N,2) float, thứ tự từ gần xe (y lớn) ra xa
        self.width = width
        self.bbox = bbox            # x, y, w, h

    @property
    def length(self):
        return float(np.linalg.norm(np.diff(self.pts, axis=0), axis=1).sum())

    @property
    def along_road(self):
        """Vạch chạy dọc đường (trên ảnh: dốc) — phân biệt với vạch ngang như vạch dừng."""
        d = self.pts[-1] - self.pts[0]
        return abs(d[1]) >= abs(d[0]) * 0.35


class LaneMarkingDetector:
    def __init__(self, debug=False):
        self.debug = debug
        self.rejected = []   # debug: (bbox, lý do bị loại) — dùng để chỉnh ngưỡng
        # Chi tiết từng vạch của lần detect gần nhất (dùng để chia làn cho drivable area):
        # dict(name, pts (N,2), style "solid"|"dashed"|None, along: bool — chạy dọc đường)
        self.details = []

    def _reject(self, bbox, reason):
        if self.debug:
            self.rejected.append((bbox, reason))

    def detect(self, image, road_mask=None, exclude_boxes=(), max_y=None, lane_mask=None, curb_side_mask=None):
        """image: PIL.Image RGB. road_mask: (H,W) bool/uint8 vùng mặt đường (None -> nửa dưới ảnh).
        exclude_boxes: [xtl,ytl,xbr,ybr] của xe/người — bỏ phần sáng trên thân xe.
        max_y: bỏ phần ảnh từ dòng này trở xuống (ca-pô).
        lane_mask: mask vạch của YolopLaneSegmenter (khuyên dùng). None -> chỉ dùng xử lý ảnh (kém hơn).
        curb_side_mask: vùng vỉa hè/cỏ/cây (SegFormer) — đường YOLOP không có sơn mà giáp vùng này là lề đường.
        Trả về (lines, warnings): lines = [(cvat_name, [x1,y1,x2,y2,...])], warnings = [str]."""
        rgb = np.asarray(image.convert("RGB"))
        h, w = rgb.shape[:2]
        roi = self._roi(road_mask, h, w, exclude_boxes, max_y)
        warnings = []
        self.details = []
        if roi.sum() == 0:
            return [], warnings

        hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
        hue, sat, val = hsv[..., 0], hsv[..., 1], hsv[..., 2]
        road_v = float(np.median(val[roi > 0]))
        if road_v < DARK_ROAD_V:
            warnings.append(f"frame tối (độ sáng mặt đường {road_v:.0f}) — vạch mờ có thể bị sót, kiểm tra tay")

        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (TOPHAT_KERNEL, TOPHAT_KERNEL))
        tophat = cv2.morphologyEx(val, cv2.MORPH_TOPHAT, k)
        road_s = float(np.median(sat[roi > 0]))
        white = (tophat >= WHITE_TOPHAT_MIN) & (sat <= max(WHITE_MAX_SAT, road_s + 15))
        yellow = ((tophat >= YELLOW_TOPHAT_MIN) & (hue >= YELLOW_HUE[0]) & (hue <= YELLOW_HUE[1])
                  & (sat >= road_s + YELLOW_SAT_ABOVE_ROAD))
        other = (tophat >= WHITE_TOPHAT_MIN) & (sat >= road_s + OTHER_SAT_ABOVE_ROAD) & ~yellow

        on_road = road_mask > 0 if road_mask is not None and np.any(road_mask) else roi > 0
        grad = cv2.magnitude(cv2.Sobel(val, cv2.CV_32F, 1, 0, ksize=3), cv2.Sobel(val, cv2.CV_32F, 0, 1, ksize=3)) / 4
        ctx = dict(val=val.astype(np.float32), grad=grad, on_road=on_road)

        segs = []
        white_blobs = []
        for color, mask in (("white", white), ("yellow", yellow)):
            for blob in self._blobs(mask & (roi > 0), ctx):
                if color == "white":
                    white_blobs.append(blob)
                elif blob["elong"] >= LINE_MIN_ELONGATION:
                    segs.append(self._to_seg("yellow", blob))

        crosswalks, used = self._find_crosswalks(white_blobs)
        lines = list(crosswalks)
        segs += [self._to_seg("white", b) for i, b in enumerate(white_blobs)
                 if i not in used and b["elong"] >= LINE_MIN_ELONGATION]
        segs = [s for s in segs if s is not None]

        if lane_mask is not None:
            # Có YOLOP: vị trí vạch lấy từ model, ảnh gốc chỉ dùng để phân loại (màu, đơn/đôi, lề đường)
            # sơn = gờ sáng hơn mặt đường (không xét màu); màu quyết định sau theo tỉ lệ pixel vàng
            yellowish = (hue >= YELLOW_HUE[0]) & (hue <= YELLOW_HUE[1]) & (sat >= road_s + YELLOW_PIXEL_SAT_ABOVE_ROAD)
            paint = dict(bright=(tophat >= PAINT_TOPHAT_MIN) | yellow, yellowish=yellowish, other=other,
                         strong=(tophat >= STYLE_TOPHAT_MIN) | yellow)
            keep = np.ones((h, w), bool)
            for x1, y1, x2, y2 in exclude_boxes:   # nới đáy box: mép gầm xe hay bị nhận nhầm là vạch
                pad = 0.05 * (y2 - y1)
                keep[max(0, int(y1)):int(np.ceil(y2 + pad)), max(0, int(x1)):int(np.ceil(x2))] = False
            if max_y is not None:
                keep[int(max_y):] = False
            # Dải sọc chỉ là crosswalk khi YOLOP cũng thấy vạch dọc mép dải (loại hàng chữ/số vẽ trên đường)
            near_lane = cv2.dilate(lane_mask.astype(np.uint8), np.ones((13, 13), np.uint8)) > 0
            confirmed = []
            for i in range(0, len(crosswalks), 2):
                pair = crosswalks[i:i + 2]
                hit = []
                for _, pts in pair:
                    smp, _ = _resample(np.array(pts).reshape(-1, 2), 4.0)
                    xi = np.clip(smp[:, 0].round().astype(int), 0, w - 1)
                    yi = np.clip(smp[:, 1].round().astype(int), 0, h - 1)
                    hit.append(near_lane[yi, xi].mean())
                if max(hit) >= 0.3:
                    confirmed += pair
                else:
                    x0, y0 = np.array(pair[0][1]).reshape(-1, 2).min(axis=0)
                    warnings.append(f"nhóm sọc giống crosswalk gần [{x0:.0f},{y0:.0f}] nhưng YOLOP không thấy — chưa gán, kiểm tra tay")
            lines = list(confirmed)
            crosswalks = confirmed
            bands = [np.array(cw[1]).reshape(-1, 2) for cw in crosswalks]
            road_near = cv2.dilate(on_road.astype(np.uint8), np.ones((2 * ON_ROAD_MARGIN + 1,) * 2, np.uint8)) > 0
            lines += self._lines_from_lane_mask(lane_mask & keep, paint, curb_side_mask, bands, warnings, road_near,
                                                keep, list(exclude_boxes))
            self.details = [dict(name=n, pts=np.array(p).reshape(-1, 2), style=None, along=False)
                            for n, p in crosswalks] + self.details
            return lines, warnings

        for blob in self._blobs(other & (roi > 0), ctx):
            if blob["elong"] < LINE_MIN_ELONGATION:
                continue
            x, y, bw, bh = blob["bbox"]
            warnings.append(f"mảng sơn màu lạ (có thể lane/single other) tại [{x},{y},{x + bw},{y + bh}] — chưa gán, kiểm tra tay")

        chains = self._chain_dashes(segs)
        lines += self._classify_chains(chains)
        return lines, warnings

    # ------------------------------------------------------------------
    # Nhánh YOLOP
    # ------------------------------------------------------------------
    def _lines_from_lane_mask(self, lane_mask, paint, curb_side_mask, crosswalk_edges, warnings, road_near,
                              visible, bridge_boxes):
        """Mask vạch của YOLOP -> đường tâm từng vạch -> phân loại bằng mặt cắt ngang trên ảnh gốc.
        visible: pixel không bị xe che / không thuộc ca-pô. bridge_boxes: box xe — vạch bị xe che được nối
        xuyên qua (1 vạch = 1 polyline liền, như cách gán tay)."""
        mask = cv2.morphologyEx(lane_mask.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
        segs = _skeleton_branches(mask)
        chains = self._chain_dashes(segs, any_direction=True, bridge_boxes=bridge_boxes)
        h, w = mask.shape

        # Vùng dải crosswalk (đã vẽ 2 mép riêng) — bỏ các đường YOLOP trùng vào đó
        cw_zone = np.zeros((h, w), np.uint8)
        for i in range(0, len(crosswalk_edges) - 1, 2):
            quad = np.concatenate([crosswalk_edges[i], crosswalk_edges[i + 1][::-1]]).astype(np.int32)
            cv2.fillPoly(cw_zone, [quad], 1)
            cv2.polylines(cw_zone, [quad], True, 1, 17)

        found = []
        for ch in chains:
            pts = np.concatenate([s.pts for s in ch])
            length = float(np.linalg.norm(np.diff(pts, axis=0), axis=1).sum())
            if length < YOLOP_MIN_LINE_LEN:
                continue
            samples, normals = _resample(pts, 5.0)
            xi = np.clip(samples[:, 0].round().astype(int), 0, w - 1)
            yi = np.clip(samples[:, 1].round().astype(int), 0, h - 1)
            if cw_zone[yi, xi].mean() >= 0.5:
                continue
            vis = visible[yi, xi]
            if vis.sum() < 4:
                continue
            style = None
            if _zebra_side(pts, paint["bright"]):
                name, why = CROSSWALK, None   # mép dải sọc / ô bàn cờ mà bước gom sọc không tách được
            else:
                # chỉ xét phần nhìn thấy — đoạn nối xuyên qua xe không có sơn, không được tính là nét đứt
                name, why, style = self._classify_profile(samples[vis], normals[vis], paint, curb_side_mask)
            if name not in (None, CURB) and road_near[yi[vis], xi[vis]].mean() < 0.5:
                continue   # vạch sơn phải nằm trên mặt đường (loại mép tường chắn, nóc xe...)
            if name in (SINGLE_WHITE, SINGLE_YELLOW, DOUBLE_WHITE, DOUBLE_YELLOW):
                style = _line_style(pts, paint["strong"], visible & road_near)
            if name is None:
                if why:
                    x0, y0 = pts.min(axis=0)
                    x1, y1 = pts.max(axis=0)
                    warnings.append(f"{why} tại [{x0:.0f},{y0:.0f},{x1:.0f},{y1:.0f}] — chưa gán, kiểm tra tay")
                continue
            simple = cv2.approxPolyDP(pts.reshape(-1, 1, 2).astype(np.float32), 2.0, False).reshape(-1, 2)
            found.append((name, simple.astype(float), length, style))
        kept = _dedupe_lines(found, (h, w))
        for n, p, st in kept:
            d = p[-1] - p[0]
            self.details.append(dict(name=n, pts=p, style=st, along=bool(abs(d[1]) >= ALONG_MIN_SLOPE * abs(d[0]))))
        return [(n, p.flatten().tolist()) for n, p, _ in kept]

    @staticmethod
    def _classify_profile(samples, normals, paint, curb_side_mask):
        """Cắt ngang vạch tại từng điểm mẫu: có sơn ngay tại vạch không, màu gì, 1 hay 2 dải sơn."""
        h, w = paint["bright"].shape
        n_paint = n_double = n_other = n_side = 0
        n_pix = n_yellow_pix = 0
        for (x, y), nv in zip(samples, normals):
            r = int(PROFILE_BASE + PROFILE_PER_Y * y)
            t = np.arange(-r, r + 1)
            px = np.clip(np.round(x + t * nv[0]).astype(int), 0, w - 1)
            py = np.clip(np.round(y + t * nv[1]).astype(int), 0, h - 1)
            runs = _runs(paint["bright"][py, px])
            # chỉ tính dải sơn chạm nửa giữa mặt cắt — dải sáng lệch hẳn sang bên (mặt vỉa hè) không tính
            near = [(a, b) for a, b in runs if a <= r + r // 2 and b >= r - r // 2]
            if near:
                n_paint += 1
                for a, b in near:
                    n_pix += b - a
                    n_yellow_pix += int(paint["yellowish"][py[a:b], px[a:b]].sum())
                if _is_double(runs, r, len(t)):
                    n_double += 1
            elif paint["other"][py, px][r - r // 2:r + r // 2 + 1].any():
                n_other += 1
            if curb_side_mask is not None:
                t2 = np.arange(-2 * r, 2 * r + 1)
                qx = np.clip(np.round(x + t2 * nv[0]).astype(int), 0, w - 1)
                qy = np.clip(np.round(y + t2 * nv[1]).astype(int), 0, h - 1)
                n_side += int(curb_side_mask[qy, qx].any())
        n = len(samples)
        if n_paint >= PAINT_MIN_FRAC * n:
            yellow = n_yellow_pix >= YELLOW_MIN_FRAC * max(n_pix, 1)
            double = n_double >= DOUBLE_MIN_FRAC * n_paint
            style = "solid" if n_paint >= SOLID_MIN_FRAC * n else "dashed"
            return {(False, False): SINGLE_WHITE, (False, True): DOUBLE_WHITE,
                    (True, False): SINGLE_YELLOW, (True, True): DOUBLE_YELLOW}[(yellow, double)], None, style
        if n_other >= PAINT_MIN_FRAC * n:
            return None, "vạch sơn màu lạ (có thể lane/single other)", None
        if curb_side_mask is not None and n_side >= CURB_SIDE_MIN_FRAC * n:
            return CURB, None, "solid"
        return None, "YOLOP thấy vạch nhưng không có sơn, cũng không giáp vỉa hè/cỏ", None

    # ------------------------------------------------------------------
    def _roi(self, road_mask, h, w, exclude_boxes, max_y):
        if road_mask is not None and np.any(road_mask):
            roi = cv2.dilate((road_mask > 0).astype(np.uint8), np.ones((ROAD_GROW_PX, ROAD_GROW_PX), np.uint8))
        else:
            roi = np.zeros((h, w), np.uint8)
            roi[h // 2:] = 1
        for x1, y1, x2, y2 in exclude_boxes:
            roi[max(0, int(y1)):int(np.ceil(y2)), max(0, int(x1)):int(np.ceil(x2))] = 0
        if max_y is not None:
            roi[int(max_y):] = 0
        return roi

    def _blobs(self, mask, ctx):
        mask = cv2.morphologyEx(mask.astype(np.uint8), cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
        n, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
        h, w = mask.shape
        out = []
        for i in range(1, n):
            x, y, bw, bh, area = stats[i]
            if area < MIN_AREA:
                continue
            comp = labels[y:y + bh, x:x + bw] == i
            ys, xs = np.where(comp)
            xs, ys = xs + x, ys + y
            bbox = (int(x), int(y), int(bw), int(bh))
            if ctx["on_road"][ys, xs].mean() < MIN_ON_ROAD:
                self._reject(bbox, "ngoài mặt đường")
                continue  # vỉa hè, cột, cọc tiêu, thân xe...
            pix = np.stack([xs, ys], axis=1).astype(np.float32)
            (cx, cy), (rw, rh), ang = cv2.minAreaRect(pix)
            long_side, short_side = max(rw, rh, 1.0), max(min(rw, rh), 1.0)
            elong = long_side / short_side
            cnts, _ = cv2.findContours(comp.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            hull = np.zeros(comp.shape, np.uint8)
            cv2.fillPoly(hull, [cv2.convexHull(np.concatenate(cnts))], 1)
            solidity = area / max(int(hull.sum()), 1)
            if elong < STRIPE_MIN_ELONGATION or solidity < MIN_SOLIDITY:
                self._reject(bbox, f"hình dạng elong={elong:.1f} solidity={solidity:.2f}")
                continue  # chữ viết, mũi tên, đốm tròn -> không phải vạch

            # "Gờ sáng": dịch mảng sang 2 bên theo pháp tuyến, cả 2 bên phải tối hơn rõ rệt. Thử vài
            # khoảng cách vì sọc crosswalk ở xa nằm sát nhau (khoảng gần có thể rơi đúng sọc bên cạnh).
            t = np.radians(ang if rw >= rh else ang + 90)
            normal = np.array([-np.sin(t), np.cos(t)])
            v_in = ctx["val"][ys, xs].mean()
            contrast = []
            for sign in (1, -1):
                best = -255.0
                for d in (short_side + 2, short_side + 5, 2 * short_side + 4):
                    sx = np.clip(np.round(xs + sign * d * normal[0]).astype(int), 0, w - 1)
                    sy = np.clip(np.round(ys + sign * d * normal[1]).astype(int), 0, h - 1)
                    best = max(best, v_in - ctx["val"][sy, sx].mean())
                contrast.append(best)
            if min(contrast) < RIDGE_MIN_CONTRAST:
                self._reject(bbox, f"không sáng hơn 2 bên: {contrast[0]:.0f}/{contrast[1]:.0f}")
                continue  # mép sáng/tối (ca-pô, bóng râm) — không phải vạch sơn

            border = cv2.morphologyEx(comp.astype(np.uint8), cv2.MORPH_GRADIENT, np.ones((3, 3), np.uint8))
            by, bx = np.where(border > 0)
            edge = ctx["grad"][by + y, bx + x].mean() if len(bx) else 0.0
            if edge < EDGE_MIN_GRAD:
                self._reject(bbox, f"mép mờ grad={edge:.1f}")
                continue  # mép loang mờ: vệt đèn pha

            out.append(dict(pix=pix, bbox=(int(x), int(y), int(bw), int(bh)), width=float(area / long_side),
                            center=(cx, cy), elong=elong, solidity=solidity))
        return out

    def _to_seg(self, color, blob):
        """Đường tâm của mảng: vạch dốc -> lấy x trung bình theo từng dòng; vạch ngang -> y theo từng cột."""
        pix = blob["pix"]
        x, y, bw, bh = blob["bbox"]
        if bh >= bw * 0.35:
            key, other = pix[:, 1], pix[:, 0]
        else:
            key, other = pix[:, 0], pix[:, 1]
        step = 3
        bins = np.floor(key / step).astype(int)
        pts = []
        for b in np.unique(bins):
            sel = bins == b
            pts.append((key[sel].mean(), other[sel].mean()))
        pts = np.array(pts, np.float32)
        if bh >= bw * 0.35:
            pts = pts[:, ::-1][::-1]          # (x, y), sắp y giảm dần: gần xe -> xa
        else:
            pts = pts[np.argsort(pts[:, 0])]   # vạch ngang: trái -> phải
        if len(pts) < 2:
            return None
        pts = cv2.approxPolyDP(pts.reshape(-1, 1, 2), 1.5, False).reshape(-1, 2)
        if len(pts) < 2:
            return None
        return _Seg(color, pts.astype(np.float32), blob["width"], blob["bbox"])

    # ------------------------------------------------------------------
    def _find_crosswalks(self, blobs):
        """Nhóm các sọc dày cùng hàng ngang, cách đều nhau -> vạch qua đường."""
        n = len(blobs)
        parent = list(range(n))

        def find(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        stripes = [i for i in range(n) if blobs[i]["solidity"] >= STRIPE_MIN_SOLIDITY]
        links = []
        for a, i in enumerate(stripes):
            for j in stripes[a + 1:]:
                kind = self._crosswalk_neighbors(blobs[i]["bbox"], blobs[j]["bbox"])
                if kind:
                    parent[find(i)] = find(j)
                    links.append((i, kind))

        groups = {}
        for i in stripes:
            groups.setdefault(find(i), []).append(i)

        lines, used = [], set()
        groups = [g for g in groups.values() if len(g) >= CROSSWALK_MIN_STRIPES]
        for idx in groups:
            # dải nằm ngang (sọc đứng cạnh nhau) hay dọc (sọc nằm ngang xếp chồng): theo kiểu liên kết chiếm đa số
            kinds = [kind for i, kind in links if i in idx]
            row = kinds.count("row") >= kinds.count("col")
            self._absorb_cut_stripes(blobs, idx, row, used, groups)
            xs0 = [blobs[i]["bbox"][0] for i in idx]
            ys0 = [blobs[i]["bbox"][1] for i in idx]
            xs1 = [blobs[i]["bbox"][0] + blobs[i]["bbox"][2] for i in idx]
            ys1 = [blobs[i]["bbox"][1] + blobs[i]["bbox"][3] for i in idx]
            k, o = (1, 0) if row else (0, 1)   # k: trục vuông góc với dải, o: trục chạy dọc dải
            lo_edge, hi_edge = [], []
            for i in idx:
                pix = blobs[i]["pix"]
                vmin, vmax = pix[:, k].min(), pix[:, k].max()
                lo_edge.append((pix[pix[:, k] <= vmin + 1][:, o].mean(), vmin))
                hi_edge.append((pix[pix[:, k] >= vmax - 1][:, o].mean(), vmax))
            t0, t1 = (min(xs0), max(xs1)) if row else (min(ys0), max(ys1))
            for edge in (lo_edge, hi_edge):   # 2 mép của dải vạch qua đường
                e = np.array(edge)
                a, b = np.polyfit(e[:, 0], e[:, 1], 1)
                p0, p1 = (t0, a * t0 + b), (t1, a * t1 + b)
                if not row:
                    p0, p1 = p0[::-1], p1[::-1]
                lines.append((CROSSWALK, [float(p0[0]), float(p0[1]), float(p1[0]), float(p1[1])]))
            used.update(idx)
        return lines, used

    @staticmethod
    def _absorb_cut_stripes(blobs, idx, row, used, groups):
        """Sọc ở rìa dải hay bị cắt cụt/méo (xe che, mép road mask) nên không qua được ngưỡng sọc.
        Mảng trắng nằm liền kề và thẳng hàng với dải thì gộp luôn vào dải, không để thành single white."""
        in_groups = {i for g in groups for i in g}
        k = 1 if row else 0   # trục vuông góc với dải
        lo = min(blobs[i]["bbox"][k] for i in idx)
        hi = max(blobs[i]["bbox"][k] + blobs[i]["bbox"][k + 2] for i in idx)
        o = 1 - k
        thick = float(np.median([blobs[i]["bbox"][o + 2] for i in idx]))   # bề sọc theo chiều chạy dọc dải
        step = thick * CROSSWALK_MAX_GAP_RATIO
        changed = True
        while changed:
            changed = False
            a0 = min(blobs[i]["bbox"][o] for i in idx)
            a1 = max(blobs[i]["bbox"][o] + blobs[i]["bbox"][o + 2] for i in idx)
            for j, b in enumerate(blobs):
                if j in in_groups or j in used:
                    continue
                b_lo, b_hi = b["bbox"][k], b["bbox"][k] + b["bbox"][k + 2]
                if min(hi, b_hi) - max(lo, b_lo) < 0.5 * (b_hi - b_lo):
                    continue
                b0, b1 = b["bbox"][o], b["bbox"][o] + b["bbox"][o + 2]
                if not (thick / 2.5 <= b1 - b0 <= thick * 2.5):
                    continue   # dày/mỏng khác hẳn các sọc trong dải -> vật khác
                if max(a0, b0) - min(a1, b1) <= step:
                    idx.append(j)
                    in_groups.add(j)
                    changed = True

    @staticmethod
    def _crosswalk_neighbors(bi, bj):
        """2 sọc kề nhau trong cùng 1 dải: cùng hàng (sọc đứng cạnh nhau) hoặc cùng cột (sọc nằm
        ngang xếp chồng — crosswalk băng qua đường nhánh), kích thước tương đương, khe hẹp."""
        xi, yi, wi, hi = bi
        xj, yj, wj, hj = bj
        r = CROSSWALK_SIZE_RATIO
        same_size = 1 / r <= wi / max(wj, 1) <= r and 1 / r <= hi / max(hj, 1) <= r
        if not same_size:
            return None
        if wi > 2 * hi and wj > 2 * hj and min(xi + wi, xj + wj) - max(xi, xj) >= 0.5 * min(wi, wj):
            gap = max(yi, yj) - min(yi + hi, yj + hj)
            if 0 <= gap <= CROSSWALK_MAX_GAP_RATIO * max(min(hi, hj), 1):
                return "col"
        if min(yi + hi, yj + hj) - max(yi, yj) >= 0.5 * min(hi, hj):
            gap = max(xi, xj) - min(xi + wi, xj + wj)
            if gap <= CROSSWALK_MAX_GAP_RATIO * max(min(wi, wj), 1):
                return "row"
        return None

    # ------------------------------------------------------------------
    def _chain_dashes(self, segs, any_direction=False, bridge_boxes=()):
        """Nối các khúc nét đứt / khúc bị cắt ở chỗ giao nhau, thẳng hàng, cùng màu thành 1 chuỗi
        (1 vạch = 1 polyline). any_direction: nối cả vạch ngang (vạch dừng bị vạch làn cắt ngang)."""
        order = sorted(range(len(segs)), key=lambda i: -segs[i].pts[0][1])
        nxt, has_prev = {}, set()
        for i in order:
            a = segs[i]
            if not (a.along_road or any_direction):
                continue
            a_dir = a.pts[-1] - a.pts[0]
            a_dir = a_dir / (np.linalg.norm(a_dir) + 1e-6)
            best, best_gap = None, None
            for j in order:
                b = segs[j]
                if j == i or j in has_prev or b.color != a.color:
                    continue
                if not any_direction and not b.along_road:
                    continue
                v = b.pts[0] - a.pts[-1]
                gap = float(np.linalg.norm(v))
                bridged = gap > DASH_MAX_GAP and _gap_in_boxes(a.pts[-1], b.pts[0], bridge_boxes) >= BRIDGE_IN_BOX
                if (gap > DASH_MAX_GAP and not (bridged and gap <= BRIDGE_MAX_GAP)) or np.dot(v, a_dir) <= 0:
                    continue
                b_dir = b.pts[-1] - b.pts[0]
                b_dir = b_dir / (np.linalg.norm(b_dir) + 1e-6)
                if np.degrees(np.arccos(np.clip(np.dot(a_dir, b_dir), -1, 1))) > DASH_MAX_ANGLE:
                    continue
                lateral = abs(a_dir[0] * v[1] - a_dir[1] * v[0])
                if lateral > DASH_LATERAL_TOL + (0.08 if bridged else 0.15) * gap:
                    continue
                if best_gap is None or gap < best_gap:
                    best, best_gap = j, gap
            if best is not None:
                nxt[i] = best
                has_prev.add(best)

        chains = []
        for i in order:
            if i in has_prev:
                continue
            chain = [i]
            while chain[-1] in nxt:
                chain.append(nxt[chain[-1]])
            chains.append([segs[k] for k in chain])
        return chains

    def _classify_chains(self, chains):
        info = []
        for ch in chains:
            pts = np.concatenate([s.pts for s in ch])
            length = sum(s.length for s in ch)
            info.append(dict(color=ch[0].color, pts=pts, length=length,
                             width=float(np.median([s.width for s in ch])),
                             along=ch[0].along_road))

        paired = {}
        for i in range(len(info)):
            for j in range(i + 1, len(info)):
                a, b = info[i], info[j]
                if i in paired or j in paired or a["color"] != b["color"] or not (a["along"] and b["along"]):
                    continue
                dist, overlap = _parallel_distance(a["pts"], b["pts"])
                w = max(a["width"], b["width"])
                if overlap >= DOUBLE_MIN_OVERLAP and w * 0.8 <= dist <= DOUBLE_MAX_GAP_WIDTHS * w + 4:
                    paired[i], paired[j] = j, i

        lines, done = [], set()
        for i, a in enumerate(info):
            if i in done:
                continue
            if i in paired:
                j = paired[i]
                done.update((i, j))
                name = DOUBLE_WHITE if a["color"] == "white" else DOUBLE_YELLOW
                if DOUBLE_AS_CENTER:
                    center = _center_line(a["pts"], info[j]["pts"])
                    if center is not None:
                        lines.append((name, center.flatten().tolist()))
                else:
                    lines.append((name, a["pts"].flatten().tolist()))
                    lines.append((name, info[j]["pts"].flatten().tolist()))
                continue
            if a["length"] < MIN_LINE_LEN:
                continue
            name = SINGLE_WHITE if a["color"] == "white" else SINGLE_YELLOW
            lines.append((name, a["pts"].astype(float).flatten().tolist()))
        return lines


def _interp_x(pts, ys):
    order = np.argsort(pts[:, 1])
    return np.interp(ys, pts[order, 1], pts[order, 0])


def _parallel_distance(a, b):
    """Khoảng cách ngang trung vị giữa 2 vạch dốc trên đoạn y chồng nhau, và tỉ lệ chồng nhau."""
    lo = max(a[:, 1].min(), b[:, 1].min())
    hi = min(a[:, 1].max(), b[:, 1].max())
    span = min(np.ptp(a[:, 1]), np.ptp(b[:, 1]))
    if hi <= lo or span <= 0:
        return np.inf, 0.0
    ys = np.linspace(lo, hi, 10)
    return float(np.median(np.abs(_interp_x(a, ys) - _interp_x(b, ys)))), float((hi - lo) / span)


def _center_line(a, b):
    lo = max(a[:, 1].min(), b[:, 1].min())
    hi = min(a[:, 1].max(), b[:, 1].max())
    if hi <= lo:
        return None
    ys = np.linspace(hi, lo, max(2, int((hi - lo) / 10)))
    xs = (_interp_x(a, ys) + _interp_x(b, ys)) / 2
    pts = np.stack([xs, ys], axis=1).astype(np.float32)
    return cv2.approxPolyDP(pts.reshape(-1, 1, 2), 1.5, False).reshape(-1, 2).astype(float)


# Ban exe (PyInstaller): models/ nam canh file exe
YOLOP_ONNX = os.path.join(os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__)), "models", "yolop-640-640.onnx")


class YolopLaneSegmenter:
    """YOLOP (hustvl/yolop, MIT, train trên BDD100K — cùng bộ nhãn lane/* với task) chạy bằng ONNX.
    Trả mask vạch kẻ đường: model đã học bỏ qua mũi tên, chữ, số vẽ trên đường (BDD không gán nhãn chúng)."""

    def __init__(self, onnx_path: str = YOLOP_ONNX):
        import onnxruntime as ort
        ort.set_default_logger_severity(3)
        self.session = ort.InferenceSession(onnx_path, providers=["CPUExecutionProvider"])

    def segment(self, image):
        """image: PIL.Image. Trả về (lane_mask, drivable_mask) bool (H, W) đúng kích thước ảnh gốc."""
        rgb = np.asarray(image.convert("RGB"))
        h, w = rgb.shape[:2]
        r = min(640 / h, 640 / w)
        nw, nh = int(round(w * r)), int(round(h * r))
        dw, dh = (640 - nw) // 2, (640 - nh) // 2
        canvas = np.full((640, 640, 3), 114, np.float32)
        canvas[dh:dh + nh, dw:dw + nw] = cv2.resize(rgb, (nw, nh), interpolation=cv2.INTER_AREA)
        x = (canvas / 255.0 - np.array([0.485, 0.456, 0.406])) / np.array([0.229, 0.224, 0.225])
        x = x.transpose(2, 0, 1)[None].astype(np.float32)
        _, da, ll = self.session.run(None, {"images": x})
        out = []
        for seg in (ll, da):
            prob = seg[0, 1, dh:dh + nh, dw:dw + nw] - seg[0, 0, dh:dh + nh, dw:dw + nw]
            out.append(cv2.resize(prob, (w, h), interpolation=cv2.INTER_LINEAR) > 0)
        return out[0], out[1]


# ----------------------------------------------------------------------
# Hàm phụ cho nhánh YOLOP
# ----------------------------------------------------------------------
def _thin(mask):
    """Làm mảnh Zhang-Suen (vector hoá numpy): mask vạch dày -> đường tâm rộng 1 px."""
    img = np.pad((mask > 0).astype(np.uint8), 1)
    while True:
        changed = False
        for step in (0, 1):
            c = img[1:-1, 1:-1]
            p2, p3, p4 = img[:-2, 1:-1], img[:-2, 2:], img[1:-1, 2:]
            p5, p6, p7 = img[2:, 2:], img[2:, 1:-1], img[2:, :-2]
            p8, p9 = img[1:-1, :-2], img[:-2, :-2]
            nb = [p2, p3, p4, p5, p6, p7, p8, p9, p2]
            b = sum(q.astype(np.int32) for q in nb[:8])
            a = sum(((nb[i] == 0) & (nb[i + 1] == 1)).astype(np.int32) for i in range(8))
            if step == 0:
                m1, m2 = p2 * p4 * p6, p4 * p6 * p8
            else:
                m1, m2 = p2 * p4 * p8, p2 * p6 * p8
            rem = (c == 1) & (b >= 2) & (b <= 6) & (a == 1) & (m1 == 0) & (m2 == 0)
            if rem.any():
                c[rem] = 0
                changed = True
        if not changed:
            return img[1:-1, 1:-1]


def _skeleton_branches(mask, min_pixels=8):
    """Tách đường tâm thành từng nhánh (cắt tại điểm giao: vạch dừng giao vạch làn...) -> list _Seg."""
    sk = _thin(mask)
    # Điểm giao thật = có >= 3 nhánh toả ra (đếm số lần chuyển 0->1 quanh pixel). Không đếm số pixel
    # lân cận: đường tâm chéo dạng bậc thang có nhiều pixel 3 lân cận nhưng không phải chỗ giao.
    p = np.pad(sk, 1)
    ring = [p[:-2, 1:-1], p[:-2, 2:], p[1:-1, 2:], p[2:, 2:], p[2:, 1:-1], p[2:, :-2], p[1:-1, :-2], p[:-2, :-2]]
    crossings = sum(((ring[i] == 0) & (ring[(i + 1) % 8] == 1)).astype(np.int32) for i in range(8))
    junction = ((sk == 1) & (crossings >= 3)).astype(np.uint8)
    sk = sk & (1 - cv2.dilate(junction, np.ones((3, 3), np.uint8)))
    n, labels = cv2.connectedComponents(sk, connectivity=8)
    segs = []
    for i in range(1, n):
        ys, xs = np.where(labels == i)
        if len(xs) < min_pixels:
            continue
        pix = np.stack([xs, ys], axis=1).astype(np.float32)
        mean = pix.mean(axis=0)
        _, _, vt = np.linalg.svd(pix - mean, full_matrices=False)
        d = vt[0]
        steep = abs(d[1]) >= abs(d[0]) * 0.35
        # hướng chuẩn: vạch dốc đi từ gần xe (y lớn) ra xa; vạch ngang đi từ trái sang phải
        if (steep and d[1] > 0) or (not steep and d[0] < 0):
            d = -d
        proj = (pix - mean) @ d
        order = np.argsort(proj)
        pix, proj = pix[order], proj[order]
        bins = np.floor(proj / 3).astype(int)   # gộp pixel cùng vị trí dọc nhánh cho mượt
        pts = np.array([pix[bins == b].mean(axis=0) for b in np.unique(bins)], np.float32)
        if len(pts) >= 2:
            bbox = (int(xs.min()), int(ys.min()), int(np.ptp(xs)) + 1, int(np.ptp(ys)) + 1)
            segs.append(_Seg("lane", pts, 1.0, bbox))
    return segs


def _resample(pts, step):
    """Lấy điểm mẫu cách đều dọc polyline + pháp tuyến đơn vị tại mỗi điểm."""
    pts = np.asarray(pts, np.float64)
    seg = np.diff(pts, axis=0)
    seg_len = np.linalg.norm(seg, axis=1)
    keep = seg_len > 1e-6
    pts = np.concatenate([pts[:1], pts[1:][keep]])
    seg, seg_len = seg[keep], seg_len[keep]
    if len(seg) == 0:
        return pts[:1], np.array([[1.0, 0.0]])
    cum = np.concatenate([[0], np.cumsum(seg_len)])
    ts = np.arange(0, cum[-1] + 1e-6, step)
    idx = np.clip(np.searchsorted(cum, ts, side="right") - 1, 0, len(seg) - 1)
    frac = (ts - cum[idx]) / seg_len[idx]
    samples = pts[idx] + seg[idx] * frac[:, None]
    tang = seg[idx] / seg_len[idx][:, None]
    normals = np.stack([-tang[:, 1], tang[:, 0]], axis=1)
    return samples, normals


def _zebra_side(pts, bright):
    """Đường chạy dọc mép 1 dải sọc/ô cờ: ở 1 bên, sơn xuất hiện rồi mất xen kẽ đều đặn."""
    h, w = bright.shape
    samples, normals = _resample(pts, 2.0)
    if len(samples) < 20:
        return False
    length = 2.0 * len(samples)
    r = (PROFILE_BASE + PROFILE_PER_Y * samples[:, 1])[:, None]
    for sign in (1, -1):
        for k in (1.0, 2.0):
            d = sign * (k * r + 3)
            occ = np.zeros(len(samples), bool)
            for dd in (-2, 0, 2):   # lấy dải hẹp 5 px để không lọt khe giữa các sọc mảnh
                q = samples + normals * (d + dd)
                xi = np.clip(q[:, 0].round().astype(int), 0, w - 1)
                yi = np.clip(q[:, 1].round().astype(int), 0, h - 1)
                occ |= bright[yi, xi]
            runs = _runs(occ)
            rate = len(runs) / (length / 100.0)
            if len(runs) < 4 or rate < ZEBRA_MIN_RATE or not (ZEBRA_FILL[0] <= occ.mean() <= ZEBRA_FILL[1]):
                continue
            # sọc/ô cờ đều đặn: độ dài sọc và khe gần như nhau (chữ, lưới tản nhiệt xe, tường thì lộn xộn)
            inner = runs[1:-1] if len(runs) > 4 else runs   # 2 sọc ở đầu mút hay bị cắt cụt
            widths = np.array([e - a for a, e in inner], float)
            gaps = np.array([a2 - e1 for (_, e1), (a2, _) in zip(runs, runs[1:])], float)
            if widths.std() > ZEBRA_MAX_CV * widths.mean() or gaps.std() > ZEBRA_MAX_CV * gaps.mean():
                continue
            # phía bên kia vạch phải là mặt đường trống
            q = samples - normals * (k * r + 3)
            xi = np.clip(q[:, 0].round().astype(int), 0, w - 1)
            yi = np.clip(q[:, 1].round().astype(int), 0, h - 1)
            if bright[yi, xi].mean() <= 0.3:
                return True
    return False


def _is_double(runs, center, size):
    """Mặt cắt của vạch đôi: 2 dải sơn rộng tương đương, cách nhau 1 khe hẹp, nằm 2 bên tâm vạch."""
    for (a1, b1), (a2, b2) in zip(runs, runs[1:]):
        w1, w2 = b1 - a1, b2 - a2
        gap = a2 - b1
        if max(w1, w2) > DOUBLE_MAX_RUN_FRAC * size or max(w1, w2) > DOUBLE_WIDTH_RATIO * min(w1, w2):
            continue
        if gap < 1 or gap > 2 * max(w1, w2):
            continue
        if a1 - 2 <= center <= b2 + 2:
            return True
    return False


def _line_style(pts, bright, visible):
    """Nét liền hay nét đứt: xét sơn dọc vạch VÀ phần kéo dài 2 đầu (chỉ chỗ mặt đường nhìn thấy được).
    YOLOP có thể chỉ bắt được 1 khúc của vạch đứt — trên khúc đó toàn sơn, phải nhìn ra ngoài mới biết.
    Trả về "solid" | "dashed" | None (không đủ phần nhìn thấy để kết luận)."""
    pts = np.asarray(pts, float)
    length = float(np.linalg.norm(np.diff(pts, axis=0), axis=1).sum())
    samples, normals = _resample(pts, 4.0)
    y_far, y_near = pts[:, 1].min(), pts[:, 1].max()
    near_part = samples[:, 1] >= y_far + STYLE_FAR_SKIP * (y_near - y_far)
    seen, gap = _paint_along(samples[near_part], normals[near_part], bright, visible)
    if seen >= STYLE_MIN_SAMPLES and gap >= DASH_GAP_MIN_SAMPLES:
        return "dashed"            # ngay trên đoạn YOLOP bắt được đã có khe
    k = max(2, len(pts) // 3)
    near_first = pts[0][1] >= pts[-1][1]   # đầu nào gần xe hơn (y lớn hơn)
    ext_ok = False
    for end, inner, is_near in ((pts[0], pts[k - 1], near_first), (pts[-1], pts[-k], not near_first)):
        if not is_near:
            continue          # chỉ kéo dài về phía gần xe
        d = end - inner
        n = np.linalg.norm(d)
        if n < 1e-6:
            continue
        d /= n
        ext = STYLE_EXTEND_NEAR * length
        ts = np.arange(4, ext, 4)
        if len(ts) == 0:
            continue
        e_samples = end + d[None, :] * ts[:, None]
        e_normals = np.repeat([[-d[1], d[0]]], len(ts), axis=0)
        e_seen, e_gap = _paint_along(e_samples, e_normals, bright, visible)
        if e_seen >= STYLE_MIN_SAMPLES // 2:
            if e_gap >= DASH_GAP_MIN_SAMPLES:
                return "dashed"    # đi tiếp theo hướng vạch thì hết sơn -> khe giữa 2 khúc nét đứt
            ext_ok = True
    if ext_ok or length >= 300:
        return "solid"
    return None


def _paint_along(samples, normals, bright, visible):
    """Trả về (số điểm mẫu nhìn thấy, khe dài nhất = số điểm nhìn thấy LIÊN TIẾP không có sơn)."""
    h, w = bright.shape
    seen = gap = longest = 0
    for (x, y), nv in zip(samples, normals):
        xi, yi = int(round(x)), int(round(y))
        if not (0 <= xi < w and 0 <= yi < h) or not visible[yi, xi]:
            continue
        r = max(2, int((PROFILE_BASE + PROFILE_PER_Y * y) / 2))   # chỉ sát tâm vạch
        t = np.arange(-r, r + 1)
        px = np.clip(np.round(x + t * nv[0]).astype(int), 0, w - 1)
        py = np.clip(np.round(y + t * nv[1]).astype(int), 0, h - 1)
        seen += 1
        gap = 0 if bright[py, px].any() else gap + 1
        longest = max(longest, gap)
    return seen, longest


def _gap_in_boxes(p, q, boxes):
    """Tỉ lệ đoạn thẳng p->q nằm trong các box xe (đoạn vạch bị xe che)."""
    if not boxes:
        return 0.0
    t = np.linspace(0, 1, 25)[:, None]
    pts = p + (q - p) * t
    inside = np.zeros(len(pts), bool)
    for x1, y1, x2, y2 in boxes:
        inside |= (pts[:, 0] >= x1 - 4) & (pts[:, 0] <= x2 + 4) & (pts[:, 1] >= y1 - 4) & (pts[:, 1] <= y2 + 4)
    return float(inside.mean())


def _runs(flags):
    """Các đoạn liên tiếp True: [(start, end)]."""
    f = np.concatenate([[0], flags.astype(np.int8), [0]])
    d = np.diff(f)
    return list(zip(np.where(d == 1)[0], np.where(d == -1)[0]))


def _dedupe_lines(found, shape):
    """Bỏ đường trùng lên đường khác (>= 70% điểm nằm sát đường dài hơn) — mỗi vạch chỉ 1 polyline."""
    found = sorted(found, key=lambda f: -f[2])
    kept = []
    for name, pts, length, style in found:
        samples, _ = _resample(pts, 4.0)
        xi = np.clip(samples[:, 0].round().astype(int), 0, shape[1] - 1)
        yi = np.clip(samples[:, 1].round().astype(int), 0, shape[0] - 1)
        dup = False
        for _, kpts, _, _ in kept:
            canvas = np.ones(shape, np.uint8)
            cv2.polylines(canvas, [np.round(kpts).astype(np.int32)], False, 0, 1)
            dist = cv2.distanceTransform(canvas, cv2.DIST_L2, 3)
            if (dist[yi, xi] <= DEDUPE_DIST).mean() >= 0.7:
                dup = True
                break
        if not dup:
            kept.append((name, pts, length, style))
    return [(n, p, st) for n, p, _, st in kept]
