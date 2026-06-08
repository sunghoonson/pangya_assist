from PySide6.QtCore import QObject, QTimer

from pangya_models import GameWindowRect, OverlayCalcState
from pangya_capture import ScreenCaptureService
from pangya_roi_settings import DEFAULT_ROIS
from pangya_vision import PangyaVisionRecognizer
from pangya_calculator_service import PangyaCalculatorService


class PangyaAutoDetectController(QObject):
    def __init__(self, overlay, get_window_rect_func, parent=None):
        super().__init__(parent)

        self.overlay = overlay
        self.get_window_rect_func = get_window_rect_func

        self.capture = ScreenCaptureService()
        self.vision = PangyaVisionRecognizer(use_easyocr=True, debug_save=True)
        self.calculator = PangyaCalculatorService()

        self.timer = QTimer()
        self.timer.timeout.connect(self.tick)

        self.debug_save_once = True

    def start(self):
        if not self.timer.isActive():
            self.timer.start(500)

    def stop(self):
        if self.timer.isActive():
            self.timer.stop()

    def tick(self):
        try:
            rect = self.get_window_rect_func()

            if rect is None:
                return

            distance_img = self.capture.capture_roi(rect, DEFAULT_ROIS["distance"])
            height_img = self.capture.capture_roi(rect, DEFAULT_ROIS["height"])
            wind_img = self.capture.capture_roi(rect, DEFAULT_ROIS["wind"])
            wind_angle_img = self.capture.capture_roi(rect, DEFAULT_ROIS["wind_angle"])

            # 최초 디버깅 때만 켜는 것을 추천
            if self.debug_save_once:
                self.capture.save_debug_image(distance_img, "distance")
                self.capture.save_debug_image(height_img, "height")
                self.capture.save_debug_image(wind_img, "wind")
                self.capture.save_debug_image(wind_angle_img, "wind_angle")
                self.debug_save_once = False

            auto_input = self.vision.recognize_all(
                distance_img,
                height_img,
                wind_img,
                wind_angle_img,
            )

            shot_results = self.calculator.calculate_all(auto_input)

            state = OverlayCalcState(
                auto_input=auto_input,
                shot_results=shot_results,
                last_error=""
            )

            self.overlay.set_calc_state(state)

        except Exception as e:
            state = OverlayCalcState()
            state.last_error = str(e)
            self.overlay.set_calc_state(state)