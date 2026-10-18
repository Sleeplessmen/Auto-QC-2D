# 📡 CVAT Webhook Integration Guide

**Hướng dẫn tích hợp LetmeQC với CVAT thông qua webhook để tự động chạy QC khi annotator hoàn thành công việc.**

Công cụ LetmeQC có thể hoạt động ở 2 chế độ:

- **Offline Mode**: Chạy QC trực tiếp trên file COCO JSON đã export
- **Online Mode (Webhook)**: Tự động trigger QC khi job trong CVAT chuyển sang status "validation"

Hướng dẫn này tập trung vào **Online Mode** - setup webhook server và cấu hình trong CVAT.

---

## 📋 Yêu cầu

Trước khi bắt đầu, đảm bảo bạn có:

- ✅ Python 3.10+ đã cài đặt
- ✅ Dự án LetmeQC đã clone và cài đặt dependencies (xem [README.md](README.md))
- ✅ Tài khoản CVAT với quyền admin/manager
- ✅ CVAT API Token (lấy từ **Profile → Settings → API Token**)

---

## 🚀 Bước 1: Cấu hình Environment

### 1.1 Tạo file `.env`

Copy file mẫu và điền thông tin:

```bash
# Từ thư mục dự án
cp .env.example .env
```

Mở `.env` và chỉnh sửa:

```ini
# === BẮT BUỘC === CVAT API Configuration
CVAT_API_URL=https://app.cvat.ai/api
CVAT_TOKEN=your_cvat_api_token_here

# === TÙY CHỌN === Webhook Configuration (cho security)
WEBHOOK_SECRET=your_super_secure_secret_key_123

# === TÙY CHỌN === QC Configuration (có thể override trong code)
MIN_BOX_AREA=100
IOU_THRESHOLD=0.95

# === TÙY CHỌN === Server Configuration
SERVER_HOST=0.0.0.0
SERVER_PORT=8000
```

**⚠️ QUAN TRỌNG:**

- `CVAT_TOKEN` **bắt buộc** - Lấy từ CVAT: **Profile → Settings → API Token**
- `WEBHOOK_SECRET` **khuyến nghị** - Để bảo vệ webhook khỏi các request không mong muốn
- Nếu dùng CVAT self-hosted (không phải app.cvat.ai), đổi `CVAT_API_URL` tương ứng

---

## 🌐 Bước 2: Chạy Webhook Server

### 2.1 Chạy server local

**Phương thức 1: Chạy trực tiếp với Python**

```bash
python app.py
```

**Phương thức 2: Chạy với uvicorn (recommended)**

```bash
uvicorn app:app --host 0.0.0.0 --port 8000 --reload
```

Server sẽ khởi động và hiển thị:

```
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
INFO:     Started reloader process [12345] using StatReloader
```

### 2.2 Verify server đang chạy

Mở trình duyệt hoặc dùng curl để test:

```bash
# Health check
curl http://localhost:8000/health

# Xem API documentation (Swagger UI)
# Mở: http://localhost:8000/docs

# Xem cấu hình hiện tại
curl http://localhost:8000/config
```

Kết quả expect:

```json
{
  "status": "healthy",
  "timestamp": "2024-10-13T10:00:00.000000",
  "cvat_api_configured": true,
  "qc_engine_ready": true
}
```

Nếu `cvat_api_configured` là `false`, kiểm tra lại `CVAT_TOKEN` trong `.env`.

---

## 🌍 Bước 3: Expose Server ra Internet với ngrok

CVAT cần gửi webhook đến server của bạn, nhưng server đang chạy local (`localhost:8000`). Bạn cần expose nó ra internet.

### 3.1 Cài đặt ngrok

1. Download ngrok từ: https://ngrok.com/download
2. Giải nén file
3. Thêm ngrok vào PATH hoặc chạy trực tiếp

**Windows:**

- Giải nén vào `C:\ngrok`
- Thêm `C:\ngrok` vào PATH

**Linux/Mac:**

```bash
# Giải nén và di chuyển
unzip ngrok.zip
mv ngrok /usr/local/bin/
```

### 3.2 Chạy ngrok

**Windows (PowerShell):**

```powershell
ngrok http 8000
```

**Linux/Mac:**

```bash
ngrok http 8000
```

Kết quả hiển thị:

```
ngrok by @inconshreveable

Session Status                online
Account                       Your Account (Plan: Free)
Version                       3.x.x
Region                        United States (us)
Web Interface                 http://127.0.0.1:4040
Forwarding                    https://abc123.ngrok.io -> http://localhost:8000

Connections                   ttl     opn     rt1     rt2     rt3     rt4
                              0       0       0.00    0.00    0.00    0.00
```

