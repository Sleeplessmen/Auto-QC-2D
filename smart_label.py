r"""
smart_label.py — Gán nhãn thông minh cho CVAT với menu tương tác.
Chạy: venv\Scripts\python.exe smart_label.py --env .env.class
"""
import argparse
import os
import sys
import unicodedata
import cv2
import numpy as np
from dotenv import load_dotenv
from ultralytics import YOLO
from cvat_client import CvatClient


# ===========================================================================
# Phát hiện màu
# ===========================================================================
CYAN_RANGES = [
    (np.array([80, 80, 50]),  np.array([105, 255, 255])),   # ban ngày
    (np.array([65, 100, 50]), np.array([80,  255, 200])),   # ban đêm / đèn vàng
]
BLUE_RANGE = (np.array([105, 80, 50]), np.array([130, 255, 255]))


def _color_ratio(hsv, lower, upper):
    mask = cv2.inRange(hsv, lower, upper)
    return np.sum(mask > 0) / max(1, mask.shape[0] * mask.shape[1])


def is_green_sm(image_rgb, box):
    xtl, ytl, xbr, ybr = [int(v) for v in box]
    crop = image_rgb[max(0, ytl):min(image_rgb.shape[0], ybr),
                     max(0, xtl):min(image_rgb.shape[1], xbr)]
    if crop.size == 0 or crop.shape[0] < 4 or crop.shape[1] < 4:
        return False
    hsv = cv2.cvtColor(cv2.cvtColor(crop, cv2.COLOR_RGB2BGR), cv2.COLOR_BGR2HSV)
    cyan = sum(_color_ratio(hsv, lo, hi) for lo, hi in CYAN_RANGES)
    if cyan < 0.08:
        return False
    if _color_ratio(hsv, *BLUE_RANGE) > cyan * 1.5:
        return False
    return True


# ===========================================================================
# Loại xe cho chế độ Tùy chọn
# key -> (tên hiển thị, lớp YOLO, cần màu Xanh SM?, từ khoá để tự khớp tên nhãn CVAT)
# ===========================================================================
VEHICLE_TYPES = {
    "greensm":      ("Ô tô Xanh SM (taxi màu xanh ngọc)", ("car", "truck", "bus"), True,
                     ("greensm", "green sm", "xanhsm", "xanh sm", "gsm")),
    "car":          ("Ô tô con",                          ("car",), False,
                     ("car", "oto", "o to", "xe con", "xe hoi", "sedan", "taxi")),
    "truck":        ("Xe tải",                            ("truck",), False,
                     ("truck", "xe tai", "pickup")),
    "bus":          ("Xe buýt / xe khách",                ("bus",), False,
                     ("bus", "xe buyt", "xe khach", "coach")),
    "greensm_bike": ("Xe máy Xanh SM (xe ôm điện)",       ("motorcycle",), True,
                     ("greensm bike", "xanhsm bike", "green sm bike", "xanh sm bike", "greensm motor")),
    "motorcycle":   ("Xe máy",                            ("motorcycle",), False,
                     ("motorcycle", "motorbike", "motor", "xe may", "scooter")),
    "bicycle":      ("Xe đạp",                            ("bicycle",), False,
                     ("bicycle", "xe dap", "bike", "cycle")),
}
GREEN_WORDS = VEHICLE_TYPES["greensm"][3]


def _norm(text):
    text = unicodedata.normalize("NFD", text.lower().replace("đ", "d"))
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return " ".join(text.replace("_", " ").replace("-", " ").split())


def match_label(key, names):
    """Tìm nhãn CVAT hợp với loại xe theo tên (khớp đúng > chứa từ khoá dài nhất). Không thấy -> None."""
    need_green, words = VEHICLE_TYPES[key][2], VEHICLE_TYPES[key][3]
    best, best_score = None, 0
    for name in names:
        n = _norm(name)
        is_green = any(w in n or w.replace(" ", "") in n for w in GREEN_WORDS)
        if is_green != need_green:
            continue            # nhãn Xanh SM chỉ dùng cho loại Xanh SM và ngược lại
        for w in words:
            if n == w or n.replace(" ", "") == w.replace(" ", ""):
                score = 100
            elif w in n:
                score = len(w)
            else:
                continue
            if score > best_score:
                best, best_score = name, score
    return best


