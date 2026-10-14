import os
import json
import argparse
from dotenv import load_dotenv
from PIL import Image
import numpy as np
import torch
import cv2
import sys

# Thêm thư mục gốc sam2 vào path (bản exe: checkpoints/ nằm cạnh file exe)
SAM2_ROOT = (os.path.dirname(sys.executable) if getattr(sys, "frozen", False)
             else os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
if SAM2_ROOT not in sys.path:
    sys.path.insert(0, SAM2_ROOT)

from sam2.build_sam import build_sam2
from sam2.sam2_image_predictor import SAM2ImagePredictor
from sam2.automatic_mask_generator import SAM2AutomaticMaskGenerator
from ultralytics import YOLO
from transformers import SegformerForSemanticSegmentation, SegformerImageProcessor
from cvat_client import CvatClient

# -----------------------------------------------------------------------
# Cấu hình
# -----------------------------------------------------------------------
SAM2_CHECKPOINT = os.path.join(SAM2_ROOT, "checkpoints", "sam2.1_hiera_tiny.pt")
SAM2_CONFIG     = "configs/sam2.1/sam2.1_hiera_t.yaml"

STUFF_CLASSES = ["road", "sidewalk", "building", "wall", "fence", "pole", "vegetation", "terrain", "sky"]
THING_CLASSES = ["person", "rider", "car", "truck", "bus", "train", "motorcycle", "bicycle", "traffic light", "traffic sign"]

YOLO_MAP = {
    "person": "person",
    "bicycle": "bicycle",
    "car": "car",
    "motorcycle": "motorcycle",
    "bus": "bus",
    "truck": "truck",
    "train": "train",
    "traffic light": "traffic light",
    "stop sign": "traffic sign",
}

# Tạo từ điển gán ID nội bộ cho 19 class để đưa vào Master Mask
INTERNAL_ID2NAME = {i+1: name for i, name in enumerate(STUFF_CLASSES + THING_CLASSES)}
INTERNAL_NAME2ID = {name: i+1 for i, name in enumerate(STUFF_CLASSES + THING_CLASSES)}


def mask_to_cvat_rle(binary_mask: np.ndarray, bbox: tuple) -> list:
    """Encode 1 vùng mask nhị phân thành định dạng Mask (RLE) của CVAT.

    CVAT lưu points = [run-length..., left, top, right, bottom]: các run-length đếm số
    pixel liên tiếp cùng giá trị, duyệt hàng-trên-xuống-dưới trong đúng bbox, run đầu
    tiên LUÔN tính cho giá trị 0 (kể cả khi = 0, nếu mask bắt đầu bằng pixel thuộc vật).
    """
    xtl, ytl, xbr, ybr = bbox
    crop = binary_mask[ytl:ybr + 1, xtl:xbr + 1].astype(np.uint8)
    flat = crop.flatten(order="C")

    change_idx = np.flatnonzero(np.diff(flat)) + 1
    boundaries = np.concatenate(([0], change_idx, [flat.size]))
    run_lengths = np.diff(boundaries).tolist()
    if flat.size > 0 and flat[0] == 1:
        run_lengths = [0] + run_lengths  # run đầu luôn tính cho giá trị 0

    return run_lengths + [int(xtl), int(ytl), int(xbr), int(ybr)]

THIN_CLASSES = {"pole", "traffic light", "traffic sign"}
BIKE_CLASSES = {"motorcycle", "bicycle"}
VEHICLE_CLASSES = ["car", "truck", "bus", "train"]
SUPPORT_GROUPS = {
    "person": ["person", "rider"], "car": VEHICLE_CLASSES, "truck": VEHICLE_CLASSES,
    "bus": VEHICLE_CLASSES, "train": VEHICLE_CLASSES,
    "bicycle": ["bicycle", "motorcycle"], "motorcycle": ["bicycle", "motorcycle"],
}

# Nhiều thang đo + lật ngang cho SegFormer (TTA) -> biên nền ổn định hơn 1 lần chạy.
SEG_SCALES = [(768, 1376), (1024, 1824)]
MIN_REGION_CONF = 0.6  # vùng lớn có xác suất TB thấp hơn mức này -> để trống, đưa review

PALETTE = {
    "road": (128, 64, 128), "sidewalk": (244, 35, 232), "building": (70, 70, 70),
    "wall": (102, 102, 156), "fence": (190, 153, 153), "pole": (153, 153, 153),
    "traffic light": (250, 170, 30), "traffic sign": (220, 220, 0),
    "vegetation": (107, 142, 35), "terrain": (152, 251, 152), "sky": (70, 130, 180),
    "person": (220, 20, 60), "rider": (255, 0, 0), "car": (0, 0, 142),
    "truck": (0, 0, 70), "bus": (0, 60, 100), "train": (0, 80, 100),
    "motorcycle": (0, 0, 230), "bicycle": (119, 11, 32),
}


def area_scale(shape) -> float:
    """Hệ số theo độ phân giải ảnh (chuẩn 1280x720) để ngưỡng diện tích dùng được cho mọi cỡ ảnh."""
    return max(0.25, (shape[0] * shape[1]) / (1280.0 * 720.0))


def min_area_for(name: str, scale: float = 1.0) -> int:
    base = 60 if (name in THIN_CLASSES or name in THING_CLASSES) else 400
    return max(8, int(base * scale))


class SemanticMaster:
    def __init__(self, device="cuda" if torch.cuda.is_available() else "cpu"):
        self.device = device

        print("Đang tải YOLOv8-seg (phát hiện vật thể + mask sơ bộ)...")
        try:
            self.yolo = YOLO("yolov8x-seg.pt")
        except Exception as e:
            print(f"  (không tải được yolov8x-seg: {e}; dùng yolov8s-seg.pt)")
            self.yolo = YOLO("yolov8s-seg.pt")
        self.yolo.to(device)

        # GPU < 8GB (vd RTX 4050 6GB): SegFormer b5 fp32 dinh ~4.7GB -> tran bo nho, loi
        # CUBLAS_STATUS_EXECUTION_FAILED / crash. -> SegFormer fp16 + lo diem nho (dinh ~3.3GB).
        # GPU < 4GB moi phai dung SAM2 tiny.
        vram = torch.cuda.get_device_properties(0).total_memory if device == "cuda" else 0
        small_gpu = device == "cuda" and vram < 8 * 1024 ** 3
        tiny_gpu = device == "cuda" and vram < 4 * 1024 ** 3
        self.small_gpu = small_gpu
        large_ckpt = os.path.join(SAM2_ROOT, "checkpoints", "sam2.1_hiera_large.pt")
        if not tiny_gpu and os.path.exists(large_ckpt) and os.path.getsize(large_ckpt) > 800_000_000:
            ckpt, cfg = large_ckpt, "configs/sam2.1/sam2.1_hiera_l.yaml"
        else:
            ckpt, cfg = SAM2_CHECKPOINT, SAM2_CONFIG
        print(f"Đang tải SAM 2 ({os.path.basename(ckpt)})" + (" — GPU < 4GB, dùng bản nhẹ" if tiny_gpu else "") + "...")
        sam_model = build_sam2(cfg, ckpt, device=device)
        self.sam2 = SAM2ImagePredictor(sam_model)
        self.auto = SAM2AutomaticMaskGenerator(
            sam_model, points_per_side=24, points_per_batch=16 if small_gpu else 48,
            pred_iou_thresh=0.8, stability_score_thresh=0.88, box_nms_thresh=0.6)
        self.last_review = []

        print("Đang tải SegFormer (phân vùng phông nền)...")
        model_name = "nvidia/segformer-b5-finetuned-cityscapes-1024-1024"
        self.processor = SegformerImageProcessor.from_pretrained(model_name)
        self.segformer = SegformerForSemanticSegmentation.from_pretrained(model_name).to(device).eval()
        if self.small_gpu:   # fp16: dinh bo nho 4.7GB -> 2.4GB, ket qua giong fp32 ~99.8% pixel
            self.segformer.half()
        seg_name2idx = {v: k for k, v in self.segformer.config.id2label.items()}
        # perm[k] = chỉ số kênh SegFormer của class nội bộ (k+1)
        self.perm = [seg_name2idx[INTERNAL_ID2NAME[k + 1]] for k in range(len(INTERNAL_ID2NAME))]

    # ------------------------------------------------------------------
    def _segformer_probs(self, image: Image.Image) -> np.ndarray:
        """Xác suất từng class (thứ tự nội bộ), trung bình nhiều thang đo + lật ngang."""
        w, h = image.size
        acc, n = None, 0
        for sh, sw in SEG_SCALES:
            for flip in (False, True):
                img = image.transpose(Image.FLIP_LEFT_RIGHT) if flip else image
                inputs = self.processor(images=img, size={"height": sh, "width": sw},
                                        return_tensors="pt").to(self.device)
                # GPU < 8GB: model fp16 + cong don tren CPU de khong tran bo nho
                if self.small_gpu:
                    inputs["pixel_values"] = inputs["pixel_values"].half()
                with torch.no_grad():
                    logits = self.segformer(**inputs).logits.float()
                    logits = torch.nn.functional.interpolate(
                        logits, size=(h, w), mode="bilinear", align_corners=False)
                    p = logits.softmax(dim=1)[0]
                    if self.small_gpu:
                        p = p.cpu()
                    del logits
                if flip:
                    p = p.flip(-1)
                acc = p if acc is None else acc + p
                n += 1
        probs = (acc / n).cpu().numpy()
        if self.small_gpu:
            torch.cuda.empty_cache()
        return probs[self.perm]

    # ------------------------------------------------------------------
    def _refine(self, init: np.ndarray, box=None, guard_px=8, min_iou=0.6, neg_pts=None, penalty=None):
        """Tinh chỉnh viền 1 vùng bằng SAM 2 (box + điểm dương + mask gợi ý), có chặn tràn.

        Ứng viên: (a) SAM2 với mask_input, (b) 3 multimask. Chọn ứng viên khớp nhất với
        vùng ban đầu; luôn giới hạn trong vùng ban đầu nở `guard_px` để không bị tràn.
        Không ứng viên nào đạt `min_iou` -> giữ nguyên vùng ban đầu.
        """
        ys, xs = np.nonzero(init)
        if len(xs) == 0:
            return init
        h, w = init.shape
        if box is None:
            pad = 3
            box = [max(0, xs.min() - pad), max(0, ys.min() - pad),
                   min(w - 1, xs.max() + pad), min(h - 1, ys.max() + pad)]
        box = np.array(box, dtype=np.float32)

        dist = cv2.distanceTransform(init.astype(np.uint8), cv2.DIST_L2, 5)
        d = dist.copy()
        pts = []
        for _ in range(3):
            y, x = np.unravel_index(int(d.argmax()), d.shape)
            if d[y, x] < 1.5:
                break
            pts.append([x, y])
            cv2.circle(d, (int(x), int(y)), int(max(6, dist[y, x])), 0, -1)
        if not pts:
            i = len(xs) // 2
            pts = [[int(xs[i]), int(ys[i])]]
        lbl = np.ones(len(pts), dtype=np.int32)
        if neg_pts is not None and len(neg_pts) > 0:
            pts = pts + [list(p) for p in neg_pts]
            lbl = np.concatenate([lbl, np.zeros(len(neg_pts), dtype=np.int32)])
        pts = np.array(pts, dtype=np.float32)

        low = cv2.resize(init.astype(np.float32), (256, 256), interpolation=cv2.INTER_AREA)
        mask_input = ((low - 0.5) * 16.0)[None].astype(np.float32)

        cands = []
        m1, s1, _ = self.sam2.predict(point_coords=pts, point_labels=lbl, box=box[None],
                                      mask_input=mask_input, multimask_output=False)
        cands.append((m1[0] > 0, float(s1[0])))
        m2, s2, _ = self.sam2.predict(point_coords=pts, point_labels=lbl, box=box[None],
                                      multimask_output=True)
        for m, s in zip(m2, s2):
            cands.append((m > 0, float(s)))

        guard = cv2.dilate(init.astype(np.uint8),
                           cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * guard_px + 1,) * 2)).astype(bool)
        best, best_sc = None, -1.0
        for m, s in cands:
            m = m & guard
            union = int((m | init).sum())
            iou = int((m & init).sum()) / max(union, 1)
            sc = 0.6 * iou + 0.3 * s
            if penalty is not None and m.any():
                sc -= 0.8 * float((m & penalty).sum()) / float(m.sum())
            if iou >= min_iou and sc > best_sc:
                best, best_sc = m, sc
        return init if best is None else best

    @staticmethod
    def _sample_pts(mask, n):
        ys, xs = np.nonzero(mask)
        if len(xs) == 0:
            return []
        order = np.argsort(xs)
        idx = np.linspace(0, len(xs) - 1, min(n, len(xs))).astype(int)
        return [[int(xs[order[i]]), int(ys[order[i]])] for i in idx]

    @staticmethod
    def _grabcut_polish(image_bgr, mask, sure_bg, pad=12):
        """Bám mép theo màu sắc thật: GrabCut khởi tạo từ mask SAM (lõi = chắc chắn là vật,
        ngoài vòng nở = nền, cùng các pixel chắc chắn là đường/cột = nền). Chỉ nhận kết quả
        khi vẫn khớp mask SAM (IoU>=0.75), rồi giữ mảnh lớn nhất và lấp lỗ."""
        h, w = mask.shape
        ys, xs = np.nonzero(mask)
        if len(xs) < 200:
            return mask
        x0, x1 = max(0, xs.min() - pad), min(w, xs.max() + pad + 1)
        y0, y1 = max(0, ys.min() - pad), min(h, ys.max() + pad + 1)
        sub = np.ascontiguousarray(image_bgr[y0:y1, x0:x1])
        m = mask[y0:y1, x0:x1].astype(np.uint8)
        bw, bh = x1 - x0, y1 - y0
        r = max(2, int(0.06 * min(bw, bh)))
        core = cv2.erode(m, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1,) * 2))
        ring = cv2.dilate(m, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1,) * 2))
        gc = np.full(m.shape, cv2.GC_BGD, np.uint8)
        gc[ring > 0] = cv2.GC_PR_BGD
        gc[m > 0] = cv2.GC_PR_FGD
        gc[core > 0] = cv2.GC_FGD
        gc[(sure_bg[y0:y1, x0:x1]) & (core == 0)] = cv2.GC_BGD
        if (gc == cv2.GC_FGD).sum() < 50 or (gc == cv2.GC_BGD).sum() < 50:
            return mask
        try:
            bgd, fgd = np.zeros((1, 65)), np.zeros((1, 65))
            cv2.grabCut(sub, gc, None, bgd, fgd, 3, cv2.GC_INIT_WITH_MASK)
        except cv2.error:
            return mask
        res = ((gc == cv2.GC_FGD) | (gc == cv2.GC_PR_FGD)).astype(np.uint8)
        inter, union = int((res & m).sum()), int((res | m).sum())
        if union == 0 or inter / union < 0.75:
            return mask
        n, comp, stats, _ = cv2.connectedComponentsWithStats(res, connectivity=8)
        if n > 1:
            res = (comp == 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))).astype(np.uint8)
        inv = (1 - res).astype(np.uint8)
        n2, comp2, stats2, _ = cv2.connectedComponentsWithStats(inv, connectivity=4)
        for cid in range(1, n2):  # lấp lỗ nhỏ nằm hẳn trong vật (không chạm biên vùng cắt)
            x, y, ww, hh, a = stats2[cid]
            if a < 0.02 * res.sum() and x > 0 and y > 0 and x + ww < bw and y + hh < bh:
                res[comp2 == cid] = 1
        out = np.zeros_like(mask)
        out[y0:y1, x0:x1] = res.astype(bool)
        return out

    # ------------------------------------------------------------------
    def _ego_region(self, h, w, probs):
        """Vùng ca-pô/táp-lô của xe gắn camera: SAM 2 với điểm dương ở đáy ảnh, điểm âm trên mặt đường."""
        road = probs[INTERNAL_NAME2ID["road"] - 1]
        y0, y1 = int(0.4 * h), int(0.75 * h)
        smooth = cv2.GaussianBlur(road[y0:y1].astype(np.float32), (0, 0), 15)
        ny, nx = np.unravel_index(int(smooth.argmax()), smooth.shape)
        neg = [[nx, ny + y0]]
        pos = [[0.5 * w, 0.96 * h], [0.2 * w, 0.96 * h], [0.8 * w, 0.96 * h]]
        pts = np.array(pos + neg, dtype=np.float32)
        lbl = np.array([1, 1, 1, 0], dtype=np.int32)
        masks, scores, _ = self.sam2.predict(point_coords=pts, point_labels=lbl, multimask_output=True)
        best, best_sc = None, -1.0
        for m, s in zip(masks, scores):
            m = m > 0
            frac = m.mean()
            bottom = m[h - 20:h - 5].mean()
            top_row = np.nonzero(m.any(1))[0].min() if m.any() else h
            if 0.03 < frac < 0.4 and bottom > 0.6 and top_row > 0.4 * h and not m[neg[0][1], neg[0][0]] and s > best_sc:
                best, best_sc = m, float(s)
        if best is None:
            return None
        best = cv2.morphologyEx(best.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((25, 25), np.uint8))
        return cv2.dilate(best, np.ones((5, 5), np.uint8)).astype(bool)

    def _snap_to_segments(self, master, segs, trusted, probs, frac=0.85):
        """Bỏ phiếu theo segment SAM 2 (vùng có mép thật theo ảnh): trong mỗi segment, các pixel lẻ
        có độ tin cậy thấp được kéo về class chiếm đa số -> ranh giới đường/xe/dải phân cách
        bám mép thật thay vì theo dự đoán thô của SegFormer."""
        h, w = master.shape
        scale = area_scale(master.shape)
        thin_ids = [INTERNAL_NAME2ID[n] for n in THIN_CLASSES]
        protect = trusted | (master == 0) | np.isin(master, thin_ids)
        cur = np.take_along_axis(probs, np.maximum(master.astype(np.int64) - 1, 0)[None], axis=0)[0]
        weak = cur < 0.6
        out = master.copy()
        for s in sorted(segs, key=lambda s: -s["area"]):  # lớn trước, nhỏ (mịn hơn) ghi đè sau
            area = int(s["area"])
            if area < 200 * scale or area > 0.15 * h * w:
                continue
            seg = s["segmentation"]
            cnt = np.bincount(master[seg], minlength=len(INTERNAL_ID2NAME) + 1)
            top = int(cnt.argmax())
            if top == 0 or top in thin_ids or cnt[top] / max(area, 1) < frac:
                continue
            move = seg & (master != top) & ~protect & weak & (probs[top - 1] > 0.1)
            if move.any():
                out[move] = top
        return out

    def _carve_obstacles(self, master, probs, segs):
        """Khoét vật cản nằm trên mặt đường (cọc tiêu, bóng xe, người...) bằng các segment SAM 2:
        segment nằm chủ yếu trong vùng road nhưng SegFormer thấy KHÔNG giống đường -> để trống + review."""
        road_id = INTERNAL_NAME2ID["road"]
        road_mask = master == road_id
        if not road_mask.any():
            return master
        h, w = master.shape
        road_prob = probs[road_id - 1]
        out = master.copy()
        for s in segs:
            area = int(s["area"])
            if area < 150 * area_scale(master.shape) or area > 0.2 * h * w:
                continue
            seg = s["segmentation"]
            in_road = road_mask & seg
            if in_road.sum() < 0.5 * area:
                continue
            rp = float(road_prob[seg].mean())
            if rp >= 0.45:
                continue
            out[in_road] = 0
            ys, xs = np.nonzero(seg)
            self.last_review.append({"issue": "OBSTACLE_IN_ROAD", "area": int(in_road.sum()),
                                     "bbox": [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())],
                                     "road_prob": round(rp, 3)})
        return out

    def create_master_mask(self, image: Image.Image):
        self.last_review = []
        w, h = image.size
        probs = self._segformer_probs(image)          # (19, h, w)
        base = probs.argmax(0)
        score = probs.copy()

        self.sam2.set_image(np.array(image))

        # --- 1) SAM 2 tinh chỉnh biên các vùng SegFormer (nền + vật) ---
        for k in range(len(INTERNAL_ID2NAME)):
            name = INTERNAL_ID2NAME[k + 1]
            thin = name in THIN_CLASSES
            binary = (base == k).astype(np.uint8)
            if not binary.any():
                continue
            n, comp, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
            order = sorted(range(1, n), key=lambda i: -stats[i, cv2.CC_STAT_AREA])[:40]
            for cid in order:
                if stats[cid, cv2.CC_STAT_AREA] < (30 if thin else 300):
                    continue
                cm = comp == cid
                refined = self._refine(cm, guard_px=3 if thin else 8, min_iou=0.5 if thin else 0.85)
                score[k][refined] += 0.5
                score[k][cm & ~refined] -= 0.5

        # --- 2) Vật thể: YOLO-seg (mask sơ bộ) + SAM 2 (viền chính xác) ---
        res = self.yolo.predict(image, conf=0.2, iou=0.5, agnostic_nms=True, device=self.device,
                                  retina_masks=True, verbose=False)[0]
        dets = []
        if res.masks is not None:
            for i, box in enumerate(res.boxes):
                cvat_name = YOLO_MAP.get(self.yolo.names[int(box.cls[0])])
                if cvat_name is None:
                    continue
                m = res.masks.data[i].cpu().numpy() > 0.5
                if m.shape != (h, w):
                    m = cv2.resize(m.astype(np.uint8), (w, h), interpolation=cv2.INTER_NEAREST).astype(bool)
                x0, y0, x1, y1 = box.xyxy[0].tolist()
                conf = float(box.conf[0])
                if conf < 0.4:
                    # Bắt thêm ứng viên tin cậy thấp, nhưng chỉ nhận khi SegFormer cũng thấy đúng nhóm class đó
                    group = SUPPORT_GROUPS.get(cvat_name, [cvat_name])
                    support = sum(float(probs[INTERNAL_NAME2ID[g] - 1][m].mean()) for g in group) if m.any() else 0.0
                    if support < 0.35:
                        continue
                dets.append({"name": cvat_name, "box": [x0, y0, x1, y1], "init": m, "conf": conf})

        trusted = np.zeros((h, w), dtype=bool)
        image_bgr = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)
        road_p = probs[INTERNAL_NAME2ID["road"] - 1]
        pole_p = probs[INTERNAL_NAME2ID["pole"] - 1]
        bike_boxes = [d["box"] for d in dets if d["name"] in BIKE_CLASSES]
        rider_k = INTERNAL_NAME2ID["rider"] - 1
        dets.sort(key=lambda d: d["box"][3])  # đáy box thấp (gần camera) -> vẽ sau, đè lên
        for rank, d in enumerate(dets):
            if not d["init"].any():
                continue
            init = d["init"]
            ring = cv2.dilate(init.astype(np.uint8), np.ones((21, 21), np.uint8)).astype(bool) & ~init
            bx0, by0, bx1, by1 = (int(v) for v in d["box"])
            in_box = np.zeros_like(init)
            in_box[max(0, by0):by1 + 1, max(0, bx0):bx1 + 1] = True
            neg = self._sample_pts(ring & (road_p > 0.8), 6) + self._sample_pts(in_box & (pole_p > 0.6), 3)
            bw_, bh_ = d["box"][2] - d["box"][0], d["box"][3] - d["box"][1]
            padv = 0.06 * max(bw_, bh_)
            sam_box = [max(0, d["box"][0] - padv), max(0, d["box"][1] - padv),
                       min(w - 1, d["box"][2] + padv), min(h - 1, d["box"][3] + padv)]
            refined = self._refine(init, box=sam_box, guard_px=6, min_iou=0.6,
                                   neg_pts=neg, penalty=(road_p > 0.6) | (pole_p > 0.5))
            # Bóng đổ/mặt đường dưới gầm xe, cột điện đứng trước xe: bỏ các pixel SegFormer chắc chắn là đường/cột
            trimmed = refined & ~((road_p > 0.7) | (pole_p > 0.6))
            if trimmed.sum() >= 0.6 * refined.sum():
                refined = trimmed
            refined = self._grabcut_polish(image_bgr, refined, (road_p > 0.85) | (pole_p > 0.6))
            name = d["name"]
            if name == "person":
                x0, y0, x1, y1 = d["box"]
                area = max((x1 - x0) * (y1 - y0), 1.0)
                on_bike = any(
                    max(0.0, min(x1, bx1) - max(x0, bx0)) * max(0.0, min(y1, by1) - max(y0, by0)) / area > 0.25
                    for bx0, by0, bx1, by1 in bike_boxes
                )
                seg_rider = (base[refined] == rider_k).mean() > 0.3 if refined.any() else False
                if on_bike or seg_rider:
                    name = "rider"
            if name in VEHICLE_CLASSES and refined.any():
                # car/truck/bus/train: kết hợp YOLO với SegFormer (phân loại đúng chuẩn Cityscapes)
                vs = {v: float(probs[INTERNAL_NAME2ID[v] - 1][refined].mean()) for v in VEHICLE_CLASSES}
                vs[name] += 0.5 * d["conf"]
                name = max(vs, key=vs.get)
            k = INTERNAL_NAME2ID[name] - 1
            score[k][refined] += 1.0 + 0.001 * rank
            trusted |= refined

        master = (score.argmax(0) + 1).astype(np.uint8)
        ego = self._ego_region(h, w, probs)
        if ego is not None:
            master[ego] = 0
        segs = self.auto.generate(np.array(image))
        master = self._snap_to_segments(master, segs, trusted, probs)
        master = self._carve_obstacles(master, probs, segs)
        master = self._fill_small(master, score)
        master = self._smooth_boundaries(master)
        return self._drop_uncertain(master, probs, trusted)

    @staticmethod
    def _smooth_boundaries(master, sigma=1.5):
        """Bo tròn/khử răng cưa biên giữa các class bằng làm mượt one-hot rồi argmax:
        mỗi pixel vẫn chỉ thuộc đúng 1 class (không chồng lấn, không lỗ), biên vẫn bám vật thể."""
        best_val = np.full(master.shape, -1.0, dtype=np.float32)
        out = master.copy()
        for uid in np.unique(master):
            g = cv2.GaussianBlur((master == uid).astype(np.float32), (0, 0), sigma)
            upd = g > best_val
            best_val[upd] = g[upd]
            out[upd] = uid
        return out

    def _drop_uncertain(self, master, probs, trusted):
        """Vùng có độ tin cậy trung bình thấp -> để trống + ghi review (không đoán bừa)."""
        conf = np.take_along_axis(probs, (master.astype(np.int64) - 1)[None], axis=0)[0]
        out = master.copy()
        for uid in np.unique(master):
            if uid == 0:
                continue
            name = INTERNAL_ID2NAME[int(uid)]
            n, comp, stats, _ = cv2.connectedComponentsWithStats(
                (master == uid).astype(np.uint8), connectivity=8)
            for cid in range(1, n):
                area = int(stats[cid, cv2.CC_STAT_AREA])
                is_mobile_thing = name in THING_CLASSES and name not in THIN_CLASSES
                if area < int((60 if is_mobile_thing else 1500) * area_scale(master.shape)):
                    continue
                region = comp == cid
                if trusted[region].mean() > 0.5:
                    continue
                mean_conf = float(conf[region].mean())
                if mean_conf < MIN_REGION_CONF:
                    out[region] = 0
                    x, y, bw, bh = (int(stats[cid, i]) for i in (0, 1, 2, 3))
                    self.last_review.append({"issue": "UNCERTAIN_CLASS", "class": name, "area": area,
                                             "bbox": [x, y, x + bw, y + bh], "mean_conf": round(mean_conf, 3)})
        return out

    # ------------------------------------------------------------------
    @staticmethod
    def _fill_small(master: np.ndarray, score: np.ndarray) -> np.ndarray:
        """Làm sạch vùng vụn mà không sinh đường biên thẳng/chéo giả:
        - mảng quá nhỏ (nhiễu) -> class tốt thứ hai theo điểm số tại chính pixel đó;
        - "đảo" nền nhỏ bị bao kín bởi 1 class khác (vd. mảng sidewalk giữa mặt đường) -> nhập vào class bao quanh."""
        h, w = master.shape
        scale = area_scale(master.shape)
        island_limit = 0.004 * h * w
        out = master.copy()
        for uid in np.unique(master):
            if uid == 0:
                continue
            name = INTERNAL_ID2NAME[int(uid)]
            is_stuff = name in STUFF_CLASSES and name not in THIN_CLASSES
            limit = min_area_for(name, scale)
            n, comp, stats, _ = cv2.connectedComponentsWithStats(
                (master == uid).astype(np.uint8), connectivity=8)
            for cid in range(1, n):
                x, y, bw, bh, area = (int(v) for v in stats[cid])
                x0, y0, x1, y1 = max(0, x - 3), max(0, y - 3), min(w, x + bw + 3), min(h, y + bh + 3)
                reg = comp[y0:y1, x0:x1] == cid
                if area >= limit:
                    if is_stuff and area < island_limit:
                        ring = cv2.dilate(reg.astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool) & ~reg
                        labs = master[y0:y1, x0:x1][ring]
                        if labs.size:
                            cnt = np.bincount(labs, minlength=len(INTERNAL_ID2NAME) + 1)
                            top = int(cnt.argmax())
                            if top not in (0, int(uid)) and cnt[top] / labs.size >= 0.9:
                                out[y0:y1, x0:x1][reg] = top
                    continue
                ys, xs = np.nonzero(reg)
                ys, xs = ys + y0, xs + x0
                sub = score[:, ys, xs].copy()
                sub[int(uid) - 1] = -np.inf
                out[ys, xs] = sub.argmax(0) + 1
        return out

    def save_overlay(self, image: Image.Image, master_mask: np.ndarray, path: str):
        color = np.zeros((*master_mask.shape, 3), dtype=np.uint8)
        for uid in np.unique(master_mask):
            if uid == 0:
                continue
            color[master_mask == uid] = PALETTE[INTERNAL_ID2NAME[int(uid)]]
        blend = (0.5 * np.array(image) + 0.5 * color).astype(np.uint8)
        Image.fromarray(blend).save(path)


    def extract_masks(self, master_mask, label_schema, frame_number):
        """Trích Mask (RLE) đúng chuẩn CVAT cho từng class, theo guideline (Mask mặc định
        cho toàn bộ 19 class, không dùng Rectangle/Polygon)."""
        shapes = []
        skipped = set()

        unique_ids = np.unique(master_mask)
        for uid in unique_ids:
            if uid == 0:
                continue  # Background
            name = INTERNAL_ID2NAME[uid]
            label = label_schema.get(name)
            if label is None:
                skipped.add(name)
                continue

            binary = (master_mask == uid).astype(np.uint8)

            # Tách các vùng rời rạc của cùng 1 class thành từng shape riêng
            num_components, components = cv2.connectedComponents(binary, connectivity=8)
            for comp_id in range(1, num_components):
                comp_mask = (components == comp_id).astype(np.uint8)
                area = int(comp_mask.sum())
                min_area = min_area_for(name, area_scale(master_mask.shape))
                if area < min_area:
                    continue

                ys, xs = np.where(comp_mask == 1)
                bbox = (int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max()))
                rle = mask_to_cvat_rle(comp_mask, bbox)

                shapes.append({
                    "type": "mask",
                    "occluded": False,
                    "z_order": 0,  # Tất cả bằng 0 vì đã non-overlap sẵn (như xếp hình)
                    "points": rle,
                    "frame": frame_number,
                    "label_id": label["id"],
                    "group": 0,
                    "source": "manual",
                    "attributes": [],
                })

        return shapes, skipped

