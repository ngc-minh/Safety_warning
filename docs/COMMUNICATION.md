# Communication — Giao tiếp Edge ↔ Backend ↔ Dashboard

> **Trạng thái:** Tài liệu thiết kế đề xuất, không phải mô tả một hệ thống đã hoàn chỉnh.
> File `PLAN.md` mà `AI/src/detect.py` (dòng 12, 182) nhắc tới không tồn tại trong repo và
> không tìm thấy trong lịch sử git. Tài liệu này được viết ra để **thay thế** chỗ trống đó,
> bằng cách suy ngược từ code đang chạy (`AI/src/detect.py`, `edge/camera_stream.py`,
> `mqtt/test_mqtt.py`) rồi bổ sung phần còn thiếu. Mỗi mục đều ghi rõ **[ĐÃ CÓ]** hay
> **[ĐỀ XUẤT]** để không ai nhầm giữa thực tế và kế hoạch.

## 1. Kiến trúc tổng quan

```
┌──────────────────┐        MQTT (alert, telemetry)        ┌──────────────────┐
│  Pi5 EDGE_PI5_01  │──────────────────────────────────────▶│                  │
│  (AI/src/detect.py)│                                       │   MQTT Broker    │
└──────────────────┘        HTTP POST (snapshot ảnh)         │   (Mosquitto)    │
        │  ▲                 [ĐỀ XUẤT]                       │  máy trung tâm,  │
        │  │                                                 │  KHÔNG trên Pi5  │
        │  └──HTTP GET /video_feed, /snapshot, /health────┐  └────────┬─────────┘
        │     (edge/camera_stream.py, port 8080)          │           │ subscribe
        ▼                                                  │           ▼
┌──────────────────┐                                        │  ┌──────────────────┐
│  Pi5 EDGE_PI5_02  │  (nhiều Pi5 khác, cùng pattern)        │  │  Backend FastAPI  │
│      ...          │                                        │  │  [ĐỀ XUẤT]        │
└──────────────────┘                                        │  └────────┬─────────┘
                                                              │           │ REST / WebSocket
                                                              └──────────▶│
                                                                          ▼
                                                                 ┌──────────────────┐
                                                                 │     Dashboard     │
                                                                 └──────────────────┘
```

Nguyên tắc nền tảng: **broker là một dịch vụ trung tâm độc lập**, không gắn với bất kỳ Pi5 nào,
vì quy ước đặt tên `EDGE_PI5_01` đã ngụ ý sẽ có nhiều thiết bị edge cùng kết nối vào một broker
chung.

## 2. Kênh MQTT

### 2.1 Broker — [ĐỀ XUẤT]

