import math
import cv2
import numpy as np
from dataclasses import dataclass

from PySide6.QtCore import Qt, QRect, Signal
from PySide6.QtGui import QPainter, QPen, QColor, QImage, QFont
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QMessageBox,
    QCheckBox,
)

from pangya_capture import ScreenCaptureService
from pangya_roi_settings import DEFAULT_ROIS
from pangya_models import RoiRect


class WindAngleCanvas(QWidget):
    degree_changed = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)

        self.image_bgr = None
        self.image_rgb = None
        self.qimage = None

        # 화살표 양 날개 끝점 2개
        self.wing_points = []

        # 계산된 각도
        self.degree = None

        # 중심에서 그릴 수직 방향선 끝점
        self.direction_point = None

        # 바람 원 중심 보정값
        # +x = 오른쪽, -x = 왼쪽
        # +y = 아래쪽, -y = 위쪽
        self.center_offset_x = 0
        self.center_offset_y = 0

        # 동적 ROI에서 전달받은 이미지 내부 바람 중심 좌표
        self.custom_center_img_x = None
        self.custom_center_img_y = None

        self.setMinimumSize(320, 320)
        self.setMouseTracking(True)

    def set_image(self, image_bgr, center_img_pos=None):
        self.image_bgr = image_bgr
        self.wing_points = []
        self.degree = None
        self.direction_point = None

        if center_img_pos is not None:
            self.custom_center_img_x = float(center_img_pos[0])
            self.custom_center_img_y = float(center_img_pos[1])
        else:
            self.custom_center_img_x = None
            self.custom_center_img_y = None

        rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
        rgb = np.ascontiguousarray(rgb)

        self.image_rgb = rgb
        h, w, ch = rgb.shape

        self.qimage = QImage(
            rgb.data,
            w,
            h,
            ch * w,
            QImage.Format_RGB888,
        ).copy()

        self.update()

    def get_image_draw_rect(self):
        if self.qimage is None:
            return QRect(0, 0, 0, 0)

        widget_w = self.width()
        widget_h = self.height()

        img_w = self.qimage.width()
        img_h = self.qimage.height()

        if img_w <= 0 or img_h <= 0:
            return QRect(0, 0, 0, 0)

        scale = min(widget_w / img_w, widget_h / img_h)

        draw_w = int(img_w * scale)
        draw_h = int(img_h * scale)

        x = (widget_w - draw_w) // 2
        y = (widget_h - draw_h) // 2

        return QRect(x, y, draw_w, draw_h)

    def widget_to_image_pos(self, pos):
        if self.qimage is None:
            return None

        rect = self.get_image_draw_rect()

        if not rect.contains(pos):
            return None

        img_w = self.qimage.width()
        img_h = self.qimage.height()

        rel_x = pos.x() - rect.x()
        rel_y = pos.y() - rect.y()

        img_x = rel_x / rect.width() * img_w
        img_y = rel_y / rect.height() * img_h

        return float(img_x), float(img_y)

    def image_to_widget_pos(self, img_x, img_y):
        rect = self.get_image_draw_rect()

        img_w = self.qimage.width()
        img_h = self.qimage.height()

        x = rect.x() + img_x / img_w * rect.width()
        y = rect.y() + img_y / img_h * rect.height()

        return int(x), int(y)

    def get_center_img_pos(self):
        if self.custom_center_img_x is not None and self.custom_center_img_y is not None:
            return (
                self.custom_center_img_x + self.center_offset_x,
                self.custom_center_img_y + self.center_offset_y,
            )

        img_w = self.qimage.width()
        img_h = self.qimage.height()

        cx = img_w / 2.0 + self.center_offset_x
        cy = img_h / 2.0 + self.center_offset_y

        return cx, cy

    def calc_degree_from_vector(self, dx, dy):
        # 위쪽 수직 방향을 0도로 계산
        degree = math.degrees(math.atan2(dx, -dy))

        if degree < 0:
            degree += 360.0

        return degree

    def calc_degree_from_wing_points(self):
        if self.qimage is None:
            return None

        if len(self.wing_points) < 2:
            return None

        cx, cy = self.get_center_img_pos()

        x1, y1 = self.wing_points[0]
        x2, y2 = self.wing_points[1]

        # 두 날개를 잇는 선의 중점
        mx = (x1 + x2) / 2.0
        my = (y1 + y2) / 2.0

        # 날개선 벡터
        vx = x2 - x1
        vy = y2 - y1

        # 클릭 두 점이 너무 가까우면 계산 불가
        wing_len = math.sqrt(vx * vx + vy * vy)
        if wing_len <= 1.0:
            return None

        # 날개선에 수직인 두 방향 후보
        n1x, n1y = -vy, vx
        n2x, n2y = vy, -vx

        # 중심에서 날개선 중점으로 향하는 벡터
        # 일반적으로 화살표 방향은 중심 -> 날개선 중점 방향과 같은 쪽이다.
        tx = mx - cx
        ty = my - cy

        dot1 = n1x * tx + n1y * ty
        dot2 = n2x * tx + n2y * ty

        if dot1 >= dot2:
            dx, dy = n1x, n1y
        else:
            dx, dy = n2x, n2y

        # 표시용 방향점 계산
        length = math.sqrt(dx * dx + dy * dy)

        if length <= 0:
            return None

        ux = dx / length
        uy = dy / length

        self.direction_point = (
            cx + ux * 70.0,
            cy + uy * 70.0,
        )

        return self.calc_degree_from_vector(dx, dy)

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            return

        if self.qimage is None:
            return

        img_pos = self.widget_to_image_pos(event.position().toPoint())

        if img_pos is None:
            return

        img_x, img_y = img_pos

        # 이미 2점을 찍은 상태에서 다시 클릭하면 새 측정 시작
        if len(self.wing_points) >= 2:
            self.wing_points = []
            self.degree = None
            self.direction_point = None

        self.wing_points.append((img_x, img_y))

        if len(self.wing_points) == 2:
            self.degree = self.calc_degree_from_wing_points()

            if self.degree is not None:
                self.degree_changed.emit(self.degree)

        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        painter.fillRect(self.rect(), QColor(30, 30, 30))

        if self.qimage is None:
            painter.setPen(QPen(QColor(230, 230, 230), 1))
            painter.setFont(QFont("Arial", 12))
            painter.drawText(self.rect(), Qt.AlignCenter, "바람각도 캡처 이미지 없음")
            return

        rect = self.get_image_draw_rect()
        painter.drawImage(rect, self.qimage)

        img_w = self.qimage.width()
        img_h = self.qimage.height()

        cx_img, cy_img = self.get_center_img_pos()
        cx, cy = self.image_to_widget_pos(cx_img, cy_img)

        # 중심점
        painter.setPen(QPen(QColor(255, 0, 0), 4))
        painter.drawPoint(cx, cy)

        # 기준 수직선
        top_x, top_y = self.image_to_widget_pos(cx_img, 0)
        bot_x, bot_y = self.image_to_widget_pos(cx_img, img_h)

        painter.setPen(QPen(QColor(255, 0, 0, 190), 1))
        painter.drawLine(top_x, top_y, bot_x, bot_y)

        # 기준 수평선
        left_x, left_y = self.image_to_widget_pos(0, cy_img)
        right_x, right_y = self.image_to_widget_pos(img_w, cy_img)

        painter.setPen(QPen(QColor(255, 0, 0, 120), 1))
        painter.drawLine(left_x, left_y, right_x, right_y)

        # 날개 점 표시
        if self.wing_points:
            painter.setPen(QPen(QColor(255, 255, 0), 6))

            for px_img, py_img in self.wing_points:
                px, py = self.image_to_widget_pos(px_img, py_img)
                painter.drawPoint(px, py)

        # 두 날개를 잇는 선
        if len(self.wing_points) >= 2:
            x1_img, y1_img = self.wing_points[0]
            x2_img, y2_img = self.wing_points[1]

            x1, y1 = self.image_to_widget_pos(x1_img, y1_img)
            x2, y2 = self.image_to_widget_pos(x2_img, y2_img)

            painter.setPen(QPen(QColor(255, 255, 0), 2))
            painter.drawLine(x1, y1, x2, y2)

            # 두 날개선의 중점 표시
            mx_img = (x1_img + x2_img) / 2.0
            my_img = (y1_img + y2_img) / 2.0
            mx, my = self.image_to_widget_pos(mx_img, my_img)

            painter.setPen(QPen(QColor(255, 160, 0), 5))
            painter.drawPoint(mx, my)

            # 계산된 수직 방향선
            if self.direction_point is not None:
                dx_img, dy_img = self.direction_point
                dx, dy = self.image_to_widget_pos(dx_img, dy_img)

                painter.setPen(QPen(QColor(0, 255, 255), 2))
                painter.drawLine(cx, cy, dx, dy)

                painter.setPen(QPen(QColor(0, 255, 255), 6))
                painter.drawPoint(dx, dy)

        # 상태 텍스트
        painter.setPen(QPen(QColor(255, 255, 255), 1))
        painter.setFont(QFont("Arial", 12))

        if self.degree is not None:
            painter.drawText(10, 24, f"Degree: {self.degree:.2f}°")
        else:
            if len(self.wing_points) == 0:
                painter.drawText(10, 24, "날개 끝 1번 클릭")
            elif len(self.wing_points) == 1:
                painter.drawText(10, 24, "반대쪽 날개 끝 2번 클릭")

