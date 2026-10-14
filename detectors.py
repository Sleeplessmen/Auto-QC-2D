"""Hai model pretrained dùng để pre-annotate, CHỈ cho đúng các nhãn:
- Object instance (Rectangle): pedestrian, rider, car, truck, bus, train, motorcycle,
  bicycle, traffic light, traffic sign.
- Drivable area (Polygon): area/drivable, area/alternative — suy ra từ lớp "road" của
  Cityscapes bằng heuristic (mảng road chạm đáy ảnh, gần xe -> drivable; mảng road tách
  biệt, xa xe hơn -> alternative). Đây là suy luận, KHÔNG chính xác 100%, cần duyệt lại tay.
- Lane marking (Polyline): chỉ "lane/road curb" được suy ra bằng heuristic (biên giữa lớp
  "road" và "sidewalk" của Cityscapes). Các nhãn lane/* còn lại (crosswalk, single/double
  white/yellow) do lane_markings.py tìm bằng xử lý ảnh trong vùng road.

- YOLOv8 (ultralytics, train trên COCO) -> Rectangle cho vật thể rời rạc.
- SegFormer (HuggingFace, fine-tune trên Cityscapes) -> Polygon vùng đường, Polyline lề
  đường, và Rectangle cho "rider".
"""
import cv2
import numpy as np
import torch

# COCO class name -> tên nhãn CVAT. Theo tài liệu "Bounding Box, Polygon & Polyline",
# nhóm Object instance (Rectangle) dùng tên có DẤU CÁCH: "traffic light", "traffic sign".
YOLO_LABEL_MAP = {
    # Nhóm người
    "person": "pedestrian",

    # Nhóm xe 2 bánh
    "bicycle": "two-wheels",
    "motorcycle": "two-wheels",

    # Nhóm xe lớn
    "car": "vehicles",
    "bus": "vehicles",
    "truck": "vehicles",
    "train": "vehicles",

    # Nhóm động vật
    "bird": "Animal",
    "cat": "Animal",
    "dog": "Animal",
    "horse": "Animal",
    "sheep": "Animal",
    "cow": "Animal",
    "elephant": "Animal",
    "bear": "Animal",
    "zebra": "Animal",
    "giraffe": "Animal",

    # Nhóm vật cản
    "traffic light": "Obstacle",
    "stop sign": "Obstacle",
    "fire hydrant": "Obstacle",
}

# Nhãn Drivable area suy ra từ lớp "road" của Cityscapes (xử lý riêng trong _extract_road_polygons,
# không dùng vòng lặp SEGFORMER_POLYGON_MAP chung).
DRIVABLE_LABEL = "area/drivable"
ALTERNATIVE_LABEL = "area/alternative"

# Nhãn lane/road curb suy ra từ biên giữa lớp "road" và "sidewalk" (xử lý riêng trong
# _extract_curb_polylines).
CURB_LABEL = "lane/road curb"

# Các lớp Cityscapes cần vẽ Rectangle (nhóm Object instance): chỉ "rider" — YOLO không có
# class tương ứng trong COCO. Các class Object instance còn lại đã do YOLO_LABEL_MAP đảm nhận.
SEGFORMER_RECTANGLE_MAP = {
    "rider": "rider",
}

# LƯU Ý: các nhãn lane/* còn lại (crosswalk, double/single white/yellow) KHÔNG có trong tập lớp
# Cityscapes -> do lane_markings.py tìm riêng bằng xử lý ảnh.

# Bài trên lớp (task 5): nhãn CVAT trùng tên thẳng với lớp Cityscapes -> lấy nguyên polygon,
# không cần suy luận heuristic như area/drivable. Nếu job không có các nhãn này trong Labels,
# build_shapes ở auto_annotate.py sẽ tự bỏ qua (không ảnh hưởng job bài về nhà).
SEGFORMER_DIRECT_POLYGON_CLASSES = {}

MIN_POLYGON_AREA = 600  # px^2 — lọc bớt mảnh vụn nhiễu của segmentation, tránh vẽ hàng chục polygon rác
MAX_POLYGONS_PER_CLASS = 12  # chỉ giữ N mảnh lớn nhất mỗi lớp, tránh rối mắt vì quá nhiều mảnh nhỏ
MORPH_KERNEL = np.ones((7, 7), np.uint8)  # làm mượt biên mask trước khi tách polygon
POLYGON_GROW_PX = 2  # nới rộng thêm vài pixel để lấp khe hở nhỏ ở biên vùng road

