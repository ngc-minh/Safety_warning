# Database Server — Thiết kế lưu trữ dữ liệu

> **Trạng thái:** Tài liệu thiết kế đề xuất. Repo hiện tại **chưa có backend, chưa có database
> nào được implement** — `AI/src/detect.py` chỉ publish MQTT, không có bên nào subscribe và ghi
> vào đâu cả. Tài liệu này đề xuất nơi đặt DB, engine, và schema, dựa trên payload đã có ở
> [COMMUNICATION.md](./COMMUNICATION.md).

## 1. Vị trí đặt database: máy trung tâm, không phải Pi5

**Khuyến nghị: DB chạy trên một máy/server trung tâm (PC, VPS, hoặc VM nội bộ), tách biệt hoàn
toàn khỏi mọi Pi5.**

| Yếu tố | Đặt trên Pi5 | Đặt trên máy trung tâm |
|---|---|---|
| Tài nguyên | YOLO inference đã chiếm phần lớn CPU/RAM; DB tranh I/O, làm giảm FPS nhận diện | Máy chuyên trách, không cạnh tranh tài nguyên với AI |
| Độ bền thẻ SD | Ghi DB liên tục làm hao mòn thẻ microSD nhanh hơn — điểm yếu phần cứng đã biết của Pi | Ổ cứng/SSD server bền hơn, dễ thay/backup |
| Nhiều thiết bị edge | Mỗi Pi5 một DB riêng → dữ liệu phân mảnh theo từng zone, dashboard phải gộp nhiều nguồn để xem tổng quan | Một DB dùng chung cho toàn bộ `device_id`, dashboard truy vấn một chỗ |
| Khi Pi5 hỏng/mất | Mất luôn lịch sử vi phạm của khu vực đó | Dữ liệu vẫn còn nguyên trên server, không phụ thuộc Pi5 sống hay chết |
| Truy vấn cho dashboard | Dashboard phải gọi qua mạng hiện trường (Wi-Fi công nghiệp, có thể chập chờn) tới từng Pi5 | Backend + DB cùng một chỗ, dashboard chỉ nói chuyện với backend |

Vai trò của Pi5 chỉ nên là: chạy AI + publish MQTT (+ tuỳ chọn buffer tạm thời khi mất mạng, xem
`COMMUNICATION.md` mục 2.4) — **không phải nơi lưu trữ lâu dài**.

## 2. Chọn engine: PostgreSQL

Lý do chọn so với các phương án khác:

- **So với SQLite:** SQLite phù hợp một tiến trình ghi/đọc đơn giản, nhưng ở đây backend vừa phải
  ghi liên tục (subscriber MQTT) vừa phục vụ nhiều truy vấn đọc từ dashboard cùng lúc — Postgres
  xử lý concurrent read/write tốt hơn nhiều.
- **So với TimescaleDB/InfluxDB (time-series chuyên dụng):** dữ liệu ở quy mô đồ án (vài thiết bị,
  alert đã được debounce nên tần suất thấp — tối đa vài chục bản ghi/phút/thiết bị) chưa đủ lớn để
  cần time-series DB chuyên dụng. PostgreSQL thường vẫn đủ nhanh, quen thuộc hơn để phát triển và
  viết báo cáo đồ án. Nếu sau này quy mô tăng mạnh (hàng chục thiết bị, log mỗi giây), có thể thêm
  extension TimescaleDB vào Postgres mà không cần đổi engine.
- **So với NoSQL (MongoDB...):** dữ liệu ở đây có cấu trúc rõ ràng, quan hệ đơn giản
  (device → alert/telemetry) — hợp với mô hình quan hệ hơn là document store.

## 3. Lưu ý quan trọng: `worker_id` không phải định danh bền vững

`WorkerRegistry` trong `AI/src/detect.py` sinh `worker_id` tăng dần bắt đầu từ 1, **reset mỗi khi
tiến trình `detect.py` khởi động lại**. Không có nhận diện khuôn mặt hay ID theo huy hiệu — nên
"Worker #3" hôm nay và "Worker #3" ngày mai là hai người hoàn toàn khác nhau, chỉ trùng số.

