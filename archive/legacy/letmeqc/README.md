# LetmeQC (phiên bản đầu, đã tắt)

LetmeQC là phiên bản đầu tiên của công cụ QC nhãn của nhóm. Nó chỉ kiểm nhãn bằng **luật**, không dùng model:

- **Webhook server** (`app.py`, FastAPI): CVAT gọi vào khi job đổi trạng thái. Tool đọc nhãn qua API, kiểm bằng luật, tạo Issue và trả job về annotation.
- **Bản dòng lệnh** (`src/main.py`): kiểm file COCO JSON.
- **Luật** (`src/rules.py`):
  - Box ra ngoài ảnh, box quá nhỏ, tỉ lệ cực đoan.
  - Polygon dưới 3 điểm, polygon xoắn, mask tràn ra ngoài box.
  - Trùng / chồng box, thiếu thuộc tính bắt buộc, người nằm trong xe.

## Trạng thái: đã tắt (2026-10-16)

Toàn bộ luật của LetmeQC đã được gộp vào Web QC (`../rule_tier.py`). Web QC còn có thêm:
- So nhãn với model (4 detector + SAM2 + CLIP).
- Tự review khi job sang validation.
- Issue gộp theo vật.

LetmeQC và Web QC cùng nhận sự kiện từ CVAT và cùng dùng cổng 8000. Chạy cả hai thì một job bị review hai lần và có Issue trùng. Vì vậy `app.py` tự thoát nếu không đặt biến `LETMEQC_ENABLE=1`.

**Dùng Web QC thay cho LetmeQC:** xem [README của repo](../README.md) và [tổng quan dự án](../TONG_QUAN_DU_AN.md).

## Chạy lại để so sánh

```bat
cd letmeqc
pip install -r requirements.txt
copy .env.example .env        :: điền CVAT_API_URL, CVAT_TOKEN
set LETMEQC_ENABLE=1
python app.py
```

Bản dòng lệnh không cần CVAT:

```bat
python src/main.py <file_coco.json> --min-area 100 --iou-threshold 0.95 --output loi.json -v
```

Lưu ý:
- Thư mục `tests/` của LetmeQC chưa có test nào.
- 2026-10-17 đã sửa 3 lỗi làm LetmeQC không chạy được: thiếu `import List` (`src/error_templates.py`), hàm `parse_coco_json` của bản dòng lệnh bị xoá ở commit `743930d` (đã khôi phục), lỗi thiếu thuộc tính chưa có mẫu lời nhắn. Thêm `shapely` vào `requirements.txt`. Đã chạy thử: bản dòng lệnh báo đúng lỗi, `app.py` nạp được (khi đặt `LETMEQC_ENABLE=1`).

## Tài liệu của LetmeQC

- [CVAT_WEBHOOK_GUIDE.md](CVAT_WEBHOOK_GUIDE.md): cài webhook trên CVAT.
- [docs/](docs/): API CVAT, cách làm luật, bài học rút ra, mẫu tài liệu.
- [DEVELOPMENT.md](DEVELOPMENT.md), [TODO.md](TODO.md), [PLAN_SUMMARY.md](PLAN_SUMMARY.md): kế hoạch phát triển cũ (trước khi gộp vào Web QC).

Nguồn gốc: repo nhóm `github.com/Sleeplessmen/LetmeQC`.
