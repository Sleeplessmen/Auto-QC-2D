"""
Pre-annotate ảnh trong 1 job CVAT bằng YOLOv8 (rectangle) + SegFormer-Cityscapes (polygon).

Cách dùng:
  python auto_annotate.py --frame 50            # xử lý thử 1 frame, chỉ ghi ra JSON (mặc định)
  python auto_annotate.py --frame 50 --push      # xử lý 1 frame RỒI đẩy thẳng lên CVAT
  python auto_annotate.py --all --push           # xử lý toàn bộ frame trong job và đẩy lên

Annotation cũ trong job KHÔNG bị xoá (dùng action=create), nhưng có thể trùng lặp với
nhãn bạn đã vẽ tay -> sau khi push, luôn mở CVAT kiểm tra & xoá bớt shape bị trùng/sai.
"""
import argparse
import json
import os

from dotenv import load_dotenv
from PIL import ImageDraw

from cvat_client import CvatClient
from detectors import YoloDetector, SegformerSegmenter


TRUNCATION_MARGIN_PX = 1.0  # box cách biên ảnh <= mức này -> coi là bị cắt (truncated)

# Camera dashcam cố định -> phần ca-pô/kính xe luôn nằm ở đáy ảnh (ước lượng ~20% chiều cao).
# Che vùng này trước khi đưa vào model để tránh nhận nhầm phản chiếu trên ca-pô thành "car"/"road".
HOOD_RATIO = 1.0


def mask_hood(image):
    """Trả về bản sao ảnh với dải ca-pô ở đáy được tô xám phẳng, để model không quét nhầm vùng đó."""
    masked = image.copy()
    w, h = masked.size
    draw = ImageDraw.Draw(masked)
    draw.rectangle([0, int(h * HOOD_RATIO), w, h], fill=(128, 128, 128))
    return masked


def _is_truncated(box, img_w, img_h):
    xtl, ytl, xbr, ybr = box
    return (
        xtl <= TRUNCATION_MARGIN_PX or ytl <= TRUNCATION_MARGIN_PX
        or xbr >= img_w - TRUNCATION_MARGIN_PX or ybr >= img_h - TRUNCATION_MARGIN_PX
    )


def build_shapes(frame_number, yolo_dets, seg_polys, seg_lines, seg_rects, img_size, label_schema, skipped):
    img_w, img_h = img_size
    shapes = []
    
    # YOLO objects - sắp xếp theo đáy ybr tăng dần để gán z_order
    yolo_dets_sorted = sorted(yolo_dets, key=lambda x: x[1][3])
    group_id_counter = 1
    
    for i, (name, box, score, polygons) in enumerate(yolo_dets_sorted):
        label = label_schema.get(name)
        if label is None:
            skipped.add(name)
            continue
        
        z_order = i + 2  # Đáy thấp (ybr cao) -> vẽ sau -> đè lên trên (z_order cao). Bắt đầu từ 2 để nhường 0, 1 cho road/sidewalk
        
        attributes = []
        truncated_spec_id = label["attributes"].get("truncated")
        if truncated_spec_id is not None:
            value = "true" if _is_truncated(box, img_w, img_h) else "false"
            attributes.append({"spec_id": truncated_spec_id, "value": value})
        shapes.append({
            "type": "rectangle",
            "occluded": False,
            "z_order": z_order,
            "points": box,
            "frame": frame_number,
            "label_id": label["id"],
            "group": 0,
            "source": "manual",
            "attributes": attributes,
        })
            
    # SegFormer rider rectangles
    for name, box, score in seg_rects:
        label = label_schema.get(name)
        if label is None:
            skipped.add(name)
            continue
        attributes = []
        truncated_spec_id = label["attributes"].get("truncated")
        if truncated_spec_id is not None:
            value = "true" if _is_truncated(box, img_w, img_h) else "false"
            attributes.append({"spec_id": truncated_spec_id, "value": value})
        shapes.append({
            "type": "rectangle",
            "occluded": False,
            "z_order": 0,
            "points": box,
            "frame": frame_number,
            "label_id": label["id"],
            "group": 0,
            "source": "manual",
            "attributes": attributes,
        })
    for name, points in seg_polys:
        label = label_schema.get(name)
        if label is None:
            skipped.add(name)
            continue
            
        # Gán z_order=1 cho sidewalk để nằm đè lên road (z_order=0)
        z_order = 1 if name == "sidewalk" else 0
        
        shapes.append({
            "type": "polygon",
            "occluded": False,
            "z_order": z_order,
            "points": points,
            "frame": frame_number,
            "label_id": label["id"],
            "group": 0,
            "source": "manual",
            "attributes": [],
        })
    for name, points in seg_lines:
        label = label_schema.get(name)
        if label is None:
            skipped.add(name)
            continue
        shapes.append({
            "type": "polyline",
            "occluded": False,
            "z_order": 0,
            "points": points,
            "frame": frame_number,
            "label_id": label["id"],
            "group": 0,
            "source": "manual",
            "attributes": [],
        })
    return shapes


