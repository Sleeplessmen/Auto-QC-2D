# CVAT 2D — gán nhãn tự động và QC nhãn

Bộ tool cho nhãn 2D trên CVAT:

- **Web QC** (`web_qc/`, chạy `web_qc.bat`): review nhãn của labeler thay người review, rồi ghi chú lên CVAT bằng **Issue**. Tool không sửa nhãn. Tool tìm các lỗi:
  - Box: sai kích thước, hình dạng phi lý (quá dẹt / quá mảnh), sai nhãn, thiếu, thừa, trùng.
  - **Polygon / mask của từng vật** (instance segmentation): vẽ lẹm, tô thừa ra nền, co / phình cả vòng, lệch vật. Tool so với mask SAM2.
  - Luật hình học (gộp từ LetmeQC): box / polygon ra ngoài ảnh, polygon xoắn hoặc dưới 3 điểm, polygon tràn ra ngoài box của nó, `pedestrian` ngồi trên xe máy (nên là `rider`).
  - Vùng đường (`drivable_area`, polygon / mask): tô thiếu, tô thừa, vẽ trùng. Tool so với model phân vùng mặt đường.
  - Một vật vừa có mask vừa có box: là lỗi trùng, hoặc là cặp hợp lệ (instance segmentation), tuỳ guideline.
  - Gán bằng Shape hay Track có đúng guideline không.
  - Nhãn cho cả ảnh (tag, ví dụ `image_info` / `weather`): ảnh chưa gán, hoặc giá trị không hợp với ảnh (so bằng CLIP).
  - Tool review **mọi nhãn của task trên mọi ảnh**: ảnh có vật hoặc mặt đường mà labeler chưa gán cũng bị báo thiếu.
  - Vi phạm guideline.
- **Gán nhãn chất lượng cao** (`label_hq_2d.py`): 4 detector + SAM2 + CLIP.
- Các tool phụ: `review.bat` (QC bằng dòng lệnh), `review_web.bat` (bản QC Gradio cũ), `menu.bat`.

**BDD100K (object detection + instance segmentation):** guideline, tập nhãn CVAT và file luật nằm trong [guideline_bdd100k/](guideline_bdd100k/). QC luôn đọc guideline: task chưa gán guideline thì dùng guideline mặc định trong Cài đặt.

**Đo hiệu quả trên job thật:** trang Tổng quan → Hiệu quả Issue. Có % Issue đúng (annotator đã sửa theo), % lỗi bắt được trước review chéo, và số vòng bị trả lại / job.

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

## Các trang của web (giao diện 2026-10-17)

- **Tự review** (trang mở đầu): sơ đồ luồng nộp validation → tool review → trả về annotation / chờ reviewer → nộp lại, kèm số liệu sống. Bảng mỗi job một dòng, % box đúng qua từng vòng. Danh sách job chờ reviewer kiểm chéo.
- **Độ tin cậy tool**: số đo độ chính xác của tool (bắt được lỗi, Issue chắc chắn đúng, báo nhầm), theo loại lỗi, theo điều kiện ảnh, trước / sau cải tiến, segmentation, test trên CVAT. Dữ liệu ở `web_qc/static/do_tin_cay.json`, tạo lại bằng `web_qc/tao_do_tin_cay.py` sau khi chạy `review_eval.py --json`.
- Tổng quan, Review job, Lịch sử, Guideline, Kết nối CVAT, Cài đặt: như cũ.
- Mở thẳng một trang bằng link `http://<máy>:8000/#tab=trust` (auto, dash, history, guide, conn, settings).

## Tự review khi labeler nộp job

Vào **Cài đặt → Tự review khi job chuyển sang validation**, tick **Bật**, chọn CVAT rồi bấm **Lưu cài đặt**.

