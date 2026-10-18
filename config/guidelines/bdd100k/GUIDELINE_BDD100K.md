# Guideline gán nhãn BDD100K: Object Detection + Instance Segmentation 2D

Phiên bản 1.1, 2026-10-17 (thêm mục 3.5a: vật dưới 10 px không bắt buộc gán). Dùng cho task CVAT của nhóm, ảnh BDD100K 1280×720. Tool QC tự động (web QC) đọc file này, nên mỗi quy tắc được viết thành một câu rõ ràng.

## 1. Phạm vi

1.1 Bài toán gồm hai phần:
- **Object detection:** mỗi vật được bao bằng một box.
- **Instance segmentation:** mỗi vật thuộc 8 loại có hình (xem mục 2) có thêm một polygon (hoặc mask) ôm sát viền.

1.2 Mỗi ảnh là một ảnh độc lập, không phải video. Gán bằng **Shape**, không dùng Track. Vật không được nối qua các khung hình.

1.3 Instance segmentation: mỗi vật vừa có box vừa có polygon. Box và polygon phải cùng nhãn và khớp nhau: polygon nằm trong box, box ôm sát polygon.

## 2. Tập nhãn

| Nhãn | Định nghĩa | Box | Polygon / mask | Thuộc tính |
| --- | --- | --- | --- | --- |
| `pedestrian` | Người đi bộ, đứng, ngồi trên vỉa hè, không ở trên xe | Có | Có | occluded, truncated |
| `rider` | Người đang lái hoặc ngồi trên xe máy / xe đạp | Có | Có | occluded, truncated |
| `car` | Ô tô con, taxi, SUV, xe van nhỏ, bán tải | Có | Có | occluded, truncated |
| `truck` | Xe tải, xe container, xe chuyên dụng chở hàng | Có | Có | occluded, truncated |
| `bus` | Xe buýt, xe khách | Có | Có | occluded, truncated |
| `train` | Tàu hỏa, tàu điện chạy trên ray | Có | Có | occluded, truncated |
| `motorcycle` | Xe máy, xe tay ga (chỉ chiếc xe, không gồm người lái) | Có | Có | occluded, truncated |
| `bicycle` | Xe đạp (chỉ chiếc xe, không gồm người lái) | Có | Có | occluded, truncated |
| `traffic light` | Đèn giao thông (cụm đèn) | Có | Không | occluded, truncated, trafficLightColor |
| `traffic sign` | Biển báo giao thông (mặt biển) | Có | Không | occluded, truncated |
| `image_info` | Tag cho cả ảnh | — | — | weather, scene, timeofday |

Giá trị thuộc tính:
- `occluded`: vật bị vật khác che một phần. `truncated`: vật bị mép ảnh cắt.
- `trafficLightColor`: red, yellow, green, none (không thấy đèn nào sáng).
- `weather`: clear, overcast, partly cloudy, rainy, snowy, foggy, undefined.
- `scene`: city street, highway, residential, parking lot, gas stations, tunnel, undefined.
- `timeofday`: daytime, night, dawn/dusk, undefined.

## 3. Box (object detection)

3.1 Box ôm sát phần nhìn thấy của vật. Chỉ vẽ phần nhìn thấy, không vẽ phần bị che (không ước lượng phần khuất).

3.2 Box không được ra ngoài ảnh. Vật bị mép ảnh cắt thì kéo box tới sát mép ảnh và chọn `truncated`.

3.3 Người lái xe máy / xe đạp là `rider` và gán box riêng. Chiếc xe gán box `motorcycle` / `bicycle` riêng, không gộp chung một box.

3.4 Mỗi vật chỉ có một box. Không vẽ hai box cùng nhãn cho cùng một vật.

3.5 Gán mọi vật nhìn thấy được, kể cả vật nhỏ ở xa, miễn là nhận ra được loại vật.

3.5a Vật có cạnh ngắn dưới 10 px không bắt buộc gán (chốt ngày 2026-10-17). Đã gán thì vẫn hợp lệ, không tính lỗi. Vật từ 10 px trở lên phải gán đủ.

3.6 Không gán: người hay xe trong gương, trên poster, biển quảng cáo; bóng phản chiếu; tượng, ma-nơ-canh.

## 4. Polygon / mask (instance segmentation)

4.1 Polygon ôm sát viền phần nhìn thấy của vật, lệch tối đa khoảng 2 px. Không vẽ lẹm vào vật, không tô ra nền.

4.2 Polygon có ít nhất 3 điểm và không được xoắn (các cạnh không cắt nhau).

4.3 Vật bị vật khác che làm nhiều mảnh: dùng mask (công cụ brush) để tô đủ các mảnh, hoặc vẽ nhiều polygon rồi group chung với box của vật.

4.4 Không tô phần của vật khác vào polygon (ví dụ người lái không nằm trong polygon xe máy).

4.5 `traffic light` và `traffic sign` chỉ cần box, không cần polygon.

## 5. Tag cho cả ảnh

5.1 Mỗi ảnh có một tag `image_info`. Bắt buộc chọn weather, scene, timeofday cho đúng với ảnh.

## 6. Thuộc tính bắt buộc

6.1 Đèn giao thông bắt buộc chọn `trafficLightColor`.

6.2 Bắt buộc chọn weather, scene, timeofday cho tag `image_info`.

## 7. Quy trình QC

7.1 Annotator gán xong lượt 1 rồi chuyển job sang stage validation. Tool QC tự review trong vòng 60 giây, rồi ghi lỗi thành Issue trên CVAT: mỗi vật một Issue, vật nhiều lỗi thì ghi rõ từng lỗi. Tool không sửa nhãn.

7.2 Còn lỗi chắc chắn thì tool tự trả job về annotation (rejected). Không còn lỗi chắc chắn thì job ở lại validation để reviewer kiểm chéo: reviewer xem các mục "Đang xem xét" và đánh dấu "tool nhầm" nếu tool sai.

7.3 Annotator sửa theo Issue rồi nộp lại. Mục "Đang xem xét": nhãn đúng thì giữ nguyên và trả lời dưới Issue, sai thì sửa. Tool review lại, tự đóng các Issue đã hết lỗi. Mỗi lần job bị trả về được tính là một vòng.

## 8. Việc nhóm cần chốt (chưa có trong BDD100K gốc)

- ~~Kích thước vật nhỏ nhất bắt buộc phải gán.~~ Đã chốt 10 px (mục 3.5a). BDD100K gốc gán cả xe khoảng 9×10 px; tool đọc câu ở mục 3.5a và không báo thiếu vật nhỏ hơn 10 px.
- Có gán thêm `drivable_area` (mặt đường xe đi được) hay không. BDD100K để phần này thành task riêng, nên tập nhãn mặc định không có. Nếu thêm thì tool tự so polygon mặt đường với model phân vùng đường.