def custom_category(yolo_name, types, image_rgb, box):
    """Chế độ Tùy chọn: loại xe (trong types) của 1 box, hoặc None.
    Xanh SM được xét trước; không chọn loại Xanh SM thì xe Xanh SM gán như xe thường cùng loại."""
    green = None
    for key in types:
        _, classes, need_green, _ = VEHICLE_TYPES[key]
        if need_green and yolo_name in classes:
            if green is None:
                green = is_green_sm(image_rgb, box)
            if green:
                return key
    for key in types:
        _, classes, need_green, _ = VEHICLE_TYPES[key]
        if not need_green and yolo_name in classes:
            return key
    return None


def nms_boxes(boxes, iou_thresh=0.5):
    if not boxes:
        return []
    boxes = sorted(boxes, key=lambda x: x[4], reverse=True)
    keep, used = [], [False] * len(boxes)
    for i in range(len(boxes)):
        if used[i]:
            continue
        keep.append(boxes[i])
        ax1, ay1, ax2, ay2 = boxes[i][:4]
        for j in range(i + 1, len(boxes)):
            if used[j]:
                continue
            bx1, by1, bx2, by2 = boxes[j][:4]
            inter = max(0, min(ax2, bx2) - max(ax1, bx1)) * max(0, min(ay2, by2) - max(ay1, by1))
            area = (ax2 - ax1) * (ay2 - ay1) + (bx2 - bx1) * (by2 - by1) - inter
            if area > 0 and inter / area >= iou_thresh:
                used[j] = True
    return keep


# ===========================================================================
# Menu tương tác
# ===========================================================================
def print_banner():
    print("=" * 58)
    print("   SMART LABEL — Gán nhãn phương tiện tự động cho CVAT")
    print("=" * 58)


def choose(prompt, options, default=0):
    """Hiện menu số, trả về index lựa chọn."""
    print("\n" + prompt)
    for i, opt in enumerate(options):
        marker = " ◀ (mặc định)" if i == default else ""
        print("  [%d] %s%s" % (i + 1, opt, marker))
    while True:
        raw = input("Nhập số lựa chọn (Enter = mặc định): ").strip()
        if raw == "":
            return default
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return int(raw) - 1
        print("  ⚠  Vui lòng nhập số từ 1 đến %d." % len(options))


def yes_no(prompt, default=True):
    hint = " [Y/n]" if default else " [y/N]"
    raw = input(prompt + hint + ": ").strip().lower()
    if raw == "":
        return default
    return raw in ("y", "yes", "có", "co")


