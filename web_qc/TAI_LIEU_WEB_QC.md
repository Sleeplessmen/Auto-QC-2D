# Web QC nhãn 2D — tài liệu cho nhóm

Cập nhật: 2026-10-14 (bản 7: ghi chú trên ảnh, sửa lời nhắn, trang cho labeler, so sánh lần trước, Issue tổng kết, thời gian chờ) · Thư mục code: `sam2/cvat_2d/web_qc/` · Chạy bằng: `cvat_2d/web_qc.bat`

---

## Mục lục

1. [Tóm tắt](#1-tóm-tắt)
2. [Ai dùng, làm gì](#2-ai-dùng-làm-gì)
3. [Cài đặt và chạy trên máy chủ](#3-cài-đặt-và-chạy-trên-máy-chủ)
4. [Kết nối CVAT](#4-kết-nối-cvat)
5. [Hướng dẫn review một job](#5-hướng-dẫn-review-một-job)
6. [Các trang của web](#6-các-trang-của-web)
7. [Guideline và file luật](#7-guideline-và-file-luật)
8. [Tool tìm lỗi như thế nào](#8-tool-tìm-lỗi-như-thế-nào)
9. [Không có ground truth thì dựa vào đâu, có cần Claude không](#9-không-có-ground-truth-thì-dựa-vào-đâu-có-cần-claude-không)
10. [Đẩy Issue lên CVAT](#10-đẩy-issue-lên-cvat)
11. [Kết quả và báo cáo](#11-kết-quả-và-báo-cáo)
12. [Độ tin cậy, giới hạn và rủi ro](#12-độ-tin-cậy-giới-hạn-và-rủi-ro)
13. [Bảo mật](#13-bảo-mật)
14. [Xử lý lỗi thường gặp](#14-xử-lý-lỗi-thường-gặp)
15. [Phần kỹ thuật cho người phát triển](#15-phần-kỹ-thuật-cho-người-phát-triển)
16. [Lộ trình](#16-lộ-trình)
17. [Phụ lục: vì sao chọn web, các bản cũ](#17-phụ-lục-vì-sao-chọn-web-các-bản-cũ)

---

## 1. Tóm tắt

Web QC nhãn 2D là trang web nội bộ làm việc thay một người review nhãn 2D trên CVAT. Tool tự đọc nhãn của job và tìm các lỗi: **sai kích thước, sai nhãn, thiếu, thừa, trùng, vi phạm guideline**. Sau đó nó ghi chú từng lỗi lên CVAT dưới dạng **Issue**. Tool **không sửa, không thêm, không xoá nhãn nào**.

Tài liệu này dành cho:

- Labeler tự kiểm tra trước khi nộp.
- Người QC review job của người khác.
- Trưởng nhóm quản lý guideline và tài khoản.
- Người phát triển tool.

Mục 1–7 là hướng dẫn dùng. Mục 8–14 giải thích cách tool làm việc và giới hạn của nó. Mục 15 dành cho người sửa code.

### Nguyên tắc không bao giờ đổi

- Box đúng thì không ghi gì.
- Box sai thì ghim một Issue đúng frame, đúng vị trí, nói rõ sai gì để labeler tự so và tự sửa.
- Không tạo, xoá, di chuyển, đổi kích thước, đổi nhãn hay đổi thuộc tính của bất kỳ shape/track nào. Vật bị thiếu cũng chỉ ghim Issue, không vẽ box.
- Trước khi đẩy thì sao lưu nhãn. Sau khi đẩy thì tải lại và so sánh để chứng minh nhãn gốc không đổi.
- Lỗi chắc chắn được chọn sẵn để đẩy. Lỗi "không chắc" chờ người xem ảnh rồi tự chọn.

### Hiện trạng (2026-10-14)

| Phần | Trạng thái |
| --- | --- |
| Web đầy đủ: 6 trang (Tổng quan, Review job, Lịch sử, Guideline, Kết nối CVAT, Cài đặt), 3 vai trò, hàng đợi | Đã dựng, đã chạy thử |
| Nhiều kết nối CVAT thêm trên web (URL, token mã hoá, tổ chức), chọn job từ danh sách CVAT | Đã có, đã thử với CVAT thật (bản 2.77.1) |
| Đánh dấu "Tool nhầm", xem theo khung hình, theo dõi Issue đã đẩy, trang Tổng quan theo labeler | Đã có |
| Chống đẩy trùng: giữ Issue cũ khi lỗi còn, đóng hoặc xoá khi lỗi hết | Đã có, đã thử với CVAT giả |
| Webhook CVAT: job hoàn thành thì tự review | Đã có, đã thử chữ ký và lọc sự kiện, chưa thử với CVAT thật |
| Tầng 2: so với model (4 detector + SAM2 + CLIP) | Đã có, đã đo trên 123 ảnh có đáp án (GT) |
| Tầng 1: kiểm tra theo file luật guideline | Đã có, mới thử trên dữ liệu giả |
| Đọc guideline PDF / DOCX / TXT / MD, tra cứu đoạn liên quan theo nhãn | Đã có, đã thử |
| Đổi job chỉ bằng file `.env` | Đã có |
| Review job 2D qua API và đẩy Issue thật lên CVAT | Có code, **chưa thử trên job thật** vì chưa có job 2D để thử |
| Báo cáo HTML, kiểm tra track, hỏi LLM cho ca khó | Chưa làm (xem [Lộ trình](#16-lộ-trình)) |

Tool không cần Claude hay dịch vụ AI trả phí nào: mọi model đều chạy trên máy chủ.

---

## 2. Ai dùng, làm gì

Mỗi người có một tài khoản web riêng, do admin tạo. Vai trò quyết định người đó được làm gì.

Tài khoản web khác với tài khoản CVAT. Issue được tạo bằng tài khoản CVAT của **kết nối** được chọn khi review (trang Kết nối CVAT), nên labeler không cần token.

| Vai trò | Làm được | Thường là |
| --- | --- | --- |
| **labeler** | Chạy review, xem kết quả và lịch sử, đẩy Issue, đọc guideline, đổi mật khẩu của mình | Người gán nhãn tự kiểm tra job của mình |
| **qc** | Mọi việc của labeler, thêm: quản lý guideline và luật, gán guideline cho task, thêm / sửa / xoá kết nối CVAT | Người review, trưởng nhóm gán nhãn |
| **admin** | Mọi việc của qc, thêm: quản lý tài khoản, cài đặt chung (ngưỡng đạt, webhook) | Người quản lý máy chủ |

---

## 3. Cài đặt và chạy trên máy chủ

Chỉ cần cài trên **một máy chủ**. Người dùng chỉ mở trình duyệt, không phải cài gì. Mục này dành cho người quản lý máy chủ.

### Yêu cầu máy chủ

- Windows 10/11, luôn bật, cùng mạng nội bộ với người dùng và kết nối được tới CVAT.
- Có GPU NVIDIA (đang chạy thử trên RTX 4050 Laptop). Không có GPU vẫn chạy được nhưng rất chậm.
- Thư mục dự án `sam2/` gồm:
  - Môi trường Python `sam2/venv/`.
  - Code `sam2/cvat_2d/`.
  - Checkpoint SAM2 `sam2/checkpoints/sam2.1_hiera_large.pt`.
- File model detector trong `cvat_2d/`: `yolo11x.pt`, `rtdetr-x.pt`, `yolov8x-seg.pt`. Model D-FINE-X và CLIP tự tải từ HuggingFace ở lần chạy đầu, nên lần đó cần Internet.

### Các bước cài

1. **Cài thư viện** (chỉ làm một lần):
   ```
   venv\Scripts\pip install -r cvat_2d\requirements.txt
   ```
   File này đã gồm `pypdf` để đọc guideline PDF.
2. **Kết nối CVAT:** sau khi đăng nhập, vào trang **Kết nối CVAT** → **Thêm kết nối**, nhập địa chỉ, token và tổ chức (nếu có), bấm **Thử kết nối** rồi **Lưu** (xem [mục 4](#4-kết-nối-cvat)).
   - Token tạo trên CVAT ở **Profile → Security → Personal Access Tokens**.
   - Nên dùng một tài khoản CVAT riêng cho tool, ví dụ `qc-bot`, và gán tài khoản này vào các task cần QC.
   - Nếu đã có `cvat_2d\.env` (4 biến `CVAT_URL`, `CVAT_TOKEN`, `CVAT_TASK_ID`, `CVAT_JOB_ID`), web tự nhập nó thành một kết nối tên ".env trên máy chủ" khi khởi động.
3. **Chạy web:** chạy `cvat_2d\web_qc.bat`, rồi mở `http://localhost:8000`.
4. **Mở cho cả nhóm:**
   - Chạy `web_qc.bat --lan`. Cửa sổ sẽ in ra địa chỉ `http://<IP máy chủ>:8000` để gửi cho nhóm.
   - Mở cổng 8000 trong Windows Firewall, chỉ cho mạng Private.
   - Muốn đổi cổng thì thêm `--port 9000`.
5. **Tài khoản admin đầu tiên:**
   - Lần chạy đầu, tool tạo tài khoản `admin` và ghi mật khẩu vào `cvat_2d\web_qc\data\MAT_KHAU_ADMIN.txt`.
   - Đăng nhập, vào **Cài đặt** đổi mật khẩu, rồi xoá file đó.
   - Muốn tự đặt mật khẩu từ đầu thì đặt biến môi trường `WEB_QC_ADMIN_PASSWORD` trước lần chạy đầu.
6. **Tạo tài khoản** cho từng người ở **Cài đặt → Tài khoản**, chọn vai trò phù hợp.
7. Bấm **Cài đặt → Kiểm tra kết nối** để chắc token dùng được và job thuộc đúng task.

### Vận hành hằng ngày

- Lần đầu bấm Đánh giá, tool mất thêm thời gian nạp model. Cứ để web chạy liên tục thì các lần sau nhanh hơn.
- Tắt web bằng cách đóng cửa sổ hoặc bấm Ctrl+C.
  - Lịch sử và kết quả vẫn còn.
  - Lần review đang chạy dở sẽ bị đánh dấu "Lỗi: Web bị tắt khi đang chạy" và cần chạy lại.
- Cần sao lưu định kỳ hai thư mục:
  - `cvat_2d\web_qc\data\`: cơ sở dữ liệu, file guideline, file export đã tải lên.
  - `cvat_2d\review_out\`: kết quả từng lần review, gồm cả bản sao nhãn trước và sau khi đẩy.

---

## 4. Kết nối CVAT

Muốn review CVAT nào thì thêm một **kết nối** trên trang **Kết nối CVAT**, không phải sửa file. Có thể có nhiều kết nối cùng lúc (CVAT công ty, CVAT test, CVAT khách hàng…); khi review chỉ cần chọn kết nối ở ô đầu tiên của thanh công cụ.

| Trường | Ý nghĩa |
| --- | --- |
| Tên gợi nhớ | Tên hiện trong danh sách, ví dụ "CVAT công ty" |
| Địa chỉ CVAT | Ví dụ `https://cvat.ten-cong-ty.vn`. Có thừa `/api` ở cuối cũng được, web tự bỏ |
| Token | Personal Access Token của tài khoản CVAT dùng để đọc nhãn và tạo Issue. Được **mã hoá khi lưu** bằng khoá riêng của máy chủ (`data/secret.key`) và **không bao giờ gửi xuống trình duyệt**; trên web chỉ hiện 4 ký tự cuối. Khi sửa kết nối, để trống ô token là giữ token cũ |
| Tổ chức | Slug tổ chức trên CVAT (gửi bằng header `X-Organization`). Bấm **Thử kết nối** để thấy danh sách tổ chức của tài khoản. Để trống nếu không dùng tổ chức. Thiếu tổ chức là lý do hay gặp khiến không thấy job |
| Mặc định | Kết nối được chọn sẵn khi mở trang Review và dùng cho webhook (nếu không chọn kết nối khác) |

- **Thử kết nối** báo tài khoản, phiên bản CVAT, số job tài khoản thấy được và các tổ chức. Nút **Thử** trên từng dòng kiểm tra lại kết nối đã lưu.
- File `cvat_2d/.env` vẫn dùng được: lúc khởi động, web tự nhập nó thành kết nối ".env trên máy chủ" (nếu chưa có kết nối trùng URL + token), và lấy `CVAT_JOB_ID` / `CVAT_TASK_ID` điền sẵn vào trang Review. Có thể thêm biến `CVAT_ORG` cho tổ chức.
- **Dòng lệnh** (`review.bat`) vẫn đọc trực tiếp `.env` như trước.
- `.env`, `.env.class` và `web_qc/data/` (chứa cơ sở dữ liệu và khoá) nằm trong `.gitignore`.

---

## 5. Hướng dẫn review một job

Toàn bộ diễn ra trên trang **Review job**.

### Chạy review

1. **Kết nối CVAT:** chọn máy CVAT ở ô đầu tiên (mặc định đã chọn sẵn).
2. **Chọn job:** bấm **Chọn** cạnh ô Job để mở danh sách job lấy trực tiếp từ CVAT.
   - Tìm theo tên task hoặc người gán, lọc theo giai đoạn / trạng thái, tick "Chỉ job 2D".
   - Mỗi dòng có người được giao, số frame và **kết quả review gần nhất** của job đó.
   - Job 3D bị khoá vì web này chỉ review 2D.
   - Biết số job thì gõ thẳng vào ô cũng được; ô Task tự điền.
3. **Đọc dòng ngữ cảnh** ngay dưới thanh công cụ. Nó cho biết trước khi chạy:
   - Job nào, task nào, 2D hay 3D, giai đoạn / trạng thái, labeler.
   - **Guideline nào sẽ được dùng và có bao nhiêu nhãn có luật** (có luật thì chạy cả tầng 1). Nếu task chưa gán guideline, dòng này báo màu vàng kèm link sang trang Guideline.
4. **Guideline:** để "Tự chọn theo task" là dùng guideline đã gán cho task. Có thể chọn tay một guideline khác, hoặc "Không dùng guideline".
5. **Chế độ:** "Chính xác" (mặc định do admin đặt) hoặc "Nhanh".
6. **Tuỳ chọn:** file export .zip (khi không đọc được từ CVAT), chạy N frame đầu, người lái xe máy, tự đẩy lỗi chắc chắn.
7. Bấm **Đánh giá**. Trạng thái: *Đang chờ (thứ N)* → *Đang chạy · ảnh 3/5* → *Xong · Đạt* hoặc *Xong · Chưa đạt*.

### Đọc kết quả

- **Đầu kết quả:** % box không có lỗi chắc chắn kèm nhãn Đạt / Chưa đạt, số lỗi chắc, số không chắc, số box, thời gian. Có nút **Mở job trên CVAT**, **Chạy lại**, **CSV**.
- **Danh sách lỗi** (bên trái): lọc Tất cả / Lỗi / Không chắc / Tool nhầm, theo loại lỗi và tầng. Bấm một lỗi để xem ảnh lớn, chi tiết và **đoạn guideline nói về nhãn đó** ở bên phải.
- **Theo khung hình:** lưới ảnh của mọi frame kèm số lỗi; bấm một ảnh để lọc danh sách theo frame đó.
- **Issue trên CVAT:** các Issue tool đã tạo trên job, số trả lời và trạng thái *Còn mở* / *Đã xử lý* (labeler bấm Resolve trên CVAT).

### Duyệt và đẩy Issue

1. Lỗi chắc chắn được tick sẵn. Lỗi "không chắc" xem ảnh rồi tự tick.
2. Tool báo sai thì bấm **Tool nhầm** (phím **X**), có thể ghi lý do. Lỗi bị đánh dấu sẽ bỏ tick, **không bao giờ được đẩy**, và được đếm vào tỉ lệ tool nhầm trên trang Tổng quan.
3. Phím tắt: **↑ ↓** chuyển lỗi, **Space** chọn / bỏ, **X** tool nhầm.
4. Ô **Đồng bộ với Issue tự động lần trước** (bật sẵn): lỗi vẫn còn thì giữ Issue cũ, không tạo trùng; lỗi đã hết thì xoá Issue cũ, hoặc đóng lại nếu labeler đã trả lời bên dưới. Issue của người review thật không bị đụng tới.
5. Bấm **Đẩy N Issue lên CVAT** → xác nhận. Kết quả báo số Issue mới, số giữ lại, số đóng, số xoá và dòng "Nhãn gốc không đổi ✔".

### Công cụ của người review

| Công cụ | Dùng khi nào | Lên CVAT thế nào |
| --- | --- | --- |
| **Ghi chú trên ảnh** (nút trên khung ảnh, phím **N**) | Tool không tự thấy nhưng bạn thấy cần nhắc labeler: kéo một khung lên đúng chỗ trên ảnh rồi gõ lời nhắn | Thành 1 Issue ghim đúng khung đó, nội dung bắt đầu `[Review tự động] [Ghi chú người review]` |
| **Sửa lời nhắn** | Lời nhắn của tool khó hiểu hoặc muốn hướng dẫn cụ thể hơn ("kéo cạnh dưới xuống bánh xe") | Issue dùng lời nhắn đã sửa. Có nút trở về lời nhắn gốc |
| **Tool nhầm** (phím **X**) | Tool báo sai | Không đẩy. Đếm vào tỉ lệ tool nhầm |
| **Khung đang xem + phóng to vùng lỗi** | Mỗi lỗi được khoanh khung xanh đứt nét trên ảnh và phóng to bên dưới, để thấy rõ chỗ sai mà không phải zoom tay | — |
| **So sánh với lần trước** | Job được review lại: hiện "Đã sửa X · Còn Y · Mới Z" so với lần review xong gần nhất của cùng job | — |
| **Kèm Issue tổng kết** (bật sẵn) | Mỗi lần đẩy thêm 1 Issue ở góc ảnh đầu tiên: % box đúng, đạt hay chưa, số mục cần xem và **link trang lỗi cho labeler** | 1 Issue `[Tổng kết]`, lần sau tự thay bằng tổng kết mới |
| **Link cho labeler** | Gửi cho labeler một trang xem lỗi kèm ảnh, **không cần đăng nhập** | — |

Mọi lời nhắn đều giữ nguyên nhãn của labeler: box đúng không bị đụng tới, chỗ sai chỉ có Issue ghim bên trên.

### Trang dành cho labeler

Bấm **Link cho labeler** (hoặc mở link trong Issue tổng kết) để có trang `…/bao-cao.html?run=12&t=<mã>`:

- Đầu trang: job, labeler, % box đúng, Đạt / Chưa đạt, so sánh với lần trước, nút **Mở job trên CVAT**, và 3 bước hướng dẫn sửa.
- Mỗi frame một khung: ảnh có **khung đánh số** đúng chỗ từng lỗi, danh sách lời nhắn cùng số, nút **Mở frame trên CVAT** (nhảy thẳng tới frame đó).
- Lỗi đánh dấu "tool nhầm" không hiện. Nếu đã đẩy Issue, trang chỉ hiện đúng những mục đã đẩy.
- Link có mã bí mật riêng cho từng lần review; sai mã thì không mở được. Dùng trong mạng nội bộ.

### Labeler sửa trên CVAT

1. Mở job (nút **Mở job trên CVAT**). Issue ghim tại đúng vị trí lỗi, nội dung bắt đầu bằng `[Review tự động]`.
2. Sửa nhãn rồi Resolve Issue. Nếu thấy tool sai, trả lời ngay dưới Issue: lần chạy sau tool sẽ đóng Issue đó thay vì xoá.
3. Chạy review lại (nút **Chạy lại**).

### Quy trình nhóm khuyến nghị

1. Labeler gán xong thì tự chạy review, sửa tới khi không còn lỗi chắc chắn rồi mới nộp.
2. Người QC chạy lại, xem tay mọi lỗi "không chắc", đánh dấu Tool nhầm những chỗ tool sai, và xem thêm ngẫu nhiên 10–20% số ảnh (tool bỏ sót khoảng 1/4 số lỗi), ưu tiên ảnh đêm, mưa, đông xe.
3. Job đạt ngưỡng (mặc định ≥ 97%, admin đổi được) thì đạt. Chưa đạt thì đẩy Issue và trả lại cho labeler.
4. Bật webhook (mục 6) để bước 2 tự chạy ngay khi labeler chuyển job sang "completed".

---

## 6. Các trang của web

| Trang | Ai dùng | Chức năng |
| --- | --- | --- |
| **Tổng quan** | Mọi vai trò | Trong 7 / 30 / 90 ngày: số lần review, tỉ lệ đạt, % box đúng trung bình, số lỗi, Issue đã đẩy, **tỉ lệ tool nhầm**; biểu đồ loại lỗi hay gặp; xu hướng theo ngày; bảng **theo labeler** (người được giao job trên CVAT) xếp từ thấp đến cao |
| **Review job** | Mọi vai trò | Thanh công cụ (kết nối, job + hộp chọn job, task, guideline, chế độ, tuỳ chọn), dòng ngữ cảnh, kết quả với 3 chế độ xem (danh sách lỗi + ảnh, theo khung hình, Issue trên CVAT), Tool nhầm, đẩy Issue |
| **Lịch sử** | Mọi vai trò | Mọi lần review: job, task, labeler, người chạy (hoặc "tự động" nếu qua webhook), kết quả, % box đúng, lỗi, số tool nhầm, số Issue. Lọc theo job và theo tên |
| **Guideline** | Xem: mọi vai trò. Sửa: qc, admin | Tải guideline lên; mỗi guideline có 3 tab: **Luật kiểm tra** (trình soạn dạng bảng), **Nội dung guideline** (tra cứu), **YAML** (nâng cao) |
| **Kết nối CVAT** | Xem, thử: mọi vai trò. Thêm/sửa/xoá: qc, admin | Danh sách kết nối, thử kết nối, đặt mặc định, thêm / sửa |
| **Cài đặt** | Đổi mật khẩu: mọi vai trò. Còn lại: admin | Ngưỡng đạt, chế độ mặc định, **webhook CVAT** (bật, chọn kết nối, tự đẩy, địa chỉ và secret để dán vào CVAT), tài khoản |

Thanh bên trái luôn hiện trạng thái: máy CVAT đang chọn, tổ chức, GPU, webhook. Link một lần review dạng `http://<máy chủ>:8000/#run=12` gửi cho người khác được.

### Webhook CVAT (tự review khi job hoàn thành)

1. Admin vào **Cài đặt** → tick **Bật webhook** → chọn kết nối → **Lưu**. Web hiện **Target URL** và **Secret**.
2. Trên CVAT: mở Project hoặc Task → **Actions → Setup webhooks → Create** → dán Target URL và Secret, chọn sự kiện **job** (update), content type `application/json`.
3. Khi labeler chuyển job sang **completed**, CVAT gọi sang web QC; web tự xếp một lần review vào hàng đợi (người chạy hiện là "webhook"). Nếu bật "tự đẩy", lỗi chắc chắn được đẩy luôn, không chờ người duyệt.
4. Điều kiện: máy CVAT phải truy cập được máy chủ QC (chạy `web_qc.bat --lan`, mở tường lửa). Web kiểm chữ ký `X-Signature-256` của CVAT, sai chữ ký thì từ chối. Job 3D bị bỏ qua.

---

## 7. Guideline và file luật

Mỗi dự án tải guideline lên **một lần**. Guideline được dùng theo hai cách:

1. **Tra cứu:** khi xem một lỗi, web hiện ngay các đoạn guideline nói về nhãn đó.
2. **Kiểm tra tự động (tầng 1):** khi guideline có kèm **file luật**, tool kiểm tra từng box theo luật và ghi số mục guideline vào Issue.

### Web đọc guideline như thế nào

- **Định dạng đọc được:** PDF có chữ, DOCX, TXT, MD.
  - PDF dạng ảnh scan không có chữ nên không đọc được. Web sẽ cảnh báo "File gần như không có chữ".
  - Khi đó hãy xuất lại sang PDF có chữ hoặc DOCX.
- **Chia mục:** web chia nội dung theo các dòng tiêu đề:
  - Dòng đánh số kiểu `1.`, `3.1`, `3.1.2`.
  - Dòng bắt đầu bằng `#`.
  - Dòng bắt đầu bằng "Chương", "Phần", "Mục".
  - Heading trong DOCX.
- **Tìm kiếm:** không phân biệt dấu và hoa thường ("xe may" tìm ra "Xe máy"). Có thể tìm nhiều từ cùng lúc, cách nhau dấu phẩy: `car, ô tô, occluded`.
- **Đoạn liên quan tới một nhãn:** web tìm theo tên nhãn và các tên trong `dong_nghia` của file luật. Mục có từ đó ở tiêu đề được xếp trước.

### Các bước cho trưởng nhóm (vai trò qc hoặc admin) — trên tab Luật kiểm tra, không cần viết YAML

1. Vào tab **Guideline**, nhập tên (ví dụ "GreenSM 2D v3"), chọn file, bấm **Tải lên**.
2. Bấm vào tên guideline để xem nội dung theo mục và thử ô tìm kiếm.
3. Nhập số **Task**, bấm **Lấy nhãn từ task**. Web đọc danh sách nhãn và thuộc tính của task (qua kết nối đang chọn) và điền sẵn bảng: mỗi nhãn một dòng, tự đoán cột "Tool hiểu là" cho nhãn quen (car, pedestrian, two-wheels…), thuộc tính của nhãn hiện mờ trong ô để điền cho nhanh.
4. Điền từng cột theo guideline: kích thước tối thiểu, tỉ lệ rộng/cao, thuộc tính bắt buộc, không để mặc định, tên gọi khác, số mục; và phần **Quy tắc chung**. Bấm **Lưu luật**. Web báo nếu có giá trị lạ.
5. Bấm **Gán guideline cho task**. Từ đó review job thuộc task này tự dùng guideline này, và dòng ngữ cảnh trên trang Review báo "Guideline: … · N nhãn có luật".
6. Tab **YAML** cho người quen viết file luật trực tiếp; hai tab luôn đồng bộ khi lưu.

### Các khoá trong file luật

File luật viết bằng YAML. Mỗi nhãn một mục, tên mục **đúng như tên nhãn trên CVAT**.

| Khoá | Ý nghĩa | Ví dụ | Khi vi phạm |
| --- | --- | --- | --- |
| `nhan.<tên>.loai_tool` | Tool hiểu nhãn này là loại nào, để tầng 2 so đúng loại. Chọn một trong: car, truck, bus, motorcycle, bicycle, person, GreenSM | `car` | — |
| `nhan.<tên>.dong_nghia` | Tên khác của nhãn trong guideline. Dùng để tra cứu, và để tool nhận ra nhãn có tên lạ | `[oto, xe hoi]` | — |
| `nhan.<tên>.kich_thuoc_toi_thieu_px` | Cạnh ngắn của box nhỏ hơn mức này | `10` | Lỗi |
| `nhan.<tên>.ti_le_rong_cao` | Tỉ lệ rộng/cao nằm ngoài khoảng [nhỏ nhất, lớn nhất]. Bỏ qua box xoay | `[0.4, 4.0]` | Không chắc |
| `nhan.<tên>.thuoc_tinh_bat_buoc` | Thuộc tính để trống | `[occluded]` | Lỗi |
| `nhan.<tên>.khong_de_mac_dinh` | Thuộc tính vẫn còn giá trị mặc định, có thể labeler quên chọn | `[truncated]` | Không chắc |
| `nhan.<tên>.muc` | Số mục guideline nói về nhãn này, được ghi vào Issue | `"3.1"` | — |
| `quy_tac.nguoi_lai_co_box_rieng` | Người lái xe máy phải có box person riêng. Ghi đè ô tick trên trang Review | `true` | — |
| `quy_tac.box_ra_ngoai_anh_px` | Box vượt mép ảnh quá N px | `2` | Lỗi |
| `quy_tac.nhan_ngoai_guideline` | `true` thì mọi box có nhãn không có trong file luật đều bị ghi chú | `false` | Lỗi |
| `quy_tac.muc_chung` | Số mục dùng khi nhãn không có `muc` riêng | `"2"` | — |

Ngoài ra, box gần như không có diện tích (rộng hoặc cao dưới 1 px) luôn bị báo lỗi.

### Ví dụ file luật

```yaml
nhan:
  car:
    loai_tool: car
    dong_nghia: [oto, xe hoi, sedan]
    kich_thuoc_toi_thieu_px: 10
    ti_le_rong_cao: [0.4, 4.0]
    thuoc_tinh_bat_buoc: [occluded]
    khong_de_mac_dinh: [truncated]
    muc: "3.1"
  two-wheels:
    loai_tool: motorcycle
    dong_nghia: [xe may, motorbike]
    kich_thuoc_toi_thieu_px: 8
    muc: "3.2"
  pedestrian:
    loai_tool: person
    dong_nghia: [nguoi di bo]
    muc: "3.3"
quy_tac:
  nguoi_lai_co_box_rieng: true
  box_ra_ngoai_anh_px: 2
  nhan_ngoai_guideline: false
  muc_chung: "2"
```

Ví dụ một Issue tầng 1 trên CVAT:

`[Review tự động] Box 'car' thiếu thuộc tính 'occluded' — Guideline mục 3.1. [shape 1234]`

### Lưu ý

- Tầng 1 chỉ chạy khi review **theo số job**, vì cần nhãn gốc và thuộc tính trên CVAT. Review từ file export thì chỉ có tầng 2.
- Nhãn có trong task mà không có trong file luật sẽ được ghi cảnh báo trong khung tiến độ, không bị coi là lỗi (trừ khi bật `nhan_ngoai_guideline`).
- Có những điều trong guideline máy không tự kiểm được, ví dụ "ước lượng hợp lý phần bị che". Những điều đó vẫn cần người kiểm.
- **Vì sao không đọc thẳng file PDF để suy ra luật:** guideline viết bằng văn tự do, máy không hiểu chắc chắn được. Chuyển một lần sang file luật thì kiểm được 100% số box, mỗi lỗi chỉ rõ vi phạm mục nào, và lần sau chạy ra cùng kết quả.
- Có thể dùng một LLM (Claude hoặc model chạy trên máy) để đọc guideline và soạn nháp file luật, rồi người duyệt lại. Bước này không bắt buộc và hiện chưa làm sẵn trong web.

---

## 8. Tool tìm lỗi như thế nào

Lỗi được bắt bởi hai tầng. Mỗi lỗi mang một trong hai mức:

- **Lỗi** (chắc chắn): được tick sẵn để đẩy.
- **Không chắc**: không được tick sẵn, chờ người QC xem ảnh rồi tự chọn. Khi đẩy, Issue có thêm câu "(không chắc — nên kiểm tra lại)".

### Tầng 1: kiểm tra theo file luật guideline

Chạy khi guideline có file luật và review theo số job. Không dùng model.

| Lỗi | Quy tắc | Mức |
| --- | --- | --- |
| Box gần như không có diện tích | Rộng hoặc cao dưới 1 px | Lỗi |
| Box vượt ra ngoài ảnh | Vượt mép quá `box_ra_ngoai_anh_px` | Lỗi |
| Box quá nhỏ | Cạnh ngắn nhỏ hơn `kich_thuoc_toi_thieu_px` | Lỗi |
| Tỉ lệ vô lý | Rộng/cao ngoài khoảng `ti_le_rong_cao`, ví dụ person nằm ngang | Không chắc |
| Thiếu thuộc tính | Thuộc tính trong `thuoc_tinh_bat_buoc` để trống | Lỗi |
| Thuộc tính còn mặc định | Thuộc tính trong `khong_de_mac_dinh` chưa được chọn | Không chắc |
| Nhãn ngoài guideline | Chỉ khi bật `nhan_ngoai_guideline` | Lỗi |
| Track bất thường (đứt quãng, nhảy vọt) | **Chưa làm** | — |

Với track, tool kiểm tra từng keyframe, bỏ qua frame `outside`.

### Tầng 2: so với model

Tool tự tìm vật trong ảnh bằng bộ model `label_hq_2d`:

- 4 detector: YOLO11x, RT-DETR-x, YOLOv8x-seg, D-FINE-X.
- SAM2 để làm khít mép box.
- CLIP để phân biệt xe GreenSM với ô tô thường.
- Ước lượng phần bị che, theo quy tắc amodal: vật bị che vẫn đóng box toàn bộ.

Sau đó tool ghép box của tool với box của người gán theo độ trùng (IoU), ưu tiên cặp cùng nhãn.

| Lỗi | Cách phát hiện | Khi nào là "Lỗi" (chắc) | Ví dụ ghi chú |
| --- | --- | --- | --- |
| Sai kích thước | So từng mép box với khoảng ước lượng của mọi model (box SAM và box tốt nhất của từng detector). Chấp nhận cả box phần nhìn thấy lẫn box ước lượng toàn bộ | Mép nằm ngoài **mọi** ước lượng, lệch quá max(6 px, 10% cạnh). IoU ≥ 0.85 coi là khít. Vật nhỏ hơn 24 px không chấm | `Box 'car' chưa khít: cạnh dưới thiếu 40px (IoU 0.78). Box đúng khoảng [...]` |
| Sai nhãn | Box khớp vị trí (IoU ≥ 0.5) nhưng tool và CLIP cho nhãn khác. Khớp khác nhóm (ví dụ gán motorcycle trùm lên người) cần IoU ≥ 0.7 | Điểm của tool cao. Điểm từ 0.36 tới ngưỡng thì là không chắc | `Sai nhãn: đang gán 'truck', vật này là 'bus'.` |
| Thiếu vật | Tool thấy vật nhưng không có box người gán nào khớp. Issue ghim tại box tool thấy | Điểm cao và vật ≥ 14 px. Điểm từ 0.38 trở lên thì là "có thể thiếu" | `Thiếu nhãn: có 1 'car' ở đây chưa được gán.` |
| Box thừa | Box người gán không khớp vật nào tool thấy | Thường là không chắc, vì tool cũng bỏ sót vật | `Tool không thấy 'car' nào trong box này, kiểm tra lại xem có phải box thừa.` |
| Trùng | Hai box người gán cùng nhãn chồng lên một vật | IoU giữa hai box ≥ 0.85 | `Box trùng: 2 box 'car' chồng lên nhau trên cùng 1 vật.` |
| Box xoay | Tool chỉ kiểm được box không xoay | Luôn là không chắc | `Box 'car' bị xoay 15°, tool chỉ kiểm tra được box không xoay.` |

Các ngưỡng trên là hằng số ở đầu `review_core.py`, đã chỉnh trên 123 ảnh GT. Khi đổi ngưỡng thì chạy lại `review_eval.py` để xem tỉ lệ báo nhầm và bỏ sót thay đổi ra sao.

**Nhãn tool không đánh giá được:** tầng 2 chỉ hiểu 7 loại: car, truck, bus, motorcycle, bicycle, person, GreenSM. Nhãn khác (ví dụ Animal, Obstacle) được liệt kê trong kết quả là "Tool không đánh giá được". Các nhãn này chỉ được kiểm ở tầng 1.

---

## 9. Không có ground truth thì dựa vào đâu, có cần Claude không

**Vẫn đánh giá được.** Job cần QC không cần có đáp án (GT). Tool so nhãn với 3 nguồn thay cho GT:

| Nguồn đối chiếu | Bắt được lỗi gì | Độ tin |
| --- | --- | --- |
| **Guideline của dự án** (file luật) | Nhãn ngoài danh sách, thiếu thuộc tính, box quá nhỏ, vi phạm quy tắc riêng | Chắc chắn, vì đúng hay sai là do luật quy định |
| **Nhiều model độc lập cùng đồng ý** (4 detector + SAM2 + CLIP), dùng như "GT tạm" | Thiếu vật, sai kích thước, sai nhãn | Cao khi các model đồng thuận. Khi chúng bất đồng thì ghi "không chắc" |
| **Tính nhất quán trong chính job** | Box trùng; sau này thêm track nhảy, cùng một vật đổi nhãn giữa các frame | Trung bình |

**GT chỉ cần để đo xem tool tin được đến đâu, không cần cho từng job.** Bộ 123 ảnh GT hiện có là cơ sở của các con số báo nhầm và bỏ sót (`review_eval.py`). Khi nhận dự án mới với ảnh kiểu khác, nên gán chuẩn 20–30 ảnh rồi đo lại, vì độ tin đo trên bộ này chưa chắc đúng với bộ khác. Quy trình đo có sẵn trong `kiem_tra_chat_luong.py`.

**Không bắt buộc dùng Claude.**

- Tool chạy hoàn toàn trên máy chủ bằng các model mã nguồn mở: YOLO11, RT-DETR, YOLOv8-seg, D-FINE, SAM2, CLIP.
- Code không gọi API của Claude hay bất kỳ dịch vụ AI trả phí nào. Mạng chỉ dùng để nói chuyện với CVAT, và để tải model ở lần chạy đầu.
- Claude chỉ được dùng để viết code và tài liệu.

---

## 10. Đẩy Issue lên CVAT

Mỗi lỗi được chọn thành một Issue ghim đúng frame, đúng vị trí. Tool chỉ gọi API tạo, đọc và xoá Issue, không gọi API nào ghi vào annotation.

### Lệnh gọi

- `POST /api/issues` với nội dung `{job, frame, position: [x1,y1, x2,y1, x2,y2, x1,y2], message}`. `frame` là số frame tuyệt đối trong task.
- Header `Authorization: Bearer <CVAT_TOKEN>`. Nếu bị 401 thì code tự thử lại dạng `Token <...>` của CVAT bản cũ.
- Gặp lỗi 5xx thì thử lại tối đa 4 lần. Gặp 403 thì báo "tài khoản không có quyền".

### Nội dung Issue

Nội dung gồm 4 phần:

1. Tiền tố `[Review tự động]`.
2. Câu mô tả lỗi.
3. Câu "(không chắc — nên kiểm tra lại)", nếu là lỗi không chắc.
4. Mã box trên CVAT, ví dụ `[shape 1234]` hoặc `[track 56]`.

Mã box giúp labeler tìm đúng box. Ví dụ:

- `[Review tự động] Box 'car' chưa khít: cạnh dưới thiếu 40px (IoU 0.78). Box đúng khoảng [...]. [shape 1234]`
- `[Review tự động] Có thể thiếu 1 'motorcycle' ở đây. (không chắc — nên kiểm tra lại)`

### Đồng bộ với Issue của lần trước (chống đẩy trùng)

Mỗi Issue tool tạo có một "dấu vân tay" ở cuối nội dung, dạng `[qc:<frame>|<loại lỗi>|<box>]` (box = mã shape/track, hoặc vị trí làm tròn với vật bị thiếu). Khi bật ô **Đồng bộ với Issue tự động lần trước**:

| Tình huống | Tool làm gì |
| --- | --- |
| Lỗi vẫn còn và đã có Issue đang mở | Giữ Issue cũ, **không tạo trùng** |
| Lỗi đã hết, Issue cũ chưa ai trả lời | Xoá Issue cũ |
| Lỗi đã hết, Issue cũ đã có trả lời | **Đóng (resolved)** để giữ lịch sử trao đổi |
| Lỗi mới | Tạo Issue mới |
| Issue đã resolved, hoặc do người review thật / tài khoản khác tạo | Không đụng tới |

Logic này đã được kiểm với một CVAT giả qua 3 lần chạy liên tiếp; chưa kiểm trên job 2D thật.

### Chứng minh không sửa nhãn

1. Trước khi chấm: lưu annotation vào `review_out/job<id>_<thời gian>/annotations_truoc_review.json`.
2. Sau khi đẩy: tải lại vào `annotations_sau_review.json`, chuẩn hoá (sắp xếp, bỏ trường thời gian) rồi so sánh.
3. Giống nhau thì web báo "Nhãn gốc không thay đổi ✔". Khác thì báo "Nhãn trên CVAT đã khác lúc review". Thường là do labeler đang sửa cùng lúc, vì tool không có lệnh ghi nào vào annotation.

**Trạng thái:** phần đẩy Issue **chưa chạy thử trên job 2D thật**. Cần kiểm trên một job 2D nhỏ, xem Issue có hiện đúng frame và đúng chỗ không, với cả job bắt đầu từ frame 0 lẫn job bắt đầu giữa task.

---

## 11. Kết quả và báo cáo

**Trên web** (tab Review job, hoặc mở lại từ Lịch sử):

- Thẻ số liệu.
- Bảng lỗi.
- Ảnh vẽ đè.
- Đoạn guideline liên quan.
- Kết quả lần đẩy Issue gần nhất.
- File CSV tải về.

**Trên máy chủ**, mỗi lần review có một thư mục `cvat_2d/review_out/job<id>_<YYYYMMDD_HHMMSS>/`:

| File | Nội dung |
| --- | --- |
| `ket_qua_review.csv` | Danh sách lỗi: frame, ảnh, số, loại, mức, nhãn, toạ độ, ghi chú. Mở được bằng Excel |
| `ket_qua_review.json` | Số liệu tổng và danh sách lỗi đầy đủ |
| `preview/` | Ảnh vẽ đè từng frame |
| `annotations_truoc_review.json` | Bản sao nhãn trước khi review |
| `annotations_sau_review.json` | Nhãn tải lại sau khi đẩy Issue |
| `issue_ids.json` | Mã các Issue đã tạo |
| `log.txt` | Toàn bộ khung tiến độ |

**Cách đọc con số "% box không có lỗi chắc chắn"** = (số box − số box có ít nhất một lỗi chắc chắn) ÷ số box. Box chỉ có lỗi "không chắc" vẫn được tính là đúng. Lỗi "thiếu vật" không làm giảm con số này vì không gắn với box nào, nên luôn xem cả số lỗi.

**Trang Tổng quan** tổng hợp các lần review theo labeler (người được giao job trên CVAT), loại lỗi hay gặp, xu hướng theo ngày và **tỉ lệ tool nhầm** (từ các đánh dấu Tool nhầm). Nên dùng để hướng dẫn lại đúng chỗ yếu, không dùng để phạt, vì tool vẫn còn báo nhầm.

**Chưa làm:** báo cáo HTML để gửi.

---

## 12. Độ tin cậy, giới hạn và rủi ro

Tool đủ tin để thay phần lớn công kiểm tra thô, nhưng **chưa thay hoàn toàn người review**. Số đo bằng `review_eval.py` trên 123 ảnh GT, ngày 2026-10-12:

| Chỉ số | Kết quả |
| --- | --- |
| Báo nhầm trên nhãn đúng | 0.8 "lỗi" + 1.8 "không chắc" trên 100 box |
| Lỗi cài sẵn bắt được | 46.5% ở mức lỗi + 28.0% ở mức không chắc |
| Lỗi cài sẵn bị bỏ sót | 25.4% |
| Bắt được theo loại | Sai kích thước 80%, thiếu 65%, sai nhãn 60%, thừa 100% (phần lớn ở mức không chắc) |

### Chỗ tool còn yếu

- Vật nhỏ hơn khoảng 30 px, và vật tool cho điểm thấp: đây là phần lớn số lỗi bị bỏ sót.
- Ban đêm và cảnh xe máy dày đặc: ảnh ví dụ ban đêm mới tìm được khoảng 6 xe máy và 23 người trong hàng trăm. Ảnh đám đông ở Hà Nội mới tìm được khoảng 40% số người.
- Box amodal: bộ GT đóng box theo phần nhìn thấy, nên chưa đo được độ đúng kiểu amodal. Tool chấp nhận cả hai kiểu box, nên lỗi amodal thường bị bỏ qua.
- Chỉ kiểm box chữ nhật 2D. Chưa chấm polygon, mask, keypoint. Job 3D bị từ chối.

### Rủi ro vận hành

| Rủi ro | Cách giảm |
| --- | --- |
| Báo nhầm làm labeler mất niềm tin | Giữ ngưỡng "chắc" chặt. Lỗi không chắc luôn để người duyệt |
| Một GPU chỉ chạy được một job mỗi lần | Hàng đợi có vị trí chờ và **thời gian chờ dự kiến**; ảnh được tải song song trong lúc GPU chấm. Đông người thì thêm GPU / máy (xem dưới) |
| Labeler sửa trong lúc đang QC | Phép so sánh trước/sau sẽ phát hiện và cảnh báo. Chạy lại review |
| CVAT nâng phiên bản làm đổi cách đánh số frame hoặc API Issue | Mỗi lần nâng cấp, chạy lại bài thử đẩy Issue trên một job nhỏ |
| Hỏng ổ đĩa máy chủ | Sao lưu `web_qc/data/` và `review_out/` |

---

### Web review được bao nhiêu người cùng lúc

- **Người dùng web:** vài chục người mở web, xem kết quả, duyệt lỗi, đẩy Issue cùng lúc không vấn đề gì (máy chủ FastAPI xử lý song song).
- **Phần chấm lỗi (GPU):** chạy **lần lượt từng job** trên 1 GPU. Chạy song song nhiều job trên cùng 1 GPU không nhanh hơn (chỉ chia nhau sức máy) và dễ tràn bộ nhớ (RTX 4050 Laptop có 6 GB).
- **Tốc độ đo được** (chế độ Chính xác, RTX 4050 Laptop, có tải ảnh song song): khoảng **1,2 giây / ảnh**. Job 100 ảnh ≈ 2 phút; khoảng **30 job 100 ảnh mỗi giờ**, đủ cho nhóm 10–20 labeler nộp rải rác. Chế độ Nhanh nhanh hơn nhưng kém chính xác.
- Người nộp sau thấy "Đang chờ · thứ 2 · còn ~3 phút" và có thể đóng trang, mở lại sau ở Lịch sử. Ảnh đã chấm được lưu cache nên **Chạy lại** cùng job nhanh hơn nhiều.
- **Muốn nhanh hơn:** chạy web QC trên máy có GPU mạnh hơn, hoặc dựng thêm máy QC thứ hai và chia task cho từng máy (mỗi máy một web QC, cùng trỏ về CVAT).

## 13. Bảo mật

**Đã làm:**

- Token CVAT nhập trên trang Kết nối được **mã hoá khi lưu** (khoá riêng `data/secret.key`, mã hoá luồng HMAC-SHA256 kèm nonce ngẫu nhiên) và không bao giờ gửi xuống trình duyệt; web chỉ hiện 4 ký tự cuối. Ai có cả file cơ sở dữ liệu **và** `secret.key` thì vẫn giải mã được, nên giữ kín thư mục `web_qc/data/`.
- Chỉ qc và admin thêm / sửa kết nối; webhook kiểm chữ ký `X-Signature-256` của CVAT.
- Đăng nhập bắt buộc, có 3 vai trò.
  - Mật khẩu được lưu dạng băm (PBKDF2-SHA256), không lưu mật khẩu gốc.
  - Đăng nhập sai bị chậm lại 1 giây mỗi lần.
- `.env`, `.env.class` và `web_qc/data/` nằm trong `.gitignore`. `.env.example` đã được thay token thật bằng chỗ trống.
- Mặc định web chỉ mở cho chính máy chủ. Phải chạy `--lan` mới mở cho mạng nội bộ.

**Nên làm khi triển khai:**

- Dùng tài khoản CVAT riêng cho tool (`qc-bot`), chỉ gán vào các project/task cần QC. Issue khi đó hiện tên bot nên dễ phân biệt với người review thật.
- Không mở web ra Internet khi chưa có HTTPS.
- Nếu `.env.example` cũ (có token thật) từng được gửi cho ai, hãy tạo token mới trên CVAT và thu hồi token cũ.

**Chưa làm:** giới hạn danh sách task/project được phép QC, nhật ký thao tác chi tiết (ai đẩy Issue lúc nào). Hiện lịch sử chỉ ghi người chạy review.

---

## 14. Xử lý lỗi thường gặp

| Thông báo hoặc hiện tượng | Nguyên nhân | Cách xử lý |
| --- | --- | --- |
| "Token sai hoặc đã hết hạn (CVAT trả 401)" | Token sai, hết hạn hoặc bị thu hồi | Tạo token mới trên CVAT, vào Kết nối CVAT → Sửa → dán token mới → Lưu |
| Hộp chọn job trống / "Không có job nào" | Thiếu tổ chức, hoặc tài khoản chưa được giao job | Sửa kết nối, điền tổ chức (bấm Thử kết nối để xem tên tổ chức) |
| "Chưa có kết nối CVAT nào" | Chưa thêm kết nối | Vào trang Kết nối CVAT → Thêm kết nối |
| Webhook không chạy | CVAT không gọi tới được máy chủ, webhook đang tắt, hoặc sai secret | Chạy `--lan`, mở tường lửa, bật webhook trong Cài đặt, dán đúng Secret vào CVAT |
| "Tài khoản '…' không có quyền vào …" | Tài khoản của token chưa được gán vào task/job đó | Nhờ admin CVAT thêm tài khoản vào task |
| "Không tìm thấy … trên CVAT (sai số job/task?)" | Sai số job, hoặc job ở máy CVAT khác | Kiểm tra số job và `CVAT_URL` |
| "Job X thuộc task Y, không phải task Z" | `CVAT_TASK_ID` không khớp với job | Sửa số task, hoặc để trống ô task |
| "Đây là job 3D…" | Web này chỉ review job 2D | Dùng bộ tool 3D trong `cvat_3d/` |
| "Không nhãn nào của job khớp với loại tool nhận ra" | Tên nhãn của task lạ với tool | Trong file luật, khai `loai_tool` (và `dong_nghia`) cho từng nhãn |
| "Tool KHÔNG đánh giá được các nhãn: …" | Nhãn ngoài 7 loại tool hiểu (Animal, Obstacle…) | Bình thường. Các nhãn này chỉ được kiểm ở tầng 1 |
| "Lần review này chỉ đánh giá file…" khi bấm đẩy | Review từ file export mà không nhập số job | Chạy lại review theo số job |
| "File gần như không có chữ" khi tải guideline | PDF dạng ảnh scan | Xuất lại PDF có chữ, hoặc dùng DOCX |
| "File luật sai cú pháp YAML…" | Thụt lề sai, thiếu dấu `:` hoặc ngoặc | Sửa đúng dòng được báo. Dùng dấu cách, không dùng Tab |
| Trạng thái "Đang chờ" rất lâu | Người khác đang chạy review, GPU chạy lần lượt | Chờ. Vị trí trong hàng đợi hiện ngay cạnh trạng thái |
| "Web bị tắt khi đang chạy" | Web bị tắt giữa chừng | Chạy lại review |
| "Nhãn trên CVAT đã khác lúc review" | Có người sửa job trong lúc QC | Chạy lại review cho kết quả mới |
| Máy khác không vào được web | Chưa chạy `--lan`, hoặc tường lửa chặn cổng | Chạy `web_qc.bat --lan`, mở cổng 8000 trong Windows Firewall |
| Review rất chậm | Máy không có GPU, hoặc job quá dài | Dùng máy có GPU, chọn chế độ Nhanh, hoặc thử trước với N frame |
| Quên mật khẩu admin | — | Một admin khác đặt lại trong Cài đặt. Nếu không còn admin nào, chạy lệnh ở dưới bảng |

Lệnh đặt lại mật khẩu admin (chạy trên máy chủ, trong thư mục `sam2`):

```
venv\Scripts\python -c "import sys; sys.path.insert(0, r'cvat_2d\web_qc'); import store; store.set_user('admin', pw='matkhaumoi', role='admin')"
```

---

## 15. Phần kỹ thuật cho người phát triển

### Kiến trúc

```
Trình duyệt (labeler / QC)
        │  HTTP, cookie phiên
        ▼
┌──────────── Máy chủ QC (một máy có GPU) ─────────────┐
│ server.py  FastAPI: đăng nhập, API, trang tĩnh       │
│     │                                                │
│     ▼                                                │
│ worker.py  hàng đợi: 1 GPU chạy 1 job mỗi lần        │
│     │                                                │
│     ├─ Đọc dữ liệu (review_core.Cvat / read_export)  │◄── chỉ đọc ── CVAT
│     ├─ Tầng 2: label_hq_2d + review_core.compare     │      (job, nhãn, ảnh)
│     ├─ Tầng 1: guideline.rule_check                  │
│     ├─ Hợp nhất lỗi, chia mức chắc / không chắc      │
│     └─ Đẩy Issue (review_core.Review.push) ──────────┼── chỉ ghi Issue ──► CVAT
│                                                      │
│ store.py  SQLite: tài khoản, lịch sử, guideline      │
│ review_out/  kết quả + bản sao nhãn trước/sau        │
└──────────────────────────────────────────────────────┘
```

Bộ đẩy Issue là nơi duy nhất ghi lên CVAT. Sau khi ghi, nó tải lại nhãn để so với bản sao.

### Các file

| File | Việc làm |
| --- | --- |
| `cvat_2d/web_qc.bat` | Tìm `venv`, chạy `web_qc/server.py`. Tham số: `--lan`, `--port` |
| `web_qc/server.py` | FastAPI: phiên đăng nhập (`SessionMiddleware`, khoá trong `data/secret.key`), phân quyền theo vai trò, toàn bộ API, phục vụ `static/` |
| `web_qc/worker.py` | Hàng đợi một luồng. Đọc lại `.env` mỗi lần (`cvat_config()`). Giữ `ToolRunner` để không phải nạp lại model. Chạy tầng 2 rồi tầng 1, lưu kết quả, đẩy Issue. Sau khi tắt rồi bật web, dựng lại kết quả cũ từ `review_out/` |
| `web_qc/store.py` | SQLite `data/web_qc.db`: bảng `users`, `runs`, `guidelines`, `task_guideline`. Tạo admin đầu tiên |
| `web_qc/guideline.py` | Đọc PDF (pypdf) / DOCX / TXT / MD, chia mục, tìm đoạn liên quan (bỏ dấu tiếng Việt), đọc và kiểm tra file luật, tạo mẫu từ nhãn task, `rule_check` (tầng 1), `apply_to_core` (đưa tên nhãn trong file luật vào bảng đồng nghĩa của tầng 2 trong lúc review) |
| `web_qc/static/` | `index.html`, `app.js`, `style.css`. JS thuần, không cần build, tự đổi theo chế độ sáng/tối |
| `cvat_2d/review_core.py` | Bộ chấm dùng chung với bản Gradio và dòng lệnh: kết nối CVAT, đọc file export, so sánh, vẽ ảnh, lưu báo cáo, đẩy Issue |
| `cvat_2d/label_hq_2d.py` | Bộ model tìm vật (4 detector + SAM2 + CLIP + amodal) |
| `cvat_2d/review_eval.py` | Đo độ tin của bộ chấm trên GT bằng cách cài lỗi giả |

### API

Mọi API (trừ đăng nhập) cần cookie phiên. Lỗi trả về dạng `{"detail": "<câu tiếng Việt>"}`.

| Phương thức và đường dẫn | Quyền | Việc làm |
| --- | --- | --- |
| `POST /api/login`, `POST /api/logout`, `GET /api/me` | — | Đăng nhập, đăng xuất, xem mình là ai |
| `POST /api/password` | Mọi vai trò | Đổi mật khẩu của mình |
| `GET /api/config` | Mọi vai trò | Danh sách kết nối (token che), kết nối mặc định, job/task trong `.env`, máy chạy, ngưỡng đạt |
| `GET/POST /api/connections`, `PUT/DELETE /api/connections/{id}`, `POST /api/connections/{id}/default` | Xem: mọi vai trò. Sửa: qc | Quản lý kết nối CVAT |
| `POST /api/connections/test` | qc | Thử kết nối theo id hoặc theo URL + token vừa nhập |
| `GET /api/connections/{id}/jobs?page&search&stage&state&dimension`, `GET /api/connections/{id}/jobs/{jid}` | Mọi vai trò | Danh sách job trên CVAT (kèm review gần nhất), thông tin một job |
| `GET /api/dashboard?days=` | Mọi vai trò | Số liệu trang Tổng quan |
| `GET/PUT /api/settings` | admin | Ngưỡng đạt, chế độ mặc định, webhook |
| `POST /api/webhook/cvat` | CVAT (chữ ký) | Nhận sự kiện job hoàn thành → tự xếp review |
| `POST /api/runs` | Mọi vai trò | Tạo lần review (form: job_id, task_id, guideline_id, mode, rider, max_frames, auto_push, file) |
| `GET /api/runs?job_id=` | Mọi vai trò | Lịch sử |
| `GET /api/runs/{id}` | Mọi vai trò | Trạng thái, vị trí chờ, log, lỗi, frame, đoạn guideline |
| `GET /api/runs/{id}/preview/{file}`, `GET /api/runs/{id}/report.csv` | Mọi vai trò | Ảnh xem trước, file CSV |
| `POST /api/runs/{id}/push` | Mọi vai trò | Đẩy các lỗi được chọn (`ids`, `replace_old`), bỏ qua lỗi đã đánh dấu tool nhầm |
| `POST /api/runs/{id}/feedback` | Mọi vai trò | Đánh dấu / bỏ đánh dấu "tool nhầm" (`finding_id`, `verdict`, `note`) |
| `GET /api/runs/{id}/issues` | Mọi vai trò | Issue tool đã tạo trên job, trạng thái resolved, số trả lời |
| `POST/PUT/DELETE /api/runs/{id}/notes[/{nid}]` | Mọi vai trò | Ghi chú tay trên ảnh (`frame`, `name`, `box`, `msg`) |
| `PUT /api/runs/{id}/findings/{fid}` | Mọi vai trò | Sửa lời nhắn của một lỗi (rỗng = về lời nhắn gốc) |
| `GET /api/public/runs/{id}?t=`, `GET /api/public/runs/{id}/preview/{file}?t=` | Có mã link | Dữ liệu và ảnh cho trang labeler `bao-cao.html` |
| `POST /api/runs/{id}/rerun` | Mọi vai trò | Chạy lại với cùng thiết lập |
| `GET/POST /api/guidelines`, `GET/DELETE /api/guidelines/{id}` | Xem: mọi vai trò. Tải lên, xoá: qc | Danh sách, tải lên, chi tiết, xoá |
| `GET /api/guidelines/{id}/file`, `GET /api/guidelines/{id}/search?q=` | Mọi vai trò | File gốc, tìm kiếm |
| `PUT /api/guidelines/{id}/rules`, `POST …/template`, `POST …/tasks` | qc | Lưu file luật, tạo mẫu từ nhãn task, gán cho task |
| `GET/POST /api/users`, `DELETE /api/users/{name}` | admin | Quản lý tài khoản |

### Dữ liệu trên máy chủ

| Đường dẫn | Nội dung |
| --- | --- |
| `web_qc/data/web_qc.db` | Cơ sở dữ liệu SQLite |
| `web_qc/data/secret.key` | Khoá ký cookie phiên. Xoá file này thì mọi người phải đăng nhập lại |
| `web_qc/data/guidelines/g<id>.<đuôi>` | File guideline gốc |
| `web_qc/data/uploads/run<id>.zip` | File export đã tải lên |
| `web_qc/data/MAT_KHAU_ADMIN.txt` | Mật khẩu admin đầu tiên. Xoá sau khi đổi |
| `review_out/job<id>_<thời gian>/` | Kết quả từng lần review (xem [mục 11](#11-kết-quả-và-báo-cáo)) |

### Đầu vào và cách khớp dữ liệu

- **Theo số job (API):**
  - `GET /api/jobs/{id}`, `/api/jobs/{id}/data/meta`: thông tin job, tên ảnh, kích thước, bước nhảy frame, frame đã xoá.
  - `/api/jobs/{id}/annotations`: shape và track.
  - `/api/labels?job_id=`: bộ nhãn.
  - `/api/jobs/{id}/data?type=frame&number=N`: ảnh từng frame, lưu cache ở `cache_hq2d/`.
- **Theo file export:** đọc CVAT for images 1.1, COCO, YOLO. Ảnh khớp với frame của job theo tên file.
- **Số frame:** Issue dùng số frame tuyệt đối trong task. CVAT bản cũ và bản mới đánh số ảnh khác nhau. Code thử cả hai cách, nhưng chưa kiểm trên job 2D thật.
- **Track:** nội suy box giữa hai keyframe, bỏ các frame `outside`.
- **Quyền đọc nhãn:** một số tài khoản không đọc được nhãn theo task (lỗi 403) nhưng đọc được theo job. Nút tạo mẫu file luật tự chuyển sang đọc theo job khi gặp trường hợp này.

### Kiểm thử đã làm (2026-10-13)

- Đăng nhập, phân quyền (labeler bị chặn 403 khi sửa guideline hay quản lý tài khoản), sai mật khẩu, tạo tài khoản.
- Đọc guideline DOCX, TXT, PDF. Chia mục và tìm đúng mục theo tên nhãn có dấu và không dấu.
- File luật: báo đúng lỗi cú pháp và cảnh báo giá trị lạ. Tầng 1 trên dữ liệu giả bắt đúng box nhỏ, tỉ lệ vô lý, thiếu thuộc tính, thuộc tính còn mặc định, box vượt ảnh.
- `apply_to_core` thêm tên nhãn lạ vào bảng đồng nghĩa trong lúc review và trả lại như cũ sau đó.
- Review 2D từ file export (1 ảnh trong `D:\DATA`): ra lỗi, ảnh xem trước, CSV, đoạn guideline. Đẩy Issue bị chặn đúng vì không có job. Kết quả dựng lại được sau khi xoá bộ nhớ.
- Kết nối CVAT thật: đọc được job 70 (task 74). Job này là 3D nên bị từ chối đúng.
- Bật web thật bằng `web_qc.bat`: trang chủ trả 200, API trả 401 khi chưa đăng nhập.

---

## 16. Lộ trình

| Giai đoạn | Nội dung | Cổng để qua giai đoạn | Trạng thái |
| --- | --- | --- | --- |
| 1. Web + guideline | Web đầy đủ, 3 vai trò, hàng đợi, lịch sử, đọc và tra cứu guideline, tầng 1 theo file luật, đổi job bằng `.env` | Chạy thử không cần CVAT ổn, đọc được CVAT | **Đã xong** |
| 2. Thử trên job 2D thật | Tạo job 2D nhỏ có vài lỗi cố ý, review theo số job, đẩy Issue thật, kiểm frame và vị trí, chạy tầng 1 trên nhãn thật | Issue hiện đúng chỗ, nhãn gốc không đổi | **Đang chờ job 2D** |
| 3. Hoàn thiện | ~~Chống đẩy trùng~~, ~~thống kê theo labeler~~, ~~webhook CVAT~~, ~~kết nối nhiều CVAT, chọn job~~, ~~tool nhầm~~ (đã xong 2026-10-14); còn lại: báo cáo HTML, kiểm tra track | 2–3 labeler dùng thử 1 tuần ổn định | **Phần lớn đã xong** |
| 4. Nâng model | Gom dữ liệu giao thông Việt Nam gán amodal (đêm, mưa, đông xe), fine-tune detector, đo lại bằng `review_eval.py` | Tỉ lệ bỏ sót dưới ngưỡng nhóm chọn | Chưa làm, cần dữ liệu |

### Việc cần chuẩn bị cho giai đoạn 2

- [ ] Có một job **2D** để thử, trên CVAT online hoặc localhost. CVAT localhost hiện đang trống.
- [ ] Tạo tài khoản CVAT `qc-bot`, tạo token, thêm thành một kết nối trên trang Kết nối CVAT (điền tổ chức nếu có).
- [ ] Một task nhỏ khoảng 10 ảnh, chia 2 job (một job bắt đầu từ frame 0, một job bắt đầu giữa task), gán nhãn có cố ý vài lỗi.
- [ ] File guideline thật của dự án (tên nhãn, thuộc tính bắt buộc, kích thước tối thiểu) để soạn file luật đầu tiên.

**Ý tưởng bỏ hẳn bước bấm nút:** CVAT có webhook. Khi labeler chuyển job sang trạng thái hoàn thành, CVAT gọi sang web QC và QC tự chạy. Điều kiện là máy CVAT phải kết nối được tới máy QC, và có quyền tạo webhook trên project/task.

---

## 17. Phụ lục: vì sao chọn web, các bản cũ

### Vì sao chọn web nội bộ thay vì app

| Phương án | Ưu điểm | Nhược điểm | Kết luận |
| --- | --- | --- | --- |
| **Web nội bộ** (đang dùng) | Người dùng chỉ cần trình duyệt. Chỉ một máy cần GPU. Token nằm một chỗ. Sửa code một lần là mọi người có bản mới | Phải có một máy chủ luôn bật | Chọn |
| App desktop (.exe) | Chạy không cần mạng nội bộ | Mỗi máy cần GPU và bản cài vài GB. Token rải rác trên nhiều máy. Đóng gói PyInstaller đã gặp nhiều lỗi và bị bỏ ngày 2026-10-12 | Không dùng |
| Dòng lệnh (`review.bat`) | Nhanh, chạy theo lô hoặc theo lịch | Labeler không quen dùng | Giữ cho người kỹ thuật |

### Các bản cũ vẫn dùng được

- `review_web.bat`: trang Gradio một người dùng, cổng 7860. Đây là bản đầu tiên, trước khi có web đầy đủ.
- `review.bat`: dòng lệnh, đọc 4 biến trong `.env`. Có thể thêm `--job N`, `--khong-day` (chỉ đánh giá), `--chi-loi-chac`, `--giu-issue-cu`, `--so-frame N`, `--nhanh`.

Cả hai bản dùng chung bộ chấm `review_core.py` với web, nên kết quả giống nhau. Bản Gradio và bản dòng lệnh không có tầng 1 (file luật guideline).
