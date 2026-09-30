import time


class ViolationTracker:
    def __init__(self, violation_seconds=5, safe_grace_seconds=1.0):
        self.violation_seconds = violation_seconds

        # Chống nhiễu: model đôi khi nhận nhầm 1-2 frame là "đủ đồ bảo hộ"
        # giữa một chuỗi vi phạm thật (false positive thoáng qua). Nếu reset
        # ngay khi gặp 1 frame an toàn (bản cũ), một vi phạm liên tục 8 giây
        # có thể không bao giờ đạt đủ violation_seconds vì bị reset lặp lại.
        # Chỉ thực sự coi là "đã hết vi phạm" khi an toàn LIÊN TỤC đủ
        # safe_grace_seconds giây.
        self.safe_grace_seconds = safe_grace_seconds

        # Lưu thông tin từng worker
        self.workers = {}

    def update(self, worker_id, helmet, vest):
        now = time.time()

        # Worker mới
        if worker_id not in self.workers:
            self.workers[worker_id] = {
                "violation_start": None,
                "safe_since": None,      # bắt đầu chuỗi frame an toàn liên tục hiện tại
                "violation_count": 0,
                "violation_active": False,
            }

        worker = self.workers[worker_id]

        # Có đầy đủ PPE ở FRAME NÀY (chưa chắc đã hết vi phạm, xem bên dưới)
        safe = helmet and vest

        if safe:
            if worker["safe_since"] is None:
                worker["safe_since"] = now

            safe_duration = now - worker["safe_since"]

            # Chỉ reset khi an toàn đã đủ lâu, liên tục -> không bị 1 frame
            # nhận nhầm đánh lừa
            if worker["violation_start"] is not None and safe_duration >= self.safe_grace_seconds:
                worker["violation_start"] = None
                worker["violation_active"] = False

        else:
            # Bất kỳ frame nào thiếu đồ bảo hộ đều huỷ chuỗi "an toàn liên tục"
            worker["safe_since"] = None

            # Bắt đầu tính thời gian vi phạm
            if worker["violation_start"] is None:
                worker["violation_start"] = now

            violation_time = now - worker["violation_start"]

            # Đủ thời gian quy định
            if violation_time >= self.violation_seconds:

                # Chỉ tăng số lần vi phạm một lần
                if not worker["violation_active"]:
                    worker["violation_count"] += 1
                    worker["violation_active"] = True

        # Tính thời gian hiện tại
        if worker["violation_start"] is not None:
            duration = now - worker["violation_start"]
        else:
            duration = 0

        return {
            "safe": safe,
            "violation_active": worker["violation_active"],
            "violation_count": worker["violation_count"],
            "violation_duration": duration,
        }