def interactive_menu(label_schema):
    """Hỏi người dùng chọn chế độ, trả về (mode, clear_first, push, out_dir)."""

    print_banner()

    # --- Chọn chế độ ---
    mode_options = [
        "🟢  Chỉ gán xe Xanh SM (GreenSM) — dùng cho cuộc thi",
        "🚗  Gán tất cả ô tô (không phân biệt hãng)",
        "🏍️  Gán tất cả xe máy + ô tô (không phân biệt hãng)",
        "🔍  Phân biệt đầy đủ: GreenSM / ô tô thường / xe tải / xe buýt / xe máy",
        "🎯  Tùy chọn: tự chọn loại xe muốn gán (Xanh SM, ô tô, xe tải, xe buýt, xe máy, xe đạp...)",
    ]
    mode_idx = choose("Chọn chế độ gán nhãn:", mode_options, default=0)
    mode_map = ["greensm", "car_only", "vehicles", "all", "custom"]
    mode = mode_map[mode_idx]

    custom = None
    if mode == "custom":
        custom = custom_menu(label_schema)
    else:
        # Kiểm tra nhãn có trong task
        avail = sorted(label_schema.keys())
        print("\nNhãn hiện có trong task CVAT: %s" % avail)
        if mode != "greensm" and len(avail) < 2:
            print("  ⚠  Task chỉ có 1 nhãn → các chế độ phân biệt sẽ chỉ gán nhãn đầu tiên tìm thấy.")

    # --- Đẩy lên CVAT không? ---
    push = yes_no("\nĐẩy nhãn trực tiếp lên CVAT?", default=True)

    clear_first = False
    if push:
        clear_first = yes_no("Xóa nhãn AUTO cũ trước khi đẩy? (tránh trùng hộp)", default=True)

    # --- Thư mục xuất ---
    default_dir = "labels_" + mode
    out_raw = input("\nThư mục lưu file YOLO .txt [%s]: " % default_dir).strip()
    out_dir = out_raw if out_raw else default_dir

    print("\n" + "-" * 58)
    print("  Chế độ   : %s" % mode_options[mode_idx])
    if custom:
        id_to_name = {info["id"]: name for name, info in label_schema.items()}
        for key, lid in custom.items():
            print("    %-34s -> nhãn %s" % (VEHICLE_TYPES[key][0], id_to_name[lid]))
    print("  Đẩy CVAT : %s" % ("CÓ" if push else "KHÔNG (dry-run)"))
    print("  Xóa cũ   : %s" % ("CÓ" if clear_first else "KHÔNG"))
    print("  Lưu .txt : %s" % out_dir)
    print("-" * 58)
    confirm = yes_no("Xác nhận chạy?", default=True)
    if not confirm:
        print("Đã hủy.")
        sys.exit(0)

    return mode, clear_first, push, out_dir, custom


def custom_menu(label_schema):
    """Chế độ Tùy chọn: chọn loại xe + nhãn CVAT cho từng loại. -> {loại xe: label_id}"""
    names = list(label_schema)
    if not names:
        print("  ⚠  Job không có nhãn nào.")
        sys.exit(1)
    keys = list(VEHICLE_TYPES)
    print("\nChọn loại xe muốn gán (gõ 1 hoặc nhiều số, vd 3 hoặc 1,3,4):")
    for i, key in enumerate(keys, 1):
        print("  [%d] %s" % (i, VEHICLE_TYPES[key][0]))
    print("  (Không chọn loại Xanh SM thì xe Xanh SM được gán như xe thường cùng loại.)")
    while True:
        raw = input("Loại xe: ").replace(" ", "")
        idx = [int(x) for x in raw.split(",") if x.isdigit() and 1 <= int(x) <= len(keys)]
        if idx:
            break
        print("  ⚠  Gõ số từ 1 đến %d, nhiều loại cách nhau dấu phẩy." % len(keys))
    types = list(dict.fromkeys(keys[i - 1] for i in idx))

    print("\nNhãn trong job CVAT:")
    for i, name in enumerate(names, 1):
        print("  %d. %s" % (i, name))
    print("Gán mỗi loại xe vào nhãn nào? (gõ số nhãn, 0 = bỏ loại này)")
    mapping = {}
    for key in types:
        auto = match_label(key, names)
        hint = " (Enter = %s)" % auto if auto else ""
        while True:
            raw = input("  %-34s -> nhãn số%s: " % (VEHICLE_TYPES[key][0], hint)).strip()
            if raw == "" and auto:
                mapping[key] = label_schema[auto]["id"]
                break
            if raw == "0":
                break
            if raw.isdigit() and 1 <= int(raw) <= len(names):
                mapping[key] = label_schema[names[int(raw) - 1]]["id"]
                break
            print("  ⚠  Gõ số nhãn từ 1 đến %d (0 = bỏ loại này)." % len(names))
    if not mapping:
        print("Không có loại xe nào được gán. Đã hủy.")
        sys.exit(0)
    return mapping