@dataclass
class DynamicWindRoi:
    name: str
    x: int
    y: int
    w: int
    h: int

    # 캡처 이미지 내부에서의 실제 바람 중심 좌표
    center_x: int = 0
    center_y: int = 0

class PangyaWindAnglePanel(QWidget):
    def __init__(self, get_window_rect_func, get_overlay_settings_func=None, on_apply_degree=None, parent=None):
        super().__init__(parent)

        self.get_window_rect_func = get_window_rect_func
        self.get_overlay_settings_func = get_overlay_settings_func
        self.on_apply_degree = on_apply_degree

        self.capture = ScreenCaptureService()
        self.current_degree = None

        self.build_ui()

    def build_ui(self):
        root = QVBoxLayout(self)

        desc = QLabel(
            "바람 UI를 캡처한 뒤, 파란 화살표의 양쪽 날개 끝을 차례대로 클릭하세요. "
            "두 점을 잇는 선에 수직인 방향을 기준으로 각도를 계산합니다. "
            "중앙 기준 수직 위쪽이 0도입니다."
        )
        desc.setWordWrap(True)
        root.addWidget(desc)

        button_layout = QHBoxLayout()

        self.capture_btn = QPushButton("바람각도 캡처")
        self.apply_btn = QPushButton("계산기 Degree에 반영")
        self.clear_btn = QPushButton("선택 초기화")
        self.invert_check = QCheckBox("180도 반전")

        button_layout.addWidget(self.capture_btn)
        button_layout.addWidget(self.apply_btn)
        button_layout.addWidget(self.clear_btn)
        button_layout.addWidget(self.invert_check)
        button_layout.addStretch(1)

        root.addLayout(button_layout)

        self.degree_label = QLabel("각도: -")
        root.addWidget(self.degree_label)

        self.canvas = WindAngleCanvas()
        root.addWidget(self.canvas, 1)

        self.capture_btn.clicked.connect(self.capture_wind_angle)
        self.apply_btn.clicked.connect(self.apply_degree)
        self.clear_btn.clicked.connect(self.clear_selection)
        self.canvas.degree_changed.connect(self.on_degree_changed)
        self.invert_check.stateChanged.connect(self.refresh_degree_label)

    def make_dynamic_wind_roi(self, rect):
        """
        오버레이 탭의 바람 X/Y/반지름 설정을 기준으로
        RoiRect(base_x/base_y/base_w/base_h)를 동적으로 만든다.

        주의:
        ScreenCaptureService.capture_roi()는 roi.base_x/base_y/base_w/base_h를 사용하므로
        x/y/w/h 필드가 아니라 RoiRect 구조를 반환해야 한다.
        """
        if self.get_overlay_settings_func is None:
            return DEFAULT_ROIS["wind_angle"], None

        settings = self.get_overlay_settings_func()

        if not settings:
            return DEFAULT_ROIS["wind_angle"], None

        base_w = int(settings.get("base_w", 2048))
        base_h = int(settings.get("base_h", 1152))

        if base_w <= 0 or base_h <= 0:
            return DEFAULT_ROIS["wind_angle"], None

        center_base_x = int(float(settings.get("wind_center_base_x", 1952)))
        center_base_y = int(float(settings.get("wind_center_base_y", 1040)))
        radius_base = int(float(settings.get("wind_radius", 82)))

        # 숫자/테두리/화살표까지 포함하기 위한 기준 해상도상의 캡처 반지름
        capture_radius_base = int(radius_base * 1.25)

        base_x = center_base_x - capture_radius_base
        base_y = center_base_y - capture_radius_base
        base_roi_w = capture_radius_base * 2
        base_roi_h = capture_radius_base * 2

        # 기준 해상도 밖으로 나가지 않게 보정
        if base_x < 0:
            base_roi_w += base_x
            base_x = 0

        if base_y < 0:
            base_roi_h += base_y
            base_y = 0

        if base_x + base_roi_w > base_w:
            base_roi_w = base_w - base_x

        if base_y + base_roi_h > base_h:
            base_roi_h = base_h - base_y

        if base_roi_w <= 10 or base_roi_h <= 10:
            return DEFAULT_ROIS["wind_angle"], None

        # 캡처 이미지 내부에서 실제 바람 중심이 어디인지 계산
        # capture_roi()가 base 좌표를 실제 픽셀로 스케일링하므로,
        # 이미지 내부 중심도 같은 비율로 환산해야 한다.
        scale_x = rect.width / base_w
        scale_y = rect.height / base_h

        center_img_x = int((center_base_x - base_x) * scale_x)
        center_img_y = int((center_base_y - base_y) * scale_y)

        roi = RoiRect(
            name="wind_angle_dynamic",
            base_x=base_x,
            base_y=base_y,
            base_w=base_roi_w,
            base_h=base_roi_h,
        )

        print(
            f"[INFO] WIND_ANGLE_ROI "
            f"base=({base_w},{base_h}), "
            f"client=({rect.width},{rect.height}), "
            f"center_base=({center_base_x},{center_base_y}), "
            f"radius_base={radius_base}, "
            f"roi_base=({base_x},{base_y},{base_roi_w},{base_roi_h}), "
            f"center_img=({center_img_x},{center_img_y})"
        )

        return roi, (center_img_x, center_img_y)
    
    def capture_wind_angle(self):
        rect = self.get_window_rect_func()

        if rect is None:
            QMessageBox.warning(
                self,
                "캡처 실패",
                "게임 창 좌표를 가져오지 못했습니다. 먼저 오버레이 Start를 눌러 대상 게임 창을 찾으세요."
            )
            return

        try:
            roi, center_img_pos = self.make_dynamic_wind_roi(rect)

            settings = self.get_overlay_settings_func() if self.get_overlay_settings_func is not None else {}
            base_w = int(settings.get("base_w", 2048))
            base_h = int(settings.get("base_h", 1152))

            image = self.capture.capture_roi(rect, roi, base_w=base_w, base_h=base_h)
            self.canvas.set_image(image, center_img_pos=center_img_pos)
            self.current_degree = None
            self.refresh_degree_label()

        except Exception as e:
            QMessageBox.critical(self, "캡처 실패", str(e))

    def on_degree_changed(self, degree):
        self.current_degree = degree
        self.refresh_degree_label()

    def get_final_degree(self):
        if self.current_degree is None:
            return None

        degree = self.current_degree

        if self.invert_check.isChecked():
            degree = (degree + 180.0) % 360.0

        return degree

    def refresh_degree_label(self):
        degree = self.get_final_degree()

        if degree is None:
            self.degree_label.setText("각도: -")
            return

        self.degree_label.setText(f"각도: {degree:.2f}°")

    def apply_degree(self):
        degree = self.get_final_degree()

        if degree is None:
            QMessageBox.warning(self, "각도 없음", "먼저 바람 화살표 양쪽 날개 끝을 클릭하세요.")
            return

        if self.on_apply_degree is not None:
            self.on_apply_degree(degree)

        #QMessageBox.information(self, "반영 완료", f"Degree에 {degree:.2f}° 값을 반영했습니다.")

    def clear_selection(self):
        self.canvas.wing_points = []
        self.canvas.degree = None
        self.canvas.direction_point = None
        self.current_degree = None
        self.canvas.update()
        self.refresh_degree_label()