- Labeler gán xong và chuyển stage của job sang **validation**. Trong vòng 60 giây, web tự đọc job, review theo guideline, rồi đẩy lỗi chắc chắn lên CVAT thành Issue.
- **Còn lỗi chắc chắn** thì web tự trả job về **annotation (rejected)** cho labeler sửa, giống LetmeQC trước đây. **Không còn lỗi chắc chắn** thì job ở lại validation để reviewer kiểm chéo. Lỗi "không chắc" không làm job bị trả về. Tắt việc trả về bằng ô "Có lỗi chắc chắn thì tự trả job về annotation".
- Labeler sửa xong, nộp lại validation, thì tool review lại. Issue có lỗi đã hết được đóng, lỗi còn thì giữ Issue cũ (không tạo trùng). Mỗi lần trả về được tính là một vòng ở Tổng quan → Hiệu quả Issue.
- Web tự hỏi CVAT nên không cần webhook hay cấu hình mạng.
- Đã thử trên CVAT localhost (2026-10-16): chuyển job sang validation, không bấm gì. Web tự review, giữ 12 Issue cũ còn lỗi, rồi trả job về `annotation / rejected`.

Tool không cần đáp án (ground truth) để review job thật. Tool tự nhìn ảnh bằng model, rồi so với nhãn labeler. Đáp án chỉ dùng để đo độ chính xác của tool (xem dưới).

## Review theo guideline

- **Chưa có guideline:** tool review dựa vào nhãn của task, so nhãn labeler với những gì model thấy.
- **Có guideline:** tải guideline lên (PDF / DOCX / TXT / MD) ở trang **Guideline**, rồi gán guideline cho task. Tool đọc guideline để lấy yêu cầu:
  - Kích thước tối thiểu: vật nhỏ hơn thì không đòi gán, box nhỏ hơn thì báo lỗi.
  - Vẽ toàn bộ vật hay chỉ phần nhìn thấy: tool ước lượng khung theo đúng cách đó.
  - Người lái xe máy có box riêng không.
  - Thuộc tính bắt buộc.
  - Box không ra ngoài ảnh.
  - Mục guideline của từng nhãn, ghi vào Issue.
- Nút **Đọc guideline + lấy nhãn từ task** điền sẵn bảng luật kèm câu gốc trong guideline để người QC kiểm lại rồi lưu.
- Nếu chưa lưu luật, mỗi lần review tool tự đọc guideline và ghi những yêu cầu đọc được vào nhật ký.

Chế độ **Phân tích** trên trang Review job vẽ chồng lên ảnh những gì tool thấy (vật phát hiện, mặt đường), đặt cạnh nhãn của labeler. Người review nhìn vào đó để kiểm chứng kết quả.

## Đo độ chính xác của tool

`review_eval.py` dùng bộ ảnh có đáp án. Nó cố ý cài lỗi vào nhãn đúng (sai kích thước, sai nhãn, thiếu, thừa, trùng, box dẹt), rồi đo tool bắt được bao nhiêu, báo nhầm bao nhiêu, và bao nhiêu % khung hình được review đúng. Kết quả được chia theo điều kiện ảnh: ngày / đêm / hoàng hôn, trời quang / mưa / tuyết.

```
venv\Scripts\python cvat_2d\review_eval.py --images <thu muc anh> --gt <thu muc dap an json> --meta <dieu_kien.json>
```

- Mỗi file đáp án có dạng `{"image": "ten.jpg", "objects": [{"cls": "car", "box": [x1, y1, x2, y2]}]}`.
- `--meta` là file `{ten anh: {timeofday, weather}}`, ví dụ trích từ nhãn của BDD100K.
- `--cond dem` / `--cond mua` giả lập ảnh đêm / mưa từ ảnh ban ngày.

Đo phần **segmentation** (polygon do người vẽ thật, COCO val2017):

```
venv\Scripts\python cvat_2d\tao_bo_seg_eval.py --ann <instances_val2017.json> --out du_lieu_danh_gia/coco_seg_eval --n 200
venv\Scripts\python cvat_2d\review_eval.py --seg du_lieu_danh_gia/coco_seg_eval --skip 120
```

Bộ 200 ảnh đã có sẵn ở `du_lieu_danh_gia/coco_seg_eval` (cạnh thư mục `cvat_2d`). Kết quả 2026-10-16 trên 80 ảnh không dùng để chỉnh ngưỡng: bắt 74.9% lỗi polygon cài vào. Báo nhầm 1.3 "lỗi" + 9.2 "không chắc" trên 100 polygon đúng.

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
