import os
import time
import cv2
import numpy as np
import mss

from pangya_models import GameWindowRect, RoiRect


class ScreenCaptureService:
    def __init__(self):
        self.sct = mss.mss()

    def capture_rect(self, left, top, width, height):
        monitor = {
            "left": int(left),
            "top": int(top),
            "width": int(width),
            "height": int(height),
        }

        img = np.array(self.sct.grab(monitor))

        # mss는 BGRA이므로 BGR로 변환
        return cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)

    def capture_roi(self, window_rect: GameWindowRect, roi: RoiRect, base_w=2048, base_h=1152):
        scale_x = window_rect.width / base_w
        scale_y = window_rect.height / base_h

        x = window_rect.left + int(roi.base_x * scale_x)
        y = window_rect.top + int(roi.base_y * scale_y)
        w = int(roi.base_w * scale_x)
        h = int(roi.base_h * scale_y)

        return self.capture_rect(x, y, w, h)

    def save_debug_image(self, image, prefix="roi"):
        debug_dir = "debug_roi"
        os.makedirs(debug_dir, exist_ok=True)

        ts = time.strftime("%Y%m%d_%H%M%S")
        path = os.path.join(debug_dir, f"{prefix}_{ts}.png")
        cv2.imwrite(path, image)

        return path