**Hệ quả cho thiết kế DB:** đặt tên cột là `worker_session_id`, không đặt `worker_id`, để không ai
sau này nhầm tưởng đây là mã nhân viên/định danh cố định. Kéo theo đó, các tính năng thống kê kiểu
"ai vi phạm nhiều nhất trong tháng" **không có ý nghĩa** với dữ liệu hiện tại — chỉ nên thống kê
theo `device_id`/zone, hoặc theo từng phiên quan sát (từ lúc `detect.py` start tới lúc dừng). Muốn
thống kê theo người thật sự cần thêm cơ chế tái định danh (face re-ID, thẻ từ...) — nằm ngoài phạm
vi hiện tại, ghi nhận là việc cần làm sau nếu có yêu cầu.

## 4. Schema đề xuất

```sql
-- Danh sách thiết bị edge
CREATE TABLE devices (
    device_id     TEXT PRIMARY KEY,       -- 'EDGE_PI5_01'
    zone_name     TEXT,                   -- 'Khu_vuc_cong_chinh' (theo mqtt/test_mqtt.py)
    last_seen_at  TIMESTAMPTZ,            -- cập nhật mỗi khi nhận được telemetry/alert
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Heartbeat định kỳ (topic .../telemetry, mỗi 60s)
CREATE TABLE telemetry (
    id                BIGSERIAL PRIMARY KEY,
    device_id         TEXT NOT NULL REFERENCES devices(device_id),
    ts                TIMESTAMPTZ NOT NULL,
    fps               REAL,
    workers_in_frame  INT,
    uptime_s          INT,
    received_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_telemetry_device_ts ON telemetry (device_id, ts DESC);

-- Cảnh báo vi phạm (topic .../alert, chỉ khi đổi trạng thái)
CREATE TABLE alerts (
    id                  BIGSERIAL PRIMARY KEY,
    device_id           TEXT NOT NULL REFERENCES devices(device_id),
    worker_session_id   INT NOT NULL,      -- xem mục 3 — KHÔNG phải định danh người bền vững
    ts                  TIMESTAMPTZ NOT NULL,
    has_hardhat         BOOLEAN NOT NULL,
    has_vest            BOOLEAN NOT NULL,
    status              TEXT NOT NULL,      -- SAFE | WARNING | VIOLATION
    violation_type      TEXT,               -- NO_VEST | NO_HARDHAT | NO_PPE | NULL
    violation_count     INT NOT NULL,
    violation_duration  REAL NOT NULL,
    snapshot_url        TEXT,               -- đường dẫn/URL ảnh đã upload, KHÔNG lưu blob ảnh ở đây
    received_at         TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Trạng thái xử lý — phục vụ workflow "đánh dấu đã nhắc nhở" trên dashboard
    -- (xem DASHBOARD.md mục 3). Không do detect.py/MQTT ghi, mà do backend cập
    -- nhật khi người dùng bấm "Đã nhắc nhở" trên giao diện.
    acknowledged_at     TIMESTAMPTZ,
    acknowledged_by     TEXT
);
CREATE INDEX idx_alerts_device_ts ON alerts (device_id, ts DESC);
CREATE INDEX idx_alerts_status ON alerts (status) WHERE status = 'VIOLATION';
-- Tra cứu nhanh các vi phạm chưa xử lý, cho feed cảnh báo trên dashboard
CREATE INDEX idx_alerts_unacked ON alerts (ts DESC) WHERE status = 'VIOLATION' AND acknowledged_at IS NULL;
```

`acknowledged_at`/`acknowledged_by` không đến từ Pi5 — chúng được backend `UPDATE` khi quản lý/giám
sát bấm nút xử lý trên dashboard (xem [DASHBOARD.md](./DASHBOARD.md) mục 3). Thiếu hai cột này thì
feed cảnh báo chỉ là một cái log để xem, không giúp theo dõi được việc gì đã thực sự xử lý.

**Ảnh snapshot lưu ngoài DB:** file JPEG lưu trên đĩa của server trung tâm (ví dụ
`/data/snapshots/{device_id}/{filename}`) hoặc object storage (MinIO/S3) nếu muốn chuẩn hoá hơn.
Cột `alerts.snapshot_url` chỉ giữ đường dẫn/URL — không nhét blob ảnh vào Postgres, vừa nặng bảng
vừa khó backup gọn.

## 5. Luồng ghi dữ liệu