def main():
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--frame", type=int, help="Xử lý 1 frame duy nhất (số thứ tự trong job)")
    group.add_argument("--all", action="store_true", help="Xử lý toàn bộ frame trong job")
    group.add_argument("--clear-auto", action="store_true", help="Chỉ xoá annotation AUTO trong job hiện tại (CVAT_JOB_ID)")
    group.add_argument("--clear-auto-all", action="store_true", help="Xoá annotation AUTO trong TẤT CẢ job của task (CVAT_TASK_ID)")
    group.add_argument("--clear-all", action="store_true", help="Xoá TOÀN BỘ annotation (manual + auto) trong job hiện tại (CVAT_JOB_ID) — KHÔNG thể hoàn tác")
    parser.add_argument("--push", action="store_true", help="Đẩy kết quả lên CVAT (mặc định chỉ dry-run)")
    parser.add_argument("--out-dir", default="preview", help="Thư mục lưu JSON preview khi dry-run")
    parser.add_argument("--env", default=".env", help="File cấu hình để dùng (mặc định .env, vd .env.class cho bài trên lớp)")
    args = parser.parse_args()

    load_dotenv(args.env, override=True)

    cvat_url = os.environ["CVAT_URL"]
    token = os.environ["CVAT_TOKEN"]
    task_id = int(os.environ["CVAT_TASK_ID"])
    job_id = int(os.environ["CVAT_JOB_ID"])

    client = CvatClient(cvat_url, token)
    label_schema = client.get_label_schema(job_id)
    print(f"Task {task_id} / Job {job_id} có {len(label_schema)} nhãn: {sorted(label_schema)}")

    # --- Xoá AUTO trong job hiện tại ---
    if args.clear_auto:
        print(f"Xoá annotation AUTO trong job {job_id}...")
        deleted = client.delete_auto_annotations(job_id)
        print(f"✓ Đã xoá {deleted} shape AUTO khỏi job {job_id}.")
        return

    # --- Xoá TOÀN BỘ annotation (manual + auto) trong job hiện tại ---
    if args.clear_all:
        print(f"Xoá TOÀN BỘ annotation trong job {job_id}...")
        deleted = client.delete_all_annotations(job_id)
        print(f"✓ Đã xoá {deleted} shape khỏi job {job_id}.")
        return

    # --- Xoá AUTO/SEMI-AUTO trong TẤT CẢ jobs ---
    if args.clear_auto_all:
        print("Lấy danh sách tất cả jobs...")
        all_jobs = client.get_all_jobs()
        print(f"Tìm thấy {len(all_jobs)} job: {all_jobs}")
        total_deleted = 0
        for jid in all_jobs:
            n = client.delete_auto_annotations(jid)
            total_deleted += n
            print(f"  Job {jid}: xoá {n} shape AUTO/SEMI-AUTO")
        print(f"✓ Hoàn tất! Tổng đã xoá {total_deleted} shape trên {len(all_jobs)} job.")
        return

    meta = client.get_job_meta(job_id)
    start_frame, stop_frame = meta["start_frame"], meta["stop_frame"]
    frames = [args.frame] if args.frame is not None else list(range(start_frame, stop_frame + 1))
    print(f"Job {job_id}: frame {start_frame}-{stop_frame} ({meta['size']} ảnh), sẽ xử lý {len(frames)} frame.")

    yolo = YoloDetector()
    seg = SegformerSegmenter()

    os.makedirs(args.out_dir, exist_ok=True)
    skipped_labels = set()

    for frame_number in frames:
        image = client.get_frame_image(job_id, frame_number)
        detect_image = mask_hood(image)
        yolo_dets = yolo.detect(detect_image)
        seg_mask = seg.segment(detect_image)
        seg_polys, seg_lines, seg_rects = seg.get_shapes(seg_mask)
        shapes = build_shapes(frame_number, yolo_dets, seg_polys, seg_lines, seg_rects, image.size, label_schema, skipped_labels)

        if args.push:
            if shapes:
                client.push_annotations(job_id, shapes)
            print(f"[frame {frame_number}] đã đẩy {len(shapes)} shape lên CVAT.")
        else:
            out_path = os.path.join(args.out_dir, f"frame_{frame_number}.json")
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(shapes, f, ensure_ascii=False, indent=2)
            print(f"[frame {frame_number}] {len(shapes)} shape -> {out_path} (dry-run, chưa đẩy lên CVAT)")

    if skipped_labels:
        print(f"\nLƯU Ý: các nhãn model dự đoán ra nhưng KHÔNG tồn tại trong task nên bị bỏ qua: {sorted(skipped_labels)}")
        print("-> kiểm tra lại tên nhãn trong Labels của task, hoặc sửa YOLO_LABEL_MAP trong detectors.py cho khớp.")

    print("\nQuá trình hoàn tất! AI đã nhận diện toàn bộ các vật thể mà bạn yêu cầu.")


if __name__ == "__main__":
    main()
