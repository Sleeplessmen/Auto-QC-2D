# Tạo link website public từ số 0

Tài liệu này mô tả đường đi ngắn nhất để đưa Auto-QC-2D lên Internet cho
người dùng cuối:

```text
GitHub -> Vercel (frontend)
             |
             +-- /api/* -> HTTPS -> VPS (FastAPI + worker + model)
                                      |
                                      +-- CVAT Cloud
```

Kết quả cuối cùng:

- `https://app.<domain-cua-ban>`: giao diện người dùng.
- `https://api.<domain-cua-ban>/health`: backend health check.

Vercel chỉ chạy frontend tĩnh. Không chạy model, worker, SQLite hoặc CVAT
token trên Vercel.

## 0. Chuẩn bị thông tin

Bạn cần:

- Tài khoản GitHub có quyền đọc repository.
- Tài khoản Vercel.
- Một domain riêng.
- Một VPS Ubuntu có IPv4 tĩnh. Bắt đầu bằng CPU để tiết kiệm; nâng cấp sang
  VPS/cloud GPU khi latency model không đáp ứng.
- Tài khoản CVAT Cloud.
- Email hoặc Slack/Teams để nhận cảnh báo.
- Một bucket object storage để backup.

Nên bật 2FA cho GitHub, Vercel, nhà cung cấp domain, VPS và CVAT.

## 1. Mua domain và chọn server

Chọn domain ngắn, dễ đọc, ví dụ `qc-example.com`. Không cần mua domain ở
Vercel; mua ở registrar có DNS dễ quản lý.

Chọn VPS theo thứ tự ưu tiên:

1. Ubuntu 22.04/24.04, IPv4 tĩnh.
2. RAM đủ cho dependency/model đang dùng.
3. SSD riêng cho database, review output và model cache.
4. Có thể mở rộng sang NVIDIA GPU nếu CPU quá chậm.

Không chọn Vercel serverless, shared hosting hoặc server không có persistent
disk cho backend này.

## 2. Tạo DNS records

Sau khi có domain và biết IP VPS:

```text
api.<domain-cua-ban>  A      <IPv4-cua-VPS>
app.<domain-cua-ban>  CNAME  <hostname-Vercel-do-Vercel-cung-cap>
```

Tạm thời không cần tạo `www`. Sau khi DNS cập nhật, kiểm tra:

```bash
nslookup api.<domain-cua-ban>
```

Tên `api.<domain>` phải trả đúng IP VPS trước khi cấp certificate backend.

## 3. Cài VPS backend

Đăng nhập VPS bằng SSH key, không dùng password root cho deploy thường ngày:

```bash
sudo apt-get update
sudo apt-get upgrade -y
sudo apt-get install -y ca-certificates curl git ufw nginx

sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw --force enable

sudo adduser --disabled-password --gecos "" qcdeploy
sudo usermod -aG sudo qcdeploy
sudo mkdir -p /opt/auto-qc-2d
sudo chown -R qcdeploy:qcdeploy /opt/auto-qc-2d
```

Cài Docker Engine và Docker Compose plugin theo tài liệu chính thức của
Docker cho Ubuntu. Sau khi đăng nhập lại bằng `qcdeploy`, kiểm tra:

```bash
docker --version
docker compose version
```

Nếu dùng GPU, cài NVIDIA driver + NVIDIA Container Toolkit phù hợp rồi kiểm
tra:

```bash
nvidia-smi
```

## 4. Lấy code đúng phiên bản

Production phải chạy commit/tag đã kiểm thử, không chạy branch đang thay đổi:

```bash
git clone https://github.com/Sleeplessmen/Auto-QC-2D.git /opt/auto-qc-2d
cd /opt/auto-qc-2d
git checkout <commit-hoac-tag-da-kiem-thu>
```

Kiểm tra các file bắt buộc:

```bash
test -f deploy/docker/Dockerfile
test -f deploy/compose/docker-compose.production.yml
test -f .env.production.example
test -f apps/web/vercel.json
```

