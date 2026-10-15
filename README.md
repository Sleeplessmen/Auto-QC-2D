# CVAT 2D — gán nhãn tự động và QC nhãn

Bộ tool cho nhãn 2D trên CVAT:

- **Web QC** (`web_qc/`, chạy `web_qc.bat`): review nhãn của labeler thay người review, rồi ghi chú lên CVAT bằng **Issue**. Tool không sửa nhãn. Tool tìm các lỗi:
  - Box: sai kích thước, hình dạng phi lý (quá dẹt / quá mảnh), sai nhãn, thiếu, thừa, trùng.
  - Vùng đường (`drivable_area`, polygon / mask): tô thiếu, tô thừa, vẽ trùng. Tool so với model phân vùng mặt đường.
  - Một vật vừa có mask vừa có box.
  - Vi phạm guideline.
- **Gán nhãn chất lượng cao** (`label_hq_2d.py`): 4 detector + SAM2 + CLIP.
- Các tool phụ: `review.bat` (QC bằng dòng lệnh), `review_web.bat` (bản QC Gradio cũ), `menu.bat`.

**Tài liệu đầy đủ:** [web_qc/TAI_LIEU_WEB_QC.md](web_qc/TAI_LIEU_WEB_QC.md). Tài liệu gồm cài đặt, hướng dẫn dùng, guideline và file luật, cách tool tìm lỗi, xử lý lỗi, phần kỹ thuật.

## Cài đặt (máy Windows mới)

Cần có:

- Windows 10/11 và Python 3.11–3.13. Khi cài Python, tick "Add python.exe to PATH".
- Git.
- GPU NVIDIA. Không có GPU vẫn chạy được nhưng rất chậm.
- Khoảng 10 GB ổ trống.

**Quan trọng:** repo này phải nằm **bên trong một bản SAM2**, ở thư mục `sam2\cvat_2d`. Tool dùng thư viện SAM2 ở thư mục cha. Nếu clone riêng ra một chỗ thì web vẫn mở được, nhưng bấm Đánh giá sẽ lỗi.

```
git clone https://github.com/facebookresearch/sam2.git
cd sam2
git clone https://github.com/letuan2k2/cvat-2d-qc.git cvat_2d
cvat_2d\cai_dat.bat
```

`cai_dat.bat` làm hết các bước. Lần đầu mất khoảng 15–30 phút, cần Internet:

- Tạo môi trường `venv`.
- Cài torch bản GPU và các thư viện.
- Tải model, khoảng 3 GB:
  - SAM2.1 large.
  - YOLO11x, RT-DETR-x, YOLOv8x-seg.
  - D-FINE-X, CLIP, SegFormer.

## Chạy web QC

1. Chạy `cvat_2d\web_qc.bat`, rồi mở `http://localhost:8000`. Muốn máy khác cùng mạng vào được thì chạy `web_qc.bat --lan`.
2. Đăng nhập `admin`. Mật khẩu lần đầu nằm trong `cvat_2d\web_qc\data\MAT_KHAU_ADMIN.txt`.
3. Vào **Kết nối CVAT** → **Thêm kết nối**, nhập địa chỉ CVAT và token. Token tạo trên CVAT ở **Profile → Security → Personal Access Tokens**. Bấm **Thử kết nối** rồi **Lưu kết nối**.
4. Vào **Review job**, bấm **Chọn** để chọn job, rồi bấm **Đánh giá**.
5. Xem lỗi, bấm **Tool nhầm** ở lỗi tool báo sai, rồi bấm **Đẩy Issue lên CVAT**.

## Tự review khi labeler nộp job

Vào **Cài đặt → Tự review khi job chuyển sang validation**, tick **Bật**, chọn CVAT rồi bấm **Lưu cài đặt**.

- Labeler gán xong và chuyển stage của job sang **validation**. Trong vòng 60 giây, web tự đọc job, review, rồi đẩy lỗi chắc chắn lên CVAT thành Issue.
- Job bị trả về annotation, rồi labeler nộp lại validation, thì tool review lại.
- Web tự hỏi CVAT nên không cần webhook hay cấu hình mạng.

Tool không cần đáp án (ground truth) để review job thật. Tool tự nhìn ảnh bằng model, rồi so với nhãn labeler. Đáp án chỉ dùng để đo độ chính xác của tool (xem dưới).

Chế độ **Phân tích** trên trang Review job vẽ chồng lên ảnh những gì tool thấy (vật phát hiện, mặt đường), đặt cạnh nhãn của labeler. Người review nhìn vào đó để kiểm chứng kết quả.

## Đo độ chính xác của tool

`review_eval.py` dùng bộ ảnh có đáp án. Nó cố ý cài lỗi vào nhãn đúng (sai kích thước, sai nhãn, thiếu, thừa, trùng, box dẹt), rồi đo tool bắt được bao nhiêu, báo nhầm bao nhiêu, và bao nhiêu % khung hình được review đúng. Kết quả được chia theo điều kiện ảnh: ngày / đêm / hoàng hôn, trời quang / mưa / tuyết.

```
venv\Scripts\python cvat_2d\review_eval.py --images <thu muc anh> --gt <thu muc dap an json> --meta <dieu_kien.json>
```

- Mỗi file đáp án có dạng `{"image": "ten.jpg", "objects": [{"cls": "car", "box": [x1, y1, x2, y2]}]}`.
- `--meta` là file `{ten anh: {timeofday, weather}}`, ví dụ trích từ nhãn của BDD100K.
- `--cond dem` / `--cond mua` giả lập ảnh đêm / mưa từ ảnh ban ngày.

## Thử nhanh khi chưa có job thật

Cần một CVAT để thử. Có thể chạy CVAT trên máy bằng Docker theo [hướng dẫn của CVAT](https://docs.cvat.ai/docs/administration/basics/installation/). Tạo tài khoản admin:

```
docker exec -it cvat_server bash -ic "python3 ~/manage.py createsuperuser"
```

Chuẩn bị một thư mục gồm ảnh và file `annotations.xml`, export ở dạng "CVAT for images 1.1" từ một job đã gán nhãn. Tạo task test từ thư mục đó:

```
venv\Scripts\python cvat_2d\tao_job_test.py D:\thu_muc_anh --url http://localhost:8080 --token <token>
```

Script tạo task với đúng các nhãn trong file XML, upload ảnh, import nhãn, rồi in ra số job để chọn trên web QC.

## Không có trong repo

- Token (`.env`).
- File model. `cai_dat.bat` sẽ tải về.
- Dữ liệu ảnh, cache, kết quả review.
- Cơ sở dữ liệu của web QC (`web_qc/data/`).