### 3.3 Lấy URL webhook

Từ output trên, bạn sẽ thấy dòng:

```
Forwarding: https://abc123.ngrok.io -> http://localhost:8000
```

**✅ URL webhook của bạn là:** `https://abc123.ngrok.io/webhook/cvat`

**📌 GHI NHỚ URL NÀY** - Bạn sẽ dùng nó trong bước tiếp theo.

### 3.4 ngrok Dashboard

Bạn có thể xem tất cả requests đến server qua ngrok dashboard:

- Mở: http://localhost:4040
- Xem đầy đủ request history
- Inspect payload, headers, response

---

## 🔗 Bước 4: Cấu hình Webhook trong CVAT

### 4.1 Đăng nhập CVAT

Mở trình duyệt và đăng nhập vào CVAT:

- https://app.cvat.ai (nếu dùng CVAT cloud)
- Hoặc URL của CVAT self-hosted

### 4.2 Đi đến Webhook Settings

Có 2 cách:

**Cách 1:**

1. Click vào avatar (góc phải trên) → **Webhooks**

**Cách 2:**

1. Click vào **Menu** (góc trái trên)
2. Chọn **Webhooks** (hoặc **Settings → Webhooks**)

### 4.3 Tạo Webhook mới

Click **Create Webhook** (hoặc **Add Webhook**)

### 4.4 Điền thông tin Webhook

| Field            | Value                                  | Ghi chú                               |
| ---------------- | -------------------------------------- | ------------------------------------- |
| **Name**         | `LetmeQC Auto QC`                      | Tên tuỳ ý, dễ nhận biết               |
| **URL**          | `https://abc123.ngrok.io/webhook/cvat` | URL từ ngrok (Bước 3.3)               |
| **Method**       | `POST`                                 | ✅ Bắt buộc chọn POST                 |
| **Content Type** | `application/json`                     | ✅ Bắt buộc chọn JSON                 |
| **Events**       | ✅ **Job: Updated**                    | Chọn sự kiện job update               |
| **Secret Key**   | `your_super_secure_secret_key_123`     | Giá trị của WEBHOOK_SECRET trong .env |

**⚠️ QUAN TRỌNG:**

- URL **phải đúng chính xác** (bao gồm `https://` và `/webhook/cvat`)
- Nếu bạn set `WEBHOOK_SECRET` trong `.env`, hãy điền cùng giá trị vào **Secret Key**
- Nếu không set `WEBHOOK_SECRET`, có thể để trống

### 4.5 Test Webhook

Trước khi save, bạn có thể test webhook:

1. Trong CVAT, **tạo 1 job mới** (hoặc dùng job hiện có)
2. **Thêm một vài annotations** (hoặc dùng job có sẵn annotations)
3. **Chuyển status job sang "validation"**
   - Vào job detail page
   - Click **"Actions"** → **"Change status"** → **"Validation"**

4. **Kiểm tra terminal** chạy `app.py`:
   ```
   2024-10-13 10:00:00 - INFO - 📥 Received webhook payload
   2024-10-13 10:00:00 - INFO - 🔔 Job Update: ID=123 | Name='test_job' | Status='validation' | Assignee=456
   2024-10-13 10:00:01 - INFO - 🚀 Starting automatic QC process for Job 123...
   ```

Nếu thấy logs trên, **webhook đã hoạt động thành công!**

### 4.6 Save Webhook

Sau khi test thành công, click **Save** (hoặc **Create**) để lưu webhook.

---

## 🎯 Bước 5: Workflow Hoạt Động

Khi mọi thứ đã setup xong, workflow sẽ hoạt động như sau:

```
1. Annotator hoàn thành annotation trên 1 job
   ↓
2. Annotator/Reviewer chuyển job sang status "validation"
   ↓
3. CVAT tự động gửi webhook POST request đến:
   https://abc123.ngrok.io/webhook/cvat
   ↓
4. LetmeQC server nhận request:
   - Parse payload (job_id, status, assignee, ...)
   - Kiểm tra event có phải "update:job" không
   - Kiểm tra status có phải "validation" không
   ↓
5. Nếu status là "validation":
   a) Fetch annotations từ CVAT API (/api/jobs/{id}/annotations)
   b) Fetch labels mapping (/api/labels?job_id={id})
   c) Parse dữ liệu thành Frame objects
   d) Chạy QC checks với QCRulesEngine
   ↓
6. Xử lý kết quả:

   🟢 NẾU KHÔNG CÓ LỖI (QC Pass):
   - Server trả về: {"action": "approved"}
   - Job giữ status "validation"
   - Sẵn sàng cho review/approval

   🔴 NẾU CÓ LỖI (QC Fail):
   - Server tự động:
     * Tạo issue trong CVAT cho mỗi frame có lỗi
     * Comment của issue chứa: số lượng lỗi, loại lỗi, frame
     * Gắn issue cho assignee của job
   - Server tự động đổi status job về "annotation"
   - Annotator nhận được issue và sửa lỗi
   - Server trả về: {"action": "rejected", "errors": [...]}
```