```
MQTT alert/telemetry ──▶ Backend (subscriber) ──▶ INSERT vào bảng tương ứng
                                │
                                └──▶ upsert devices.last_seen_at
```

Backend (FastAPI, như comment trong `detect.py` đã giả định) chạy một MQTT client subscribe cả hai
topic, mỗi message nhận được thì `INSERT` thẳng vào `alerts`/`telemetry`, đồng thời cập nhật
`devices.last_seen_at` để dashboard biết thiết bị nào đang online.

## 6. Ví dụ truy vấn phục vụ dashboard

```sql
-- Thiết bị nào đang "offline" (không có telemetry > 90s, chu kỳ gửi là 60s)
SELECT device_id, last_seen_at
FROM devices
WHERE last_seen_at < now() - interval '90 seconds';

-- Số vi phạm theo loại, 7 ngày gần nhất, theo từng zone
SELECT d.zone_name, a.violation_type, count(*)
FROM alerts a JOIN devices d USING (device_id)
WHERE a.status = 'VIOLATION' AND a.ts > now() - interval '7 days'
GROUP BY d.zone_name, a.violation_type
ORDER BY d.zone_name;

-- Vi phạm theo giờ trong ngày (cho biểu đồ line/bar)
SELECT date_trunc('hour', ts) AS hour, count(*)
FROM alerts
WHERE status = 'VIOLATION' AND ts > now() - interval '24 hours'
GROUP BY hour
ORDER BY hour;

-- Safety Score theo zone, hôm nay (tỉ lệ thời gian SAFE / tổng thời gian quan sát)
-- xấp xỉ bằng tỉ lệ số alert SAFE trên tổng số alert trong ngày, vì alert chỉ
-- được ghi khi trạng thái ĐỔI (edge-triggered) — cách tính chính xác hơn cần
-- tích phân theo thời lượng mỗi trạng thái, để lại cho lúc implement backend.
SELECT d.zone_name,
       round(100.0 * count(*) FILTER (WHERE a.status = 'SAFE') / count(*), 1) AS safety_score
FROM alerts a JOIN devices d USING (device_id)
WHERE a.ts > date_trunc('day', now())
GROUP BY d.zone_name;

-- Feed cảnh báo trực tiếp: vi phạm chưa được xử lý, mới nhất trước
SELECT a.id, d.zone_name, a.ts, a.violation_type, a.snapshot_url
FROM alerts a JOIN devices d USING (device_id)
WHERE a.status = 'VIOLATION' AND a.acknowledged_at IS NULL
ORDER BY a.ts DESC;
```

## 7. Backup & retention — [ĐỀ XUẤT, cần quyết định thêm]

Chưa có chính sách chính thức; gợi ý tối thiểu:
- Backup `pg_dump` định kỳ (hằng ngày) cho toàn bộ DB.
- Ảnh snapshot: cân nhắc dọn định kỳ (ví dụ giữ 90 ngày) vì tích luỹ nhanh nếu nhiều vi phạm — đây
  là quyết định về chính sách, không phải kỹ thuật, nên cần thống nhất trong nhóm/với giảng viên
  hướng dẫn trước khi implement.

## 8. Việc cần làm tiếp (chưa có trong repo)

- [ ] Dựng broker MQTT trung tâm + Postgres trên cùng một máy chủ trung tâm.
- [ ] Viết backend FastAPI: subscriber MQTT + API REST/WebSocket cho dashboard (xem
      [COMMUNICATION.md](./COMMUNICATION.md)).
- [ ] Endpoint upload snapshot từ Pi5 lên backend.
- [ ] Migration script tạo schema ở mục 4 (ví dụ bằng Alembic nếu dùng SQLAlchemy).
- [ ] Bật auth cho MQTT + kết nối DB (không dùng mật khẩu mặc định khi lên môi trường thật).
- [ ] API `PATCH` đánh dấu alert đã xử lý (`acknowledged_at`/`acknowledged_by`) cho dashboard gọi.

## 9. Tài liệu liên quan

- [COMMUNICATION.md](./COMMUNICATION.md) — nguồn dữ liệu MQTT được ghi vào các bảng ở đây.
- [DASHBOARD.md](./DASHBOARD.md) — cách dữ liệu trong các bảng này được hiển thị và dùng để ra quyết định.
