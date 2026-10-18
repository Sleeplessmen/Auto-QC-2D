# QC Rule-Based Pipeline - Thiết kế & Triển khai

Tài liệu ghi chép các quyết định thiết kế và hướng dẫn triển khai cho **Pipeline QC Tầng 1 (Rule-Based Layer)** trong hệ thống LetmeQC.

---

## 📋 Mục Lục

1. [Tổng quan Pipeline](#-tổng-quan-pipeline)
2. [Quy định Tọa độ & Message cho Lỗi](#-quy-định-tọa-độ--message-cho-lỗi)
3. [Phương án Sinh Message](#-phương-án-sinh-message)
4. [Thứ tự Ưu tiên Triển khai (Rule Matrix)](#-thứ-tự-ưu-tiên-triển-khai-rule-matrix)
5. [Hướng dẫn Triển khai các Rule](#-hướng-dẫn-triển-khai-các-rule)

---

## 🎯 Tổng quan Pipeline

### Mục tiêu
- **Tầng**: Rule-Based Layer (Tầng 1)
- **Độ trễ mục tiêu**: **< 2 giây** sau khi đổi sang validation
- **Kiến trúc**: Deterministic, zero-cost, low-latency

### Lưu ý chính
- **Mapping**: Chú ý mapping các trường dữ liệu, đặc biệt là `frame_index`
- **Tích hợp API**: Sử dụng các endpoint CVAT API đã được tài liệu hóa trong [CVAT_API_ENDPOINT.md](./CVAT_API_ENDPOINT.md)

---

## 📏 Quy định Tọa độ & Message cho Lỗi

API `POST /api/issues` yêu cầu mảng `position: [x1, y1, x2, y2]` để hiển thị box màu đỏ trên UI CVAT.

### Bảng Quy định Tọa độ & Message

| **Loại lỗi** | **Cách tính tọa độ position cho Issue** | **Message hiển thị mẫu** |
|--------------|----------------------------------------|--------------------------|
| **Bbox Out of Bounds** | Tọa độ của chính Bbox đó (hoặc xê dịch khống chế trong phạm vi `[0, 0, W_img, H_img]`). | `[High] Box vượt ngoài viền ảnh (1280x720). Tọa độ xbr/ybr vượt quá giới hạn.` |
| **Bbox Too Small** | Tọa độ Bbox gây lỗi. | `[High] Area = 50px (< 100px threshold). Phát hiện box rác hoặc do click đúp.` |
| **Overlapping Bboxes** | Tọa độ vùng giao nhau (Intersection Box) giữa 2 Bbox **hoặc** Bbox của object thứ 2. | `[Medium] Phát hiện 2 box 'car' (ID 12 & 15) bị trùng lắp tới 96% IoU.` |
| **Self-intersecting Polygon** | Bounding box ôm gọn toàn bộ các điểm `points` của Polygon lỗi. | `[High] Polygon bị xoắn/vặn chéo nét (Self-intersection).` |
| **Mask Out of Bbox** | Bounding box của chính Polygon đó. | `[Medium] Mask nhãn 'car' bị lem ra ngoài Bbox tương ứng > 2px.` |
| **Duplicate Objects** | Bounding box của object bị trùng. | `[High] Duplicate Object: Trùng lặp hoàn toàn tọa độ và nhãn với ID 10.` |
| **Extreme Aspect Ratio** | Tọa độ Bbox gây lỗi. | `[Low] Aspect ratio bất thường (Ratio = 12.5). Box quá dẹp hoặc quá dài.` |
| **Invalid Polygon Point Count** | Bounding box ôm gọn Polygon. | `[High] Polygon chỉ có 2 điểm, không đủ điều kiện tạo thành đa giác (cần ≥ 3 điểm).` |

### Severity Levels
- **High**: Lỗi cấu trúc, phải sửa ngay
- **Medium**: Lỗi logic, ảnh hưởng chất lượng
- **Low**: Lỗi heuristic, cảnh báo để cải thiện

---

## 💬 Phương án Sinh Message

### Chiến lược
- **Rule-based (Static/Template)**: ✅ **Lựa chọn**
  - **Lý do**:
    - Latency thấp (<2s)
    - Deterministic (không hallucination như VLM)
    - Cost miễn phí hoàn toàn

- **VLM-based**: ❌ Bỏ qua do latency cao và risk hallucination

### Thiết kế Dynamic JSON/String Template

#### Cấu trúc Template

```python
def generate_error_payload(error_type, obj, frame_name, extra_info):
    templates = {
        "Bbox_Too_Small": {
            "Severity": "high",
            "Suggestion": "Hãy phóng to khu vực này để kiểm tra. Nếu là object thật, hãy vẽ sát viền; nếu là điểm rác, hãy xóa đi.",
            "Message": f"Diện tích box ({extra_info['area']:.1f}px) nhỏ hơn mức cho phép ({extra_info['min_area']}px)."
        },
        "Bbox_Out_Of_Bounds": {
            "Severity": "high",
            "Suggestion": "Kéo viền box thu gọn vào bên trong viền ảnh.",
            "Message": f"Tọa độ box tràn ra ngoài kích thước ảnh ({extra_info['img_w']}x{extra_info['img_h']})."
        },
        "Polygon_Self_Intersect": {
            "Severity": "high",
            "Suggestion": "Xóa điểm vắt chéo hoặc dùng công cụ Split/Edit polygon để điều chỉnh lại các đỉnh.",
            "Message": "Polygon bị lỗi tự cắt chéo nét (Self-intersection)."
        }
    }
    
    info = templates.get(error_type, {
        "Severity": "medium", 
        "Suggestion": "Kiểm tra lại nhãn theo Guidelines.", 
        "Message": "Phát hiện lỗi không xác định."
    })
    
    return {
        "Frame": frame_name,
        "Object_ID": obj.id,
        "Error_Type": error_type,
        "Message": info["Message"],
        "Severity": info["Severity"],
        "Suggestion": info["Suggestion"],
        "Details": {
            "label": obj.label,
            "bounds": [obj.xtl, obj.ytl, obj.xbr, obj.ybr] if hasattr(obj, 'xtl') else None,
            **extra_info
        }
    }
```

#### Ưu điểm
- ✅ Dynamic: Thay đổi dựa trên dữ liệu đầu vào
- ✅ Consistent: Format thống nhất
- ✅ Maintainable: Dễ dẫn thêm template mới
- ✅ Multilingual-ready: Dễ dàng hỗ trợ nhiều ngôn ngữ

---

## 📊 Thứ tự Ưu tiên Triển khai (Rule Matrix)

Để hệ thống chạy ổn định và đem lại giá trị ngay lập tức, triển khai theo **3 giai đoạn**:

```
Phase 1: Critical (Triển khai ngay) ──> Phase 2: Geometry & Logic ──> Phase 3: Advanced
```

### Phase 1 - Structural & Critical Rules (Bắt buộc phải có)

| # | Rule | Mô tả | Severity | Tác động |
|---|------|-------|----------|----------|
| 1 | **Bbox Out of Bounds** | Check viền ảnh | High | Loại bỏ box vượt khỏi ảnh |
| 2 | **Bbox Too Small** | Loại bỏ box rác do nhấp chuột lỗi | High | Loại box diện tích < threshold |
| 3 | **Polygon Point Count** | Check N_points < 3 | High | Polygon không hợp lệ |

**Mục tiêu**: Đảm bảo dữ liệu hợp lệ cơ bản, tránh crash hệ thống.

---

### Phase 2 - Spatial & Attribute Logic (Nâng cao chất lượng gán nhãn)

| # | Rule | Mô tả | Severity | Tác động |
|---|------|-------|----------|----------|
| 4 | **Overlapping Bboxes** | Check IoU cùng class | Medium | Trùng lắp giữa các object |
| 5 | **Self-intersecting Polygon** | Dùng `shapely.is_valid` | High | Polygon bị xoắn |
| 6 | **Duplicate Objects** | IoU = 1.0 & trùng class & attributes | High | Loại bỏ duplicate |
| 7 | **Missing Required Attributes** | Thiếu attribute bắt buộc | Medium | Đảm bảo đầy đủ metadata |

**Mục tiêu**: Nâng cao chất lượng annotation, giảm thiểu lỗi logic.

---

### Phase 3 - Heuristic & Anomaly Detection

| # | Rule | Mô tả | Severity | Tác động |
|---|------|-------|----------|----------|
| 8 | **Mask Out of Bbox** | Mask tràn ra ngoài bbox | Medium | Đảm bảo consistency |
| 9 | **Extreme Aspect Ratio** | Check w/h > threshold_max hoặc < threshold_min | Low | Cảnh báo box bất thường |
| 10 | **Label Consistency** | Class không tương thích (pedestrian trong car) | Medium | Logic semantic |

**Mục tiêu**: Phát hiện anomaly và cải thiện chất lượng theo ngữ nghĩa.

---

## 🛠️ Hướng dẫn Triển khai các Rule

### A. Mask Out of Bbox (`mask_out_of_bbox`)

**Áp dụng**: Khi gán nhãn Instance Segmentation (vừa có Bbox vừa có Polygon/Mask cho 1 object).

#### Logic (Đã sửa đổi)
Trong CVAT, một Bbox và một Polygon độc lập sẽ có 2 `id` khác nhau. Để ánh xạ (map) đúng Polygon vào Bbox của nó, sử dụng một trong hai cách:
1. **Dựa vào `group_id` (Ưu tiên):** Bbox và Polygon được annotator group lại với nhau (có chung thuộc tính `group`).
2. **Dựa vào Không gian (Spatial Mapping):** Nếu không có `group`, tìm Bbox có *cùng label* và chứa trọn (hoặc chứa phần lớn) Polygon đó (IoU hoặc Intersection over Polygon Area cao nhất).

**Không sử dụng so sánh `bbox.id == poly.id`.**


Các bước tiếp theo giữ nguyên:
1. Tạo 1 `Polygon` từ các điểm của mask bằng `Shapely`.
2. Lấy `bounds` của nó (`min_x, min_y, max_x, max_y`).
3. So sánh `bounds` này với tọa độ của Bbox đã map thành công.

#### Code mẫu

```python
from shapely.geometry import Polygon as ShapelyPoly

def check_mask_out_of_bbox(poly_obj, bbox_obj, tolerance=2.0):
    """
    Kiểm tra xem mask có tràn ra ngoài bbox hay không.
    
    Args:
        poly_obj: Object chứa Polygon points
        bbox_obj: Object chứa Bounding Box (xtl, ytl, xbr, ybr)
        tolerance: Độ dung sai (pixel) cho phép lem ra ngoài
        
    Returns:
        bool: True nếu mask tràn ra ngoài bbox
    """
    shapely_poly = ShapelyPoly(poly_obj.points)
    min_x, min_y, max_x, max_y = shapely_poly.bounds

    # Cho phép lẻ vài pixel viền (tolerance)
    if (min_x < bbox_obj.xtl - tolerance or 
        min_y < bbox_obj.ytl - tolerance or 
        max_x > bbox_obj.xbr + tolerance or 
        max_y > bbox_obj.ybr + tolerance):
        return True  # Có lỗi mask tràn ra ngoài Bbox
    return False
```

#### Position cho Issue
Sử dụng bounding box của chính Polygon đó: `[min_x, min_y, max_x, max_y]`

---

### B. Duplicate Objects (`duplicate_objects`)

**Mục đích**: Bắt lỗi Annotator lỡ tay ấn Duplicate (Ctrl+C / Ctrl+V) nhiều lần tại 1 vị trí mà không biết.

#### Logic
Hai object được coi là Duplicate khi **ĐỒNG THỜI** thỏa mãn:
1. Cùng `label_name`
2. Chỉ số IoU giữa 2 box **> 0.98** (gần như đè khít lên nhau)
3. Tất cả các `attributes` giống hệt nhau

#### Implementation

```python
def calculate_iou(box1, box2):
    """Tính IoU giữa 2 bounding box."""
    # box format: [x1, y1, x2, y2]
    inter_x1 = max(box1[0], box2[0])
    inter_y1 = max(box1[1], box2[1])
    inter_x2 = min(box1[2], box2[2])
    inter_y2 = min(box1[3], box2[3])
    
    inter_area = max(0, inter_x2 - inter_x1) * max(0, inter_y2 - inter_y1)
    box1_area = (box1[2] - box1[0]) * (box1[3] - box1[1])
    box2_area = (box2[2] - box2[0]) * (box2[3] - box2[1])
    
    union_area = box1_area + box2_area - inter_area
    return inter_area / union_area if union_area > 0 else 0

def is_duplicate(obj1, obj2, iou_threshold=0.98):
    """Kiểm tra 2 object có phải duplicate hay không."""
    if obj1.label != obj2.label:
        return False
    
    iou = calculate_iou(
        [obj1.xtl, obj1.ytl, obj1.xbr, obj1.ybr],
        [obj2.xtl, obj2.ytl, obj2.xbr, obj2.ybr]
    )
    
    if iou < iou_threshold:
        return False
    
    # Check tất cả attributes
    if obj1.attributes != obj2.attributes:
        return False
    
    return True

def find_duplicates(objects):
    """Tìm tất cả duplicate objects."""
    duplicates = []
    n = len(objects)
    checked = set()
    
    for i in range(n):
        if i in checked:
            continue
        for j in range(i + 1, n):
            if is_duplicate(objects[i], objects[j]):
                duplicates.append((objects[i], objects[j]))
                checked.add(j)
    
    return duplicates
```

#### Position cho Issue
Sử dụng bounding box của object bị trùng (có thể chọn object thứ 2): `[x1, y1, x2, y2]`

---

### C. Overlapping Bboxes (`overlapping_bboxes`)

#### Logic
Kiểm tra tất cả cặp object có cùng `label`:
- Tính IoU giữa các box
- Nếu IoU > threshold (VD: 0.5, 0.7, 0.9) → báo lỗi

#### Position cho Issue
Sử dụng **Intersection Box** (vùng giao nhau) hoặc bounding box của object thứ 2.

---

### D. Self-intersecting Polygon (`self_intersecting_polygon`)

#### Logic
Dùng thư viện `Shapely`:

```python
from shapely.geometry import Polygon as ShapelyPoly

def is_self_intersecting(poly_obj):
    """Kiểm tra polygon có bị self-intersect hay không."""
    shapely_poly = ShapelyPoly(poly_obj.points)
    return not shapely_poly.is_valid
```

#### Position cho Issue
Sử dụng bounding box ôm gọn toàn bộ các điểm `points`:
```python
points = poly_obj.points
min_x = min(p[0] for p in points)
min_y = min(p[1] for p in points)
max_x = max(p[0] for p in points)
max_y = max(p[1] for p in points)
position = [min_x, min_y, max_x, max_y]
```

---

### E. Bbox Out of Bounds (`bbox_out_of_bounds`)

#### Logic

```python
def is_bbox_out_of_bounds(bbox_obj, img_width, img_height):
    """Kiểm tra bbox có vượt ngoài viền ảnh hay không."""
    return (bbox_obj.xtl < 0 or 
            bbox_obj.ytl < 0 or 
            bbox_obj.xbr > img_width or 
            bbox_obj.ybr > img_height)
```

#### Position cho Issue
Sử dụng tọa độ của chính Bbox đó. Để tránh hiển thị ngoài viền, có thể xê dịch khống chế:
```python
position = [
    max(0, bbox_obj.xtl),
    max(0, bbox_obj.ytl),
    min(img_width, bbox_obj.xbr),
    min(img_height, bbox_obj.ybr)
]
```

---

### F. Bbox Too Small (`bbox_too_small`)

#### Logic

```python
def is_bbox_too_small(bbox_obj, min_area=100):
    """Kiểm tra bbox có quá nhỏ hay không."""
    area = (bbox_obj.xbr - bbox_obj.xtl) * (bbox_obj.ybr - bbox_obj.ytl)
    return area < min_area
```

#### Position cho Issue
Sử dụng tọa độ của chính Bbox gây lỗi.

---

### G. Invalid Polygon Point Count (`invalid_polygon_point_count`)

#### Logic

```python
def has_invalid_point_count(poly_obj, min_points=3):
    """Kiểm tra polygon có đủ điểm hay không."""
    return len(poly_obj.points) < min_points
```

#### Position cho Issue
Sử dụng bounding box ôm gọn Polygon.

---

### H. Extreme Aspect Ratio (`extreme_aspect_ratio`)

#### Logic

```python
def has_extreme_aspect_ratio(bbox_obj, min_ratio=0.1, max_ratio=10.0):
    """Kiểm tra aspect ratio của bbox."""
    width = bbox_obj.xbr - bbox_obj.xtl
    height = bbox_obj.ybr - bbox_obj.ytl
    
    if width <= 0 or height <= 0:
        return True  # Invalid box
    
    ratio = width / height
    return ratio < min_ratio or ratio > max_ratio
```

#### Position cho Issue
Sử dụng tọa độ của chính Bbox gây lỗi.

---

### I. Missing Required Attributes (`missing_attributes`)

**Mục đích**: Đảm bảo Annotator không bỏ sót việc điền các trường metadata (attributes) quan trọng cho object.

#### Logic
1. Duyệt qua tất cả các object (bbox, polygon).
2. So sánh danh sách attributes thực tế của object với danh sách attributes bắt buộc (được định nghĩa trước trong code hoặc lấy từ `label.json`).
3. Nếu object bị thiếu một key bắt buộc, hoặc value đang ở trạng thái rỗng/chưa chọn (tùy định nghĩa), hệ thống sẽ báo lỗi.

#### Position cho Issue
Sử dụng tọa độ bounding box của chính object bị thiếu thuộc tính.

---

## 📁 Tài liệu liên quan

- [CVAT API Endpoints](./CVAT_API_ENDPOINT.md) - Hướng dẫn gọi API
- [Shapely Documentation](https://shapely.readthedocs.io/) - Thư viện xử lý hình học
- [CVAT Python SDK](https://github.com/openvinotoolkit/cvat) - SDK chính thức

---

## 🏷️ Tags

`qc-pipeline` `rule-based` `implementation` `design-decision` `cvats`

---

*Tài liệu được tạo từ ghi chép quyết định trước khi triển khai QC Rule-Based Pipeline cho hệ thống LetmeQC*