---

## 🛡️ Webhook Security (Tùy chọn)

### Sử dụng WEBHOOK_SECRET

Để bảo vệ webhook khỏi các request giả mạo, bạn có thể cấu hình secret key:

1. Trong `.env`:

   ```ini
   WEBHOOK_SECRET=your_super_secure_secret_key_123
   ```

2. Trong CVAT webhook settings:
   - Điền cùng giá trị vào **Secret Key** field

3. CVAT sẽ gửi header:

   ```
   X-CVAT-Webhook-Secret: your_super_secure_secret_key_123
   ```

4. Server sẽ verify header với giá trị trong `.env`

**Nếu secret không khớp**, server trả về:

```
401 Unauthorized: Invalid webhook secret
```

### Cấu hình HTTPS

Ngrok tự động cung cấp HTTPS endpoint. Nếu bạn deploy server trên production (không dùng ngrok), đảm bảo:

- Server chạy với HTTPS (không HTTP)
- Có SSL certificate hợp lệ
- CVAT chỉ gửi webhook đến HTTPS endpoints

---

## 🔧 Custom Configuration

### Thay đổi QC Thresholds

Bạn có thể thay đổi thresholds trong `.env`:

```ini
# Diện tích bbox tối thiểu (pixels)
MIN_BOX_AREA=150

# Ngưỡng IoU cho overlap detection (0-1)
IOU_THRESHOLD=0.90
```

Hoặc override trực tiếp trong code `app.py`:

```python
qc_engine = QCRulesEngine(
    min_box_area=150,
    iou_threshold=0.90
)
```

### Thay đổi Required Attributes

Trong `src/rules.py`, bạn có thể cấu hình các attribute bắt buộc:

```python
# Frame-level required tags
self.required_frame_tags = ["weather", "time_of_day"]

# Object-level required attributes
self.required_obj_attrs = {
    "car": ["occluded", "truncated"],
    "pedestrian": ["occluded"]
}
```

### Custom QC Rules

Bạn có thể thêm custom rules vào `QCRulesEngine`:

```python
# Trong src/rules.py
def _check_custom_rule(self, frame: Frame) -> List[Dict]:
    errors = []
    # Thêm logic kiểm tra custom
    for box in frame.bboxes:
        if box.label == "person" and box.ytl > frame.height * 0.8:
            errors.append(self._format_error(
                frame.name, box.id, "Person_Too_Low",
                "Person bbox ở phần dưới 20% của ảnh"
            ))
    return errors

# Gọi trong _check_single_frame
def _check_single_frame(self, frame: Frame) -> List[Dict]:
    frame_errors = []
    # ... existing checks
    frame_errors.extend(self._check_custom_rule(frame))
    return frame_errors
```

---

## 🐛 Troubleshooting

### ✅ Common Issues & Solutions

| Vấn đề                        | Nguyên nhân               | Giải pháp                                                                                             |
| ----------------------------- | ------------------------- | ----------------------------------------------------------------------------------------------------- |
| **Webhook không đến server**  | ngrok không chạy          | Kiểm tra `ngrok http 8000` đang chạy                                                                  |
|                               | URL sai                   | Kiểm tra URL webhook trong CVAT                                                                       |
|                               | Firewall chặn             | Tắt firewall tạm thời hoặc cho phép port 8000                                                         |
| **401 Unauthorized**          | WEBHOOK_SECRET không khớp | Kiểm tra secret trong `.env` và CVAT                                                                  |
|                               | Không gửi secret header   | Đảm bảo CVAT gửi `X-CVAT-Webhook-Secret`                                                              |
| **500 Internal Server Error** | CVAT_TOKEN sai            | Kiểm tra `CVAT_TOKEN` trong `.env`                                                                    |
|                               | CVAT_API_URL sai          | Kiểm tra `CVAT_API_URL`                                                                               |
|                               | Job không có annotations  | Job trống hoặc chưa được annotate                                                                     |
| **ConnectionError**           | Mạng không ổn định        | Kiểm tra kết nối internet                                                                             |
|                               | CVAT API không trả về     | Thử access API thủ công: `curl -H "Authorization: Token YOUR_TOKEN" https://app.cvat.ai/api/jobs/123` |
| **ModuleNotFoundError**       | Thiếu dependencies        | `pip install -r requirements.txt`                                                                     |

