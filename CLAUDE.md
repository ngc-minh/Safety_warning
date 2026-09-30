# CLAUDE.md

File này cung cấp hướng dẫn cho Claude Code (claude.ai/code) khi làm việc với code trong repo này.

## Đây là gì

Hệ thống giám sát an toàn PPE (trang bị bảo hộ cá nhân) phía edge cho đồ án tốt nghiệp Samsung Innovation Campus. Một model YOLO chạy trên Raspberry Pi 5 theo dõi luồng camera, xác định từng người có đội mũ bảo hộ vàng và mặc áo phản quang hay không, rồi gửi cảnh báo vi phạm qua MQTT tới backend/dashboard nằm **ngoài repo này**.

Repo chỉ chứa phần edge. `AI/src/detect.py` có nhắc tới một file `PLAN.md` định nghĩa hợp đồng MQTT — file đó không có trong repo, nên phần topic/payload trong `Publisher` (`AI/src/detect.py:180`) chính là bản sao cục bộ đáng tin cậy nhất của hợp đồng đó.

Comment, log output và CLI help text đều bằng tiếng Việt (chuỗi log/help chủ yếu không dấu để chạy ổn trên terminal SSH thuần). Khi sửa code, giữ đúng phong cách này.

## Chạy chương trình

Mọi thứ chạy trực tiếp bằng `python`; không có package, test runner hay cấu hình lint. Dependencies: `ultralytics`, `opencv-python`, `paho-mqtt` (chỉ có `edge/requirements.txt`, và nó chỉ liệt kê phần camera streamer).

```bash
# Bộ nhận diện chính — chạy từ AI/ hoặc bất kỳ đâu (đường dẫn tự resolve theo __file__)
python AI/src/detect.py                                  # camera 0, cửa sổ OpenCV (cần màn hình/VNC)
python AI/src/detect.py --view stream --port 8090        # headless: xem tại http://<ip-pi>:8090/
python AI/src/detect.py --view none --mqtt --broker <ip> # chạy nền như một service
python AI/src/detect.py --source AI/test.mp4 --imgsz 320 # không cần camera; 320 nhanh gấp ~3 lần trên Pi 5

# Server MJPEG camera độc lập cho dashboard (không có AI) — /video_feed, /snapshot, /health
python edge/camera_stream.py --camera 0 --port 8080

# Smoke test (không dùng framework nào — mỗi file là một script chạy rồi tự nhìn kết quả)
cd AI && python test_detect.py     # chụp 1 frame -> detect.jpg; chạy được qua SSH, không cần màn hình
cd AI/src && python test_camera.py # cửa sổ trực tiếp có box; đường dẫn model tương đối nên phải cd trước
cd AI/src && python test_mqtt.py   # gửi 1 message tới localhost:1883
python mqtt/test_mqtt.py           # giả lập telemetry + cảnh báo NO_VEST theo đúng topic trong PLAN.md
```

`AI/src/test_camera.py` và `AI/src/main.py` hardcode đường dẫn tương đối `models/best.pt`, nên chỉ chạy đúng khi working directory phù hợp. `detect.py` và `test_detect.py` không gặp vấn đề này.

## Kiến trúc

### Pipeline nhận diện (`AI/src/detect.py`)

Một vòng lặp đồng bộ duy nhất, không có queue hay thread nào trên đường xử lý chính. Mỗi frame:

1. `model.track(..., tracker="bytetrack.yaml", persist=True)` — một lần gọi YOLO cho cả bounding box lẫn ByteTrack ID.
2. Tách box theo class id: `0 = người, 1 = mũ vàng, 2 = áo phản quang vàng` (`CLS_PERSON/CLS_HELMET/CLS_VEST`). Các chỉ số này gắn liền với model đã train — đổi model thì phải đổi các chỉ số này.
3. `match_gear()` gán đồ bảo hộ cho từng người. Mũ chỉ được tính nếu tâm của nó rơi vào 0–40% phía trên box người (`HEAD_BAND`), áo là dải 20–80% (`BODY_BAND`). Đây là phép **gán một-một trên toàn cục**: các cặp ứng viên được chấm điểm theo độ lệch tâm ngang, sắp xếp rồi gán tham lam (greedy) để không có cái mũ nào được tính cho hai người cùng lúc.
4. `WorkerRegistry.resolve()` ánh xạ ByteTrack ID sang một `Worker #` ổn định. Khi ByteTrack làm mất ID, nó ghép lại theo tâm gần nhất trong bán kính `MATCH_DIST` (120 px) — nhưng chỉ với các worker đã thấy trong `WORKER_TTL` gần nhất (3 giây), để một vị trí cũ không "hút" nhầm người mới.
5. `ViolationTracker.update()` (`AI/src/violation.py`) có debounce: thiếu PPE chỉ được tính là `VIOLATION` sau 5 giây liên tục (`--violation-seconds`), và `violation_count` chỉ tăng một lần mỗi đợt vi phạm, không tăng theo từng frame.
6. Trạng thái gồm `SAFE` / `WARNING` (thiếu PPE nhưng đồng hồ đếm chưa đủ) / `VIOLATION`.