# area/drivable vs area/alternative: mảng "road" nào có điểm thấp nhất (gần đáy ảnh, gần xe)
# lệch không quá mức này so với mảng road chạm đáy xa nhất -> coi là cùng làn chính (drivable).
# Mảng road tách biệt, ở xa hơn (vd làn ngược chiều bị chia cách) -> alternative.
DRIVABLE_BOTTOM_TOLERANCE_PX = 40

# lane/road curb: đoạn biên của mặt đường giáp vỉa hè / bãi cỏ / đất / cây (SegFormer hay xếp lề cỏ
# vào "terrain", "vegetation" chứ không phải "sidewalk"). Biên giáp xe, nhà, hàng rào, trời... KHÔNG phải lề.
CURB_NEIGHBOR_CLASSES = ("sidewalk", "terrain", "vegetation")
# Coi 1 đoạn biên là 1 polyline nếu có ít nhất chừng này điểm liên tiếp giáp các lớp trên (lọc đoạn ngắn/nhiễu).
CURB_MIN_RUN_LEN = 40
CURB_BORDER_MARGIN = 3  # px — biên road chạy dọc mép ảnh là do ảnh bị cắt, không phải lề đường
CURB_APPROX_EPS = 3.0  # px — sai số làm mượt polyline lề đường

# Ngưỡng riêng cho từng lớp rectangle từ segmentation (vật càng mảnh thì diện tích tối thiểu càng nhỏ,
# nhưng phải bù bằng điều kiện tỉ lệ khung hình để không lẫn với nhiễu)
RECT_RULES = {
    "rider": dict(min_area=300, min_height=15, min_hw_ratio=0.0),
}
CONNECT_KERNEL = {}
RECT_IOU_MERGE = 0.15  # 2 box cùng lớp overlap hơn mức này -> gộp làm 1 (tránh vẽ trùng nhiều box lên 1 cột)

# YOLO hay nhận nhầm cọc tiêu cam thành biển "stop sign" ở ngưỡng tin cậy thấp -> nâng riêng ngưỡng này lên.
YOLO_PER_CLASS_MIN_CONF = {"stop sign": 0.6}


def _iou(a, b):
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
    inter = iw * ih
    if inter == 0:
        return 0.0
    area_a = (ax2 - ax1) * (ay2 - ay1)
    area_b = (bx2 - bx1) * (by2 - by1)
    return inter / min(area_a, area_b)  # so với box NHỎ HƠN, để bắt cả trường hợp 1 box nằm lọt trong box kia


def _merge_overlapping_boxes(boxes, iou_thresh=RECT_IOU_MERGE):
    """boxes: list [xtl,ytl,xbr,ybr]. Gộp các box overlap nhiều thành 1 box bao trùm, tránh vẽ trùng lặp."""
    merged = []
    used = [False] * len(boxes)
    for i in range(len(boxes)):
        if used[i]:
            continue
        cur = list(boxes[i])
        used[i] = True
        changed = True
        while changed:
            changed = False
            for j in range(len(boxes)):
                if used[j]:
                    continue
                if _iou(cur, boxes[j]) >= iou_thresh:
                    cur = [min(cur[0], boxes[j][0]), min(cur[1], boxes[j][1]),
                           max(cur[2], boxes[j][2]), max(cur[3], boxes[j][3])]
                    used[j] = True
                    changed = True
        merged.append(cur)
    return merged


class YoloDetector:
    def __init__(self, model_name: str = "yolov8s-seg.pt", device: str | None = None):
        from ultralytics import YOLO
        self.model = YOLO(model_name)
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")

    def detect(self, image, conf: float = 0.3):
        """image: PIL.Image. Trả về list (cvat_label_name, [xtl, ytl, xbr, ybr], score, polygon)."""
        results = self.model.predict(image, conf=conf, device=self.device, verbose=False)[0]
        out = []
        for i, box in enumerate(results.boxes):
            coco_name = self.model.names[int(box.cls[0])]
            cvat_name = YOLO_LABEL_MAP.get(coco_name)
            if cvat_name is None:
                continue
            score = float(box.conf[0])
            if score < YOLO_PER_CLASS_MIN_CONF.get(coco_name, 0.0):
                continue
            xtl, ytl, xbr, ybr = box.xyxy[0].tolist()
            # Kẹp toạ độ trong biên ảnh — box không được vượt ra ngoài ảnh
            w, h = image.size
            xtl, xbr = max(0.0, xtl), min(float(w), xbr)
            ytl, ybr = max(0.0, ytl), min(float(h), ybr)
            polygons = []
            if results.masks is not None:
                mask = results.masks[i]
                for segment in mask.xy:
                    if len(segment) >= 3:
                        poly = []
                        for pt in segment:
                            poly.extend([
                                max(0.0, min(float(w), float(pt[0]))),
                                max(0.0, min(float(h), float(pt[1])))
                            ])
                        polygons.append(poly)
                            
            out.append((cvat_name, [xtl, ytl, xbr, ybr], score, polygons))
        return out