- Phần mềm: Mosquitto (nhẹ, phổ biến, đủ dùng cho quy mô đồ án).
- Vị trí: máy trung tâm (PC/server/VM), lý do chi tiết xem [DATABASE.md](./DATABASE.md#1-vị-trí-đặt-database-máy-trung-tâm-không-phải-pi5) — cùng lý do áp dụng cho broker.
- Hiện tại code test trỏ tới hai địa chỉ khác nhau tuỳ file — cần thống nhất một broker duy nhất trước khi triển khai thật:
  - `AI/src/detect.py` mặc định `--broker localhost` (dùng khi test tại chỗ trên Pi5).
  - `mqtt/test_mqtt.py` trỏ cứng `BROKER_IP = "10.50.1.232"` (IP một máy tính cụ thể trong mạng LAN — cần thay bằng địa chỉ/broker thật khi dùng).

### 2.2 Topic — [ĐÃ CÓ trong detect.py, ĐANG DÙNG]

| Topic | Hướng | QoS | Tần suất | Publisher |
|---|---|---|---|---|
| `safety/edge/{device_id}/alert` | Pi5 → broker | 1 | Chỉ khi trạng thái người đổi (edge-triggered) | `Publisher.alert()` (`AI/src/detect.py:216`) |
| `safety/edge/{device_id}/telemetry` | Pi5 → broker | 1 | Mỗi 60s (`--mqtt-report-every`, mặc định trong `Publisher.telemetry`) | `Publisher.telemetry()` (`AI/src/detect.py:238`) |

`{device_id}` mặc định là `EDGE_PI5_01` (`--device-id`), mỗi Pi5 vật lý cần một `device_id` riêng biệt khi triển khai nhiều thiết bị.

Có một schema topic **cũ, đã bị thay thế**, không nên dùng tiếp: `smart-safety/worker/{worker_id}` trong `AI/src/main.py` — publish mỗi frame mỗi người (~90 msg/s), đã được `detect.py` sửa lại bằng cơ chế edge-triggered ở trên.

### 2.3 Payload — [ĐÃ CÓ]

**`alert`** (gửi khi trạng thái một worker thay đổi — SAFE / WARNING / VIOLATION):

```json
{
  "device_id": "EDGE_PI5_01",
  "timestamp": "2026-09-29T10:15:03",
  "worker_id": 3,
  "has_hardhat": true,
  "has_vest": false,
  "status": "VIOLATION",
  "violation_type": "NO_VEST",
  "violation_count": 2,
  "violation_duration": 5.4,
  "image_snapshot": "snapshot_EDGE_PI5_01_20260929_101503_w3.jpg"
}
```

- `violation_type` ∈ `NO_VEST | NO_HARDHAT | NO_PPE | null` (null khi `status` không phải VIOLATION), tính bởi `Publisher._violation_type()`.
- `worker_id`: **ID phiên theo dõi, không phải định danh người bền vững** — `WorkerRegistry` reset ID mỗi lần `detect.py` khởi động lại, không có nhận diện khuôn mặt. Backend/DB không nên coi đây là "danh tính công nhân" lâu dài (xem chi tiết ở [DATABASE.md](./DATABASE.md#3-lưu-ý-quan-trọng-worker_id-không-phải-định-danh-bền-vững)).
- `image_snapshot`: **chỉ là tên file**, ảnh thật nằm cục bộ trong `AI/snapshots/` trên Pi5, chưa được truyền đi đâu cả (xem mục 3.3).

**`telemetry`** (heartbeat định kỳ):

```json
{
  "device_id": "EDGE_PI5_01",
  "timestamp": "2026-09-29T10:16:00",
  "fps": 8.3,
  "workers_in_frame": 2,
  "uptime_s": 4210
}
```

### 2.4 Ứng xử khi broker mất kết nối — [ĐÃ CÓ, cần cân nhắc nâng cấp]

`Publisher.__init__` bắt lỗi kết nối, đặt `self.ok = False`, và toàn bộ pipeline nhận diện **vẫn chạy tiếp bình thường** — đây là chủ đích thiết kế để một demo không chết vì mất mạng.

Hệ quả đánh đổi: mọi alert phát sinh trong lúc broker down **bị mất vĩnh viễn**, không có hàng đợi giữ lại. Với đồ án/demo thì chấp nhận được. Nếu cần đảm bảo không mất dữ liệu:

- **[ĐỀ XUẤT]** Thêm hàng đợi cục bộ (SQLite nhỏ trên Pi5, hoặc dùng tính năng persistent queue của thư viện MQTT) để lưu tạm alert khi mất kết nối, phát lại (replay) khi `on_connect` báo đã nối lại.

### 2.5 Bảo mật MQTT — [ĐỀ XUẤT, hiện chưa có]

Hiện tại không có xác thực (`mqtt.Client().connect()` không kèm username/password ở bất kỳ script nào), không TLS. `Publisher` trong `detect.py` đã có sẵn tham số `username`/`password` (`--mqtt-user`, `--mqtt-pass`) nhưng chưa có broker nào được cấu hình yêu cầu chúng.

Trước khi triển khai ngoài mạng LAN tin cậy:
- Bật `password_file` trên Mosquitto, luôn truyền `--mqtt-user/--mqtt-pass` khi chạy `detect.py`.
- Cân nhắc TLS (`mqtts://`, port 8883) nếu Pi5 nối qua mạng không kiểm soát được (Wi-Fi công cộng, 4G).

## 3. Kênh video (HTTP, không qua MQTT)

MQTT không hợp để truyền ảnh liên tục — video luôn đi qua HTTP riêng, đúng như code hiện tại đã tách biệt.

### 3.1 `edge/camera_stream.py` — [ĐÃ CÓ]

Server MJPEG độc lập, **không chạy AI**, cổng mặc định 8080, bật CORS (`Access-Control-Allow-Origin: *`) để dashboard gọi trực tiếp từ trình duyệt:

| Endpoint | Nội dung |
|---|---|
| `GET /video_feed` (hoặc `/`, `/stream`) | MJPEG stream liên tục (`multipart/x-mixed-replace`) |
| `GET /snapshot` | Một frame JPEG tĩnh hiện tại |
| `GET /health` | `{"status": "ok", "service": "pi5-camera-stream"}` |

### 3.2 `MjpegServer` trong `detect.py` — [ĐÃ CÓ]

Khi chạy `detect.py --view stream`, có một server MJPEG khác (cổng mặc định 8090) phát **frame đã vẽ box/nhãn AI** (khác với `camera_stream.py` là ảnh thô không AI). Hai server này phục vụ hai mục đích khác nhau — đừng nhầm lẫn khi tích hợp dashboard:
- `camera_stream.py:8080` → xem hình ảnh gốc, luôn chạy được kể cả khi không có model AI.
- `detect.py --view stream:8090` → xem kết quả AI trực tiếp (box, trạng thái SAFE/WARNING/VIOLATION).

### 3.3 Snapshot ảnh vi phạm chưa được truyền đi — [ĐỀ XUẤT bổ sung]

Hiện `image_snapshot` trong payload alert chỉ là tên file, ảnh vật lý ở `AI/snapshots/` trên Pi5. Dashboard/backend không thể hiển thị ảnh này trừ khi bổ sung một trong hai cách:

1. **Pi5 chủ động đẩy đi (khuyến nghị):** ngay sau `cv2.imwrite()` snapshot, `detect.py` gọi `POST` ảnh lên một endpoint upload của backend (ví dụ `POST /api/devices/{device_id}/snapshots`). Tần suất thấp (chỉ khi có vi phạm mới, đã debounce) nên chi phí không đáng kể.
2. Backend chủ động kéo về qua endpoint kiểu `/snapshot` — phức tạp hơn vì phải biết đúng thời điểm để gọi.

### 3.4 Lệnh điều khiển ngược chiều (backend → Pi5) — [ĐỀ XUẤT, hiện chưa có]

`detect.py` hiện chỉ publish, không subscribe topic nào. Nếu cần điều khiển từ xa (đổi ngưỡng `--conf`, bật/tắt snapshot, restart), có thể bổ sung topic `safety/edge/{device_id}/cmd` mà Pi5 subscribe.

## 4. Bảng tổng hợp trạng thái

| Thành phần | Trạng thái | File liên quan |
|---|---|---|
| Publish alert/telemetry qua MQTT | ✅ Đã code | `AI/src/detect.py` (`Publisher`) |
| MJPEG video (ảnh gốc) | ✅ Đã code | `edge/camera_stream.py` |
| MJPEG video (có overlay AI) | ✅ Đã code | `AI/src/detect.py` (`MjpegServer`) |
| Broker trung tâm cấu hình sẵn | ❌ Chưa có, cần dựng | — |
| Backend subscribe MQTT + ghi DB | ❌ Chưa có | xem `DATABASE.md` |
| Upload/lưu ảnh snapshot tập trung | ❌ Chưa có | — |
| Auth/TLS cho MQTT | ❌ Chưa bật | — |
| Hàng đợi cục bộ khi mất mạng | ❌ Chưa có | — |
| Topic điều khiển ngược (cmd) | ❌ Chưa có | — |

## 5. Tài liệu liên quan

- [DATABASE.md](./DATABASE.md) — thiết kế nơi lưu dữ liệu do backend ghi vào sau khi subscribe các topic ở trên.
- [DASHBOARD.md](./DASHBOARD.md) — cách dữ liệu này được hiển thị cho người quản lý sử dụng.