Toàn bộ thiết kế xoay quanh **edge-triggering**: snapshot, cảnh báo MQTT và log chỉ bắn ra khi trạng thái của một worker *thay đổi*. Việc publish hoặc ghi JPEG mỗi frame chính là bug mà đoạn code này được viết ra để sửa — đừng đưa nó trở lại.

### Ba chế độ xem

`--view window` (OpenCV `imshow`, cần desktop), `--view stream` (`MjpegServer`, một `ThreadingHTTPServer` chạy nền ở cổng 8090, giữ một buffer JPEG mới nhất có khóa lock), `--view none`. Pi chạy headless qua SSH thì dùng `stream` hoặc `none`.

`edge/camera_stream.py` là một server MJPEG riêng, không có AI, ở cổng 8080, bật CORS cho web dashboard, dùng thread đọc camera riêng để một client HTTP chậm không làm nghẽn việc đọc camera.

### MQTT

Repo hiện có hai schema MQTT không tương thích nhau:

- **Hiện hành** (`detect.py`, `mqtt/test_mqtt.py`) — `safety/edge/{device_id}/alert` và `safety/edge/{device_id}/telemetry`, QoS 1, device id `EDGE_PI5_01`. Alert mang `has_hardhat`/`has_vest`/`status`/`violation_type` (`NO_VEST` | `NO_HARDHAT` | `NO_PPE`) và tên file `image_snapshot`; telemetry là nhịp tim (heartbeat) mỗi 60 giây.
- **Cũ** (`main.py`) — `smart-safety/worker/{worker_id}`, publish mỗi frame cho mỗi người. Đã bị thay thế.

Broker bị mất kết nối không làm crash chương trình — đây là chủ đích thiết kế: `Publisher.__init__` bắt lỗi connect, đặt `ok = False`, và việc nhận diện vẫn tiếp tục chạy.

### Code cũ / đã thay thế

`AI/src/main.py` và `AI/src/safety.py` là phiên bản trước. Docstring của module `detect.py` liệt kê đầy đủ những gì nó đã thay thế (spam MQTT mỗi frame, đồ bảo hộ bị dùng chung giữa nhiều người, vị trí worker tồn tại vĩnh viễn, đường dẫn model phụ thuộc cwd). Phát triển tiếp trên `detect.py`; coi `main.py`/`safety.py` chỉ để tham khảo.

### Các lỗi phần cứng được xử lý có chủ đích

Webcam USB giá rẻ trên Pi hay bị rớt khỏi bus giữa chừng, và một số camera enumerate được nhưng chỉ trả về frame đen toàn bộ. `frames_are_alive()` kiểm tra trường hợp frame đen lúc khởi động và thoát kèm hướng dẫn khắc phục phần cứng; vòng lặp chính tự mở lại camera tối đa `--max-reconnect` lần (mặc định 10) thay vì làm chết cả buổi demo trực tiếp. Camera bị ép FOURCC sang MJPG vì YUYV thường chỉ đạt tối đa 640x480. Đừng đơn giản hóa/bỏ bớt các phần này — chúng là những chỗ quan trọng để demo chạy được ổn định.

## Vệ sinh repo

Không có `.gitignore`, nên `__pycache__/`, trọng số model (`AI/models/best.pt`, `best.onnx`), snapshot và media test đều đang được commit. Cẩn thận khi dùng `git add -A` để biết chính xác mình thêm gì.
