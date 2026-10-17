# CVAT API Endpoints - Hướng dẫn Triển khai

Tài liệu này cung cấp hướng dẫn chi tiết về cách triển khai các CVAT API endpoints cho hệ thống Quality Control (QC) tự động.

---

## 📋 Mục Lục

1. [Xác thực & Cấu hình Header](#-xác-thực--cấu-hình-header)
2. [Quản lý Issue & Comment](#-quản-lý-issue--comment)
3. [Cập nhật Trạng thái Job](#-cập-nhật-trạng-thái-job)
4. [Export Dataset (Bất đồng bộ)](#-export-dataset-bất-đồng-bộ)
5. [Best Practices & Error Handling](#-best-practices--error-handling)

---

## 🔐 Xác thực & Cấu hình Header

### Header Bắt buộc

Tất cả các request gọi đến CVAT API đều yêu cầu các header sau:

```http
Authorization: Bearer <PERSONAL_ACCESS_TOKEN>
Content-Type: application/json
```

### Header Organization (Nếu áp dụng)

Khi Project/Job thuộc về một Organization, **bắt buộc** phải bổ sung:

```http
X-Organization: <org_slug>
```

> ⚠️ **Lưu ý**: Không truyền header này sẽ dẫn đến lỗi `401 Unauthorized` hoặc `404 Not Found`.

### Timeout & Error Logging

- **Timeout**: Đặt timeout từ **10-30 giây** cho tất cả requests
- **Error Logging**: Luôn đọc `e.response.text` khi bắt exception để ghi log chi tiết lỗi từ Django REST Framework

---

## 🎯 Quản lý Issue & Comment

### Base URLs
- **Issues**: `/api/issues`
- **Comments**: `/api/comments`

---

### 1. Tạo Issue mới

**Endpoint**: `POST /api/issues`

#### Request Payload (Bắt buộc)

```json
{
  "job": 123,
  "frame": 45,
  "position": [100.5, 200.3, 300.7, 400.1],
  "message": "Lỗi nhãn không chính xác"
}
```

| Parameter | Type | Mô tả |
|-----------|------|-------|
| `job` | integer | ID của job chứa lỗi |
| `frame` | integer | Số thứ tự frame (0, 1, 2, ...) |
| `position` | array[float] | Bounding box [x1, y1, x2, y2] biểu diễn vị trí lỗi |
| `message` | string | Nội dung mô tả lỗi |

#### Response

```json
{
  "id": 789,
  "job": 123,
  "frame": 45,
  "position": [100.5, 200.3, 300.7, 400.1],
  "message": "Lỗi nhãn không chính xác",
  "status": "open",
  "created_date": "2026-10-14T10:30:00Z",
  "comments": [
    {
      "id": 101,
      "message": "Lỗi nhãn không chính xác",
      "issue": 789,
      "created_date": "2026-10-14T10:30:00Z"
    }
  ]
}
```

> ✅ **Tự động tạo comment**: Khi tạo issue thành công, CVAT tự động tạo comment đầu tiên với nội dung từ trường `message`.

---

### 2. Thêm Comment cho Issue

**Endpoint**: `POST /api/comments`

#### Request Payload

```json
{
  "issue": 789,
  "message": "Gợi ý sửa đổi: nên điều chỉnh bounding box sang phải 10px"
}
```

| Parameter | Type | Mô tả |
|-----------|------|-------|
| `issue` | integer | ID của issue cần bổ sung comment |
| `message` | string | Nội dung comment/gợi ý sửa đổi |

---

### 3. Cập nhật Issue

**Endpoint**: `PATCH /api/issues/{id}`

#### Request Payload

```json
{
  "status": "resolved"
}
```

| Parameter | Type | Mô tả | Giá trị có thể |
|-----------|------|-------|----------------|
| `status` | string | Trạng thái của issue | `"open"`, `"resolved"` |

#### Use Case

- **Đóng issue**: Khi QC rerun và phát hiện lỗi đã được sửa, dùng PATCH để cập nhật `status: "resolved"`
- **Mở lại issue**: Nếu lỗi tái phát, có thể mở lại với `status: "open"`

---

### 4. Xóa Issue

**Endpoint**: `DELETE /api/issues/{id}`

> ⚠️ **Cảnh báo**: Chỉ sử dụng khi QC bắt nhầm lỗi (**false positive**) để tránh mất lịch sử review.

---

## 🔄 Cập nhật Trạng thái Job

### Base URL
- **Jobs**: `/api/jobs`

---

### Endpoint

**PATCH /api/jobs/{id}**

### Request Payload

#### Trường hợp 1: Reject Job (Yêu cầu sửa lại)

```json
{
  "stage": "annotation",
  "state": "rejected"
}
```

#### Trường hợp 2: Pass QC Test

```json
{
  "stage": "acceptance",
  "state": "completed"
}
```

Hoặc giữ nguyên stage:

```json
{
  "stage": "validation",
  "state": "accepted"
}
```

---

### Phân quyền (RBAC)

User/Token gọi API phải có quyền:
- **Maintainer** hoặc **Owner** của Project
- Hoặc được gán vai trò **Reviewer** của Job đó

> ❌ **Lỗi 403 Forbidden**: Nếu chỉ là Assignee (Annotator) và cố gắng đổi status sau khi đã submit bài.

---

## 📦 Export Dataset (Bất đồng bộ)

### Bản chất

Export dataset là tác vụ tốn thời gian. API **không** trả về file `.zip` ngay lập tức mà trả về **Request ID (rq_id)**.

---

### Luồng triển khai (Polling Pattern)

#### Bước 1: Khởi tạo Export Request

**Endpoint**: `POST /api/jobs/<job_id>/dataset/export`

**Query Parameters**:
- `format`: Định dạng export (VD: `COCO 1.0`, `YOLO`, `Pascal VOC`, etc.)
- `save_images`: `True`/`False` - Có lưu ảnh hay không

```bash
curl -X POST \
  'https://cvat.example.com/api/jobs/123/dataset/export?format=COCO%201.0&save_images=False' \
  -H 'Authorization: Bearer YOUR_TOKEN' \
  -H 'Content-Type: application/json'
```

**Response**:
```json
{
  "id": 456,
  "status": "queued",
  "created_date": "2026-10-14T10:30:00Z",
  "job": 123
}
```

---

#### Bước 2: Kiểm tra trạng thái Request (Polling)

**Endpoint**: `GET /api/requests/<rq_id>`

```bash
curl -X GET \
  'https://cvat.example.com/api/requests/456' \
  -H 'Authorization: Bearer YOUR_TOKEN'
```

**Response Examples**:

Trạng thái **queued**:
```json
{
  "id": 456,
  "status": "queued",
  "created_date": "2026-10-14T10:30:00Z"
}
```

Trạng thái **started**:
```json
{
  "id": 456,
  "status": "started",
  "created_date": "2026-10-14T10:30:00Z"
}
```

Trạng thái **finished**:
```json
{
  "id": 456,
  "status": "finished",
  "created_date": "2026-10-14T10:30:00Z",
  "result_url": "https://cvat.example.com/api/requests/456/result"
}
```

---

#### Bước 3: Tải File Export

Khi `status == "finished"`, tải file từ `result_url`:

```bash
curl -X GET \
  'https://cvat.example.com/api/requests/456/result' \
  -H 'Authorization: Bearer YOUR_TOKEN' \
  --output dataset.zip
```

---

### Polling Implementation (Python Example)

```python
import requests
import time

# Bước 1: Khởi tạo
job_id = 123
export_url = f"https://cvat.example.com/api/jobs/{job_id}/dataset/export?format=COCO%201.0&save_images=False"
response = requests.post(export_url, headers={"Authorization": "Bearer YOUR_TOKEN"})
request_id = response.json()["id"]

# Bước 2: Polling
poll_interval = 2  # giây
while True:
    status_response = requests.get(
        f"https://cvat.example.com/api/requests/{request_id}",
        headers={"Authorization": "Bearer YOUR_TOKEN"}
    )
    status_data = status_response.json()
    
    if status_data["status"] == "finished":
        result_url = status_data["result_url"]
        break
    elif status_data["status"] == "failed":
        raise Exception(f"Export failed: {status_data.get('error', 'Unknown error')}")
    
    time.sleep(poll_interval)

# Bước 3: Tải file
download_response = requests.get(result_url, headers={"Authorization": "Bearer YOUR_TOKEN"})
with open("dataset.zip", "wb") as f:
    f.write(download_response.content)
```

---

### Tối ưu hóa cho QC Real-time

| Phương pháp | Ưu điểm | Nhược điểm | Khuyến nghị |
|-------------|---------|-------------|-------------|
| **Export Dataset** | File .zip hoàn chỉnh | Độ trễ cao (phải đợi tạo file) | Chỉ dùng cho offline audit |
| **RAW Annotations** | Nhanh, real-time | Chưa có ảnh | ✅ **Ưu tiên** cho QC real-time |

**Endpoint thay thế**: `GET /api/jobs/{id}/annotations`

---

## ⚡ Best Practices & Error Handling

### ✅ Recommended Practices

1. **Luôn truyền X-Organization header** khi làm việc với Organization
2. **Đặt timeout hợp lý** (10-30s) cho tất cả requests
3. **Polling interval**: 1-2 giây cho export dataset
4. **Sử dụng RAW Annotations** thay vì Export Dataset cho QC real-time
5. **Ghi log chi tiết** khi gặp lỗi từ CVAT

### ❌ Common Mistakes

1. **Không truyền X-Organization** → 401/404 errors
2. **Sử dụng Assignee token** để cập nhật job status → 403 Forbidden
3. **Xóa Issue** không đúng trường hợp → Mất lịch sử review
4. **Không đợi export finished** → Tải file không hoàn chỉnh
5. **Không đọc response.text** → Log lỗi không đầy đủ

### Error Response Examples

```json
{
  "error": "You do not have permission to perform this action.",
  "status_code": 403
}
```

```json
{
  "error": "Not found.",
  "status_code": 404
}
```

---

## 📚 Tham khảo

- [CVAT Official Documentation](https://docs.cvat.ai/)
- [CVAT API Reference](https://docs.cvat.ai/en/latest/api_reference/)
- [Django REST Framework Errors](https://www.django-rest-framework.org/api-guide/exceptions/)

---

*Tài liệu được tạo từ nội dung hướng dẫn triển khai CVAT API endpoints cho hệ thống LetmeQC*
