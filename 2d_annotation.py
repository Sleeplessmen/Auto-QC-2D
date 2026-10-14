"""
Pre-annotate CVAT job đúng theo tài liệu AI20K:
  - Object instance  → Rectangle  : pedestrian, rider, car, truck, bus, train,
                                     motorcycle, bicycle, traffic light, traffic sign
  - Drivable area    → Polygon     : area/drivable, area/alternative
  - Lane marking     → Polyline    : lane/road curb, lane/crosswalk, lane/single white|yellow,
                                     lane/double white|yellow  (lane/single other: chỉ cảnh báo, vẽ tay)

Pipeline:
  1. YOLO phát hiện object instance → bounding box → Rectangle.
  2. SAM 2 nhận box YOLO làm prompt → trả mask → dùng để CHỈNH CHẶT bounding box
     (vẫn lưu dưới dạng Rectangle, không lưu polygon).
  3. SegFormer → Polygon area/drivable + area/alternative, Polyline lane/road curb.
  4. lane_markings.py → Polyline vạch sơn trên mặt đường (crosswalk, vạch đơn/đôi, trắng/vàng).

Cách dùng:
  python sam2_annotate.py --frame 50            # dry-run 1 frame
  python sam2_annotate.py --frame 50 --push     # đẩy 1 frame lên CVAT
  python sam2_annotate.py --all --push          # toàn bộ job
"""
import argparse
import json
import os
import sys

import cv2
import numpy as np
import torch
from dotenv import load_dotenv
from PIL import Image, ImageDraw

# Thêm thư mục gốc sam2 vào path (bản exe: checkpoints/ nằm cạnh file exe)
if getattr(sys, "frozen", False):
    APP_DIR = SAM2_ROOT = os.path.dirname(sys.executable)
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))
    SAM2_ROOT = os.path.dirname(APP_DIR)
if SAM2_ROOT not in sys.path:
    sys.path.insert(0, SAM2_ROOT)

from cvat_client import CvatClient
from detectors import (
    YOLO_LABEL_MAP, YOLO_PER_CLASS_MIN_CONF,
    SegformerSegmenter, DRIVABLE_LABEL, ALTERNATIVE_LABEL, CURB_LABEL
)
from lane_markings import LaneMarkingDetector, YolopLaneSegmenter, YOLOP_ONNX
from traffic_light import classify_light_color, find_color_attribute, pick_value
from drivable_area import build_road_mask, split_drivable, BLOCKING_LABELS, DIRECT, ALTERNATIVE
from label_mapping import resolve_drivable, resolve_lane

# -----------------------------------------------------------------------
# Cấu hình
# -----------------------------------------------------------------------
# Bản large bám mép vật thể tốt hơn hẳn bản tiny (đổi lại chạy chậm hơn)
SAM2_CHECKPOINT = os.path.join(SAM2_ROOT, "checkpoints", "sam2.1_hiera_large.pt")
SAM2_CONFIG     = "configs/sam2.1/sam2.1_hiera_l.yaml"

TRUNCATION_MARGIN_PX = 1.0
HOOD_RATIO           = 0.85    # che ~15% phần ca-pô cuối ảnh
YOLO_CONF            = 0.30
YOLO_MODEL           = os.path.join(APP_DIR, "yolov8x-seg.pt")  # bản x: box chuẩn hơn bản s
YOLO_IMGSZ           = 1280    # ảnh to hơn -> bắt được xe xa, đèn/biển báo nhỏ

# Kiểm soát chất lượng khi SAM 2 thu chặt box:
REFINE_MIN_IOU     = 0.60   # box SAM lệch quá xa box YOLO (IoU < mức này) -> SAM tách sai vật, giữ box YOLO
REFINE_MIN_SCORE   = 0.50   # SAM tự đánh giá mask kém -> giữ box YOLO
BOX_EXPAND_RATIO   = 0.15   # mask chỉ được phép vượt box YOLO tối đa 15% mỗi chiều (tránh lan sang xe bên cạnh)
MIN_COMPONENT_FRAC = 0.10   # bỏ mảnh mask nhỏ hơn 10% mảnh lớn nhất (đốm nhiễu làm box phình ra)