## 5. Tạo secrets backend

```bash
cd /opt/auto-qc-2d
cp .env.production.example .env.production
chmod 600 .env.production
nano .env.production
```

Điền các giá trị sau, thay toàn bộ hostname mẫu:

```dotenv
CVAT_URL=https://app.cvat.ai
CVAT_TOKEN=<token-tao-trong-CVAT>
CVAT_ORG=<organization-slug-neu-co>
WEB_QC_ADMIN_PASSWORD=<mat-khau-dai-va-ngau-nhien>

QC_PUBLIC_BASE_URL=https://api.<domain-cua-ban>
QC_CORS_ORIGINS=https://app.<domain-cua-ban>
QC_SESSION_SAME_SITE=lax
QC_SESSION_SECURE=true

QC_DATA_DIR=/var/lib/auto-qc-2d/data
QC_REVIEW_OUTPUT_DIR=/var/lib/auto-qc-2d/review
QC_ARTIFACT_DIR=/var/lib/auto-qc-2d/artifacts
QC_MODEL_CACHE_DIR=/var/lib/auto-qc-2d/models
```

Không đặt `CVAT_TOKEN` trong Vercel. Không commit file `.env.production`.

## 6. Build và chạy backend

```bash
docker compose -f deploy/compose/docker-compose.production.yml config
docker compose -f deploy/compose/docker-compose.production.yml up -d --build
docker compose -f deploy/compose/docker-compose.production.yml ps
docker compose -f deploy/compose/docker-compose.production.yml logs --tail=200 qc
```

Kiểm tra trực tiếp trên VPS:

```bash
curl -fsS http://127.0.0.1:8000/health
```

Kết quả đúng:

```json
{"status":"ok"}
```

Nếu container lỗi import dependency/model, dừng ở đây và sửa Dockerfile hoặc
quy trình nạp model. Không bỏ qua lỗi để tiếp tục cấu hình DNS.

Lần chạy đầu tạo file mật khẩu admin tạm trong volume data. Đăng nhập lần đầu,
đổi mật khẩu trong **Cài đặt**, rồi xóa file tạm khỏi volume.

## 7. Bật HTTPS cho backend

Dùng Nginx/Caddy/Traefik làm reverse proxy. Có mẫu Nginx tại
`deploy/reverse_proxy/nginx.conf.example`.

Các yêu cầu bắt buộc:

- `http://api.<domain>` redirect sang HTTPS.
- Proxy tới `127.0.0.1:8000`.
- `client_max_body_size` đủ lớn cho file export CVAT.
- Timeout dài cho review và upload.
- Truyền `X-Forwarded-Proto`, `X-Forwarded-Host`, `X-Real-IP`.
- Cấu hình certificate Let's Encrypt.
- Không public port 8000 sau khi proxy hoạt động.

Kiểm tra từ máy cá nhân:

```bash
curl -fsS https://api.<domain-cua-ban>/health
```

Chỉ chuyển bước tiếp theo khi lệnh trên trả HTTP 200 và JSON `status=ok`.

## 8. Tạo project Vercel

Trong Vercel:

1. Chọn **Add New Project** → import repository GitHub.
2. Đặt **Root Directory** là `apps/web`.
3. Đặt **Output Directory** là `static`.
4. Để **Build Command** trống.
5. Thêm domain production `app.<domain-cua-ban>`.
6. Sửa `apps/web/vercel.json`, thay `api.example.com` bằng hostname backend
   thật.
7. Deploy preview trước.
8. Chỉ promote production sau khi preview chạy đủ checklist.

Vercel rewrite phải có dạng:

```json
{
  "rewrites": [
    {
      "source": "/api/:path*",
      "destination": "https://api.<domain-cua-ban>/api/:path*"
    }
  ]
}
```

Không đặt URL có dấu `/` thừa ở cuối. Nếu dùng nhiều Vercel preview trực tiếp
cross-origin thay vì rewrite, phải thêm từng origin preview vào
`QC_CORS_ORIGINS`; production nên chỉ allowlist domain chính.

