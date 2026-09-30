# Dashboard & Data Visualization — thiết kế hướng tới người quản lý

> **Trạng thái:** Tài liệu thiết kế đề xuất. Repo hiện chưa có dashboard/frontend nào được
> implement. Tài liệu này mô tả dashboard nên hiển thị gì và vì sao, dựa trên dữ liệu đã định
> nghĩa ở [DATABASE.md](./DATABASE.md) và nguồn cấp dữ liệu ở [COMMUNICATION.md](./COMMUNICATION.md).

Trọng tâm thiết kế: người dùng chính là **quản lý/giám sát an toàn công trường, không phải kỹ
sư phần mềm**. Họ cần biết *ngay bây giờ có an toàn không*, *xu hướng ra sao để ra quyết định*,
và *có bằng chứng khi cần xử lý/báo cáo* — không cần thấy chi tiết kỹ thuật (track ID, FPS, log).

## 1. Ba tầng thông tin

| Tầng | Dành cho | Tần suất xem | Nội dung chính |
|---|---|---|---|
| 1. Tổng quan | Quản lý cấp cao | Vài giây, nhiều lần/ngày | Safety Score, số vi phạm đang diễn ra, trạng thái thiết bị |
| 2. Giám sát trực tiếp | Giám sát an toàn hiện trường | Theo dõi liên tục trong ca làm | Camera live, feed cảnh báo, đánh dấu xử lý |
| 3. Lịch sử & báo cáo | Ra quyết định, báo cáo cấp trên | Định kỳ (tuần/tháng) | Biểu đồ xu hướng, xuất PDF/Excel |

Chi tiết kỹ thuật (worker_session_id, FPS, trạng thái ByteTrack...) chỉ nên xuất hiện ở log hệ
thống dành cho admin, không đưa lên các tầng trên — quản lý không cần và không nên bị làm rối bởi
những con số này.

## 2. Tầng 1 — Overview

Mục tiêu: trả lời "công trường hôm nay ổn không" trong 5 giây, không cần đọc thêm gì.