# ===========================================================================
# Xử lý chính
# ===========================================================================
def get_category(yolo_name, mode, image_rgb, box):
    if mode == "greensm":
        return "GreenSM" if (yolo_name in ("car", "truck", "bus") and is_green_sm(image_rgb, box)) else None

    if mode == "car_only":
        if yolo_name in ("car", "truck", "bus"):
            return "GreenSM" if is_green_sm(image_rgb, box) else "car"
        return None

    if mode == "vehicles":
        if yolo_name in ("car", "truck", "bus"):
            return "GreenSM" if is_green_sm(image_rgb, box) else "car"
        if yolo_name in ("motorcycle", "bicycle"):
            return "motorcycle"
        return None

    # mode == "all"
    if yolo_name in ("car", "truck", "bus"):
        return "GreenSM" if is_green_sm(image_rgb, box) else yolo_name
    if yolo_name in ("motorcycle", "bicycle"):
        return yolo_name
    return None


def run(mode, clear_first, push, out_dir, client, job_id, label_schema, model, custom=None):
    meta = client.get_job_meta(job_id)
    start_frame, stop_frame = meta["start_frame"], meta["stop_frame"]

    # Bảng label_id — chỉ dùng nhãn tồn tại trong task
    cat_to_id = {}
    for cat in ("GreenSM", "car", "truck", "bus", "motorcycle", "bicycle"):
        for lname, info in label_schema.items():
            if lname.lower() == cat.lower():
                cat_to_id[cat] = info["id"]
                break
    # Fallback: nếu chế độ phân biệt nhiều loại nhưng task chỉ có 1 nhãn
    fallback_id = list(label_schema.values())[0]["id"] if label_schema else None
    if mode == "custom":            # Tùy chọn: chỉ các loại xe đã chọn, nhãn theo bảng người dùng chọn
        cat_to_id, fallback_id = dict(custom), None

    if clear_first and push:
        print("\nĐang xóa nhãn AUTO cũ trong job %d..." % job_id)
        deleted = client.delete_auto_annotations(job_id)
        print("✓ Đã xóa %d nhãn." % deleted)

    os.makedirs(out_dir, exist_ok=True)
    print("\nBắt đầu xử lý %d frame (job %d)...\n" % (stop_frame - start_frame + 1, job_id))

    allowed_yolo = ("car", "truck", "bus", "motorcycle", "bicycle")
    total = 0

    for frame_idx in range(start_frame, stop_frame + 1):
        image_pil = client.get_frame_image(job_id, frame_idx)
        w, h = image_pil.size
        img_np = np.array(image_pil)

        results = model(img_np, conf=0.2, verbose=False)[0]

        candidates = {}
        for box in results.boxes:
            yolo_name = model.names[int(box.cls[0])]
            if yolo_name not in allowed_yolo:
                continue
            xtl, ytl, xbr, ybr = box.xyxy[0].tolist()
            score = float(box.conf[0])
            if (ybr - ytl) < 12:
                continue
            if mode == "custom":
                cat = custom_category(yolo_name, cat_to_id, img_np, [xtl, ytl, xbr, ybr])
            else:
                cat = get_category(yolo_name, mode, img_np, [xtl, ytl, xbr, ybr])
            if cat is None:
                continue
            candidates.setdefault(cat, []).append([xtl, ytl, xbr, ybr, score])

        yolo_lines, cvat_shapes, counts = [], [], {}
        for cat, boxes in candidates.items():
            label_id = cat_to_id.get(cat, fallback_id)
            for xtl, ytl, xbr, ybr, score in nms_boxes(boxes):
                counts[cat] = counts.get(cat, 0) + 1
                cx = ((xtl + xbr) / 2) / w
                cy = ((ytl + ybr) / 2) / h
                bw = (xbr - xtl) / w
                bh = (ybr - ytl) / h
                yolo_lines.append("0 %.6f %.6f %.6f %.6f" % (cx, cy, bw, bh))
                if push:
                    cvat_shapes.append({
                        "type": "rectangle", "occluded": False, "z_order": 0,
                        "points": [xtl, ytl, xbr, ybr], "frame": frame_idx,
                        "label_id": label_id, "group": 0, "source": "auto", "attributes": [],
                    })

        txt_path = os.path.join(out_dir, "frame_%06d.txt" % frame_idx)
        with open(txt_path, "w") as f:
            if yolo_lines:
                f.write("\n".join(yolo_lines) + "\n")

        if push and cvat_shapes:
            client.push_annotations(job_id, cvat_shapes)

        total += sum(counts.values())
        summary = ", ".join("%s:%d" % (VEHICLE_TYPES[k][0] if mode == "custom" else k, v)
                            for k, v in sorted(counts.items()))
        flag = "✓ CVAT" if (push and cvat_shapes) else "○ dry-run"
        print("[Frame %3d] %-35s %s" % (frame_idx, summary or "không có xe", flag))

    print("\n" + "=" * 58)
    print("  ✓ Hoàn tất! Tổng %d hộp nhãn." % total)
    print("  File .txt lưu tại: %s" % out_dir)
    print("=" * 58)