### 🔍 Debug Webhook

#### 1. Kiểm tra ngrok Inspector

Mở: http://localhost:4040

- Xem tất cả requests đến server
- Kiểm tra request body, headers, response
- Kiểm tra status code

#### 2. Kiểm tra Server Logs

Server in ra đầy đủ logs trên terminal:

```
2024-10-13 10:00:00 - INFO - 📥 Received webhook payload
2024-10-13 10:00:00 - INFO - Job Update: ID=123 | Status=validation
2024-10-13 10:00:01 - INFO - Fetching annotations for Job 123...
2024-10-13 10:00:02 - INFO - Successfully parsed 10 frames
2024-10-13 10:00:03 - INFO - QC Result: 0 errors found
```

Nếu có lỗi, sẽ thấy traceback đầy đủ.

#### 3. Test Webhook Thủ Công

Sử dụng curl để test webhook endpoint:

```bash
# Test ping event
curl -X POST http://localhost:8000/webhook/cvat \
  -H "Content-Type: application/json" \
  -d '{"event": "ping"}'

# Test update:job event
curl -X POST http://localhost:8000/webhook/cvat \
  -H "Content-Type: application/json" \
  -H "X-CVAT-Webhook-Secret: your_super_secure_secret_key_123" \
  -d '{
    "event": "update:job",
    "job": {
      "id": 123,
      "status": "validation",
      "name": "test_job",
      "assignee": {"id": 456}
    }
  }'
```

Expect response:

```json
{
  "message": "QC passed - No errors found",
  "job_id": 123,
  "action": "approved",
  ...
}
```

#### 4. Kiểm tra CVAT API

Thử fetch annotations thủ công:

```bash
curl -H "Authorization: Token YOUR_CVAT_TOKEN" \
  https://app.cvat.ai/api/jobs/123/annotations | python -m json.tool
```

Nếu trả về JSON annotations, API đang hoạt động tốt.

---

## 📚 API Reference

### LetmeQC Webhook Server Endpoints

| Method | Endpoint        | Mô tả                          |
| ------ | --------------- | ------------------------------ |
| GET    | `/`             | Service info                   |
| GET    | `/health`       | Health check                   |
| GET    | `/config`       | Hiển thị cấu hình hiện tại     |
| GET    | `/docs`         | Swagger UI (API documentation) |
| POST   | `/webhook/cvat` | CVAT webhook endpoint          |

### CVAT API Endpoints

| Endpoint                     | Method | Mô tả                         | Authentication |
| ---------------------------- | ------ | ----------------------------- | -------------- |
| `/api/jobs`                  | GET    | Lấy danh sách jobs            | Token          |
| `/api/jobs/{id}`             | GET    | Lấy thông tin job             | Token          |
| `/api/jobs/{id}`             | PATCH  | Cập nhật job status           | Token          |
| `/api/jobs/{id}/annotations` | GET    | Lấy annotations (COCO format) | Token          |
| `/api/labels`                | GET    | Lấy danh sách labels          | Token          |
| `/api/labels?job_id={id}`    | GET    | Lấy labels cho job            | Token          |
| `/api/issues`                | POST   | Tạo issue mới                 | Token          |
| `/api/issues`                | GET    | Lấy danh sách issues          | Token          |

**Authentication Header:**

```
Authorization: Token YOUR_CVAT_TOKEN
```

---

## 🏃 Example Workflow

### Scenario: Annotator Submit Job for Review

**1. Annotator hoàn thành annotation**

- Job ID: 456
- Status: "annotation" → **chuyển sang "validation"**

**2. CVAT gửi webhook**

```json
POST https://abc123.ngrok.io/webhook/cvat
Content-Type: application/json
X-CVAT-Webhook-Secret: your_super_secure_secret_key_123

{
  "event": "update:job",
  "job": {
    "id": 456,
    "status": "validation",
    "name": "traffic_signs_001",
    "assignee": {"id": 789}
  }
}
```

**3. LetmeQC xử lý**

```
- Parse payload: job_id=456, status=validation
- Fetch annotations từ CVAT API
- Parse annotations thành 50 frames
- Chạy QC checks với min_box_area=100, iou_threshold=0.95
- Phát hiện 3 lỗi:
  * Frame 0: Bbox quá nhỏ (diện tích 50px)
  * Frame 5: Hai bbox "car" overlap (IoU=0.98)
  * Frame 10: Polygon self-intersect
```

