# Web QC nhãn 2D — tài liệu cho nhóm

Cập nhật: 2026-10-17 (bản 8: giao diện mới, trang Tự review và Độ tin cậy tool, Issue gộp theo vật, lỗi chưa đủ bằng chứng ghi "Đang xem xét", guideline 10 px, phóng to dải giữa ảnh) · Thư mục code: `sam2/cvat_2d/web_qc/` · Chạy bằng: `cvat_2d/web_qc.bat`

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
- Box sai thì ghim một Issue đúng frame, đúng vị trí, nói rõ sai gì để labeler tự so và tự sửa. **Mỗi vật một Issue**: vật có nhiều lỗi thì gộp vào một Issue và ghi rõ tên từng lỗi.
- Không tạo, xoá, di chuyển, đổi kích thước, đổi nhãn hay đổi thuộc tính của bất kỳ shape/track nào. Vật bị thiếu cũng chỉ ghim Issue, không vẽ box.
- Trước khi đẩy thì sao lưu nhãn. Sau khi đẩy thì tải lại và so sánh để chứng minh nhãn gốc không đổi.
- Lỗi chắc chắn được chọn sẵn để đẩy. Lỗi chưa đủ bằng chứng ghi **"Đang xem xét"** kèm lý do, chờ người xem ảnh rồi tự chọn, và không bao giờ làm job bị trả về.

### Hiện trạng (2026-10-17)