# ===========================================================================
# Entry point
# ===========================================================================
def main():
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--env", default=".env", help="File cấu hình (.env)")
    # Các tham số dòng lệnh (tùy chọn — nếu không truyền thì hiện menu)
    parser.add_argument("--mode", choices=["greensm", "car_only", "vehicles", "all", "custom"],
                        help="Bỏ qua menu, chạy thẳng với mode đã chọn")
    parser.add_argument("--types", help="Mode custom: loại xe, vd truck,bus (%s); nhãn CVAT tự khớp theo tên"
                        % ",".join(VEHICLE_TYPES))
    parser.add_argument("--push", action="store_true", help="Đẩy lên CVAT")
    parser.add_argument("--clear-first", action="store_true", help="Xóa nhãn AUTO cũ trước")
    parser.add_argument("--out-dir", default=None, help="Thư mục lưu .txt")
    args = parser.parse_args()

    load_dotenv(args.env, override=True)
    cvat_url = os.environ["CVAT_URL"]
    token    = os.environ["CVAT_TOKEN"]
    job_id   = int(os.environ["CVAT_JOB_ID"])

    client = CvatClient(cvat_url, token)
    label_schema = client.get_label_schema(job_id)

    # Nếu không truyền --mode → hiện menu tương tác
    custom = None
    if args.mode is None:
        mode, clear_first, push, out_dir, custom = interactive_menu(label_schema)
    else:
        mode        = args.mode
        clear_first = args.clear_first
        push        = args.push
        out_dir     = args.out_dir or ("labels_" + mode)
        if mode == "custom":
            custom = {}
            for key in (args.types or "").replace(" ", "").split(","):
                if key not in VEHICLE_TYPES:
                    sys.exit("--types: không có loại xe '%s' (chọn trong: %s)" % (key, ",".join(VEHICLE_TYPES)))
                name = match_label(key, list(label_schema))
                if name is None:
                    print("  ⚠  Bỏ %s: job không có nhãn nào khớp tên" % key)
                    continue
                custom[key] = label_schema[name]["id"]
                print("  %s -> nhãn %s" % (VEHICLE_TYPES[key][0], name))
            if not custom:
                sys.exit("Không có loại xe nào khớp được nhãn trong job.")

    model_path = "yolov8x-seg.pt" if os.path.exists("yolov8x-seg.pt") else "yolov8s-seg.pt"
    model = YOLO(model_path)
    print("\nModel: %s" % model_path)

    run(mode, clear_first, push, out_dir, client, job_id, label_schema, model, custom)


if __name__ == "__main__":
    main()
