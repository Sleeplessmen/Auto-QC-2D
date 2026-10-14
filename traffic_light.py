"""Nhận màu đèn giao thông đang sáng (đỏ / vàng / xanh / không sáng) trong box "traffic light".

Cách làm: trong box (đã được SAM 2 thu chặt), tìm pixel vừa SÁNG vừa ĐẬM MÀU (bóng đèn đang bật),
đếm theo dải màu. Màu có nhiều pixel nhất, vượt hẳn màu thứ hai -> màu đèn. Không có bóng nào sáng
-> "none" (đèn tắt / nhìn từ phía sau / từ bên hông). Kết quả không chắc (2 màu gần bằng nhau, vị trí
bóng sáng ngược với thứ tự đỏ-vàng-xanh của đèn dọc, box quá nhỏ) -> trả None để kiểm tra tay,
KHÔNG đoán bừa.
"""
import cv2
import numpy as np

RED, YELLOW, GREEN, NONE = "red", "yellow", "green", "none"

LIT_MIN_V = 130            # bóng đèn đang bật: sáng
LIT_MIN_S = 110            # ... và đậm màu (vỏ đèn, trời xanh nhạt, nhà phía sau thì nhạt màu hơn)
BORDER_FRAC = 0.1          # bỏ dải 10% sát viền box: box lệch vài px hay dính nền trời/cây phía sau
HUE_RANGES = {             # thang hue OpenCV 0-180
    RED: [(0, 8), (165, 180)],
    YELLOW: [(10, 34)],    # đèn vàng/hổ phách thường ngả cam
    GREEN: [(40, 95)],     # đèn LED xanh thường ngả xanh ngọc (~75-90); trời xanh ~100-110 -> loại
}
MIN_LIT_PX = 4             # ít hơn -> coi như không có bóng nào sáng
MIN_LIT_FRAC = 0.01        # ... hoặc ít hơn 1% diện tích box
DOMINANCE = 2.0            # màu thắng phải nhiều pixel gấp đôi màu thứ hai, không thì không chắc
NONE_MIN_LONG_SIDE = 20    # px — đèn nhỏ hơn mà không thấy bóng sáng thì KHÔNG kết luận "tắt" (bóng sáng chỉ
                           # vài px, dễ mất do mờ) -> để trống, báo kiểm tra tay
MIN_BOX_SIDE = 6           # px — box nhỏ hơn thì không đủ pixel để phân biệt màu

# Thứ tự bóng trên đèn dọc (từ trên xuống): đỏ ở 1/3 trên, vàng giữa, xanh 1/3 dưới
VERTICAL_POSITION = {RED: (0.0, 0.5), YELLOW: (0.2, 0.8), GREEN: (0.5, 1.0)}


def classify_light_color(image, box):
    """image: PIL.Image RGB, box: [xtl, ytl, xbr, ybr]. Trả về (màu | None, ghi chú)."""
    rgb = np.asarray(image.convert("RGB"))
    x1, y1 = max(0, int(box[0])), max(0, int(box[1]))
    x2, y2 = min(rgb.shape[1], int(np.ceil(box[2]))), min(rgb.shape[0], int(np.ceil(box[3])))
    bw, bh = x2 - x1, y2 - y1
    if bw < MIN_BOX_SIDE or bh < MIN_BOX_SIDE:
        return None, f"box quá nhỏ ({bw}x{bh}px)"

    hsv = cv2.cvtColor(rgb[y1:y2, x1:x2], cv2.COLOR_RGB2HSV)
    hue, sat, val = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    lit = (val >= LIT_MIN_V) & (sat >= LIT_MIN_S)
    mx, my = int(bw * BORDER_FRAC), int(bh * BORDER_FRAC)
    inner = np.zeros(lit.shape, bool)
    inner[my:bh - my, mx:bw - mx] = True
    lit &= inner

    masks = {}
    for color, ranges in HUE_RANGES.items():
        m = np.zeros(hue.shape, bool)
        for lo, hi in ranges:
            m |= (hue >= lo) & (hue <= hi)
        masks[color] = lit & m
    counts = {c: int(m.sum()) for c, m in masks.items()}
    ranked = sorted(counts, key=counts.get, reverse=True)
    best, second = ranked[0], ranked[1]

    if counts[best] < max(MIN_LIT_PX, MIN_LIT_FRAC * bw * bh):
        if max(bw, bh) < NONE_MIN_LONG_SIDE:
            return None, f"đèn nhỏ ({bw}x{bh}px), không thấy bóng sáng — không chắc là tắt"
        return NONE, "không có bóng nào sáng"
    if counts[best] < DOMINANCE * counts[second]:
        return None, f"lẫn màu {best}={counts[best]}px / {second}={counts[second]}px"

    if bh >= 1.5 * bw:   # đèn dọc: kiểm tra bóng sáng nằm đúng vị trí của màu đó
        ys = np.where(masks[best])[0]
        pos = float(np.median(ys)) / bh
        lo, hi = VERTICAL_POSITION[best]
        if not (lo <= pos <= hi):
            return None, f"bóng {best} sáng ở vị trí {pos:.0%} chiều cao đèn — ngược thứ tự đỏ/vàng/xanh"
    return best, f"{counts[best]}px"


# Từ khoá để khớp màu với giá trị thuộc tính khai báo trong task CVAT (không phân biệt hoa thường)
VALUE_KEYWORDS = {
    RED: ("red", "đỏ", "do"),
    YELLOW: ("yellow", "amber", "vàng", "vang"),
    GREEN: ("green", "xanh"),
    NONE: ("none", "off", "n/a", "na", "unknown", "không", "khong", "tắt", "tat"),
}
ATTR_NAME_KEYWORDS = ("color", "colour", "màu", "mau", "light")


def find_color_attribute(label):
    """label: phần tử của label_schema. Trả về (spec_id, [giá trị hợp lệ]) của thuộc tính màu đèn, hoặc None."""
    for name, spec_id in label["attributes"].items():
        if any(k in name.lower() for k in ATTR_NAME_KEYWORDS):
            return spec_id, label.get("attr_values", {}).get(name, [])
    return None


def pick_value(values, color):
    """Chọn giá trị thuộc tính khớp với màu. Trả về None nếu task không có giá trị tương ứng."""
    keys = VALUE_KEYWORDS[color]
    for v in values:
        low = v.lower().strip()
        if low in keys or any(len(k) > 3 and k in low for k in keys):
            return v
    return None
