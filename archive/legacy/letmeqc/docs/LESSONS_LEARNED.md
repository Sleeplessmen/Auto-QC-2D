# Bài Học Kinh Nghiệm

Tài liệu tổng hợp các bài học rút ra từ quá trình triển khai và vận hành hệ thống LetmeQC.

---

## Bảng Tóm Tắt

| ID  | Ngày | Chủ đề | Vấn đề | Chi tiết | Bài học rút ra |
| --- | ---- | ------ | ------ | -------- | -------------- |

---

## Hướng dẫn Sử dụng

1. **Thêm bài học mới**: Điền thông tin vào hàng trống hoặc thêm hàng mới
2. **ID**: Số thứ tự tự động (1, 2, 3,...)
3. **Ngày**: Định dạng YYYY-MM-DD
4. **Chủ đề**: Lĩnh vực (VD: CVAT API, QC Rules, Performance, vv)
5. **Vấn đề**: Mô tả ngắn gọn vấn đề gặp phải
6. **Chi tiết**: Mô tả chi tiết vấn đề
7. **Bài học rút ra**: Giải pháp/điều cần ghi nhớ

---

## Ví dụ Điền

| ID  | Ngày       | Chủ đề         | Vấn đề                                   | Chi tiết                                       | Bài học rút ra                                                     |
| --- | ---------- | -------------- | ---------------------------------------- | ---------------------------------------------- | ------------------------------------------------------------------ |
| 1   | 2026-10-14 | CVAT API       | Lỗi 401 Unauthorized                     | Không truyền X-Organization header khi gọi API | Luôn truyền header `X-Organization: <org_slug>` cho tất cả request |
| 2   | 2026-10-14 | Issue Position | Box lỗi không hiển thị trên UI           | Truyền position=[0,0,0,0] thay vì tọa độ thực  | Tính position dựa trên loại lỗi theo bảng quy định                 |
| 3   | 2026-10-14 | Job Status     | Không thể cập nhật status sau khi submit | Sử dụng token của Assignee (Annotator)         | Phải dùng token có quyền Maintainer/Owner/Reviewer                 |
| 4   | 2026-10-14 | CVAT Entity Mapping | Giả định sai về Object ID của hệ thống CVAT | Hàm kiểm tra Mask tràn Bbox sử dụng bbox.id == poly.id để đối chiếu, trong khi CVAT cấp ID riêng biệt cho từng hình học trừ khi được nhóm lại. | Phải map các hình học liên quan thông qua trường group_id của CVAT hoặc sử dụng thuật toán đối chiếu không gian (spatial mapping bằng IoU), tuyệt đối không map qua id trực tiếp. |
| 5   | 2026-10-14 | QC Rules & Test Data | Hardcode logic không khớp với dữ liệu test | Hàm _get_label_hierarchy hardcode các class (truck, bus, person) không hề tồn tại trong tập label.json kiểm thử. | Hạn chế tối đa việc hardcode cấu trúc nhãn vào mã nguồn. Nên nạp logic phân cấp từ cấu hình bên ngoài và đảm bảo dữ liệu mock bao phủ toàn bộ các class được khai báo. |
| 6   | 2026-10-14 | Implementation Sync | Bỏ sót rule khi chuyển đổi từ Design sang Code | File tài liệu định nghĩa 10 rule nhưng file rules.py chỉ thực thi 9 rule (thiếu hàm Missing Attributes). | Bắt buộc đối chiếu chéo (traceability) giữa danh sách rule trong tài liệu Markdown và các hàm thực thi trong Python trước khi kiểm thử. |
| 7   | 2026-10-14 | Mock Data Quality | Thiếu thuộc tính để kiểm thử toàn vẹn rẽ nhánh | Rule Duplicate Objects có nhánh kiểm tra so sánh attributes, nhưng toàn bộ nhãn hình học trong JSON lại không có thuộc tính nào để test. | Dữ liệu mock (JSON) phải chứa đầy đủ các cấu trúc mở rộng (như attributes, occluded) để kích hoạt và kiểm thử toàn vẹn mọi nhánh if/else trong rule engine. |

---

_Tài liệu được cập nhật liên tục trong quá trình phát triển hệ thống LetmeQC_