| Phần | Trạng thái |
| --- | --- |
| Web: 8 trang (Tổng quan, **Tự review**, Review job, Lịch sử, **Độ tin cậy tool**, Guideline, Kết nối CVAT, Cài đặt), 3 vai trò, hàng đợi | Đã có. Giao diện mới 2026-10-17, đã chụp thử cả 9 trang (kể cả đăng nhập), không lỗi JavaScript |
| **Tự review khi job chuyển sang validation**: đẩy lỗi chắc chắn, còn lỗi thì trả job về annotation, không lỗi thì chờ reviewer | Đã có, đã thử trên CVAT localhost (2026-10-16). Trang Tự review xem kết quả từng job theo vòng |
| Nhiều kết nối CVAT thêm trên web (URL, token mã hoá, tổ chức), chọn job từ danh sách CVAT | Đã có, đã thử với CVAT 2.77.1 và 2.78.1 |
| Đánh dấu "Tool nhầm", xem theo khung hình, chế độ Phân tích, theo dõi Issue đã đẩy, Tổng quan theo labeler | Đã có |
| Chống đẩy trùng: giữ Issue cũ khi lỗi còn, đóng (resolve) khi lỗi hết | Đã có, đã thử trên CVAT localhost |
| **Issue gộp theo vật**, ghi rõ tên từng lỗi; lỗi chưa chắc ghi "Đang xem xét — có thể …" kèm lý do | Đã có (2026-10-17). 149/149 Issue trên dữ liệu thật ghim đúng box của vật |
| Webhook CVAT: job hoàn thành thì tự review | Đã có, đã thử chữ ký và lọc sự kiện. Luồng chính của nhóm là tự review khi sang validation (không cần webhook) |
| Tầng 2: so với model (4 detector + SAM2 + CLIP, phóng to dải giữa ảnh) | Đã có, đo trên 123 ảnh Việt Nam và 735 ảnh BDD100K có đáp án (mục 12) |
| Tầng 1: kiểm tra theo file luật guideline; tự đọc yêu cầu trong guideline thành luật | Đã có |
| Box hình dạng phi lý (quá dẹt / quá mảnh so với loại vật) | Đã có (2026-10-15) |
| Vùng đường (`drivable_area`, polygon / mask): thiếu, tô thừa, trùng, so với SegFormer Cityscapes; trùng mask + box | Đã có (2026-10-15). Từ 2026-10-16 đọc cả polygon / mask trong file .zip (CVAT XML, COCO) |
| **Segmentation từng vật**: polygon / mask của xe, người... so viền với SAM2 (lẹm, tô thừa, co / phình, lệch) | Đã có (2026-10-16), đo trên 200 ảnh COCO val2017 polygon người vẽ (mục 12) |
| Tầng luật hình học gộp từ LetmeQC (ra ngoài ảnh, polygon xoắn / < 3 điểm, polygon tràn box, trùng box của nhãn model không chấm, rider / pedestrian...) | Đã có (2026-10-16), LetmeQC `app.py` đã tắt |
| Kiểm tra track: lỗi ID (tráo ID, đổi vật, 1 vật 2 ID, 2 ID 1 vật, kết thúc sớm, kích thước không đồng bộ), đứt track, nhảy vị trí | Đã có (2026-10-16), thử trên CVAT localhost: 7/7 và 6/6 kịch bản |
| Shape hay track theo guideline; guideline mặc định cho task chưa gán | Đã có (2026-10-16) |
| Đo hiệu quả Issue trên job thật: % Issue đúng, % lỗi bắt trước review chéo, số vòng trả lại / job | Đã có, thử đầu cuối trên CVAT localhost (75% Issue đúng trên 1 job giả lập). **Chưa có số đo trên job thật** |
| Trang lỗi cho labeler (`bao-cao.html`, không cần đăng nhập) | Đã có |
| Đọc guideline PDF / DOCX / TXT / MD, tra cứu đoạn liên quan theo nhãn | Đã có |
| Hỏi LLM cho ca khó, huấn luyện thêm detector trên BDD100K | Chưa làm (xem [Lộ trình](#16-lộ-trình)) |

Tool không cần Claude hay dịch vụ AI trả phí nào: mọi model đều chạy trên máy chủ.

---

## 2. Ai dùng, làm gì

Mỗi người có một tài khoản web riêng, do admin tạo. Vai trò quyết định người đó được làm gì.

Tài khoản web khác với tài khoản CVAT. Issue được tạo bằng tài khoản CVAT của **kết nối** được chọn khi review (trang Kết nối CVAT), nên labeler không cần token.

| Vai trò | Làm được | Thường là |
| --- | --- | --- |
| **labeler** | Chạy review, xem kết quả và lịch sử, đẩy Issue, đọc guideline, đổi mật khẩu của mình | Người gán nhãn tự kiểm tra job của mình |
| **qc** | Mọi việc của labeler, thêm: quản lý guideline và luật, gán guideline cho task, thêm / sửa / xoá kết nối CVAT | Người review, trưởng nhóm gán nhãn |
| **admin** | Mọi việc của qc, thêm: quản lý tài khoản, cài đặt chung (ngưỡng đạt, guideline mặc định, tự review khi sang validation, webhook), nút Kiểm tra ngay trên trang Tự review | Người quản lý máy chủ |

Annotator làm theo luồng tự review thì **không cần tài khoản web**: chỉ làm việc trên CVAT, đọc Issue và nộp lại.

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

1. **Cài thư viện và tải model** (chỉ làm một lần): chạy `cvat_2d\cai_dat.bat`. Script tạo `venv`, cài torch bản CUDA (nếu có GPU NVIDIA) và `requirements.txt`, rồi tải toàn bộ model (khoảng 3 GB, cần Internet). Nếu đã có `venv` thì chỉ cần:
   ```
   venv\Scripts\pip install -r cvat_2d\requirements.txt
   venv\Scripts\python cvat_2d\tai_model.py
   ```
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
7. Trên trang **Kết nối CVAT**, bấm **Thử** ở dòng kết nối để chắc token dùng được.
8. Bật **Cài đặt → Tự review khi job chuyển sang validation** (mục 6) nếu muốn tool tự review mỗi khi annotator nộp job.

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

- **Đầu kết quả:** % box không có lỗi chắc chắn kèm nhãn Đạt / Chưa đạt, số lỗi chắc chắn, số mục "Đang xem xét", số box, thời gian. Có nút **Mở job trên CVAT**, **Copy link gửi labeler**, **Review lại**, **Tải Excel** (file CSV). Job đã review trước đó thì có thêm dòng so sánh "Đã sửa X · Còn Y · Mới Z".
- Kết quả có **4 chế độ xem**:
  - **Danh sách lỗi** (bên trái): lọc Tất cả / Lỗi / Đang xem xét / Tool nhầm / Ghi chú, theo loại lỗi và tầng. Bấm một lỗi để xem ảnh lớn, vùng lỗi phóng to, chi tiết và **đoạn guideline nói về nhãn đó** ở bên phải.
  - **Phân tích:** vẽ chồng lên ảnh gốc nhãn của labeler (xanh = khớp với tool, vàng = nghi, đỏ = lỗi) và những gì tool thấy (nét đứt), kèm bảng đối chiếu từng vật. Người review dùng để kiểm chứng kết quả.
  - **Theo khung hình:** lưới ảnh của mọi frame kèm số lỗi; bấm một ảnh để lọc danh sách theo frame đó.
  - **Issue trên CVAT:** các Issue tool đã tạo trên job, số trả lời và trạng thái *Còn mở* / *Đã xử lý* (labeler bấm Resolve trên CVAT).

### Duyệt và đẩy Issue

1. Lỗi chắc chắn được tick sẵn. Mục "Đang xem xét" thì xem ảnh rồi tự tick.
2. Tool báo sai thì bấm **Tool nhầm** (phím **X**), có thể ghi lý do. Lỗi bị đánh dấu sẽ bỏ tick, **không bao giờ được đẩy**, và được đếm vào tỉ lệ tool nhầm trên trang Tổng quan.
3. Phím tắt: **↑ ↓** chuyển lỗi, **Space** chọn / bỏ, **X** tool nhầm, **N** ghi chú trên ảnh.
4. Ô **Đồng bộ với Issue lần trước** (bật sẵn): lỗi vẫn còn thì giữ Issue cũ, không tạo trùng; lỗi đã hết thì **đóng (resolve)** Issue cũ, không xoá, để còn đo % Issue đúng. Issue của người review thật không bị đụng tới.
5. Các lỗi cùng một vật được **gộp thành 1 Issue** khi đẩy (xem [mục 10](#10-đẩy-issue-lên-cvat)).
6. Bấm **Đẩy N Issue lên CVAT** → xác nhận. Kết quả báo số Issue mới, số giữ lại, số đóng, số thay (lỗi còn nhưng lời nhắn đổi) và dòng "Nhãn gốc không đổi ✔".

### Công cụ của người review

| Công cụ | Dùng khi nào | Lên CVAT thế nào |
| --- | --- | --- |
| **Ghi chú trên ảnh** (nút trên khung ảnh, phím **N**) | Tool không tự thấy nhưng bạn thấy cần nhắc labeler: kéo một khung lên đúng chỗ trên ảnh rồi gõ lời nhắn | Thành 1 Issue ghim đúng khung đó, nội dung là đúng lời nhắn bạn gõ |
| **Sửa lời nhắn** | Lời nhắn của tool khó hiểu hoặc muốn hướng dẫn cụ thể hơn ("kéo cạnh dưới xuống bánh xe") | Issue dùng lời nhắn đã sửa. Có nút trở về lời nhắn gốc |
| **Tool nhầm** (phím **X**) | Tool báo sai | Không đẩy. Đếm vào tỉ lệ tool nhầm |
| **Khung đang xem + phóng to vùng lỗi** | Mỗi lỗi được khoanh khung xanh đứt nét trên ảnh và phóng to bên dưới, để thấy rõ chỗ sai mà không phải zoom tay | — |
| **So sánh với lần trước** | Job được review lại: hiện "Đã sửa X · Còn Y · Mới Z" so với lần review xong gần nhất của cùng job | — |
| **Kèm Issue tổng kết** (tắt sẵn, tick khi cần) | Mỗi lần đẩy thêm 1 Issue ở góc ảnh đầu tiên: % box đúng, đạt hay chưa, số lỗi cần sửa và **link trang lỗi cho labeler** | 1 Issue "Tổng kết (không phải lỗi): …"; lần đẩy sau đóng tổng kết cũ, tạo tổng kết mới |
| **Copy link gửi labeler** | Gửi cho labeler một trang xem lỗi kèm ảnh, **không cần đăng nhập** | — |

Mọi lời nhắn đều giữ nguyên nhãn của labeler: box đúng không bị đụng tới, chỗ sai chỉ có Issue ghim bên trên.

### Trang dành cho labeler

Bấm **Copy link gửi labeler** (hoặc mở link trong Issue tổng kết) để có trang `…/bao-cao.html?run=12&t=<mã>`:

- Đầu trang: job, labeler, % box đúng, Đạt / Chưa đạt, so sánh với lần trước, nút **Mở job trên CVAT**, và 3 bước hướng dẫn sửa.
- Mỗi frame một khung: ảnh có **khung đánh số** đúng chỗ từng lỗi, danh sách lời nhắn cùng số, nút **Mở frame trên CVAT** (nhảy thẳng tới frame đó).
- Lỗi đánh dấu "tool nhầm" không hiện. Nếu đã đẩy Issue, trang chỉ hiện đúng những mục đã đẩy.
- Link có mã bí mật riêng cho từng lần review; sai mã thì không mở được. Dùng trong mạng nội bộ.

### Labeler sửa trên CVAT

1. Mở job (nút **Mở job trên CVAT**). Issue ghim tại đúng box của vật có lỗi. Mỗi vật một Issue; vật nhiều lỗi thì Issue liệt kê từng lỗi kèm tên lỗi.
2. Sửa nhãn rồi Resolve Issue. Mục "Đang xem xét": kiểm tra lại, nhãn đúng thì giữ nguyên và trả lời ngay dưới Issue; sai thì sửa.
3. Chuyển job sang **validation** lại (hoặc bấm **Review lại** trên web). Lần review sau tự đóng Issue của lỗi đã hết, giữ Issue của lỗi còn.

### Quy trình nhóm khuyến nghị

1. Bật **tự review khi job chuyển sang validation** (mục 6). Annotator chỉ làm việc trên CVAT: gán xong thì chuyển validation.
2. Tool tự review. Còn lỗi chắc chắn thì đẩy Issue và trả job về annotation; annotator sửa rồi nộp lại.
3. Job không còn lỗi chắc chắn thì chờ reviewer kiểm chéo (trang **Tự review → Chờ reviewer kiểm chéo**): xem các mục "Đang xem xét", đánh dấu **Tool nhầm** chỗ tool sai, và xem thêm ngẫu nhiên 10–20% số ảnh, vì tool còn bỏ sót khoảng 1/4 số lỗi. Ưu tiên ảnh đêm, mưa, đông xe, vật nhỏ.
4. Job đạt ngưỡng (mặc định ≥ 97%, admin đổi được) thì đạt.
5. Hằng tuần, trưởng nhóm bấm **Đo** ở Tổng quan → Hiệu quả Issue để xem % Issue đúng trên job thật.

---

## 6. Các trang của web

| Trang | Ai dùng | Chức năng |
| --- | --- | --- |
| **Tổng quan** | Mọi vai trò | Trong 7 / 30 / 90 ngày: số lần review, tỉ lệ đạt, % box đúng trung bình, số lỗi, Issue đã đẩy, **tỉ lệ tool nhầm**; biểu đồ loại lỗi hay gặp; xu hướng theo ngày; **Hiệu quả Issue** đo trên CVAT (bấm Đo); bảng **theo labeler** (người được giao job trên CVAT) xếp từ thấp đến cao |
| **Tự review** (trang mở đầu) | Mọi vai trò; nút Kiểm tra ngay: admin | Trạng thái theo dõi (CVAT nào, lần hỏi gần nhất); sơ đồ luồng Annotator nộp → Web QC phát hiện → Tool review → trả về annotation / chờ reviewer → sửa và nộp lại, kèm số liệu sống; 6 số liệu (job đã tự review, % lần bị trả về, vòng / job, Issue tự đẩy, thời gian TB); **bảng mỗi job một dòng** với % box đúng qua từng vòng và kết quả gần nhất; **job chờ reviewer kiểm chéo**; annotator bị trả về nhiều nhất. Tự làm mới mỗi 15 giây |
| **Review job** | Mọi vai trò | Thanh công cụ (kết nối, job + hộp chọn job, task, guideline, chế độ, tuỳ chọn), dòng ngữ cảnh, kết quả với 4 chế độ xem (danh sách lỗi + ảnh, Phân tích, theo khung hình, Issue trên CVAT), Tool nhầm, ghi chú trên ảnh, sửa lời nhắn, đẩy Issue |
| **Lịch sử** | Mọi vai trò | Mọi lần review: job, task, labeler, người chạy ("tự động" nếu tự review khi sang validation, "webhook" nếu qua webhook), kết quả, % box đúng, lỗi / đang xem xét, số tool nhầm, số Issue. Lọc theo job và theo tên |
| **Độ tin cậy tool** | Mọi vai trò | Số đo độ chính xác **của tool** trên ảnh có đáp án: bắt được lỗi, Issue chắc chắn đúng, báo nhầm / 100 box, tool nói "sạch" thì đúng; theo loại lỗi; trước / sau cải tiến; theo điều kiện ảnh (ngày, đêm, thời tiết); segmentation; test đầu cuối trên CVAT; cách đo và các tầng kiểm tra. Đổi bộ dữ liệu BDD100K / ảnh Việt Nam. Số liệu ở `static/do_tin_cay.json`, tạo bằng `tao_do_tin_cay.py` |
| **Guideline** | Xem: mọi vai trò. Sửa: qc, admin | Tải guideline lên; mỗi guideline có 3 tab: **Luật kiểm tra** (trình soạn dạng bảng), **Nội dung guideline** (tra cứu), **YAML** (nâng cao) |
| **Kết nối CVAT** | Xem, thử: mọi vai trò. Thêm/sửa/xoá: qc, admin | Danh sách kết nối, thử kết nối, đặt mặc định, thêm / sửa |
| **Cài đặt** | Đổi mật khẩu: mọi vai trò. Còn lại: admin | Ngưỡng đạt, chế độ mặc định, **guideline mặc định**, **tự review khi job sang validation** (tự đẩy lỗi chắc chắn, tự trả job về annotation khi còn lỗi), **webhook CVAT**, tài khoản |

Thanh bên trái chia 3 nhóm (Vận hành, Báo cáo, Thiết lập) và luôn hiện trạng thái: máy CVAT đang chọn, tổ chức, GPU, webhook, tự review (chấm xanh nhấp nháy khi đang theo dõi). Link gửi cho người khác được:

- Một lần review: `http://<máy chủ>:8000/#run=12`.
- Một trang: `#tab=auto`, `#tab=dash`, `#tab=trust`, `#tab=history`, `#tab=guide`, `#tab=conn`, `#tab=settings`.

### Tự review khi job chuyển sang validation (luồng chính của nhóm)

Cài đặt → **Tự review khi job chuyển sang validation** → tick Bật, chọn CVAT → Lưu.

- Labeler gán xong và chuyển stage của job sang **validation**. Trong vòng 60 giây, web tự đọc job, review theo guideline, rồi đẩy lỗi chắc chắn lên CVAT thành Issue.
- **Còn lỗi chắc chắn** thì web tự trả job về **annotation (rejected)** cho labeler sửa, giống LetmeQC trước đây. **Không còn lỗi chắc chắn** thì job ở lại validation để reviewer kiểm chéo. Mục "Đang xem xét" không làm job bị trả về. Tắt việc trả về bằng ô "Có lỗi chắc chắn thì tự trả job về annotation".
- Labeler sửa xong, nộp lại validation, thì tool review lại. Issue có lỗi đã hết được đóng, lỗi còn thì giữ Issue cũ (không tạo trùng). Mỗi lần trả về được tính là một vòng ở Tổng quan → Hiệu quả Issue.
- Web tự hỏi CVAT nên không cần webhook hay cấu hình mạng. Lần đầu bật, web chỉ ghi nhận các job đang ở validation, không review lại job cũ.
- Kết quả mỗi lần (trả về annotation / chờ reviewer / không trả về được) được lưu và hiện trên trang **Tự review**. Trang này cũng có nút **Kiểm tra ngay** (admin) để hỏi CVAT luôn, không chờ 60 giây.
- Đã thử trên CVAT localhost (2026-10-16): chuyển job sang validation, không bấm gì. Web tự review, giữ 12 Issue cũ còn lỗi, rồi trả job về `annotation / rejected`.

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
3. Nhập số **Task**, bấm **Đọc guideline + lấy nhãn từ task**. Web đọc danh sách nhãn và thuộc tính của task (qua kết nối đang chọn) và điền sẵn bảng: mỗi nhãn một dòng, tự đoán cột "Tool hiểu là" cho nhãn quen (car, pedestrian, two-wheels…), thuộc tính của nhãn hiện mờ trong ô để điền cho nhanh. Web cũng **tự đọc các câu yêu cầu trong guideline** (kích thước tối thiểu, vật dưới N px không bắt buộc gán, vẽ toàn bộ vật hay phần nhìn thấy, Shape hay Track, box kèm polygon, người lái có box riêng, thuộc tính bắt buộc) và điền vào bảng, kèm câu gốc bên dưới để người QC kiểm lại.
4. Kiểm lại và điền thêm từng cột theo guideline: kích thước tối thiểu, tỉ lệ rộng/cao, thuộc tính bắt buộc, không để mặc định, tên gọi khác, số mục; và phần **Quy tắc chung** (người lái có box riêng, vật bị che, Shape hay Track, box kèm polygon, box vượt mép ảnh, **không bắt buộc gán vật dưới N px**). Bấm **Lưu luật**. Web báo nếu có giá trị lạ.
5. Bấm **Gán guideline cho task**. Từ đó review job thuộc task này tự dùng guideline này, và dòng ngữ cảnh trên trang Review báo "Guideline: … · N nhãn có luật".
6. Tab **YAML** cho người quen viết file luật trực tiếp; hai tab luôn đồng bộ khi lưu.

### Các khoá trong file luật

File luật viết bằng YAML. Mỗi nhãn một mục, tên mục **đúng như tên nhãn trên CVAT**.

| Khoá | Ý nghĩa | Ví dụ | Khi vi phạm |
| --- | --- | --- | --- |
| `nhan.<tên>.loai_tool` | Tool hiểu nhãn này là loại nào, để tầng 2 so đúng loại. Chọn một trong: car, truck, bus, motorcycle, bicycle, person, GreenSM | `car` | — |
| `nhan.<tên>.dong_nghia` | Tên khác của nhãn trong guideline. Dùng để tra cứu, và để tool nhận ra nhãn có tên lạ | `[oto, xe hoi]` | — |
| `nhan.<tên>.kich_thuoc_toi_thieu_px` | Cạnh ngắn của box nhỏ hơn mức này (box nhỏ là **lỗi**; tool cũng không đòi gán vật nhỏ hơn) | `10` | Lỗi |
| `nhan.<tên>.ti_le_rong_cao` | Tỉ lệ rộng/cao nằm ngoài khoảng [nhỏ nhất, lớn nhất]. Bỏ qua box xoay | `[0.4, 4.0]` | Đang xem xét |
| `nhan.<tên>.thuoc_tinh_bat_buoc` | Thuộc tính để trống | `[occluded]` | Lỗi |
| `nhan.<tên>.khong_de_mac_dinh` | Thuộc tính vẫn còn giá trị mặc định, có thể labeler quên chọn | `[truncated]` | Đang xem xét |
| `nhan.<tên>.muc` | Số mục guideline nói về nhãn này, được ghi vào Issue | `"3.1"` | — |
| `quy_tac.khong_bat_buoc_duoi_px` | Vật có cạnh ngắn nhỏ hơn mức này **không bắt buộc gán**: tool không báo thiếu, box đã gán vẫn hợp lệ (khác `kich_thuoc_toi_thieu_px`). Tool báo thiếu từ mức này trở lên (mặc định 14 px khi không đặt) | `10` | — |
| `quy_tac.nguoi_lai_co_box_rieng` | Người lái xe máy phải có box person riêng. Ghi đè ô tick trên trang Review | `true` | — |
| `quy_tac.toan_bo_vat` | `true` = vẽ toàn bộ vật kể cả phần bị che; `false` = chỉ vẽ phần nhìn thấy. Tool ước lượng khung theo đúng cách này | `false` | — |
| `quy_tac.kieu_nhan` | `shape` = ảnh rời (mỗi vật 1 shape); `track` = video | `shape` | Lỗi / Đang xem xét |
| `quy_tac.polygon_kem_box` | `cap` = instance segmentation (mỗi vật box + polygon, polygon nằm trong box); `trung` = chỉ cần một trong hai | `cap` | Lỗi |
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
  khong_bat_buoc_duoi_px: 10
  box_ra_ngoai_anh_px: 2
  nhan_ngoai_guideline: false
  muc_chung: "2"
```

File luật thật của BDD100K: `guideline_bdd100k/luat_bdd100k.yaml`.

Ví dụ một Issue tầng 1 trên CVAT:

`Box 'car' thiếu thuộc tính 'occluded' — Guideline mục 3.1.`

### Lưu ý

- Tầng 1 chỉ chạy khi review **theo số job**, vì cần nhãn gốc và thuộc tính trên CVAT. Review từ file export thì chỉ có tầng 2.
- Nhãn có trong task mà không có trong file luật sẽ được ghi cảnh báo trong khung tiến độ, không bị coi là lỗi (trừ khi bật `nhan_ngoai_guideline`).
- Có những điều trong guideline máy không tự kiểm được, ví dụ "ước lượng hợp lý phần bị che". Những điều đó vẫn cần người kiểm.
- **Tool tự đọc guideline thế nào:** web dò các câu yêu cầu theo mẫu câu (có số px, "bắt buộc", "phần nhìn thấy", "Shape / Track", "instance segmentation"…) rồi điền vào luật, kèm câu gốc. Mục nào file luật để trống thì mỗi lần review tool đọc thêm từ guideline và ghi vào nhật ký. Guideline viết bằng văn tự do nên máy không hiểu chắc chắn được mọi câu: vẫn nên **lưu file luật đã kiểm lại**, để kiểm được 100% số box, mỗi lỗi chỉ rõ vi phạm mục nào, và lần sau chạy ra cùng kết quả.
- Có thể dùng một LLM để đọc guideline và soạn nháp file luật, rồi người duyệt lại. Bước này không bắt buộc và hiện chưa làm sẵn trong web.
- Web dùng **bản guideline lưu trong cơ sở dữ liệu** của nó. Sửa file guideline / file luật trong repo thì phải tải lại lên trang Guideline, hoặc sửa trên web rồi bấm Lưu luật.

---

## 8. Tool tìm lỗi như thế nào

Lỗi được bắt bởi các tầng: luật guideline (tầng 1), luật hình học, so với model (tầng 2), segmentation và track. Mỗi lỗi mang một trong hai mức:

- **Lỗi** (chắc chắn): được tick sẵn để đẩy, và làm job bị trả về khi bật tự review.
- **Đang xem xét**: tool chưa đủ bằng chứng (lệch ít, vật bị che, vùng quá tối, vật mờ / nhỏ, model không đồng ý nhau). Không được tick sẵn, chờ người QC xem ảnh rồi tự chọn. Khi đẩy, Issue ghi "Đang xem xét — có thể … Kiểm tra lại: nhãn đúng thì giữ nguyên và trả lời Issue này, sai thì sửa." Không bao giờ làm job bị trả về.

### Tầng 1: kiểm tra theo file luật guideline

Chạy khi guideline có file luật và review theo số job. Không dùng model.

| Lỗi | Quy tắc | Mức |
| --- | --- | --- |
| Box gần như không có diện tích | Rộng hoặc cao dưới 1 px | Lỗi |
| Box vượt ra ngoài ảnh | Vượt mép quá `box_ra_ngoai_anh_px` | Lỗi |
| Box quá nhỏ | Cạnh ngắn nhỏ hơn `kich_thuoc_toi_thieu_px` | Lỗi |
| Tỉ lệ vô lý | Rộng/cao ngoài khoảng `ti_le_rong_cao`, ví dụ person nằm ngang | Đang xem xét |
| Thiếu thuộc tính | Thuộc tính trong `thuoc_tinh_bat_buoc` để trống | Lỗi |
| Thuộc tính còn mặc định | Thuộc tính trong `khong_de_mac_dinh` chưa được chọn | Đang xem xét |
| Nhãn ngoài guideline | Chỉ khi bật `nhan_ngoai_guideline` | Lỗi |

Với track, tool kiểm tra từng keyframe, bỏ qua frame `outside`. Lỗi riêng của track (đứt track, nhảy vị trí, lỗi ID) nằm ở mục [Shape hay track](#shape-hay-track).

### Tầng 2: so với model

Tool tự tìm vật trong ảnh bằng bộ model `label_hq_2d`:

- 4 detector bỏ phiếu: YOLO11x, RT-DETR-x, YOLOv8x-seg, D-FINE-X. Mỗi model nhìn ảnh nguyên, ảnh lật, 4 ô cắt 60%, và ảnh đã làm sáng khi ảnh tối / mưa.
- **Phóng to dải giữa ảnh** (2026-10-17): dải từ 22% tới 72% chiều cao (quanh đường chân trời, nơi có xe / người nhỏ ở xa) được cắt 3 ô chồng nhau, mỗi ô phóng to khoảng 2,4 lần. Chỉ lấy vật nhỏ (cạnh ngắn ≤ 48 px) từ lượt này. Thêm khoảng 1,5 giây mỗi ảnh. Tắt bằng `FAR_ZOOM = False` trong `review_core.py`.
- SAM2 để làm khít mép box.
- CLIP để phân biệt xe GreenSM, kiểm lại car / truck / bus khi labeler và tool khác loại xe, và nhận ra vật giả (biển báo có hình xe, quảng cáo, bóng phản chiếu).
- Khung vật bị che được ước lượng theo guideline: vẽ toàn bộ vật (`toan_bo_vat: true`) hay chỉ phần nhìn thấy (`false`, ví dụ BDD100K).

Sau đó tool ghép box của tool với box của người gán theo độ trùng (IoU ≥ 0.5), ưu tiên cặp cùng nhãn. Khớp khác nhóm (ví dụ gán motorcycle trùm lên người) cần IoU ≥ 0.7.

| Lỗi | Cách phát hiện | Khi nào là "Lỗi" (chắc chắn) | Ví dụ ghi chú |
| --- | --- | --- | --- |
| Sai kích thước | So từng mép box với khoảng ước lượng của mọi model (box SAM và box tốt nhất của từng detector). Chỉ tính lệch khi mép nằm ngoài **mọi** ước lượng quá max(6 px, 10% cạnh). IoU ≥ 0.85 coi là khít. Vật nhỏ hơn 24 px không chấm | Tool chắc về vật, box SAM ổn, và cạnh lệch nhiều nhất **≥ 20% cạnh vật**. Lệch ít hơn, vật bị box khác che đúng phía cạnh lệch, hoặc vùng box quá tối (độ sáng < 30) thì ghi "Đang xem xét" kèm lý do | `Box chưa khít: cạnh dưới thiếu 40px.` · `Box lệch nhiều so với vật: cạnh trái thừa 25px.` |
| Box quá dẹt / quá mảnh | Tỉ lệ rộng/cao phi lý với loại vật (khoảng riêng cho xe 4 bánh, xe 2 bánh, người; `Cyclist` tính như xe 2 bánh). Bỏ qua vật bị mép ảnh cắt | Ngoài khoảng chắc chắn của loại vật. Vật bị box khác che (ví dụ chỉ thấy nóc xe) thì ghi "Đang xem xét" | `Box 'car' quá dẹt (912×14px), không đúng 1 vật. Xoá và vẽ lại.` |
| Sai nhãn | Box khớp vị trí nhưng tool cho nhãn khác | Điểm của tool cao. **Nhầm giữa car / truck / bus** (xe bán tải, xe van dễ nhầm) chỉ chắc khi CLIP cũng chắc ≥ 80% là loại tool nói. Điểm từ 0.36 tới ngưỡng thì là Đang xem xét | `Sai nhãn: đây là 'bus', không phải 'truck'.` |
| Thiếu vật | Tool thấy vật nhưng không có box người gán nào khớp. Issue ghim tại box tool thấy | Tool chắc về vật, vật ≥ 14 px (hoặc ≥ `khong_bat_buoc_duoi_px` của guideline), và vật **không nằm khuất ≥ 40% sau box đã gán** cùng nhóm. Điểm từ 0.33, hoặc vật tool đã bỏ (điểm 0.30–0.33) mà ≥ 3/4 model cùng thấy, thì là "có thể thiếu" | `Thiếu box 'car' ở đây (vật nhỏ ở xa, phóng to để thấy).` |
| Box thừa | Box người gán (≥ 20 px) không chạm vật nào tool thấy, kể cả box tool đã bỏ | CLIP chắc ≥ 90% đây là vật giả (biển báo, quảng cáo, bóng phản chiếu…). Còn lại là Đang xem xét, vì tool cũng bỏ sót vật | `Box thừa: không có 'car' ở đây (biển báo / quảng cáo / bóng phản chiếu?).` |
| Trùng | Hai box người gán **cùng nhóm** (cùng nhãn, hoặc khác nhãn như `car` + `truck`) chồng lên một vật. Báo trên box vẽ sau | IoU giữa hai box ≥ 0.85. IoU 0.6–0.85 mà tool chỉ thấy đúng 1 vật ở đó thì là "có thể trùng" | `Trùng: 2 box 'car' cho cùng 1 vật, xoá 1 box.` |
| Box xoay | Tool chỉ kiểm được box không xoay | Luôn là Đang xem xét | `Box bị xoay 15°, tool không kiểm tra được, xem lại.` |

Các ngưỡng trên là hằng số ở đầu `review_core.py`. Chúng được chỉnh trên 123 ảnh Việt Nam và 400 ảnh BDD100K đầu (`--limit 400`), rồi kiểm lại trên 335 ảnh BDD100K giữ riêng (`--skip 400`). Khi đổi ngưỡng thì chạy lại `review_eval.py` trên phần ảnh giữ riêng để xem tỉ lệ báo nhầm và bỏ sót thay đổi ra sao.

**rider / pedestrian (BDD100K):** job có nhãn `rider` thì người tool thấy đang ngồi trên xe 2 bánh (≥ 25% box người nằm trên box xe, chân người ở tầm xe) được hiểu là `rider`, còn lại là `pedestrian`. Gán ngược thì báo sai nhãn, chỉ chắc khi người nằm hẳn trên xe (≥ 40%).

### Tầng luật hình học (luôn bật, gộp từ LetmeQC)

Chạy **trước** model, không cần GPU, không cần file luật (`rule_tier.py`). Đây là các luật của LetmeQC (`src/rules.py` của nhóm) đã gộp vào web QC, nên chỉ còn một server, một bộ Issue. `app.py` của LetmeQC đã tắt.

| Lỗi | Quy tắc | Mức |
| --- | --- | --- |
| Box gần như không có diện tích | Rộng hoặc cao dưới 1 px | Lỗi |
| Box / polygon vượt ra ngoài ảnh | Vượt mép quá 2 px | Lỗi |
| Box rất nhỏ | Diện tích < 25 px² (LetmeQC dùng 100, nhưng BDD100K gán cả xe xa khoảng 9×10 px) | Đang xem xét |
| Tỉ lệ rộng/cao phi lý | > 10 hoặc < 0.1, chỉ với nhãn tool không hiểu. Nhãn tool hiểu thì dùng khoảng theo từng loại vật (tầng 2). **Bỏ qua box bị mép ảnh cắt** (ví dụ box `Van` rộng 6 px ở mép phải) | Lỗi |
| Trùng box của nhãn model không chấm | Hai box cùng nhãn (ví dụ `traffic sign`, `Tram`, `Misc`) chồng lên nhau IoU ≥ 0.85. Nhãn model chấm được thì trùng box do tầng 2 báo | Lỗi |
| Polygon hỏng | Ít hơn 3 điểm, hoặc viền tự cắt nhau (xoắn) | Lỗi |
| Polygon tràn ra ngoài box của nó | Chỉ khi job vẽ box + polygon cho mỗi vật (`polygon_kem_box: cap`). Cho phép lệch max(3 px, 3% cạnh), quá max(8 px, 8%) thì là lỗi | Lỗi / Đang xem xét |
| `pedestrian` đang ngồi trên xe 2 bánh | Job có nhãn `rider`: box người nằm trên box xe máy / xe đạp của chính labeler | Lỗi / Đang xem xét |
| `rider` không có xe bên dưới | Job có nhãn `rider` mà không có box xe 2 bánh dưới người | Đang xem xét |
| Người trùng box xe | Box `pedestrian` / `person` gần như trùng box `car` / `truck` / `bus` (IoU > 0.5) | Đang xem xét |

Box lệch, thiếu, thừa và trùng box của nhãn model chấm được nằm ở tầng 2, nên không lặp lại ở đây. Khi đẩy, mọi lỗi của cùng một vật (từ mọi tầng) được gộp thành **một Issue**.

### Segmentation từng vật (polygon / mask): so viền với SAM2

File `seg_check.py`. Áp dụng cho polygon / mask của mọi nhãn tool hiểu (xe, người, xe 2 bánh), đọc từ job CVAT hoặc từ file export (CVAT for images 1.1, COCO).

1. Mỗi polygon được cho SAM2 xem bằng **2 prompt**: box của vật mà detector thấy (khớp theo vị trí), và box của chính polygon nới rộng 8%. Nếu mask SAM từ box detector gần như không chạm polygon (IoU < 0.2), thì box đó là vật khác và bị bỏ.
2. So mask labeler với mask SAM. Bỏ qua một dải mép rộng max(2 px, 2% kích thước), vì viền vẽ tay không thể khít từng px:
   - **vẽ lẹm**: phần vật SAM thấy mà polygon không phủ, ≥ 15% vật và ≥ 150 px;
   - **tô thừa ra nền**: phần polygon nằm ngoài vật;
   - **co vào / phình ra cả vòng**: viền lệch đều ≥ 1.5 px quanh ≥ 60% chu vi. Lỗi này khó thấy bằng diện tích khi vật nhỏ;
   - **lệch vật**: vừa thiếu vừa thừa, trùng dưới 50%.
3. Chỉ báo **chắc chắn** khi lỗi nặng (≥ 22%), SAM tự tin (≥ 0.85), vật đủ lớn (≥ 40 px) **và** cả 2 prompt cùng thấy sai. Riêng lỗi tô thừa: nếu một trong 3 phương án mask của SAM khớp polygon (SAM hay chỉ lấy một phần người, ví dụ áo), thì hạ xuống "Đang xem xét".
4. Issue ghim đúng hình phần sai (polygon). Trang **Phân tích** vẽ viền mask SAM2 (nét đứt) chồng lên polygon của labeler, kèm % trùng.

Polygon của vật được tính là một nhãn khi so với tool. Job chỉ vẽ polygon (không box) không bị báo "thiếu" oan. Polygon thì không bị chấm kích thước kiểu box.

**Một vật vừa có box vừa có polygon** là quy ước của job, đặt trong file luật bằng `polygon_kem_box`:
- `trung` (mặc định cũ): báo trùng, vì job chỉ cần một trong hai.
- `cap`: instance segmentation (BDD100K của nhóm). Mỗi vật có cả hai, polygon phải nằm trong box của nó.

Nếu file luật để trống mục này, tool đọc guideline: câu có "instance segmentation" hoặc "box kèm polygon" thì hiểu là `cap`.

### Shape hay track

Đặt trong file luật bằng `kieu_nhan: shape | track`. Để trống thì tool đọc guideline ("gán bằng Shape, không dùng Track", "ảnh rời / độc lập" → shape; "track", "nội suy qua các frame" → track).
- **shape** (ảnh rời, ví dụ BDD100K): mọi track trong job bị báo "cần gán bằng Shape". Issue ghim tại keyframe đầu.
- **track** (video): shape trong job nhiều khung bị báo "cần gán bằng Track".
- Không có guideline mà task CVAT là ảnh rời (mode `annotation`): track bị báo ở mức "Đang xem xét".

**Job dùng Track (video) được review như sau:**
- **Box dạng track**: chấm ở mọi khung, box mỗi khung tính theo nội suy của CVAT.
- **Polygon / mask dạng track**: viền được so với SAM2 **chỉ ở keyframe**, vì keyframe là khung annotator tự vẽ. Ở khung nội suy, CVAT tự sinh hình nên tool không chấm viền, nhưng vẫn tính vật là đã có nhãn, để không báo "thiếu" oan. Tầng luật (polygon xoắn, polygon dưới 3 điểm...) cũng chạy trên keyframe.
- **Lỗi riêng của track** (mức "Đang xem xét", Issue loại "Track bất thường"):
  - **Đứt track**: một track bắt đầu trong vòng 3 khung sau khi track khác cùng nhãn kết thúc, ở cùng chỗ (IoU ≥ 0.4). Có thể là 1 vật bị tách làm 2 track.
  - **Nhảy vị trí**: giữa 2 keyframe gần nhau, tâm box nhảy xa hơn cạnh dài của box và hai box gần như không chạm nhau. Có thể track đã chuyển nhầm sang vật khác. Nhảy đi rồi nhảy về thì chỉ báo 1 lần.
- **Kiểm tra lỗi ID** (`id_check.py`, chạy khi job có track và không phải job ảnh rời):
  - Cách làm: tool tự dựng **track riêng của tool**, bằng cách nối vật detector thấy qua từng khung theo độ trùng vị trí và độ giống hình dạng (embedding CLIP, ghép tối ưu bằng thuật toán Hungarian). Rồi tool đối chiếu ID của annotator với ID của tool, giống chỉ số IDSW của bài toán theo dõi nhiều vật (MOT).

  | Lỗi | Khi nào báo | Mức |
  | --- | --- | --- |
  | **Tráo ID** | Hai track đổi vật cho nhau ở cùng một khung, ví dụ 2 xe đi sát hoặc cắt qua nhau. Bắt được cả khi detector không thấy vật ban đầu của một trong hai track | Lỗi |
  | **Đổi vật (ID switch)** | Track rời vật đang theo, trong khi vật đó vẫn còn: theo ID của tool, hoặc theo vị trí dự đoán (box trước + vận tốc). Hoặc hình vật đổi hẳn | Lỗi khi tool vẫn theo được vật cũ, còn lại là Đang xem xét |
  | **1 vật 2 ID** | Một vật bị tách thành 2 track nối tiếp mà tool theo dõi liên tục, kể cả khi vật đã đi chỗ khác hoặc 2 track khác nhãn. Thay cho luật "đứt track" theo vị trí | Lỗi |
  | **2 ID 1 vật** | Hai track cùng nằm trên một vật từ 2 khung trở lên, kể cả khi 2 box không trùng sát tới mức báo "trùng" | Lỗi |
  | **Track kết thúc sớm** | Track đã outside mà vật vẫn còn trong ảnh, detector thấy chắc ≥ 3 khung liền | Đang xem xét |
  | **Kích thước không đồng bộ** | Mỗi khung lấy tỉ lệ box annotator / box của vật mà tool thấy, so riêng chiều cao và chiều rộng. Vật lại gần hay ra xa thì cả 2 box cùng đổi nên tỉ lệ giữ nguyên. Khung nào lệch > 20% (và ≥ 6 px) so với trung vị của track thì bị báo, kèm kích thước đúng ước lượng và cho biết là keyframe vẽ lệch hay khung nội suy lệch (cần thêm keyframe). Khung annotator đánh dấu `occluded` không bị chấm | Lỗi khi lệch > 35%, còn lại là Đang xem xét |
  | **Kích thước nhảy** (khi detector không thấy vật) | Đoạn 1–3 keyframe liền nhau cao hoặc rộng khác > 30% so với keyframe hai bên, trong khi hai bên gần bằng nhau | Đang xem xét |

  - Ghi chú "thiếu" lặp trên cùng một vật qua nhiều khung được gộp thành 1 ("thiếu ở 4 khung: 0–3, cùng 1 vật: gán 1 track cho cả đoạn"). Đoạn đã có ghi chú "track kết thúc sớm" thì không báo "thiếu" nữa.
  - Đã thử trên CVAT localhost (2026-10-16, video 8 khung có vật chuyển động, 13 track, `kiem_thu/test_e2e_id.py`). Đạt 7/7: bắt đủ 5 kiểu lỗi ID và lỗi kích thước không đồng bộ, không báo nhầm track đúng nào.
  - Giới hạn: vật mà detector gần như không thấy (bị che nhiều, quá nhỏ) thì tool không có bằng chứng, nên lỗi ID trên vật đó có thể bị bỏ sót. Video mới thử trên cảnh dựng (camera lia ngang), chưa thử trên video thật có vật đi cắt nhau. Nên đo thêm khi nhóm có video thật.
- **Cùng một lỗi trên cùng một track lặp ở nhiều khung** (thường là khung nội suy) được gộp thành **1 Issue** ở khung đầu, kèm "lặp ở N khung: a–b". Annotator sửa một lần là hết.
- Đã thử trên CVAT localhost (2026-10-16, job video 6 khung, 16 track, `kiem_thu/test_e2e_track.py`). Đạt 6/6: bắt lỗi lẹm ở keyframe, không báo oan ở khung nội suy, không báo "thiếu" oan, bắt đứt track, bắt nhảy vị trí, không báo "cần Shape".

### QC luôn đọc guideline

- Task chưa gán guideline thì dùng **guideline mặc định** (Cài đặt → Đánh giá → Guideline mặc định).
- Có file luật thì file luật được ưu tiên. Mục nào file luật để trống thì tool **đọc thêm từ chữ trong guideline** và ghi vào log ("+ theo guideline: ...").
- Bộ guideline + tập nhãn + file luật cho BDD100K nằm trong `guideline_bdd100k/` (xem [mục 7](#7-guideline-và-file-luật)).

**Nhãn tool hiểu và không hiểu:**

- Tầng 2 hiểu 7 loại: car, truck, bus, motorcycle, bicycle, person, GreenSM. Tên nhãn của task được khớp theo bảng đồng nghĩa (`oto`, `xe may`, `pedestrian`…), theo nhóm (`vehicle`, `two-wheels`…), và **chấp nhận gõ sai nhẹ** (ví dụ `perdestrian` vẫn hiểu là người).
- **Nhãn đi kèm** (2026-10-17): `Van` (xe van, chấp nhận khi tool thấy car / truck / bus), `Person_sitting` (người ngồi), `Cyclist` / `Motorcyclist` (1 box bao cả người và xe, không chấm kích thước theo box người của tool). Labeler gán đúng các nhãn này thì không bị báo sai nhãn.
- Nhãn khác (ví dụ `traffic sign`, `Tram`, `Misc`, Animal, Obstacle) được liệt kê trong kết quả là "Tool không đánh giá được". Các nhãn này vẫn được kiểm bằng **luật hình học** (ra ngoài ảnh, tỉ lệ phi lý, trùng box, polygon hỏng) và tầng 1, chỉ không bị báo thiếu / sai nhãn.

---

## 9. Không có ground truth thì dựa vào đâu, có cần Claude không

**Vẫn đánh giá được.** Job cần QC không cần có đáp án (GT). Tool so nhãn với 3 nguồn thay cho GT:

| Nguồn đối chiếu | Bắt được lỗi gì | Độ tin |
| --- | --- | --- |
| **Guideline của dự án** (file luật) | Nhãn ngoài danh sách, thiếu thuộc tính, box quá nhỏ, vi phạm quy tắc riêng | Chắc chắn, vì đúng hay sai là do luật quy định |
| **Nhiều model độc lập cùng đồng ý** (4 detector + SAM2 + CLIP), dùng như "GT tạm" | Thiếu vật, sai kích thước, sai nhãn | Cao khi các model đồng thuận. Khi chúng bất đồng thì ghi "Đang xem xét" |
| **Tính nhất quán trong chính job** | Box trùng; sau này thêm track nhảy, cùng một vật đổi nhãn giữa các frame | Trung bình |

**GT chỉ cần để đo xem tool tin được đến đâu, không cần cho từng job.** Các bộ có đáp án hiện có là cơ sở của các con số báo nhầm và bỏ sót (`review_eval.py`, mục 12): 123 ảnh đường phố Việt Nam (`D:\DATA`), 735 ảnh BDD100K (`D:\DATA_EXT\bdd_eval`), 150 ảnh rất tối ExDark, 200 ảnh COCO có polygon. Khi nhận dự án mới với ảnh kiểu khác, nên gán chuẩn 20–30 ảnh rồi đo lại, vì độ tin đo trên bộ này chưa chắc đúng với bộ khác.

**Không bắt buộc dùng Claude.**

- Tool chạy hoàn toàn trên máy chủ bằng các model mã nguồn mở: YOLO11, RT-DETR, YOLOv8-seg, D-FINE, SAM2, CLIP.
- Code không gọi API của Claude hay bất kỳ dịch vụ AI trả phí nào. Mạng chỉ dùng để nói chuyện với CVAT, và để tải model ở lần chạy đầu.
- Claude chỉ được dùng để viết code và tài liệu.

---

## 10. Đẩy Issue lên CVAT

Các lỗi được chọn thành Issue ghim đúng frame, đúng vị trí; các lỗi của cùng một vật được gộp thành một Issue. Tool chỉ gọi API tạo, đọc và đóng (resolve) Issue, và khi bật tự trả về thì đổi stage / state của job. **Không gọi API nào ghi vào annotation.**

### Lệnh gọi

- `POST /api/issues` với nội dung `{job, frame, position: [x1,y1, x2,y1, x2,y2, x1,y2], message}`. `frame` là số frame tuyệt đối trong task.
- `PATCH /api/issues/{id}` với `{resolved: true}` để đóng Issue khi lỗi đã hết.
- `PATCH /api/jobs/{id}` với `{stage: "annotation", state: "rejected"}`: chỉ khi tự review bật "trả job về annotation" và còn lỗi chắc chắn.
- Header `Authorization: Bearer <CVAT_TOKEN>`. Nếu bị 401 thì code tự thử lại dạng `Token <...>` của CVAT bản cũ.
- Gặp lỗi 5xx thì thử lại tối đa 4 lần. Gặp 403 thì báo "tài khoản không có quyền".

### Nội dung Issue

Issue chỉ ghi lỗi, ngắn gọn (bản 2026-10-15 bỏ tiền tố `[Review tự động]`, mã box, IoU và toạ độ). Issue đã ghim đúng chỗ nên không cần toạ độ. Nội dung gồm:

1. Câu mô tả lỗi.
2. Lỗi chưa đủ bằng chứng (nhãn gần đúng, lệch ít, hoặc tool có thể nhầm) ghi **"Đang xem xét — có thể ..."** kèm lý do, và nhắc labeler kiểm tra: nhãn đúng thì giữ nguyên và trả lời Issue, sai thì sửa.
3. **Mỗi vật một Issue** (bản 2026-10-17). Một box / polygon / track có nhiều lỗi thì gộp vào một Issue, đánh số từng lỗi, lỗi chắc lên trước. Issue ghim vào đúng box của vật đó (vật ra ngoài ảnh thì ghim phần nằm trong ảnh), không ghim sang vật khác. Vật bị thiếu thì ghim ở chỗ tool thấy vật.
4. Dòng cuối là mã `[qc:frame|loại|box]`, Issue gộp thì nhiều mã nối bằng `;`. Tool dùng mã này để nhận Issue của mình và không tạo trùng; labeler bỏ qua. Trang Hiệu quả Issue vẫn tính từng lỗi trong Issue gộp theo đúng loại.

Ví dụ:

- `Box chưa khít: cạnh dưới thừa 11px.`
- `Thiếu box 'car' ở đây (vật nhỏ ở xa, phóng to để thấy).`
- `Đang xem xét — có thể box thừa: không thấy 'car' ở đây. Kiểm tra lại: nhãn đúng thì giữ nguyên và trả lời Issue này, sai thì sửa.`
- Một vật có 2 lỗi:
  ```
  'car' này có 3 lỗi: Sai kích thước, Lỗi ID: đổi vật (ID switch), Sai nhãn.
  1. [Sai kích thước] Box chưa khít: cạnh dưới thừa 14px.
  2. [Lỗi ID: đổi vật (ID switch)] Đổi vật: tới khung 3, track 7 chuyển sang xe bên cạnh. Mỗi track chỉ theo 1 vật.
  3. [Sai nhãn] Đang xem xét — có thể sai nhãn: giống 'truck' hơn. Kiểm tra lại: nhãn đúng thì giữ nguyên và trả lời Issue này, sai thì sửa.
  ```

Issue vùng đường được ghim theo đúng đường viền vùng, không theo khung chữ nhật. Issue kiểu cũ (có `[Review tự động]`) vẫn được nhận ra khi đồng bộ.

### Đồng bộ với Issue của lần trước (chống đẩy trùng)

Mỗi Issue tool tạo có một "dấu vân tay" ở cuối nội dung, dạng `[qc:<frame>|<loại lỗi>|<box>]` (box = mã shape/track, hoặc vị trí làm tròn với vật bị thiếu). Khi bật ô **Đồng bộ với Issue tự động lần trước**:

| Tình huống | Tool làm gì |
| --- | --- |
| Lỗi vẫn còn và đã có Issue đang mở | Giữ Issue cũ, **không tạo trùng** |
| Lỗi vẫn còn nhưng lời nhắn đổi, Issue cũ chưa ai trả lời | Đóng Issue cũ, tạo Issue mới với lời nhắn mới |
| Lỗi đã hết | **Đóng (resolved)** Issue cũ, **không xoá**, để giữ lịch sử và đo % Issue đúng |
| Lỗi mới | Tạo Issue mới |
| Issue đã resolved, hoặc do người review thật / tài khoản khác tạo | Không đụng tới |

Issue gộp nhiều lỗi của một vật mang nhiều mã nối bằng `;`. Issue được giữ khi đúng bộ mã đó vẫn còn. Đã kiểm trên CVAT localhost qua các lần review liên tiếp (`kiem_thu/test_e2e_bdd.py`).

### Chứng minh không sửa nhãn

1. Trước khi chấm: lưu annotation vào `review_out/job<id>_<thời gian>/annotations_truoc_review.json`.
2. Sau khi đẩy: tải lại vào `annotations_sau_review.json`, chuẩn hoá (sắp xếp, bỏ trường thời gian) rồi so sánh.
3. Giống nhau thì web báo "Nhãn gốc không thay đổi ✔". Khác thì báo "Nhãn trên CVAT đã khác lúc review". Thường là do labeler đang sửa cùng lúc, vì tool không có lệnh ghi nào vào annotation.

**Trạng thái:** đã chạy thử đầu cuối trên **CVAT localhost** (2026-10-16): Issue hiện đúng frame và đúng chỗ, nhãn gốc không đổi. **Chưa chạy trên job thật của nhóm.** Cần kiểm thêm với job bắt đầu giữa task (không bắt đầu từ frame 0) trên CVAT của nhóm.

---

## 11. Kết quả và báo cáo

**Trên web** (tab Review job, hoặc mở lại từ Lịch sử):

- Thẻ số liệu.
- Bảng lỗi.
- Ảnh vẽ đè, vùng lỗi phóng to, chế độ Phân tích.
- Đoạn guideline liên quan.
- Kết quả lần đẩy Issue gần nhất.
- File Excel (CSV) tải về.
- Trang lỗi cho labeler (`bao-cao.html`), mở được không cần đăng nhập.

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

**Cách đọc con số "% box không có lỗi chắc chắn"** = (số box − số box có ít nhất một lỗi chắc chắn) ÷ số box. Box chỉ có mục "Đang xem xét" vẫn được tính là đúng. Lỗi "thiếu vật" không làm giảm con số này vì không gắn với box nào, nên luôn xem cả số lỗi.

**Trang Tổng quan** tổng hợp các lần review theo labeler (người được giao job trên CVAT), loại lỗi hay gặp, xu hướng theo ngày và **tỉ lệ tool nhầm** (từ các đánh dấu Tool nhầm). Nên dùng để hướng dẫn lại đúng chỗ yếu, không dùng để phạt, vì tool vẫn còn báo nhầm.

**Trang Tự review** tổng hợp riêng các lần tự review khi job sang validation: theo job và theo vòng. **Trang Độ tin cậy tool** là báo cáo về chính tool (mục 12), dùng cho reviewer và người chấm đề tài.

---

### Đo hiệu quả trên job thật (Tổng quan → Hiệu quả Issue)

Bấm **Đo** trên trang Tổng quan. Web đọc Issue và nhãn hiện tại của các job đã đẩy Issue trên CVAT (`web_qc/hieu_qua.py`). Mỗi Issue của tool mang mã `[qc:frame|loại|vật]`. Web so nhãn **lúc review** (`annotations_truoc_review.json` của lần review đã tạo Issue đó) với nhãn **hiện tại**:

| Kết quả | Khi nào | Tính là |
| --- | --- | --- |
| Đã sửa | Vật bị Issue chỉ ra đã được sửa / xoá, hoặc chỗ báo thiếu đã có vật mới | Issue **đúng** |
| Đóng không sửa | Issue đã resolved mà nhãn không đổi | Issue **sai** (tool báo nhầm) |
| Tool nhầm | Người review đánh dấu "tool nhầm" trên web | Issue **sai** |
| Còn mở | Issue chưa đóng, nhãn chưa đổi | Chưa tính |

| Chỉ số | Công thức |
| --- | --- |
| **% Issue đúng** (annotator sửa theo) | Đã sửa / (Đã sửa + Đóng không sửa + Tool nhầm) |
| **% lỗi bắt được trước review chéo** | Đã sửa / (Đã sửa + Issue do người review tạo thêm). Issue người tạo là Issue không có mã qc: lỗi tool bỏ sót |
| **Số vòng bị trả lại / job** | Số lần review có đẩy Issue (mỗi lần job quay lại annotator một vòng) |

Kèm bảng theo loại lỗi (để biết loại nào tool hay đúng, loại nào hay nhầm) và bảng theo job / labeler.

Để số liệu đúng: khi review lại, Issue có lỗi đã hết được **đóng (resolved)**, không xoá, nên vẫn còn để đo. Issue gộp nhiều lỗi của một vật được tính **từng lỗi** theo đúng loại. Annotator sửa vật đó theo bất kỳ cách nào thì mọi lỗi trong Issue đều được tính là "đã sửa".

Đã thử đầu cuối trên CVAT localhost (2026-10-16, task BDD100K 4 ảnh, 10 lỗi cài vào, chạy lại được bằng `venv\Scripts\python cvat_2d\kiem_thu\test_e2e_bdd.py`, ảnh ở `du_lieu_danh_gia/bdd_e2e`):
- Tool bắt **10/10** lỗi (9 chắc chắn, 1 đang xem xét).
- Giả lập annotator sửa 5 lỗi (6 Issue), đóng 1 Issue mà không sửa. Reviewer đánh "tool nhầm" 1 ghi chú và tự thêm 1 Issue.
- Web tính ra: % Issue đúng **75%** (6/8), % lỗi bắt trước review chéo **85.7%** (6/7), số vòng trả lại **2**.
- Nhãn gốc không đổi sau khi đẩy Issue.

---

## 12. Độ tin cậy, giới hạn và rủi ro

Tool đủ tin để thay phần lớn công kiểm tra thô, nhưng **chưa thay hoàn toàn người review**. Số đo bằng `review_eval.py`, cố ý cài lỗi đã biết vào nhãn đúng, ngày 2026-10-17. Ảnh dùng để báo cáo **không dùng để chỉnh ngưỡng**. Xem kèm biểu đồ ở trang **Độ tin cậy tool**.

| Chỉ số | BDD100K: 335 ảnh giữ riêng, vật từ 10 px | Ảnh đường phố Việt Nam: 123 ảnh |
| --- | --- | --- |
| **Bắt được lỗi** (chắc chắn + đang xem xét) | **77,4%** (chắc chắn 36%) | 70,4% (chắc chắn 39%) |
| **Issue chắc chắn là lỗi thật** | **84%** | 93% |
| **Báo nhầm / 100 box đúng** | **1,45** chắc chắn + 18,7 đang xem xét | 0,7 chắc chắn + 6,2 đang xem xét |
| Tool nói ảnh "sạch" thì sạch thật | 96% | 89% |
| Theo loại (BDD100K) | Trùng 98%, thừa 90%, sai kích thước 82%, thiếu 69%, sai nhãn 68% | |
| Theo điều kiện (BDD100K) | Ban ngày 80%, hoàng hôn 80%, ban đêm 70% | |

**So với bản trước cải tiến 2026-10-17** (cùng 335 ảnh BDD100K, cùng lỗi cài vào, vật từ 10 px):

| Chỉ số | Trước | Sau |
| --- | --- | --- |
| Bắt được lỗi | 74,2% | 77,4% |
| Issue chắc chắn đúng | 69% | 84% |
| Báo nhầm chắc chắn / 100 box | 4,0 | 1,45 |

**Những thay đổi tạo ra kết quả trên:**
- Lỗi chưa đủ bằng chứng chuyển sang "Đang xem xét". Lỗi không bị bỏ đi, chỉ hạ mức.
- CLIP kiểm lại khi labeler và tool khác nhau về loại xe.
- Bắt trùng box khác nhãn hoặc lệch nhẹ.
- Báo "có thể thiếu" với vật mờ mà nhiều model cùng thấy.
- Phóng to dải giữa ảnh.
- Guideline 10 px.

Cái giá phải trả là mỗi 100 box có thêm khoảng 7 mục "Đang xem xét" để reviewer xem.

### Chỗ tool còn yếu

- **Vật nhỏ 10–20 px:** tool chỉ bắt khoảng một nửa số lỗi thiếu vật / sai nhãn ở cỡ này (vật trên 60 px bắt khoảng 90%). Khoảng một phần ba số vật 10–15 px **không model nào thấy**, kể cả khi đã phóng to. Muốn tăng thì phải huấn luyện thêm detector trên BDD100K.
- **Ban đêm và cảnh xe máy dày đặc:** bắt kém ban ngày khoảng 10 điểm %. Ảnh đám đông ở Hà Nội mới tìm được khoảng 40% số người.
- **Mục "Đang xem xét" thừa:** BDD100K có khoảng 19 mục / 100 box đúng. Một phần là vật thật mà đáp án BDD100K không gán, phần còn lại là tool nghi oan. Reviewer xem các mục này.
- **Box amodal** (vẽ cả phần bị che): bộ đáp án đóng box theo phần nhìn thấy, nên chưa đo được độ đúng kiểu amodal.
- Chấm box và polygon / mask 2D. Chưa chấm keypoint, polyline. Job 3D bị từ chối.
- Tool chưa có model cho `train`, `traffic light`, `traffic sign`. Các nhãn này chỉ được kiểm bằng luật (ra ngoài ảnh, trùng box, thuộc tính bắt buộc…), không bị báo thiếu.
- **Segmentation:** lỗi "mất 1 phần vật" bỏ lọt khoảng 1/3, "vẽ thô ít điểm" khoảng 60%. Vật nhỏ dưới 64 px chỉ bắt được khoảng 63%.

### Số đo segmentation (2026-10-16)

`review_eval.py --seg` trên COCO val2017: ảnh đường phố có xe, polygon do người vẽ thật (`tao_bo_seg_eval.py`). Ngưỡng chỉnh trên 120 ảnh, kiểm lại trên **80 ảnh không dùng để chỉnh**.

| Chỉ số | 80 ảnh kiểm | 120 ảnh chỉnh |
| --- | --- | --- |
| Polygon được chấm | 445 | 699 |
| Báo nhầm trên polygon đúng / 100 | 1.3 lỗi + 9.2 đang xem xét | 1.3 lỗi + 7.0 đang xem xét |
| Lỗi polygon cài vào bắt được | **74.9%** (chắc 39.1%) / 179 lỗi | 66.4% (chắc 35.9%) / 262 lỗi |
| Co lẹm viền / phình ra nền / lệch vị trí | 78% / 80% / 91% | 71% / 73% / 83% |
| Mất 1 phần vật / vẽ thô | 67% / 42% | 47% / 48% |
| Vật nhỏ < 64 px / 64–160 px / ≥ 160 px | 63% / 86% / 89% | 52% / 84% / 94% |

SAM2 so với polygon COCO cũng chỉ trùng trung vị 0.85: một phần ba polygon người vẽ lệch SAM quá 20%. Vì vậy phần lớn ghi chú segmentation ở mức "Đang xem xét", cần người xem. Trước 2026-10-16, polygon / mask của từng vật **không được kiểm** (0%).

### Rủi ro vận hành

| Rủi ro | Cách giảm |
| --- | --- |
| Báo nhầm làm labeler mất niềm tin | Giữ ngưỡng "chắc" chặt. Mục "Đang xem xét" luôn để người duyệt, không làm job bị trả về |
| Một GPU chỉ chạy được một job mỗi lần | Hàng đợi có vị trí chờ và **thời gian chờ dự kiến**; ảnh được tải song song trong lúc GPU chấm. Đông người thì thêm GPU / máy (xem dưới) |
| Labeler sửa trong lúc đang QC | Phép so sánh trước/sau sẽ phát hiện và cảnh báo. Chạy lại review |
| CVAT nâng phiên bản làm đổi cách đánh số frame hoặc API Issue | Mỗi lần nâng cấp, chạy lại bài thử đẩy Issue trên một job nhỏ |
| Hỏng ổ đĩa máy chủ | Sao lưu `web_qc/data/` và `review_out/` |

---

### Web review được bao nhiêu người cùng lúc

- **Người dùng web:** vài chục người mở web, xem kết quả, duyệt lỗi, đẩy Issue cùng lúc không vấn đề gì (máy chủ FastAPI xử lý song song).
- **Phần chấm lỗi (GPU):** chạy **lần lượt từng job** trên 1 GPU. Chạy song song nhiều job trên cùng 1 GPU không nhanh hơn (chỉ chia nhau sức máy) và dễ tràn bộ nhớ (RTX 4050 Laptop có 6 GB).
- **Tốc độ đo được** (chế độ Chính xác, RTX 4050 Laptop, lịch sử review trên máy chủ):
  - **Ảnh mới** (chưa có cache): khoảng **5–20 giây / ảnh**, tuỳ số vật và ảnh đêm / mưa. Lượt phóng to dải giữa ảnh thêm khoảng 1,5 giây.
  - **Ảnh đã chấm** (có cache kết quả detect): khoảng **1 giây / ảnh**.
  - Job 100 ảnh mới mất khoảng 10–30 phút. Lần chạy đầu sau khi bật web còn mất thêm thời gian nạp model.
  - Chế độ Nhanh nhanh hơn nhưng kém chính xác.
- Người nộp sau thấy "Đang chờ · thứ 2 · còn ~3 phút" và có thể đóng trang, mở lại sau ở Lịch sử hoặc trang Tự review. Ảnh đã chấm được lưu cache nên **Review lại** cùng job nhanh hơn nhiều.
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
| "Tool KHÔNG đánh giá được các nhãn: …" | Nhãn ngoài các loại tool hiểu (traffic sign, Tram, Animal, Obstacle…) | Bình thường. Các nhãn này vẫn được kiểm bằng luật hình học và tầng 1, chỉ không bị báo thiếu / sai nhãn |
| Tự review không chạy khi job sang validation | Chưa bật hoặc chưa Lưu trong Cài đặt; lỗi hỏi CVAT (token hết hạn); lần đầu bật | Xem dòng trạng thái trên trang **Tự review**. Lần đầu bật, web chỉ ghi nhận job đang ở validation, không review job cũ: chuyển job về annotation rồi nộp lại, hoặc bấm **Kiểm tra ngay** |
| Tool báo thiếu nhiều vật rất nhỏ | Guideline chưa có kích thước "không bắt buộc gán" | Điền ô **Không bắt buộc gán vật dưới (px)** trong luật của guideline (BDD100K: 10) rồi Lưu luật |
| Sửa guideline / file luật trong repo mà tool không theo | Web dùng bản guideline lưu trong cơ sở dữ liệu | Tải lại guideline lên, hoặc sửa luật trên web rồi bấm Lưu luật |
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
│   + luồng tự review: hỏi CVAT mỗi 60 giây, job mới   │◄── đọc job ở ── CVAT
│     vào validation thì xếp hàng                      │    validation
│     │                                                │
│     ├─ Đọc dữ liệu (review_core.Cvat / read_export)  │◄── chỉ đọc ── CVAT
│     ├─ Luật hình học: rule_tier.check                │      (job, nhãn, ảnh)
│     ├─ Tầng 2: label_hq_2d + review_core.compare     │
│     │   (+ seg_check, area_check, frame_check,       │
│     │    id_check cho polygon, đường, tag, track)    │
│     ├─ Tầng 1: guideline.rule_check                  │
│     ├─ Hợp nhất lỗi, chia mức chắc / đang xem xét    │
│     ├─ Đẩy Issue gộp theo vật (Review.push) ─────────┼── ghi / đóng Issue ──► CVAT
│     └─ Tự review: còn lỗi chắc → trả job về ─────────┼── đổi stage job ──► CVAT
│                                                      │
│ store.py  SQLite: tài khoản, lịch sử, guideline      │
│ review_out/  kết quả + bản sao nhãn trước/sau        │
└──────────────────────────────────────────────────────┘
```

Bộ đẩy Issue (và bước trả job về khi tự review) là nơi duy nhất ghi lên CVAT, và không bao giờ ghi vào annotation. Sau khi ghi, bộ đẩy tải lại nhãn để so với bản sao.

### Các file

| File | Việc làm |
| --- | --- |
| `cvat_2d/web_qc.bat` | Tìm `venv`, chạy `web_qc/server.py`. Tham số: `--lan`, `--port` |
| `web_qc/server.py` | FastAPI: phiên đăng nhập (`SessionMiddleware`, khoá trong `data/secret.key`), phân quyền theo vai trò, toàn bộ API, phục vụ `static/` |
| `web_qc/worker.py` | Hàng đợi một luồng. Đọc `.env` khi cần (`env_config()`), lấy kết nối và client CVAT (`connection_for()`, `cvat_client()`). Giữ `ToolRunner` để không phải nạp lại model. Chạy tầng 2 rồi tầng 1, lưu kết quả, đẩy Issue. Luồng thứ hai hỏi CVAT mỗi 60 giây (`poll_validation`) để tự review job mới vào validation; `return_job` trả job về annotation và lưu kết quả vào `runs.returned`. Sau khi tắt rồi bật web, dựng lại kết quả cũ từ `review_out/` |
| `web_qc/store.py` | SQLite `data/web_qc.db`: bảng `users`, `runs`, `guidelines`, `task_guideline`, `connections`, `feedback`, `settings`, `notes`, `edits`. Tự thêm cột mới khi nâng cấp. Mã hoá token. Tạo admin đầu tiên |
| `web_qc/guideline.py` | Đọc PDF (pypdf) / DOCX / TXT / MD, chia mục, tìm đoạn liên quan (bỏ dấu tiếng Việt), đọc và kiểm tra file luật, tạo mẫu từ nhãn task, `rule_check` (tầng 1), `apply_to_core` (đưa tên nhãn trong file luật vào bảng đồng nghĩa của tầng 2 trong lúc review) |
| `web_qc/static/` | `index.html`, `app.js`, `style.css` (giao diện), `bao-cao.html` (trang lỗi cho labeler), `do_tin_cay.json` (số liệu trang Độ tin cậy). JS thuần, không cần build, tự đổi theo chế độ sáng/tối |
| `web_qc/tao_do_tin_cay.py` | Gom kết quả `review_eval.py --json` và test đầu cuối thành `static/do_tin_cay.json` |
| `cvat_2d/review_core.py` | Bộ chấm dùng chung với bản Gradio và dòng lệnh: kết nối CVAT, đọc file export, so sánh (`compare`), phóng to dải giữa ảnh (`detect_far`), khớp tên nhãn (`build_label_map`, nhãn đi kèm, gõ sai), vẽ ảnh, lưu báo cáo, gộp Issue theo vật (`issue_groups`) và đẩy Issue |
| `cvat_2d/label_hq_2d.py` | Bộ model tìm vật (4 detector + SAM2 + CLIP + amodal) |
| `cvat_2d/review_eval.py` | Đo độ tin của bộ chấm trên GT bằng cách cài lỗi giả. Tuỳ chọn: `--visible` (vẽ phần nhìn thấy), `--min-px N` (guideline không bắt buộc gán vật dưới N px), `--limit` / `--skip` (chia ảnh chỉnh / ảnh giữ riêng), `--rows` (kết quả từng lỗi kèm cỡ vật), `--dump` (từng mục báo nhầm), `--no-far` (tắt phóng to), `--cond dem/mua`, `--seg <thư mục>` (đo segmentation) |
| `cvat_2d/id_check.py` | Lỗi ID của track: tool tự dựng track (vị trí + CLIP + Hungarian), đối chiếu ID annotator (tráo ID, đổi vật, 1 vật 2 ID, 2 ID 1 vật, kết thúc sớm) |
| `cvat_2d/seg_check.py` | Segmentation từng vật: so polygon / mask với mask SAM2 (2 prompt, dải mép, lệch đều cả vòng) |
| `cvat_2d/rule_tier.py` | Tầng luật hình học gộp từ LetmeQC, chạy trước model (gồm trùng box của nhãn model không chấm) |
| `cvat_2d/area_check.py`, `frame_check.py` | Vùng đường `drivable_area` (so với SegFormer) và tag cho cả ảnh (so bằng CLIP) |
| `cvat_2d/kiem_thu/` | Test đầu cuối trên CVAT (`test_e2e_bdd.py`, `test_e2e_id.py`, `test_e2e_track.py`), dùng kết nối số 2 và bản sao dữ liệu web |
| `cvat_2d/tao_bo_seg_eval.py` | Tạo bộ đo segmentation từ COCO val2017 (ảnh đường phố, polygon người vẽ) |
| `cvat_2d/web_qc/hieu_qua.py` | Đo hiệu quả Issue trên job thật (% Issue đúng, % lỗi bắt trước review chéo, số vòng trả lại) |
| `cvat_2d/guideline_bdd100k/` | Guideline BDD100K (det + ins-seg), tập nhãn CVAT `labels_bdd100k.json`, file luật `luat_bdd100k.yaml` |

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
| `GET /api/setup` | — | Trang đăng nhập biết đây có phải lần chạy đầu không (không lộ mật khẩu) |
| `GET/PUT /api/settings` | admin | Ngưỡng đạt, chế độ mặc định, guideline mặc định, tự review khi sang validation, webhook |
| `GET /api/auto/status` | Mọi vai trò | Trạng thái tự review: bật chưa, kết nối theo dõi, lần hỏi gần nhất, lỗi, hàng đợi (không lộ token / secret) |
| `POST /api/auto/check` | admin | Hỏi CVAT ngay, không chờ 60 giây |
| `GET /api/hieu_qua?days=` | Mọi vai trò | Hiệu quả Issue đo trên CVAT (% Issue đúng, lỗi bắt trước review chéo, số vòng trả lại) |
| `GET /api/runs/{id}/analysis/{stem}`, `GET /api/runs/{id}/raw/{stem}` | Mọi vai trò | Dữ liệu và ảnh gốc cho chế độ Phân tích |
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
| `web_qc/data/secret.key` | Khoá ký cookie phiên **và** khoá mã hoá token CVAT. Xoá file này thì mọi người phải đăng nhập lại **và mọi token đã lưu không giải mã được nữa** (phải nhập lại token cho từng kết nối) |
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

### Kiểm thử đã làm (2026-10-16 → 2026-10-17)

- Test đầu cuối trên CVAT localhost (2.78.1): job BDD100K box + polygon 10/10 lỗi, lỗi ID 7/7, job Track 6/6 (`kiem_thu/`).
- Đo độ chính xác trên 735 ảnh BDD100K (400 chỉnh / 335 giữ riêng), 123 ảnh Việt Nam, 150 ảnh ExDark, 80 ảnh COCO segmentation (mục 12).
- Luật hình học trên nhãn thật của 2 bộ nhóm gán (29 ảnh Việt Nam, 204 ảnh KITTI): bắt 100% lỗi cài vào (ra ngoài ảnh, không có diện tích, polygon xoắn / dưới 3 điểm, trùng box nhãn lạ), 0 báo nhầm; bắt đủ 1123/1123 box bị lặp trong job 4598181.
- Gộp Issue theo vật: 149/149 Issue trên dữ liệu review thật ghim đúng box của vật; đo hiệu quả với Issue gộp kiểm bằng CVAT giả.
- Giao diện mới: chạy web trên bản sao dữ liệu, chụp màn hình 9 trang bằng Chrome headless, không có lỗi JavaScript.

---

## 16. Lộ trình

| Giai đoạn | Nội dung | Cổng để qua giai đoạn | Trạng thái |
| --- | --- | --- | --- |
| 1. Web + guideline | Web đầy đủ, 3 vai trò, hàng đợi, lịch sử, đọc và tra cứu guideline, tầng 1 theo file luật, đổi job bằng `.env` | Chạy thử không cần CVAT ổn, đọc được CVAT | **Đã xong** |
| 2. Thử trên CVAT | Tạo job 2D có lỗi cố ý, review theo số job, đẩy Issue thật, kiểm frame và vị trí, tự review khi sang validation | Issue hiện đúng chỗ, nhãn gốc không đổi | **Đã xong trên CVAT localhost** (2026-10-16). Còn thử trên job thật của nhóm |
| 3. Hoàn thiện | Chống đẩy trùng, thống kê theo labeler, webhook, nhiều kết nối, tool nhầm, kiểm tra track và lỗi ID, trang cho labeler, tự review khi sang validation, đo hiệu quả Issue, Issue gộp theo vật, trang Tự review và Độ tin cậy | 2–3 labeler dùng thử 1 tuần ổn định | **Đã xong**, chờ dùng thử |
| 4. Nâng model | Huấn luyện thêm detector trên BDD100K (`D:\DATA_EXT\bdd_train`, 9.265 ảnh) và dữ liệu giao thông Việt Nam (đêm, mưa, đông xe), đo lại bằng `review_eval.py` trên ảnh giữ riêng | Bắt được lỗi ≥ 85% ở vật từ 10 px, báo nhầm chắc chắn ≤ 1,5 / 100 box | Chưa làm |

### Việc tiếp theo

- [ ] Chạy 3–5 **job thật** của nhóm qua tự review, đo % Issue đúng ở Tổng quan → Hiệu quả Issue.
- [ ] Thử với job bắt đầu giữa task trên CVAT của nhóm (kiểm số frame của Issue).
- [ ] Giới hạn số vòng trả về (ví dụ 3 vòng), quá mức thì chuyển reviewer, để annotator và tool không đẩy qua đẩy lại mãi.
- [ ] Chạy web QC như dịch vụ tự khởi động cùng Windows, sao lưu `web_qc/data/` hằng ngày.
- [ ] Huấn luyện thêm detector (giai đoạn 4). Trước khi chấm, kiểm ảnh huấn luyện không trùng với 735 ảnh dùng để chấm.

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
