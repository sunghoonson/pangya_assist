import os
import sys
import time
import ctypes
import math

# =========================================================
# DPI 설정
# 반드시 PySide6 import 전에 실행
# =========================================================

def enable_dpi_awareness():
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        print("[INFO] DPI Awareness: Per Monitor V2")
        return
    except Exception:
        pass

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        print("[INFO] DPI Awareness: Per Monitor")
        return
    except Exception:
        pass

    try:
        ctypes.windll.user32.SetProcessDPIAware()
        print("[INFO] DPI Awareness: System DPI Aware")
    except Exception as e:
        print(f"[WARN] DPI Awareness 설정 실패: {e}")


os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "0"
os.environ["QT_SCALE_FACTOR"] = "1"
os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "0"

enable_dpi_awareness()


import psutil
import win32con
import win32gui
import win32process

from PySide6.QtWidgets import QApplication, QWidget
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPainter, QPen, QColor, QFont


# =========================================================
# 기본 설정
# =========================================================

TARGET_EXE = "ProjectG127.exe"

DEBUG_LOG_INTERVAL_SEC = 2.0

# 게임 Client 기준 해상도
BASE_W = 2048
BASE_H = 1152

# 현재 컵 중심 보정값
CUP_BASE_X = 1024
CUP_BASE_Y = 345

# 창 전체 너비 기준 총 폭
GRID_TOTAL_VALUE = 5.2
GRID_HALF_VALUE = GRID_TOTAL_VALUE / 2

# 0.1 칸 단위
GRID_STEP = 0.1

# =========================================================
# 우하단 바람 각도 표시 설정
# =========================================================

# 2048x1152 기준 우하단 바람 UI 중심 좌표
# 정확한 위치는 나중에 스크린샷 보면서 조정
WIND_CENTER_BASE_X = 1952
WIND_CENTER_BASE_Y = 1040

# 바람 각도 원 반지름
WIND_RADIUS = 82

# 5도 간격
WIND_ANGLE_STEP = 5

# 숫자를 원 바깥쪽으로 빼기 위한 오프셋
WIND_TEXT_RADIUS_OFFSET = 18
WIND_TEXT_TANGENT_OFFSET = 10

# 오버레이 추적 주기
TRACK_INTERVAL_MS = 10


# =========================================================
# 윈도우 / DPI 유틸
# =========================================================

def get_dpi_for_window(hwnd):
    try:
        return ctypes.windll.user32.GetDpiForWindow(hwnd)
    except Exception:
        return 96