- **Safety Score** — chỉ số tổng hợp duy nhất, dễ hiểu:
  ```
  Safety Score (%) = thời gian mọi người ở trạng thái SAFE / tổng thời gian quan sát × 100
  ```
  Hiển thị theo toàn công trường, và breakdown theo từng zone. Xem gợi ý truy vấn gần đúng ở
  [DATABASE.md mục 6](./DATABASE.md#6-ví-dụ-truy-vấn-phục-vụ-dashboard) — vì alert chỉ được ghi
  khi trạng thái *đổi* (edge-triggered, xem `COMMUNICATION.md`), công thức chính xác cần tích phân
  theo thời lượng mỗi trạng thái; bản gần đúng bằng tỉ lệ số alert SAFE là đủ dùng cho bản đầu.
- **Số vi phạm đang diễn ra** — đếm `alerts` có `status = VIOLATION AND acknowledged_at IS NULL`.
  To, màu đỏ nếu > 0, xanh nếu = 0. Đây là con số quan trọng nhất trên màn hình.
- **Trạng thái thiết bị**: X/Y camera online, dựa vào `devices.last_seen_at` so với thời điểm hiện
  tại (lệch quá ~90s so với chu kỳ telemetry 60s → coi là offline). Quan trọng để tránh quản lý
  hiểu nhầm "không có cảnh báo" là "đang an toàn" trong khi thực ra camera khu đó đã mất kết nối.

## 3. Tầng 2 — Live monitoring

- **Lưới camera trực tiếp**: mỗi ô một zone, viền màu theo trạng thái (xanh/vàng/đỏ), nhúng qua
  endpoint MJPEG (`COMMUNICATION.md` mục 3) — nên proxy qua backend thay vì trỏ thẳng IP Pi5, để
  không lộ địa chỉ thiết bị ra trình duyệt và có một điểm auth duy nhất.
- **Feed cảnh báo trực tiếp** — thành phần quan trọng nhất về mặt vận hành. Mỗi dòng gồm: thời
  điểm, zone, loại vi phạm, ảnh thumbnail (`snapshot_url`), và nút **"Đã nhắc nhở"**.
  - Bấm nút này gọi `PATCH /api/alerts/{id}/ack` → backend ghi `acknowledged_at`, `acknowledged_by`
    (đã bổ sung vào schema `alerts`, xem [DATABASE.md mục 4](./DATABASE.md#4-schema-đề-xuất)).
  - Không có bước này thì feed cảnh báo chỉ là một log để xem, không giúp quản lý biết việc gì đã
    thực sự được xử lý ngoài hiện trường — đây là điểm khác biệt giữa "hệ thống giám sát" và "công
    cụ quản lý".
  - Mặc định lọc hiển thị các vi phạm **chưa xử lý** trước; có tab riêng xem lịch sử đã xử lý.
- **Cảnh báo chủ động (đẩy ra ngoài dashboard)**: quản lý không ngồi xem màn hình cả ngày, cần được
  chủ động báo khi có vi phạm nghiêm trọng/lặp lại — ví dụ một zone có > 3 vi phạm trong 1 giờ.
  Kênh phù hợp thực tế: email hoặc bot Telegram/Zalo qua webhook, để xem được ngay trên điện thoại.

## 4. Tầng 3 — Reports & xu hướng

Khi implement phần biểu đồ, dùng skill `dataviz` để đảm bảo màu sắc/bố cục nhất quán. Mỗi biểu đồ
phải trả lời một câu hỏi cụ thể của quản lý, không vẽ chỉ vì có dữ liệu:

| Câu hỏi | Biểu đồ | Nguồn dữ liệu |
|---|---|---|
| Tình hình có cải thiện không? | Line chart Safety Score / số vi phạm theo ngày, có so sánh tuần này–tuần trước | `alerts` group by ngày |
| Khu vực nào là điểm nóng? | Bar chart ngang, xếp hạng zone theo số vi phạm | `alerts JOIN devices` group by zone |
| Thiếu mũ hay thiếu áo nhiều hơn? | Donut/stacked bar theo `violation_type` | `alerts.violation_type` |
| Vi phạm hay xảy ra lúc nào? | Heatmap giờ × ngày trong tuần | `alerts.ts` |
| Báo cáo nộp ban ATLĐ/chủ đầu tư | Xuất PDF/Excel tuần/tháng kèm ảnh bằng chứng các vi phạm nghiêm trọng, tuỳ chọn lên lịch gửi email tự động | tổng hợp từ các bảng trên |

**Giới hạn cần tôn trọng:** không làm biểu đồ/bảng "công nhân vi phạm nhiều nhất" theo
`worker_session_id` — ID này reset mỗi khi `detect.py` khởi động lại, không phải định danh người
bền vững (xem [DATABASE.md mục 3](./DATABASE.md#3-lưu-ý-quan-trọng-worker_id-không-phải-định-danh-bền-vững)).
Thống kê chỉ nên dừng ở mức zone/thời gian cho tới khi hệ thống có cơ chế tái định danh.

## 5. Phân quyền

| Vai trò | Xem được | Thao tác được |
|---|---|---|
| Quản lý cấp cao | Tầng 1 + Tầng 3 | Xem báo cáo, không cần thao tác |
| Giám sát an toàn hiện trường | Tầng 1 + Tầng 2 | Xem camera live, đánh dấu xử lý vi phạm |
| Admin hệ thống | Toàn bộ + cấu hình | Thêm/xoá thiết bị, đặt ngưỡng cảnh báo, quản lý user |

## 6. Lựa chọn công nghệ

- **Đi nhanh để demo**: Grafana trỏ vào Postgres cho Tầng 3 (biểu đồ lịch sử có sẵn, không cần
  code frontend), kết hợp một trang HTML/JS đơn giản tự viết cho Tầng 1–2 — vì Grafana không hợp
  để nhúng camera live hay nút "đánh dấu xử lý".
- **Dashboard riêng cho sản phẩm hoàn chỉnh**: web app tự viết (React/Vue hoặc HTML+JS thuần) gọi
  API FastAPI, WebSocket cho phần real-time (feed cảnh báo, trạng thái camera).
  **Bắt buộc responsive/dùng tốt trên điện thoại** — quản lý công trường kiểm tra tình hình khi
  đang đi lại ngoài hiện trường, không phải ngồi bàn làm việc; đây là yêu cầu thực tế chứ không
  phải chi tiết UI phụ.

## 7. Việc cần làm tiếp (chưa có trong repo)

- [ ] API `PATCH /api/alerts/{id}/ack` để cập nhật `acknowledged_at`/`acknowledged_by`.
- [ ] API tổng hợp Safety Score theo zone/toàn công trường.
- [ ] WebSocket/SSE đẩy alert mới real-time xuống feed cảnh báo (không polling).
- [ ] Tích hợp gửi cảnh báo chủ động (email hoặc bot Telegram/Zalo) khi vượt ngưỡng cấu hình.
- [ ] Chức năng xuất báo cáo PDF/Excel định kỳ.
- [ ] Phân quyền theo vai trò (quản lý cấp cao / giám sát hiện trường / admin).

## 8. Tài liệu liên quan

- [COMMUNICATION.md](./COMMUNICATION.md) — nguồn dữ liệu MQTT nuôi dashboard.
- [DATABASE.md](./DATABASE.md) — schema và truy vấn phục vụ các thành phần ở trên.