# Chống gán trùng: mỗi vật thể chỉ được 1 box
DUP_IOU         = 0.70   # 2 box (bất kể nhãn) trùng nhau quá mức này -> cùng 1 vật, giữ box điểm cao hơn
DUP_CONTAIN_SAME = 0.90  # box cùng nhãn nằm gần trọn trong box khác -> box thừa, bỏ


# -----------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------
def mask_hood(image: Image.Image) -> Image.Image:
    masked = image.copy()
    w, h = masked.size
    draw = ImageDraw.Draw(masked)
    draw.rectangle([0, int(h * HOOD_RATIO), w, h], fill=(128, 128, 128))
    return masked


def _is_truncated(box, img_w, img_h):
    xtl, ytl, xbr, ybr = box
    return (
        xtl <= TRUNCATION_MARGIN_PX or ytl <= TRUNCATION_MARGIN_PX
        or xbr >= img_w - TRUNCATION_MARGIN_PX
        or ybr >= img_h - TRUNCATION_MARGIN_PX
    )


def box_iou(a, b) -> float:
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def remove_duplicates(dets: list) -> tuple:
    """dets: list (cvat_name, box, score). Giữ box điểm cao nhất cho mỗi vật, bỏ box trùng/thừa.
    Trả về (dets_giữ_lại, số_box_bị_bỏ)."""
    kept = []
    for name, box, score in sorted(dets, key=lambda d: -d[2]):
        area = max(1e-6, (box[2] - box[0]) * (box[3] - box[1]))
        dup = False
        for k_name, k_box, _ in kept:
            if box_iou(box, k_box) >= DUP_IOU:
                dup = True
                break
            if k_name == name:
                ix = max(0.0, min(box[2], k_box[2]) - max(box[0], k_box[0]))
                iy = max(0.0, min(box[3], k_box[3]) - max(box[1], k_box[1]))
                k_area = max(1e-6, (k_box[2] - k_box[0]) * (k_box[3] - k_box[1]))
                if ix * iy / min(area, k_area) >= DUP_CONTAIN_SAME:
                    dup = True
                    break
        if not dup:
            kept.append((name, box, score))
    return kept, len(dets) - len(kept)


def clean_mask(mask_np: np.ndarray, prompt_box: list) -> np.ndarray:
    """Cắt mask trong vùng box nới rộng một chút, rồi bỏ các mảnh nhiễu nhỏ."""
    mask = (mask_np > 0).astype(np.uint8)
    h, w = mask.shape
    x1, y1, x2, y2 = prompt_box
    dx, dy = (x2 - x1) * BOX_EXPAND_RATIO, (y2 - y1) * BOX_EXPAND_RATIO
    limit = np.zeros_like(mask)
    limit[max(0, int(y1 - dy)):min(h, int(np.ceil(y2 + dy))),
          max(0, int(x1 - dx)):min(w, int(np.ceil(x2 + dx)))] = 1
    mask &= limit

    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    if n <= 2:
        return mask
    areas = stats[1:, cv2.CC_STAT_AREA]
    keep = [i + 1 for i, a in enumerate(areas) if a >= MIN_COMPONENT_FRAC * areas.max()]
    return np.isin(labels, keep).astype(np.uint8)


def tighten_box_from_mask(mask_np: np.ndarray, original_box: list, score: float = 1.0):
    """Dùng SAM 2 mask để chỉnh chặt bounding box. Trả về ([xtl,ytl,xbr,ybr], đã_chỉnh?).

    Nếu mask không đáng tin (điểm thấp, rỗng, hoặc lệch hẳn so với box gốc) thì giữ box gốc.
    """
    if score < REFINE_MIN_SCORE:
        return original_box, False
    mask = clean_mask(mask_np, original_box)
    ys, xs = np.where(mask > 0)
    if len(xs) == 0:
        return original_box, False
    # +1 vì box ôm trọn pixel cuối cùng (mép phải/dưới của pixel)
    tight = [float(xs.min()), float(ys.min()), float(xs.max() + 1), float(ys.max() + 1)]
    if box_iou(tight, original_box) < REFINE_MIN_IOU:
        return original_box, False
    return tight, True


LANE_PREVIEW_COLORS = {  # BGR
    "lane/road curb": (0, 0, 255),
    "lane/crosswalk": (0, 255, 0),
    "lane/single white": (255, 0, 255),
    "lane/double white": (255, 0, 0),
    "lane/single yellow": (0, 255, 255),
    "lane/double yellow": (0, 128, 255),
}