def find_window_by_process_name(process_name):
    result = []

    def callback(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return

        _, pid = win32process.GetWindowThreadProcessId(hwnd)

        try:
            proc = psutil.Process(pid)

            if proc.name().lower() == process_name.lower():
                title = win32gui.GetWindowText(hwnd)

                if title.strip():
                    result.append(hwnd)

        except psutil.NoSuchProcess:
            pass
        except psutil.AccessDenied:
            pass
        except Exception as e:
            print(f"[WARN] find_window_by_process_name error: {e}")

    win32gui.EnumWindows(callback, None)

    if result:
        return result[0]

    return None


def get_client_rect_on_screen(hwnd):
    window_left, window_top, window_right, window_bottom = win32gui.GetWindowRect(hwnd)

    client_left, client_top, client_right, client_bottom = win32gui.GetClientRect(hwnd)

    client_screen_left, client_screen_top = win32gui.ClientToScreen(
        hwnd,
        (client_left, client_top)
    )

    client_screen_right, client_screen_bottom = win32gui.ClientToScreen(
        hwnd,
        (client_right, client_bottom)
    )

    return (
        client_screen_left,
        client_screen_top,
        client_screen_right,
        client_screen_bottom,
        window_left,
        window_top,
        window_right,
        window_bottom,
        client_left,
        client_top,
        client_right,
        client_bottom
    )


# =========================================================
# 오버레이 클래스
# =========================================================

class PangyaOverlay(QWidget):
    def __init__(self):
        super().__init__()

        self.target_hwnd = None
        self.overlay_hwnd = None
        self.last_debug_log_time = 0

        self.last_left = None
        self.last_top = None
        self.last_width = None
        self.last_height = None

        self.setWindowFlags(
            Qt.FramelessWindowHint |
            Qt.WindowStaysOnTopHint |
            Qt.Tool
        )

        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_NoSystemBackground)

        self.show()
        self.overlay_hwnd = int(self.winId())

        self.apply_overlay_window_style()

        self.timer = QTimer()
        self.timer.timeout.connect(self.update_overlay)
        self.timer.start(TRACK_INTERVAL_MS)

    def apply_overlay_window_style(self):
        if not self.overlay_hwnd:
            return

        try:
            ex_style = win32gui.GetWindowLong(self.overlay_hwnd, win32con.GWL_EXSTYLE)

            ex_style |= win32con.WS_EX_LAYERED
            ex_style |= win32con.WS_EX_TRANSPARENT
            ex_style |= win32con.WS_EX_TOOLWINDOW
            ex_style |= win32con.WS_EX_TOPMOST

            win32gui.SetWindowLong(self.overlay_hwnd, win32con.GWL_EXSTYLE, ex_style)

        except Exception as e:
            print(f"[WARN] apply_overlay_window_style failed: {e}")

    def move_overlay_native(self, left, top, width, height):
        if not self.overlay_hwnd:
            self.overlay_hwnd = int(self.winId())

        flags = (
            win32con.SWP_NOACTIVATE |
            win32con.SWP_SHOWWINDOW
        )

        win32gui.SetWindowPos(
            self.overlay_hwnd,
            win32con.HWND_TOPMOST,
            int(left),
            int(top),
            int(width),
            int(height),
            flags
        )

    def update_overlay(self):
        self.target_hwnd = find_window_by_process_name(TARGET_EXE)

        if not self.target_hwnd:
            self.hide()
            return

        try:
            (
                left,
                top,
                right,
                bottom,
                window_left,
                window_top,
                window_right,
                window_bottom,
                client_left,
                client_top,
                client_right,
                client_bottom
            ) = get_client_rect_on_screen(self.target_hwnd)

        except Exception as e:
            print(f"[ERROR] get_client_rect_on_screen failed: {e}")
            self.hide()
            return

        width = right - left
        height = bottom - top

        if width <= 0 or height <= 0:
            self.hide()
            return

        if (
            self.last_left != left or
            self.last_top != top or
            self.last_width != width or
            self.last_height != height
        ):
            self.move_overlay_native(left, top, width, height)

            self.last_left = left
            self.last_top = top
            self.last_width = width
            self.last_height = height

        if not self.isVisible():
            self.show()

        self.update()

        self.print_debug_log(
            left=left,
            top=top,
            right=right,
            bottom=bottom,
            window_left=window_left,
            window_top=window_top,
            window_right=window_right,
            window_bottom=window_bottom,
            client_left=client_left,
            client_top=client_top,
            client_right=client_right,
            client_bottom=client_bottom
        )

    def print_debug_log(
        self,
        left,
        top,
        right,
        bottom,
        window_left,
        window_top,
        window_right,
        window_bottom,
        client_left,
        client_top,
        client_right,
        client_bottom
    ):
        now = time.time()

        if now - self.last_debug_log_time < DEBUG_LOG_INTERVAL_SEC:
            return

        self.last_debug_log_time = now

        client_width = right - left
        client_height = bottom - top

        target_dpi = get_dpi_for_window(self.target_hwnd)
        overlay_dpi = get_dpi_for_window(self.overlay_hwnd)

        print("========== Pangya Overlay Debug ==========")
        print(f"Target EXE        : {TARGET_EXE}")
        print(f"Target HWND       : {self.target_hwnd}")
        print(f"Overlay HWND      : {self.overlay_hwnd}")
        print(f"Target DPI        : {target_dpi}")
        print(f"Overlay DPI       : {overlay_dpi}")
        print(f"ClientOnScreen    : left={left}, top={top}, right={right}, bottom={bottom}")
        print(f"ClientSize        : width={client_width}, height={client_height}")
        print(f"NativeLast        : x={self.last_left}, y={self.last_top}, width={self.last_width}, height={self.last_height}")
        print(f"CUP_BASE          : x={CUP_BASE_X}, y={CUP_BASE_Y}")
        print(f"GRID              : -{GRID_HALF_VALUE:.2f} ~ +{GRID_HALF_VALUE:.2f}")
        print("==========================================")

    def draw_wind_angle_area(self, painter, scale_x, scale_y):
        """
        우하단 바람 UI 위에 5도 간격 각도 눈금을 그린다.
        원을 4분할해서 각 사분면마다 0~90으로 표시한다.
        숫자는 원 바깥쪽에 표시해서 화살표 끝을 가리지 않게 한다.
        """
        center_x = int(WIND_CENTER_BASE_X * scale_x)
        center_y = int(WIND_CENTER_BASE_Y * scale_y)
        radius = int(WIND_RADIUS * scale_x)

        if radius <= 0:
            return

        painter.setRenderHint(QPainter.Antialiasing, True)

        # 외곽 원 그림자
        painter.setPen(QPen(QColor(0, 0, 0, 180), 3))
        painter.drawEllipse(
            center_x - radius,
            center_y - radius,
            radius * 2,
            radius * 2
        )

        # 외곽 원 본체
        painter.setPen(QPen(QColor(255, 255, 255, 230), 1))
        painter.drawEllipse(
            center_x - radius,
            center_y - radius,
            radius * 2,
            radius * 2
        )

        quadrant_starts = [0, 90, 180, 270]

        for q_start in quadrant_starts:
            for local_deg in range(0, 91, WIND_ANGLE_STEP):
                abs_deg = q_start + local_deg
                rad = math.radians((abs_deg % 360) - 90)

                # 기본 5도 눈금
                tick_len = 7
                line_width = 1

                # 15도 단위
                if local_deg % 15 == 0:
                    tick_len = 11
                    line_width = 1

                # 30도 / 60도 강조
                if local_deg in (30, 60):
                    tick_len = 15
                    line_width = 2

                # 0 / 90 경계축은 더 강조
                if local_deg in (0, 90):
                    tick_len = 20
                    line_width = 2

                outer_x = center_x + math.cos(rad) * radius
                outer_y = center_y + math.sin(rad) * radius

                inner_x = center_x + math.cos(rad) * (radius - tick_len)
                inner_y = center_y + math.sin(rad) * (radius - tick_len)

                # 그림자
                painter.setPen(QPen(QColor(0, 0, 0, 200), line_width + 2))
                painter.drawLine(
                    int(inner_x), int(inner_y),
                    int(outer_x), int(outer_y)
                )

                # 본선
                painter.setPen(QPen(QColor(255, 255, 255, 255), line_width))
                painter.drawLine(
                    int(inner_x), int(inner_y),
                    int(outer_x), int(outer_y)
                )

                # 숫자는 각 사분면별 0 / 30 / 60 / 90만 표시
                if local_deg in (0, 30, 60, 90):
                    # 원 바깥쪽에 숫자 배치
                    text_radius = radius + WIND_TEXT_RADIUS_OFFSET

                    # 접선 방향 벡터
                    tangent_x = -math.sin(rad)
                    tangent_y = math.cos(rad)

                    # 0과 90은 같은 축에 몰리므로 접선 방향으로 살짝 벌려줌
                    tangent_offset = 0
                    if local_deg == 0:
                        tangent_offset = -WIND_TEXT_TANGENT_OFFSET
                    elif local_deg == 90:
                        tangent_offset = WIND_TEXT_TANGENT_OFFSET

                    text_x = (
                        center_x +
                        math.cos(rad) * text_radius +
                        tangent_x * tangent_offset
                    )
                    text_y = (
                        center_y +
                        math.sin(rad) * text_radius +
                        tangent_y * tangent_offset
                    )

                    text = str(local_deg)

                    painter.setFont(QFont("Arial", 8))

                    # 글자 그림자
                    painter.setPen(QPen(QColor(0, 0, 0, 230), 1))
                    painter.drawText(int(text_x) - 10, int(text_y) + 5, text)

                    # 글자 본체
                    painter.setPen(QPen(QColor(255, 255, 255, 255), 1))
                    painter.drawText(int(text_x) - 11, int(text_y) + 4, text)

        # 중심점
        painter.setPen(QPen(QColor(0, 0, 0, 220), 4))
        painter.drawPoint(center_x, center_y)

        painter.setPen(QPen(QColor(255, 0, 0, 255), 3))
        painter.drawPoint(center_x, center_y)
        
    def paintEvent(self, event):
        if not self.target_hwnd:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        width = self.width()
        height = self.height()

        if width <= 0 or height <= 0:
            return

        scale_x = width / BASE_W
        scale_y = height / BASE_H

        cup_x = int(CUP_BASE_X * scale_x)
        cup_y = int(CUP_BASE_Y * scale_y)

        # 창 전체 너비 기준
        pixels_per_value = width / GRID_TOTAL_VALUE

        # --------------------------------------------------
        # 1. 정보 텍스트
        # --------------------------------------------------
        # painter.setFont(QFont("Arial", 14))
        # painter.setPen(QPen(QColor(255, 255, 0, 230), 1))
        # painter.drawText(30, 40, "Pangya Assist Overlay")

        # painter.setFont(QFont("Arial", 10))
        # painter.setPen(QPen(QColor(255, 255, 255, 255), 1))
        # painter.drawText(30, 65, f"Client Size: {width} x {height}")
        # painter.drawText(30, 85, f"Scale: x={scale_x:.4f}, y={scale_y:.4f}")
        # painter.drawText(30, 105, f"Cup Base: x={CUP_BASE_X}, y={CUP_BASE_Y}")
        # painter.drawText(30, 125, f"Grid: window width = {GRID_TOTAL_VALUE}")

        # --------------------------------------------------
        # 2. 컵 중심 표시
        # TEMP CUP 텍스트 제거
        # --------------------------------------------------
        painter.setPen(QPen(QColor(255, 0, 0, 255), 2))
        painter.drawEllipse(cup_x - 8, cup_y - 8, 16, 16)

        # 컵 중심 가로 기준선
        painter.setPen(QPen(QColor(255, 0, 0, 255), 1))
        painter.drawLine(cup_x - 50, cup_y, cup_x + 50, cup_y)

        # 컵 중심 0 기준 세로 짧은 선
        painter.setPen(QPen(QColor(255, 0, 0, 255), 2))
        painter.drawLine(cup_x, cup_y - 30, cup_x, cup_y + 30)

        # --------------------------------------------------
        # 3. 창 전체 기준 0.1 단위 눈금
        # 0.1도 더 잘 보이게 검은 그림자 + 진한 흰색
        # --------------------------------------------------
        painter.setFont(QFont("Arial", 8))

        # 눈금은 또렷하게 보이도록 안티앨리어싱 끔
        painter.setRenderHint(QPainter.Antialiasing, False)

        min_i = int(-GRID_HALF_VALUE / GRID_STEP)
        max_i = int(GRID_HALF_VALUE / GRID_STEP)

        for i in range(min_i, max_i + 1):
            value = round(i * GRID_STEP, 1)
            x = int(cup_x + value * pixels_per_value)

            if x < 0 or x > width:
                continue

            abs_i = abs(i)

            # 기본 0.1 눈금
            tick_top = cup_y - 12
            tick_bottom = cup_y + 12
            shadow_width = 3
            line_width = 2

            # 0.5 단위
            if abs_i % 5 == 0:
                tick_top = cup_y - 18
                tick_bottom = cup_y + 18
                shadow_width = 3
                line_width = 2

            # 1.0 단위
            if abs_i % 10 == 0:
                tick_top = cup_y - 26
                tick_bottom = cup_y + 26
                shadow_width = 4
                line_width = 3

            # 0 중심
            if i == 0:
                painter.setPen(QPen(QColor(0, 0, 0, 220), 4))
                painter.drawLine(x, cup_y - 34, x, cup_y + 34)

                painter.setPen(QPen(QColor(255, 0, 0, 255), 2))
                painter.drawLine(x, cup_y - 32, x, cup_y + 32)

                painter.setPen(QPen(QColor(0, 0, 0, 220), 1))
                painter.drawText(x - 7, cup_y + 41, "0")

                painter.setPen(QPen(QColor(255, 255, 255, 255), 1))
                painter.drawText(x - 8, cup_y + 40, "0")
                continue

            # 그림자 선
            painter.setPen(QPen(QColor(0, 0, 0, 180), shadow_width))
            painter.drawLine(x, tick_top, x, tick_bottom)

            # 실제 흰색 선
            painter.setPen(QPen(QColor(255, 255, 255, 255), line_width))
            painter.drawLine(x, tick_top, x, tick_bottom)

            # 1.0 단위 숫자
            if abs_i % 10 == 0:
                # 글자 그림자
                painter.setPen(QPen(QColor(0, 0, 0, 220), 1))
                painter.drawText(x - 11, cup_y + 39, f"{value:.1f}")

                # 글자 본체
                painter.setPen(QPen(QColor(255, 255, 255, 255), 1))
                painter.drawText(x - 12, cup_y + 38, f"{value:.1f}")

            # 양 끝 값 표시
            if i == min_i or i == max_i:
                painter.setPen(QPen(QColor(0, 0, 0, 220), 1))
                painter.drawText(x - 17, cup_y - 31, f"{value:.1f}")

                painter.setPen(QPen(QColor(255, 255, 255, 255), 1))
                painter.drawText(x - 18, cup_y - 32, f"{value:.1f}")

        # 이후 다른 도형 그릴 때 다시 안티앨리어싱 켬
        painter.setRenderHint(QPainter.Antialiasing, True)

        # --------------------------------------------------
        # 4. 화면 좌우 끝 기준선
        # --------------------------------------------------
        painter.setPen(QPen(QColor(255, 255, 255, 255), 1))
        painter.drawLine(0, cup_y - 25, 0, cup_y + 25)
        painter.drawLine(width - 1, cup_y - 25, width - 1, cup_y + 25)

        # --------------------------------------------------
        # 5. 우하단 바람각도 영역 임시 표시
        # --------------------------------------------------
        self.draw_wind_angle_area(painter, scale_x, scale_y)

        # --------------------------------------------------
        # 6. 좌하단 공기울기 영역 임시 표시
        # --------------------------------------------------
        slope_center_x = int(115 * scale_x)
        slope_center_y = int(1040 * scale_y)
        slope_line_half_width = int(55 * scale_x)

        # 검은 그림자 선
        painter.setPen(QPen(QColor(0, 0, 0, 220), 4))
        painter.drawLine(
            slope_center_x - slope_line_half_width,
            slope_center_y,
            slope_center_x + slope_line_half_width,
            slope_center_y
        )

        # 본선
        painter.setPen(QPen(QColor(255, 255, 255, 255), 2))
        painter.drawLine(
            slope_center_x - slope_line_half_width,
            slope_center_y,
            slope_center_x + slope_line_half_width,
            slope_center_y
        )


# =========================================================
# 실행부
# =========================================================

if __name__ == "__main__":
    app = QApplication(sys.argv)

    overlay = PangyaOverlay()

    sys.exit(app.exec())