## 9. Kiểm tra link website

Mở:

```text
https://app.<domain-cua-ban>/
https://app.<domain-cua-ban>/#tab=settings
```

Kiểm tra theo thứ tự:

1. Trang login hiển thị.
2. Login sai trả thông báo bình thường, không lộ traceback.
3. Login đúng vào được dashboard.
4. Refresh trình duyệt vẫn giữ session.
5. Logout hoạt động.
6. Mở trực tiếp hash URL vẫn hiển thị đúng trang.
7. `/api/setup` đi qua Vercel rewrite và trả response.
8. Tạo kết nối CVAT, bấm **Thử kết nối**.
9. Chọn job test, chạy review.
10. Push một Issue test lên CVAT.
11. Mở link report từ frontend và tải CSV/preview.

Nếu login bị lặp:

- kiểm tra `QC_SESSION_SECURE=true`;
- kiểm tra backend thật sự chạy HTTPS;
- kiểm tra `QC_PUBLIC_BASE_URL`;
- kiểm tra Vercel rewrite không trỏ sai hostname;
- kiểm tra `QC_CORS_ORIGINS` đúng domain, không có khoảng trắng thừa.

## 10. Kết nối CVAT Cloud

Trong CVAT:

1. Tạo personal access token có quyền tối thiểu cần thiết.
2. Trong Web QC mở **Kết nối CVAT**.
3. Nhập URL CVAT, organization và token.
4. Bấm **Thử kết nối**.
5. Lưu và chọn connection mặc định.
6. Đọc một job test.
7. Review và push một Issue.
8. Push lại để kiểm tra không tạo Issue trùng.

Chỉ bật **Tự review khi job chuyển sang validation** sau khi manual flow đã
thành công.

## 11. Backup và khả năng khôi phục

Backup cùng lúc:

- SQLite database.
- `secret.key`.
- Guidelines/uploads.
- Review outputs.
- Manifest/version model.

Không backup riêng database mà bỏ `secret.key`, vì token CVAT được mã hóa bằng
khóa này.

Tạo backup dừng service để có snapshot nhất quán:

```bash
docker compose -f deploy/compose/docker-compose.production.yml stop qc
tar -czf /tmp/auto-qc-2d-backup-$(date -u +%Y%m%dT%H%M%SZ).tgz \
  /var/lib/auto-qc-2d/data /var/lib/auto-qc-2d/review
docker compose -f deploy/compose/docker-compose.production.yml start qc
```

Upload archive đã mã hóa lên object storage. Thử restore trên máy khác trước
khi coi backup là hợp lệ.

## 12. Monitoring và deploy lần sau

Theo dõi tối thiểu:

```bash
docker compose -f deploy/compose/docker-compose.production.yml ps
docker compose -f deploy/compose/docker-compose.production.yml logs -f qc
docker stats
df -h
```

Khi deploy bản mới:

```bash
git fetch --tags origin
git checkout <commit-moi>
docker compose -f deploy/compose/docker-compose.production.yml config
docker compose -f deploy/compose/docker-compose.production.yml up -d --build
curl -fsS https://api.<domain-cua-ban>/health
```

Giữ image/commit trước đó để rollback. Nếu health hoặc smoke test fail:

```bash
git checkout <commit-cu>
docker compose -f deploy/compose/docker-compose.production.yml up -d --build
```

Không dùng rollback code để thay thế migration database; schema phải tương
thích với cả bản cũ và bản mới.

## Checklist kết thúc

- [ ] Domain đã mua và DNS resolve đúng.
- [ ] `api.<domain>/health` trả 200 qua HTTPS.
- [ ] Frontend Vercel mở được.
- [ ] Login/session/logout hoạt động.
- [ ] CVAT connection và Issue push hoạt động.
- [ ] Backend tự restart sau container restart.
- [ ] Data/model/review output không mất sau rebuild.
- [ ] Backup đã upload và restore thử thành công.
- [ ] Có monitoring/alert.
- [ ] Có commit/image trước đó để rollback.