AREA_PREVIEW_COLORS = {DIRECT: (0, 0, 230), ALTERNATIVE: (230, 90, 0)}  # BGR — theo màu quen của BDD


def save_lane_preview(image: Image.Image, lane_lines: list, path: str, areas: list = ()):
    """Vẽ drivable area (đỏ = direct, xanh = alternative) + các polyline lane/* để duyệt nhanh trước khi push."""
    vis = cv2.cvtColor(np.asarray(image.convert("RGB")), cv2.COLOR_RGB2BGR)
    fill = vis.copy()
    for a in areas:
        if "area_type" not in a:
            continue
        p = np.round(np.array(a["points"]).reshape(-1, 2)).astype(np.int32)
        cv2.fillPoly(fill, [p], AREA_PREVIEW_COLORS[a["area_type"]])
    vis = cv2.addWeighted(fill, 0.35, vis, 0.65, 0)
    for a in areas:
        if "area_type" not in a:
            continue
        p = np.round(np.array(a["points"]).reshape(-1, 2)).astype(np.int32)
        cv2.polylines(vis, [p], True, AREA_PREVIEW_COLORS[a["area_type"]], 1)
        tag = a["area_type"] + (" (review)" if a.get("needs_review") else "")
        c = p.mean(axis=0).astype(int)
        cv2.putText(vis, tag, (int(c[0]) - 30, int(c[1])), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
    for entry in lane_lines:
        name, pts = entry[0], entry[1]
        p = np.round(np.array(pts).reshape(-1, 2)).astype(np.int32)
        color = LANE_PREVIEW_COLORS.get(name, (200, 200, 200))
        cv2.polylines(vis, [p], False, color, 3)
        cv2.putText(vis, name.split("/", 1)[1], tuple(int(v) for v in p[0]), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
    cv2.imwrite(path, vis)


# -----------------------------------------------------------------------
# SAM 2
# -----------------------------------------------------------------------
class Sam2Predictor:
    def __init__(self):
        from sam2.build_sam import build_sam2
        from sam2.sam2_image_predictor import SAM2ImagePredictor
        print("Đang tải SAM 2 model...")
        device = "cuda" if torch.cuda.is_available() else "cpu"
        sam_model = build_sam2(SAM2_CONFIG, SAM2_CHECKPOINT, device=device)
        self.predictor = SAM2ImagePredictor(sam_model)
        self.device = device
        self._image_id = None
        print(f"SAM 2 sẵn sàng trên {device.upper()}.")

    @torch.inference_mode()
    def _set_image(self, image: Image.Image):
        # Mã hoá ảnh là bước nặng nhất -> chỉ làm 1 lần mỗi frame, không làm lại cho từng box
        if self._image_id != id(image):
            self.predictor.set_image(np.array(image.convert("RGB")))
            self._image_id = id(image)

    @torch.inference_mode()
    def refine_boxes(self, image: Image.Image, boxes: list) -> list:
        """Thu chặt nhiều box cùng lúc. Trả về list (box, đã_chỉnh?) theo đúng thứ tự đầu vào."""
        if not boxes:
            return []
        self._set_image(image)
        masks, scores, _ = self.predictor.predict(
            point_coords=None,
            point_labels=None,
            box=np.array(boxes, dtype=np.float32),
            multimask_output=False,
        )
        h, w = masks.shape[-2:]
        masks = masks.reshape(len(boxes), -1, h, w)[:, 0]
        scores = np.asarray(scores).reshape(len(boxes), -1)[:, 0]
        return [tighten_box_from_mask(m, b, float(s)) for m, b, s in zip(masks, boxes, scores)]

    def get_tight_box(self, image: Image.Image, box_xyxy: list) -> list:
        """Thu chặt 1 bounding box về đúng mép vật thể. Trả về [xtl, ytl, xbr, ybr]."""
        return self.refine_boxes(image, [box_xyxy])[0][0]

    @torch.inference_mode()
    def get_polygon_from_points(self, image: Image.Image, points: list) -> list:
        """
        Dùng SAM 2 nhận point_coords để sinh mask, sau đó chuyển thành polygon (danh sách tọa độ 1D).
        points: list of [x, y].
        """
        self._set_image(image)
        pts_np = np.array(points, dtype=np.float32)
        labels_np = np.ones(len(points), dtype=np.int32) # Tất cả là positive points
        masks, scores, _ = self.predictor.predict(
            point_coords=pts_np[None],
            point_labels=labels_np[None],
            box=None,
            multimask_output=False,
        )
        if masks is None or len(masks) == 0:
            return []
        best = int(np.argmax(scores))
        mask = (masks[best] > 0).astype(np.uint8)
        
        # Chuyển mask thành polygon
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return []
        
        # Lấy contour lớn nhất
        cnt = max(contours, key=cv2.contourArea)
        epsilon = 0.005 * cv2.arcLength(cnt, True)
        approx = cv2.approxPolyDP(cnt, epsilon, True)
        if len(approx) < 3:
            return []
            
        flat = approx.reshape(-1, 2).astype(float).flatten().tolist()
        return flat


# -----------------------------------------------------------------------
# YOLO
# -----------------------------------------------------------------------
class SimpleYolo:
    def __init__(self):
        from ultralytics import YOLO
        self.model = YOLO(YOLO_MODEL)
        self.device = "cuda" if torch.cuda.is_available() else "cpu"

    def detect(self, image: Image.Image):
        # agnostic_nms: 1 xe không bị vẽ 2 box chồng nhau (vd vừa "car" vừa "truck")
        results = self.model.predict(
            image, conf=YOLO_CONF, imgsz=YOLO_IMGSZ, agnostic_nms=True,
            device=self.device, verbose=False,
        )[0]
        out = []
        for box in results.boxes:
            coco_name = self.model.names[int(box.cls[0])]
            cvat_name = YOLO_LABEL_MAP.get(coco_name)
            if cvat_name is None:
                continue
            score = float(box.conf[0])
            if score < YOLO_PER_CLASS_MIN_CONF.get(coco_name, 0.0):
                continue
            w, h = image.size
            xtl, ytl, xbr, ybr = box.xyxy[0].tolist()
            xtl, xbr = max(0.0, xtl), min(float(w), xbr)
            ytl, ybr = max(0.0, ytl), min(float(h), ybr)
            out.append((cvat_name, [xtl, ytl, xbr, ybr], score))
        return out


# -----------------------------------------------------------------------
# Build shapes — ĐÚNG theo tài liệu AI20K
# -----------------------------------------------------------------------
def build_shapes(
    frame_number: int,
    yolo_dets: list,      # (cvat_name, tight_box, score)
    seg_polys: list,      # dict(area_type=direct|alternative, points, needs_review) hoặc dict(label, points)
    lane_lines: list,     # (cvat_name, [x1,y1,...][, style, along]) — lane/* (road curb + vạch sơn)
    img_size: tuple,
    label_schema: dict,
    skipped: set,
    light_colors: list | None = None,   # màu đèn cho từng phần tử yolo_dets (None = không gán)
):
    img_w, img_h = img_size
    shapes = []

    # --- 1. Object instance → Rectangle (đúng tài liệu) ---
    for i, (cvat_name, box, score) in enumerate(yolo_dets):
        label = label_schema.get(cvat_name)
        if label is None:
            skipped.add(cvat_name)
            continue

        attributes = []
        trunc_id = label["attributes"].get("truncated")
        if trunc_id is not None:
            val = "true" if _is_truncated(box, img_w, img_h) else "false"
            attributes.append({"spec_id": trunc_id, "value": val})

        color = light_colors[i] if light_colors else None
        if color is not None:
            attr = find_color_attribute(label)
            if attr is None:
                skipped.add(f"{cvat_name}: task không có thuộc tính màu đèn (màu nhận được: {color})")
            else:
                spec_id, values = attr
                value = pick_value(values, color)
                if value is None:
                    skipped.add(f"{cvat_name}: thuộc tính màu không có giá trị cho '{color}' (các giá trị: {values})")
                else:
                    attributes.append({"spec_id": spec_id, "value": value})

        shapes.append({
            "type": "rectangle",          # ✅ Đúng tài liệu: Object instance = Rectangle
            "occluded": False,
            "z_order": i + 2,
            "points": box,                # [xtl, ytl, xbr, ybr]
            "frame": frame_number,
            "label_id": label["id"],
            "group": 0,
            "source": "manual",
            "attributes": attributes,
        })

    # --- 2. Drivable area → Polygon, mỗi làn 1 polygon (đúng tài liệu) ---
    for poly in seg_polys:
        if "area_type" in poly:
            label_id, attrs = resolve_drivable(label_schema, poly["area_type"], poly.get("needs_review", False))
            if label_id is None:
                skipped.add(f"drivable {poly['area_type']}: {attrs}")
                continue
        else:
            label = label_schema.get(poly["label"])
            if label is None:
                skipped.add(poly["label"])
                continue
            label_id, attrs = label["id"], []
        shapes.append({
            "type": "polygon",            # ✅ Đúng tài liệu: Drivable area = Polygon
            "occluded": False,
            "z_order": 1 if poly.get("area_type") == ALTERNATIVE else 0,
            "points": poly["points"],
            "frame": frame_number,
            "label_id": label_id,
            "group": 0,
            "source": "manual",
            "attributes": attrs,
        })

    # --- 3. Lane marking → Polyline (đúng tài liệu) ---
    for entry in lane_lines:
        cvat_name, pts = entry[0], entry[1]
        style, along = (entry[2], entry[3]) if len(entry) >= 4 else (None, None)
        label_id, attrs = resolve_lane(label_schema, cvat_name, style, along)
        if label_id is None:
            skipped.add(f"{cvat_name}: {attrs}")
            continue
        shapes.append({
            "type": "polyline",           # ✅ Đúng tài liệu: Lane marking = Polyline
            "occluded": False,
            "z_order": 0,
            "points": pts,
            "frame": frame_number,
            "label_id": label_id,
            "group": 0,
            "source": "manual",
            "attributes": attrs,
        })

    return shapes


# -----------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser()
    grp = parser.add_mutually_exclusive_group(required=True)
    grp.add_argument("--frame", type=int)
    grp.add_argument("--all", action="store_true")
    parser.add_argument("--push", action="store_true")
    parser.add_argument("--clear", action="store_true", help="Xóa sạch nhãn cũ trên CVAT trước khi push")
    parser.add_argument("--manual-only", action="store_true", help="Bỏ qua YOLO/Segformer, CHỈ gán nhãn bằng tọa độ thủ công")
    parser.add_argument("--out-dir", default="preview_sam2")
    parser.add_argument("--env", default=".env")
    parser.add_argument("--manual", default=None, help="Đường dẫn file JSON chứa tọa độ điểm/box thủ công cho SAM2")
    args = parser.parse_args()

    load_dotenv(args.env, override=True)
    cvat_url = os.environ["CVAT_URL"]
    token    = os.environ["CVAT_TOKEN"]
    task_id  = int(os.environ["CVAT_TASK_ID"])
    job_id   = int(os.environ["CVAT_JOB_ID"])

    client       = CvatClient(cvat_url, token)
    label_schema = client.get_label_schema(job_id)
    print(f"Task {task_id} / Job {job_id} — {len(label_schema)} nhãn")

    meta    = client.get_job_meta(job_id)
    start_f = meta["start_frame"]
    stop_f  = meta["stop_frame"]
    frames  = [args.frame] if args.frame is not None else list(range(start_f, stop_f + 1))
    print(f"Sẽ xử lý {len(frames)} frame ({start_f}→{stop_f}).\n")

    if args.push and args.clear:
        count = client.delete_all_annotations(job_id)
        print(f"Đã XÓA SẠCH {count} nhãn cũ trên CVAT (job {job_id}) để tránh bị đè nhãn.\n")

    print("Khởi tạo models...")
    yolo = SimpleYolo()
    sam2 = Sam2Predictor()
    seg  = SegformerSegmenter()
    lane = LaneMarkingDetector()
    yolop = YolopLaneSegmenter() if os.path.exists(YOLOP_ONNX) else None
    if yolop is None:
        print(f"⚠️  Không thấy {YOLOP_ONNX} — vạch kẻ đường chỉ dùng xử lý ảnh (kém chính xác hơn nhiều)")

    os.makedirs(args.out_dir, exist_ok=True)
    skipped = set()

    manual_data = {}
    if args.manual and os.path.exists(args.manual):
        with open(args.manual, "r", encoding="utf-8") as f:
            manual_data = json.load(f)
        print(f"Đã tải dữ liệu tọa độ thủ công từ: {args.manual}")

    for frame_number in frames:
        print(f"\n[frame {frame_number}] Tải ảnh...")
        image      = client.get_frame_image(job_id, frame_number)
        detect_img = mask_hood(image)
        img_w, img_h = image.size

        refined_dets = []
        seg_polys, lane_lines, seg_rects = [], [], []
        seg_mask = yolop_da = None

        if not args.manual_only:
            # YOLO detect
            print(f"[frame {frame_number}] YOLO: phát hiện vật thể...")
            raw_dets = yolo.detect(detect_img)
            print(f"[frame {frame_number}] YOLO: {len(raw_dets)} vật thể.")

            # SegFormer: area/drivable, area/alternative (Polygon) + lane/road curb (Polyline)
            print(f"[frame {frame_number}] SegFormer: phân vùng đường...")
            seg_mask = seg.segment(detect_img)
            _, lane_lines, seg_rects = seg.get_shapes(seg_mask, max_y=img_h * HOOD_RATIO)

            # Vạch kẻ đường + lề đường: YOLOP (train trên BDD100K) tìm vị trí, lane_markings phân loại.
            # Có YOLOP thì lề đường cũng lấy từ đó (lề đường suy từ biên SegFormer hay sai/sót).
            lane_mask = curb_side = None
            if yolop is not None:
                lane_mask, yolop_da = yolop.segment(detect_img)
                curb_side = np.isin(seg_mask, seg._curb_neighbor_ids)
                lane_lines = []
            paint_lines, lane_warns = lane.detect(
                detect_img, seg_mask == seg._road_id,
                exclude_boxes=[box for _, box, _ in raw_dets] + [box for _, box, _ in seg_rects],
                max_y=img_h * HOOD_RATIO, lane_mask=lane_mask, curb_side_mask=curb_side,
            )
            if lane.details:   # kèm nét liền/đứt + hướng để điền thuộc tính Style/Direction
                paint_lines = [(d["name"], d["pts"].astype(float).flatten().tolist(), d["style"], d["along"])
                               for d in lane.details]
            lane_lines.extend(paint_lines)
            counts = {}
            for entry in paint_lines:
                counts[entry[0]] = counts.get(entry[0], 0) + 1
            print(f"[frame {frame_number}] Vạch kẻ đường: {len(paint_lines)} polyline {counts}")
            for w in lane_warns:
                print(f"[frame {frame_number}] ⚠️  {w}")

            # SAM 2: chỉnh chặt bounding box cho mọi vật thể (cả rider từ SegFormer)
            all_dets = list(raw_dets) + list(seg_rects)
            print(f"[frame {frame_number}] SAM 2: tinh chỉnh {len(all_dets)} bounding box...")
            refined = sam2.refine_boxes(image, [box for _, box, _ in all_dets])
            not_tight = []
            for (cvat_name, _, score), (tight_box, changed) in zip(all_dets, refined):
                if not changed:
                    not_tight.append((cvat_name, [round(v) for v in tight_box]))
                # Kẹp trong biên ảnh
                tight_box = [
                    max(0.0, tight_box[0]), max(0.0, tight_box[1]),
                    min(float(img_w), tight_box[2]), min(float(img_h), tight_box[3])
                ]
                refined_dets.append((cvat_name, tight_box, score))
            for cvat_name, b in not_tight:
                print(f"[frame {frame_number}] ⚠️  CHƯA ôm sát (SAM không chắc, giữ box YOLO) — kiểm tra tay: {cvat_name} {b}")
        else:
            print(f"[frame {frame_number}] Chế độ Manual-Only: Bỏ qua YOLO và Segformer.")

        # --- ÁP DỤNG MANUAL PROMPTS NẾU CÓ ---
        frame_str = str(frame_number)
        if frame_str in manual_data:
            print(f"[frame {frame_number}] Áp dụng tọa độ thủ công từ {args.manual}...")
            for prompt in manual_data[frame_str]:
                lbl = prompt.get("label")
                if not lbl: continue
                if "box" in prompt:
                    tb = sam2.get_tight_box(image, prompt["box"])
                    tb = [max(0.0, tb[0]), max(0.0, tb[1]), min(float(img_w), tb[2]), min(float(img_h), tb[3])]
                    refined_dets.append((lbl, tb, 1.0))
                elif "points" in prompt:
                    poly = sam2.get_polygon_from_points(image, prompt["points"])
                    if poly:
                        if lbl.startswith("lane/"):
                            lane_lines.append((lbl, poly))
                        elif lbl in (DRIVABLE_LABEL, ALTERNATIVE_LABEL):
                            kind = DIRECT if lbl == DRIVABLE_LABEL else ALTERNATIVE
                            seg_polys.append(dict(area_type=kind, points=poly, needs_review=False))
                        else:
                            seg_polys.append(dict(label=lbl, points=poly))

        # Mỗi vật thể chỉ 1 box — bỏ box trùng/thừa (box thủ công score=1.0 được ưu tiên)
        refined_dets, n_dup = remove_duplicates(refined_dets)
        if n_dup:
            print(f"[frame {frame_number}] Bỏ {n_dup} box trùng lên cùng vật thể.")

        # Drivable area: mỗi làn 1 polygon, direct = làn đang đi, alternative = làn được phép chuyển sang
        if seg_mask is not None:
            max_y = img_h * HOOD_RATIO
            dets2 = [(n, b) for n, b, _ in refined_dets]
            road = build_road_mask(seg_mask == seg._road_id, yolop_da,
                                   [b for n, b in dets2 if n in BLOCKING_LABELS], max_y)
            areas = split_drivable(road, lane.details, dets2, max_y)
            seg_polys = areas + seg_polys
            for a in areas:
                flag = " ⚠️ needs_review" if a["needs_review"] else ""
                note = f" — {a['note']}" if a["note"] else ""
                print(f"[frame {frame_number}] Drivable {a['area_type']}: {len(a['points']) // 2} điểm{flag}{note}")

        # Màu đèn giao thông: đỏ / vàng / xanh / không sáng. Không chắc -> để trống, báo kiểm tra tay
        light_colors = []
        for cvat_name, box, _ in refined_dets:
            if cvat_name != "traffic light":
                light_colors.append(None)
                continue
            color, note = classify_light_color(image, box)
            light_colors.append(color)
            b = [round(v) for v in box]
            if color is None:
                print(f"[frame {frame_number}] ⚠️  Đèn giao thông {b}: chưa chắc màu ({note}) — gán màu tay")
            else:
                print(f"[frame {frame_number}] Đèn giao thông {b}: {color} ({note})")

        # Build shapes đúng theo tài liệu
        shapes = build_shapes(
            frame_number, refined_dets, seg_polys, lane_lines,
            (img_w, img_h), label_schema, skipped, light_colors
        )

        n_rect = sum(1 for s in shapes if s["type"] == "rectangle")
        n_poly = sum(1 for s in shapes if s["type"] == "polygon")
        n_line = sum(1 for s in shapes if s["type"] == "polyline")
        summary = f"Rectangle={n_rect} | Polygon={n_poly} | Polyline={n_line}"

        if args.push:
            if shapes:
                client.push_annotations(job_id, shapes)
            print(f"[frame {frame_number}] ✅ Đẩy {len(shapes)} shape ({summary}) lên CVAT.")
        else:
            out_path = os.path.join(args.out_dir, f"frame_{frame_number}.json")
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(shapes, f, ensure_ascii=False, indent=2)
            print(f"[frame {frame_number}] 💾 {len(shapes)} shape ({summary}) → {out_path} (dry-run)")
            vis_path = os.path.join(args.out_dir, f"frame_{frame_number}_lanes.jpg")
            save_lane_preview(image, lane_lines, vis_path, seg_polys)
            print(f"[frame {frame_number}] 🖼️  Ảnh xem trước vạch kẻ đường → {vis_path}")

    if skipped:
        print(f"\n⚠️  Nhãn bị bỏ qua: {sorted(skipped)}")

    print("\n✅ Hoàn tất! Annotation đúng theo tài liệu AI20K:")
    print("   Rectangle : car, truck, bus, pedestrian, rider, motorcycle, bicycle, traffic light, traffic sign, train")
    print("   Polygon   : area/drivable, area/alternative")
    print("   Polyline  : lane/road curb, lane/crosswalk, lane/single white/yellow, lane/double white/yellow")
    print("\n📝 Cần kiểm tra / vẽ tay thêm:")
    print("   Polyline  : lane/single other (chỉ in cảnh báo vị trí), vạch bị sót ở frame tối hoặc vạch mờ")


if __name__ == "__main__":
    main()
