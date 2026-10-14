# CVAT 2D — gán nhãn tự động và QC nhãn

Bộ tool cho nhãn 2D trên CVAT:

- **Web QC** (`web_qc/`, chạy `web_qc.bat`): review nhãn của labeler thay người review. Tool tìm lỗi sai kích thước, sai nhãn, thiếu, thừa, trùng, vi phạm guideline, rồi ghi chú lên CVAT bằng **Issue**. Tool không sửa nhãn.
- **Gán nhãn chất lượng cao** (`label_hq_2d.py`): 4 detector + SAM2 + CLIP.
- Các tool phụ: `review.bat` (QC bằng dòng lệnh), `review_web.bat` (bản QC Gradio cũ), `menu.bat`.

**Tài liệu đầy đủ:** [web_qc/TAI_LIEU_WEB_QC.md](web_qc/TAI_LIEU_WEB_QC.md). Tài liệu gồm cài đặt, hướng dẫn dùng, guideline và file luật, cách tool tìm lỗi, xử lý lỗi, phần kỹ thuật.

## Cài nhanh

1. Repo này là thư mục `cvat_2d/` bên trong một bản [SAM2](https://github.com/facebookresearch/sam2). Cài SAM2 vào môi trường `venv` theo hướng dẫn của SAM2, rồi tải checkpoint về `checkpoints/sam2.1_hiera_large.pt`.
2. Cài thư viện:
   ```
   venv\Scripts\pip install -r cvat_2d\requirements.txt
   ```
3. Đặt các file model vào `cvat_2d/`. Chúng không có trong repo vì quá lớn:
   - `yolo11x.pt`, `rtdetr-x.pt`, `yolov8x-seg.pt`: Ultralytics tự tải khi chạy lần đầu nếu thiếu.
   - D-FINE-X và CLIP: tự tải từ HuggingFace khi chạy lần đầu.
4. Chép `.env.example` thành `.env`, rồi điền `CVAT_URL`, `CVAT_TOKEN`, `CVAT_TASK_ID`, `CVAT_JOB_ID`.
5. Chạy `web_qc.bat` rồi mở `http://localhost:8000`. Muốn máy khác cùng mạng vào được thì chạy `web_qc.bat --lan`.

## Không có trong repo

- Token (`.env`).
- File model.
- Dữ liệu ảnh, cache, kết quả review.
- Cơ sở dữ liệu của web QC (`web_qc/data/`).