def main():
    parser = argparse.ArgumentParser()
    grp = parser.add_mutually_exclusive_group(required=True)
    grp.add_argument("--frame", type=int)
    grp.add_argument("--all", action="store_true")
    parser.add_argument("--push", action="store_true")
    parser.add_argument("--replace", action="store_true",
                         help="Trước khi push, xoá các shape thuộc 19 class do script này quản lý "
                              "tại đúng frame đang xử lý (tránh chồng lấn với lần chạy trước, "
                              "không đụng tới annotation khác như lane/area do người vẽ tay).")
    parser.add_argument("--replace-all", action="store_true",
                         help="Giống --replace nhưng xoá TOÀN BỘ shape (mọi label) tại đúng frame "
                              "đang xử lý, kể cả annotation vẽ tay trước đó ở frame đó.")
    parser.add_argument("--hood-ratio", type=float, default=0.0,
                         help="Tỉ lệ chiều cao (0-1) từ đó trở xuống là ca-pô/táp-lô xe của camera; "
                              "vùng này để trống. Mặc định 0 = tự tìm ca-pô bằng SAM 2.")
    parser.add_argument("--env", default=".env")
    args = parser.parse_args()

    load_dotenv(args.env, override=True)
    cvat_url = os.environ["CVAT_URL"]
    token    = os.environ["CVAT_TOKEN"]
    task_id  = int(os.environ["CVAT_TASK_ID"])
    job_id   = int(os.environ["CVAT_JOB_ID"])

    client = CvatClient(cvat_url, token)
    label_schema = client.get_label_schema(job_id)
    print(f"Task {task_id} / Job {job_id} — {len(label_schema)} nhãn")

    meta = client.get_job_meta(job_id)
    start_f = meta["start_frame"]
    stop_f  = meta["stop_frame"]
    frames = [args.frame] if args.frame is not None else list(range(start_f, stop_f + 1))
    print(f"Sẽ xử lý {len(frames)} frame ({start_f}→{stop_f}).\n")

    annotator = SemanticMaster()
    
    for frame_number in frames:
        print(f"\n[frame {frame_number}] Tải ảnh...")
        image = client.get_frame_image(job_id, frame_number)

        print(f"[frame {frame_number}] Tạo Master Mask bằng SAM 2 và SegFormer...")
        master_mask = annotator.create_master_mask(image)
        if args.hood_ratio > 0:
            master_mask[int(master_mask.shape[0] * args.hood_ratio):, :] = 0
        os.makedirs("preview_sam2", exist_ok=True)
        with open(f"preview_sam2/review_frame_{frame_number}.json", "w", encoding="utf-8") as fh:
            json.dump(annotator.last_review, fh, ensure_ascii=False, indent=1)
        if annotator.last_review:
            print(f"[frame {frame_number}] ⚠️  {len(annotator.last_review)} vùng không chắc -> để trống, xem review_frame_{frame_number}.json")
        annotator.save_overlay(image, master_mask, f"preview_sam2/overlay_frame_{frame_number}.jpg")

        print(f"[frame {frame_number}] Trích xuất Mask không chồng lấn...")
        shapes, skipped = annotator.extract_masks(master_mask, label_schema, frame_number)
        print(f"[frame {frame_number}] → {len(shapes)} mask sẵn sàng.")

        if args.push:
            if args.replace_all:
                existing = client.get_shapes_for_frame(job_id, frame_number)
                if existing:
                    client.delete_shapes(job_id, existing)
                    print(f"[frame {frame_number}] 🗑️  Đã xoá TOÀN BỘ {len(existing)} shape cũ tại frame này.")
            elif args.replace:
                managed_label_ids = {label_schema[n]["id"] for n in INTERNAL_NAME2ID if n in label_schema}
                existing = client.get_shapes_for_frame(job_id, frame_number)
                to_delete = [s for s in existing if s.get("label_id") in managed_label_ids]
                if to_delete:
                    client.delete_shapes(job_id, to_delete)
                    print(f"[frame {frame_number}] 🗑️  Đã xoá {len(to_delete)} shape cũ (19 class quản lý bởi script).")

            if shapes:
                client.push_annotations(job_id, shapes)
            print(f"[frame {frame_number}] ✅ Đẩy {len(shapes)} MASK lên CVAT.")

        if skipped:
            print(f"⚠️  Bỏ qua các nhãn không có trong hệ thống: {skipped}")

    print("\n✅ Hoàn tất Semantic Segmentation với SAM 2 (Non-overlapping)!")

if __name__ == "__main__":
    main()
