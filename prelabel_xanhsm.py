import argparse
import os
import cv2
import numpy as np
from dotenv import load_dotenv
from ultralytics import YOLO
from cvat_client import CvatClient


def is_green_sm(image, box):
    """
    Phân biệt xe Xanh SM dựa trên màu Cyan đặc trưng (xanh ngọc / xanh mòng két).
    image: numpy array (RGB)
    box: [xtl, ytl, xbr, ybr]
    Trả về True nếu vùng xe chứa đủ màu Cyan đặc trưng của xe Xanh SM.
    """
    xtl, ytl, xbr, ybr = [int(v) for v in box]
    crop = image[max(0, ytl):min(image.shape[0], ybr), max(0, xtl):min(image.shape[1], xbr)]
    if crop.size == 0 or crop.shape[0] < 4 or crop.shape[1] < 4:
        return False

    crop_bgr = cv2.cvtColor(crop, cv2.COLOR_RGB2BGR)
    hsv = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2HSV)

    # --- Dải màu Cyan đặc trưng Xanh SM (xanh ngọc/mòng két) ---
    # Hue 80-105: xanh cyan thuần (ban ngày tốt)
    # Saturation >= 80: phải đủ bão hòa, loại bỏ màu xám / trắng / trời xanh nhạt
    # Value >= 50: không phải vùng tối hoàn toàn
    lower_cyan = np.array([80, 80, 50])
    upper_cyan = np.array([105, 255, 255])
    mask_day = cv2.inRange(hsv, lower_cyan, upper_cyan)

    # Ban đêm / đèn vàng làm xe ngả xanh lục hơn (Hue thấp xuống 65-80)
    # Cần Saturation cao hơn (>= 100) để tránh nhầm với cây cối / tường xanh
    lower_night = np.array([65, 100, 50])
    upper_night = np.array([80, 255, 200])
    mask_night = cv2.inRange(hsv, lower_night, upper_night)

    # Loại màu xanh dương đậm (Mazda, taxi...) — Hue 105-130 bị lọc bỏ
    # Loại màu xanh lá đậm (VinFast xanh lá, xe buýt) — Hue < 65 bị lọc bỏ

    mask = cv2.bitwise_or(mask_day, mask_night)
    total_pixels = mask.shape[0] * mask.shape[1]
    cyan_ratio = np.sum(mask > 0) / total_pixels

    # Ngưỡng 8%: đủ nghiêm để loại xe khác màu, đủ rộng để nhận xe bị che 1 phần
    # Xe Xanh SM thường có phần thân rất rõ màu → tỷ lệ thực tế 15-40%
    # Xe xanh dương/lá hãng khác thường < 5% trong dải Cyan này
    return cyan_ratio > 0.08


def nms_boxes(boxes, iou_thresh=0.5):
    """
    Non-Maximum Suppression: loại bỏ các hộp trùng lặp trên cùng một xe.
    boxes: list [xtl, ytl, xbr, ybr, score]
    """
    if not boxes:
        return []
    boxes = sorted(boxes, key=lambda x: x[4], reverse=True)
    keep = []
    used = [False] * len(boxes)
    for i in range(len(boxes)):
        if used[i]:
            continue
        keep.append(boxes[i])
        ax1, ay1, ax2, ay2 = boxes[i][:4]
        for j in range(i + 1, len(boxes)):
            if used[j]:
                continue
            bx1, by1, bx2, by2 = boxes[j][:4]
            ix1, iy1 = max(ax1, bx1), max(ay1, by1)
            ix2, iy2 = min(ax2, bx2), min(ay2, by2)
            iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
            inter = iw * ih
            area_a = max(1, (ax2 - ax1) * (ay2 - ay1))
            area_b = max(1, (bx2 - bx1) * (by2 - by1))
            iou = inter / (area_a + area_b - inter)
            if iou >= iou_thresh:
                used[j] = True
    return keep