class SegformerSegmenter:
    def __init__(self, model_name: str = "nvidia/segformer-b5-finetuned-cityscapes-1024-1024", device: str | None = None):
        from transformers import SegformerForSemanticSegmentation, SegformerImageProcessor
        self.processor = SegformerImageProcessor.from_pretrained(model_name)
        self.model = SegformerForSemanticSegmentation.from_pretrained(model_name)
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.model.to(self.device).eval()
        self.id2label = self.model.config.id2label
        self._road_id = next((cid for cid, n in self.id2label.items() if n == "road"), None)
        self._curb_neighbor_ids = [int(cid) for cid, n in self.id2label.items() if n in CURB_NEIGHBOR_CLASSES]

    @torch.no_grad()
    def segment(self, image):
        """image: PIL.Image. Trả về mảng numpy (H, W) chỉ số lớp, đã resize về đúng kích thước ảnh gốc."""
        inputs = self.processor(images=image, return_tensors="pt").to(self.device)
        outputs = self.model(**inputs)
        logits = outputs.logits
        upsampled = torch.nn.functional.interpolate(
            logits, size=image.size[::-1], mode="bilinear", align_corners=False
        )
        return upsampled.argmax(dim=1)[0].cpu().numpy()

    def get_shapes(self, seg_mask: np.ndarray, max_y: float | None = None):
        """Trả về tuple: (polys, lines, rects).
        polys: (cvat_name, [x1,y1,x2,y2,...]) — area/drivable, area/alternative.
        lines: (cvat_name, [x1,y1,x2,y2,...]) — lane/road curb (bỏ phần từ dòng max_y trở xuống: ca-pô).
        rects: (cvat_name, [xtl,ytl,xbr,ybr], score) — rider.
        """
        polys, lines, rects = [], [], []
        if self._road_id is not None:
            polys.extend(self._extract_road_polygons(seg_mask))
            if self._curb_neighbor_ids:
                lines.extend(self._extract_curb_polylines(seg_mask, max_y))
        for class_id, name in self.id2label.items():
            if name in SEGFORMER_RECTANGLE_MAP:
                cvat_name = SEGFORMER_RECTANGLE_MAP[name]
                rects.extend(self._extract_rects(seg_mask, int(class_id), cvat_name))
            if name in SEGFORMER_DIRECT_POLYGON_CLASSES:
                cvat_name = SEGFORMER_DIRECT_POLYGON_CLASSES[name]
                polys.extend(self._extract_class_polygons(seg_mask, int(class_id), cvat_name))
        return polys, lines, rects

    def _extract_class_polygons(self, seg_mask, class_id, cvat_name):
        """Trích polygon trực tiếp từ 1 lớp Cityscapes, không suy luận gì thêm (dùng cho
        các nhãn CVAT trùng tên thẳng với lớp, vd road/sidewalk/building/vegetation/sky)."""
        mask = (seg_mask == class_id).astype(np.uint8)
        if mask.sum() == 0:
            return []
            
        # Điều chỉnh tham số cho các nhãn mảnh/nhỏ (pole, traffic sign)
        if cvat_name == "pole":
            min_area = 50
            max_polys = 50
            # Chỉ close nhẹ để nối đứt gãy, không open để tránh mất nét mảnh
            kernel = np.ones((3, 3), np.uint8)
            mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
        elif cvat_name == "traffic sign":
            min_area = 100
            max_polys = 20
            kernel = np.ones((3, 3), np.uint8)
            mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
        elif cvat_name == "road":
            min_area = MIN_POLYGON_AREA
            max_polys = MAX_POLYGONS_PER_CLASS
            mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, MORPH_KERNEL)
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, MORPH_KERNEL)
            mask = cv2.dilate(mask, np.ones((5, 5), np.uint8)) # Nới rộng mặt đường để chui xuống dưới vỉa hè
        else:
            min_area = MIN_POLYGON_AREA
            max_polys = MAX_POLYGONS_PER_CLASS
            mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, MORPH_KERNEL)
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, MORPH_KERNEL)

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        contours = [c for c in contours if cv2.contourArea(c) >= min_area]
        contours = sorted(contours, key=cv2.contourArea, reverse=True)[:max_polys]

        out = []
        for cnt in contours:
            epsilon = 0.01 * cv2.arcLength(cnt, True)
            approx = cv2.approxPolyDP(cnt, epsilon, True)
            if len(approx) < 3:
                continue
            points = approx.reshape(-1, 2).astype(float).flatten().tolist()
            out.append((cvat_name, points))
        return out

    def _extract_road_polygons(self, seg_mask):
        """area/drivable: mảng road chạm đáy ảnh gần xe nhất. area/alternative: mảng road
        tách biệt, ở xa hơn (heuristic, không phân biệt hoàn toàn chính xác)."""
        mask = (seg_mask == self._road_id).astype(np.uint8)
        if mask.sum() == 0:
            return []
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, MORPH_KERNEL)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, MORPH_KERNEL)

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        contours = [c for c in contours if cv2.contourArea(c) >= MIN_POLYGON_AREA]
        if not contours:
            return []
        max_bottom_y = max(c[:, 0, 1].max() for c in contours)
        contours = sorted(contours, key=cv2.contourArea, reverse=True)[:MAX_POLYGONS_PER_CLASS]

        out = []
        for cnt in contours:
            cvat_name = (
                DRIVABLE_LABEL
                if cnt[:, 0, 1].max() >= max_bottom_y - DRIVABLE_BOTTOM_TOLERANCE_PX
                else ALTERNATIVE_LABEL
            )
            epsilon = 0.01 * cv2.arcLength(cnt, True)
            approx = cv2.approxPolyDP(cnt, epsilon, True)
            if len(approx) < 3:
                continue
            points = approx.reshape(-1, 2).astype(float).flatten().tolist()
            out.append((cvat_name, points))
        return out

    def _extract_curb_polylines(self, seg_mask, max_y=None):
        """lane/road curb: đoạn biên của mảng "road" tiếp giáp vỉa hè / cỏ / đất / cây."""
        mask_road = (seg_mask == self._road_id).astype(np.uint8)
        mask_side = np.isin(seg_mask, self._curb_neighbor_ids).astype(np.uint8)
        if mask_road.sum() == 0 or mask_side.sum() == 0:
            return []
        mask_road = cv2.morphologyEx(mask_road, cv2.MORPH_CLOSE, MORPH_KERNEL)
        sidewalk_near = cv2.dilate(mask_side, np.ones((9, 9), np.uint8))
        h, w = seg_mask.shape
        m = CURB_BORDER_MARGIN

        contours, _ = cv2.findContours(mask_road, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        out = []
        for cnt in contours:
            if cv2.contourArea(cnt) < MIN_POLYGON_AREA:
                continue
            pts = cnt.reshape(-1, 2)
            near_sidewalk = sidewalk_near[pts[:, 1], pts[:, 0]] > 0
            near_sidewalk &= (pts[:, 0] >= m) & (pts[:, 0] < w - m) & (pts[:, 1] >= m) & (pts[:, 1] < h - m)
            if max_y is not None:
                near_sidewalk &= pts[:, 1] < max_y

            runs, start = [], None
            for i, flag in enumerate(near_sidewalk):
                if flag and start is None:
                    start = i
                elif not flag and start is not None:
                    runs.append((start, i))
                    start = None
            if start is not None:
                runs.append((start, len(near_sidewalk)))

            for s, e in runs:
                if e - s < CURB_MIN_RUN_LEN:
                    continue
                seg_pts = pts[s:e].reshape(-1, 1, 2)
                simplified = cv2.approxPolyDP(seg_pts, CURB_APPROX_EPS, False)
                flat = simplified.reshape(-1, 2).astype(float).flatten().tolist()
                if len(flat) >= 4:  # ít nhất 2 điểm
                    out.append((CURB_LABEL, flat))
        return out

    def _extract_rects(self, seg_mask, class_id, cvat_name):
        mask = (seg_mask == class_id).astype(np.uint8)
        if mask.sum() == 0:
            return []
        # Nối liền các đoạn bị đứt quãng (vd cột điện bị dây điện/vật khác che cắt thành nhiều khúc)
        if cvat_name in CONNECT_KERNEL:
            mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, CONNECT_KERNEL[cvat_name])

        rule = RECT_RULES[cvat_name]
        num_labels, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)

        boxes = []
        for i in range(1, num_labels):  # bỏ qua label 0 (background)
            x, y, w, h, area = stats[i]
            if area < rule["min_area"] or h < rule["min_height"]:
                continue
            if rule["min_hw_ratio"] > 0 and (h / max(w, 1)) < rule["min_hw_ratio"]:
                continue
            boxes.append([float(x), float(y), float(x + w), float(y + h)])

        # Gộp các box chồng lấn nhiều (vd 2 khúc của cùng 1 cột dính sát nhau) -> tránh vẽ trùng
        boxes = _merge_overlapping_boxes(boxes)
        return [(cvat_name, box, 1.0) for box in boxes]