**4. LetmeQC tạo issues**

```
- Tạo issue cho frame 0:
  * Job: 456
  * Frame: 0
  * Comment: "QC Check Failed: 1 error(s) found\nError types: Bbox_Too_Small\nFrame: 0"
  * Assignee: 789

- Tạo issue cho frame 5:
  * Job: 456
  * Frame: 5
  * Comment: "QC Check Failed: 1 error(s) found\nError types: Bbox_Overlap\nFrame: 5"
  * Assignee: 789

- Tạo issue cho frame 10:
  * Job: 456
  * Frame: 10
  * Comment: "QC Check Failed: 1 error(s) found\nError types: Polygon_Self_Intersect\nFrame: 10"
  * Assignee: 789
```

**5. LetmeQC cập nhật job status**

```
PATCH https://app.cvat.ai/api/jobs/456
Authorization: Token YOUR_CVAT_TOKEN

{
  "status": "annotation"
}
```

**6. Kết quả**

- ✅ Annotator (ID: 789) nhận được 3 issues
- ✅ Job 456 quay trở lại status "annotation"
- ✅ Annotator có thể xem issues và sửa lỗi

---

## 🎉 Production Deployment

Khi deploy lên production (không dùng ngrok), bạn có thể:

### Option 1: Deploy trên VPS (DigitalOcean, AWS, etc.)

```bash
# SSH vào server
ssh user@your-server-ip

# Clone repository
git clone <repository-url>
cd LetmeQC

# Tạo virtual environment
python -m venv venv
source venv/bin/activate

# Cài dependencies
pip install -r requirements.txt

# Chạy với gunicorn + nginx (recommended)
# Hoặc chạy trực tiếp:
uvicorn app:app --host 0.0.0.0 --port 8000
```

### Option 2: Deploy với Docker

**Tạo Dockerfile:**

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
```

**Build & Run:**

```bash
docker build -t letmeqc .
docker run -p 8000:8000 --env-file .env letmeqc
```

### Option 3: Deploy trên Kubernetes

Tham khảo: https://fastapi.tiangolo.com/deployment/

---

## 📖 Tài liệu liên quan

- [README.md](README.md) - Hướng dẫn tổng quan về dự án
- [CVAT Documentation](https://docs.cvat.ai/en/latest/)
- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [ngrok Documentation](https://ngrok.com/docs)

---

## 💡 Tips & Best Practices

### 1. Sử dụng ngrok hiệu quả

- **Free plan**: Có giới hạn requests (40 connections/minute)
- **Paid plan**: Không giới hạn, custom subdomains
- **Reconnect**: ngrok free tunnel thay đổi URL sau mỗi lần restart
- **Alternative**: Sử dụng [localtunnel](https://localtunnel.github.io/www/) hoặc [serveo](https://serveo.net/)

### 2. Monitor Webhook

- Sử dụng **ngrok inspector** (http://localhost:4040) để debug
- Log tất cả webhook requests đến file:
  ```python
  # Trong app.py
  import logging
  logging.basicConfig(
      level=logging.INFO,
      format="%(asctime)s - %(levelname)s - %(message)s",
      handlers=[
          logging.FileHandler("webhook.log"),
          logging.StreamHandler()
      ]
  )
  ```

### 3. Handling Large Jobs

- Job có nhiều frames (>1000) có thể khiến QC chậm
- Consider:
  - Tăng timeout cho requests
  - Chạy QC trên subset frames
  - Optimize QC rules

### 4. Custom Error Messages

Bạn có thể custom message trong `src/rules.py`:

```python
def _format_error(self, frame_name: str, obj_id: any, error_type: str, message: str) -> Dict:
    return {
        "Frame": frame_name,
        "Object_ID": obj_id,
        "Error_Type": error_type,
        "Message": message,
        "Severity": "high" if error_type in ["Bbox_Out_Of_Bounds"] else "medium",
        "Suggestion": self._get_suggestion(error_type)
    }
```

---

## 🚨 Warning & Notes

1. **ngrok Free Tunnel**: URL sẽ thay đổi sau mỗi lần restart. Cần cập nhật webhook URL trong CVAT.
2. **CVAT Token Security**: Không bao giờ commit `CVAT_TOKEN` vào repository. Sử dụng `.gitignore`.
3. **Rate Limiting**: CVAT API có rate limit. Nếu có nhiều jobs, consider thêm delay giữa các request.
4. **Error Handling**: Server đã handle hầu hết errors, nhưng vẫn có thể có edge cases.
5. **Webhook Payload**: CVAT có thể gửi nhiều loại event. Server chỉ xử lý `update:job` và `ping`.