def detect_occlusion(box, all_boxes, img_w, img_h, edge_margin=3, overlap_thresh=0.15):
    """
    Tự động phát hiện xe bị che khuất (occluded) — tương đương nhấn Q trong CVAT.
    Trả về True nếu xe bị che, False nếu không.

    Hai trường hợp bị coi là occluded:
    1. Hộp chạm sát mép ảnh (xe bị cắt khỏi khung hình — truncated).
    2. Hộp bị một hộp khác đè chồng lên đáng kể (xe bị xe/vật khác che khuất).
    """
    xtl, ytl, xbr, ybr = box

    # Trường hợp 1: xe bị cắt ở mép ảnh
    if xtl <= edge_margin or ytl <= edge_margin or xbr >= img_w - edge_margin or ybr >= img_h - edge_margin:
        return True

    # Trường hợp 2: xe bị hộp khác đè chồng lên
    area_self = max(1, (xbr - xtl) * (ybr - ytl))
    for other in all_boxes:
        if other is box:
            continue
        ox1, oy1, ox2, oy2 = other[:4]
        ix1, iy1 = max(xtl, ox1), max(ytl, oy1)
        ix2, iy2 = min(xbr, ox2), min(ybr, oy2)
        inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
        # Tỷ lệ phần diện tích của xe bị hộp khác che
        if inter / area_self >= overlap_thresh:
            return True

    return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", default=".env", help="File cấu hình (.env)")
    parser.add_argument("--out-dir", default="labels_xanhsm", help="Thư mục xuất nhãn YOLO")
    parser.add_argument("--push", action="store_true", help="Đẩy nhãn lên CVAT")
    parser.add_argument("--clear-first", action="store_true",
                        help="Xóa toàn bộ nhãn AUTO cũ trong job trước khi đẩy nhãn mới (tránh trùng hộp)")
    args = parser.parse_args()

    load_dotenv(args.env, override=True)

    cvat_url = os.environ["CVAT_URL"]
    token = os.environ["CVAT_TOKEN"]
    task_id = int(os.environ["CVAT_TASK_ID"])
    job_id = int(os.environ["CVAT_JOB_ID"])

    client = CvatClient(cvat_url, token)
    meta = client.get_job_meta(job_id)
    start_frame, stop_frame = meta["start_frame"], meta["stop_frame"]

    label_schema = client.get_label_schema(job_id)
    print(f"Nhãn trong task: {sorted(label_schema.keys())}")

    green_sm_label_id = None
    for name, info in label_schema.items():
        nl = name.lower()
        if "greensm" in nl or "green sm" in nl or "xanh sm" in nl or "xanh_sm" in nl:
            green_sm_label_id = info["id"]
            print(f"  → Tìm thấy nhãn GreenSM: '{name}' (id={green_sm_label_id})")
            break

    if green_sm_label_id is None and label_schema:
        first_name = list(label_schema.keys())[0]
        green_sm_label_id = label_schema[first_name]["id"]
        print(f"  → Không tìm thấy nhãn GreenSM, dùng nhãn đầu tiên: '{first_name}' (id={green_sm_label_id})")

    # Xóa nhãn AUTO cũ trước khi đẩy lại để tránh hộp trùng nhau
    if args.push and args.clear_first:
        print(f"\nĐang xóa toàn bộ nhãn AUTO cũ trong job {job_id}...")
        deleted = client.delete_auto_annotations(job_id)
        print(f"✓ Đã xóa {deleted} nhãn AUTO cũ.\n")

    os.makedirs(args.out_dir, exist_ok=True)

    model_path = "yolov8x-seg.pt" if os.path.exists("yolov8x-seg.pt") else "yolov8s-seg.pt"
    print(f"Sử dụng model: {model_path}")
    model = YOLO(model_path)

    print(f"Xử lý job {job_id} (frame {start_frame}-{stop_frame})...")

    for frame_idx in range(start_frame, stop_frame + 1):
        image_pil = client.get_frame_image(job_id, frame_idx)
        w, h = image_pil.size
        img_np = np.array(image_pil)

        results = model(img_np, conf=0.2, verbose=False)[0]

        candidates = []
        for box in results.boxes:
            cls_id = int(box.cls[0])
            name = model.names[cls_id]
            # Chỉ xét ô tô, xe tải, xe buýt — bỏ qua motorcycle, bicycle, person...
            if name not in ["car", "truck", "bus"]:
                continue

            xtl, ytl, xbr, ybr = box.xyxy[0].tolist()
            score = float(box.conf[0])

            # Quy tắc 5: chiều cao tối thiểu 12px
            if (ybr - ytl) < 12:
                continue

            # Chỉ giữ xe CÓ màu Cyan đặc trưng (phân biệt Xanh SM với xe hãng khác)
            if not is_green_sm(img_np, [xtl, ytl, xbr, ybr]):
                continue

            candidates.append([xtl, ytl, xbr, ybr, score])

        # NMS: loại bỏ hộp trùng lặp trên cùng một xe (tránh 2 hộp chồng lên 1 chiếc)
        kept = nms_boxes(candidates, iou_thresh=0.5)

        boxes_yolo = []
        cvat_shapes = []
        n_occluded = 0
        for item in kept:
            xtl, ytl, xbr, ybr, score = item
            cx = ((xtl + xbr) / 2) / w
            cy = ((ytl + ybr) / 2) / h
            bw = (xbr - xtl) / w
            bh = (ybr - ytl) / h
            boxes_yolo.append(f"0 {cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f}")

            # Tự động đánh dấu occluded (tương đương nhấn Q trong CVAT)
            occluded = detect_occlusion([xtl, ytl, xbr, ybr], kept, w, h)
            if occluded:
                n_occluded += 1

            if args.push:
                cvat_shapes.append({
                    "type": "rectangle",
                    "occluded": occluded,
                    "z_order": 0,
                    "points": [xtl, ytl, xbr, ybr],
                    "frame": frame_idx,
                    "label_id": green_sm_label_id,
                    "group": 0,
                    "source": "auto",
                    "attributes": [],
                })

        # Ảnh không có xe Xanh SM vẫn tạo file rỗng (theo quy tắc guideline)
        txt_path = os.path.join(args.out_dir, f"frame_{frame_idx:06d}.txt")
        with open(txt_path, "w") as f:
            if boxes_yolo:
                f.write("\n".join(boxes_yolo) + "\n")

        if args.push and cvat_shapes:
            client.push_annotations(job_id, cvat_shapes)
            occ_note = f", {n_occluded} bị che (occluded)" if n_occluded else ""
            print(f"[Frame {frame_idx}] ✓ Đẩy {len(cvat_shapes)} xe Xanh SM lên CVAT{occ_note}.")
        elif args.push:
            print(f"[Frame {frame_idx}] – Không có xe Xanh SM.")
        else:
            occ_note = f", {n_occluded} bị che" if n_occluded else ""
            print(f"[Frame {frame_idx}] {len(boxes_yolo)} xe Xanh SM{occ_note} → {txt_path}")

    print("\nHoàn tất! Các file nhãn YOLO được lưu tại thư mục:", args.out_dir)


if __name__ == "__main__":
    main()
