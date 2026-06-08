import os
import sys
import time
import json
import ctypes
import math
from copy import deepcopy
import ctypes.wintypes

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

from PySide6.QtWidgets import (
    QApplication,
    QWidget,
    QLabel,
    QLineEdit,
    QPushButton,
    QGridLayout,
    QVBoxLayout,
    QHBoxLayout,
    QGroupBox,
    QSpinBox,
    QDoubleSpinBox,
    QCheckBox,
    QMessageBox,
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPainter, QPen, QColor, QFont


# =========================================================
# 기본 설정
# =========================================================

BASE_W = 2048
BASE_H = 1152

DEBUG_LOG_INTERVAL_SEC = 2.0
TRACK_INTERVAL_MS = 10

WIND_ANGLE_STEP = 5
WIND_TEXT_RADIUS_OFFSET = 18
WIND_TEXT_TANGENT_OFFSET = 10

HOTKEY_ID_TOGGLE_OVERLAY = 1001

DEFAULT_SETTINGS = {
    "target_exe": "ProjectG127.exe",

    # 게임 Client 기준 해상도
    "base_w": BASE_W,
    "base_h": BASE_H,

    # 컵 중심
    "cup_base_x": 1024,
    "cup_base_y": 345,

    # 창 전체 너비 기준 총 폭
    "grid_total_value": 5.2,
    "grid_step": 0.1,

    # 우하단 바람 각도 표시
    "wind_center_base_x": 1952,
    "wind_center_base_y": 1040,
    "wind_radius": 82,

    # 좌하단 기울기 가로선
    "slope_center_base_x": 115,
    "slope_center_base_y": 1040,
    "slope_line_half_width": 55,

    # 표시 옵션
    "show_cup": True,
    "show_grid": True,
    "show_wind": True,
    "show_slope": True,

    # 전역 토글 단축키
    # 예: F8, Ctrl+F8, Ctrl+Alt+F8
    "toggle_hotkey": "F8",
}


# =========================================================
# 설정 파일 유틸
# =========================================================

def get_app_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)

    return os.path.dirname(os.path.abspath(__file__))


def get_settings_path():
    return os.path.join(get_app_dir(), "pangya_overlay_settings.json")


def normalize_settings(settings):
    normalized = deepcopy(DEFAULT_SETTINGS)
    normalized.update(settings or {})
    return normalized


def load_settings():
    path = get_settings_path()

    if not os.path.exists(path):
        return normalize_settings({})

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        return normalize_settings(data)

    except Exception as e:
        print(f"[WARN] 설정 파일 로드 실패. 기본값 사용: {e}")
        return normalize_settings({})


def save_settings(settings):
    path = get_settings_path()

    with open(path, "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False, indent=4)

    print(f"[INFO] 설정 저장 완료: {path}")


# =========================================================
# 전역 단축키 유틸
# =========================================================

VK_MAP = {
    "F1": 0x70,
    "F2": 0x71,
    "F3": 0x72,
    "F4": 0x73,
    "F5": 0x74,
    "F6": 0x75,
    "F7": 0x76,
    "F8": 0x77,
    "F9": 0x78,
    "F10": 0x79,
    "F11": 0x7A,
    "F12": 0x7B,
    "SPACE": 0x20,
    "TAB": 0x09,
    "ESC": 0x1B,
    "ESCAPE": 0x1B,
    "INSERT": 0x2D,
    "DELETE": 0x2E,
    "HOME": 0x24,
    "END": 0x23,
    "PAGEUP": 0x21,
    "PAGEDOWN": 0x22,
    "LEFT": 0x25,
    "UP": 0x26,
    "RIGHT": 0x27,
    "DOWN": 0x28,
}

for i in range(10):
    VK_MAP[str(i)] = ord(str(i))

for i in range(26):
    ch = chr(ord("A") + i)
    VK_MAP[ch] = ord(ch)


def parse_hotkey_text(hotkey_text):
    text = (hotkey_text or "").strip().upper().replace(" ", "")

    if not text:
        raise ValueError("단축키가 비어 있습니다.")

    parts = text.split("+")
    modifiers = 0
    key = None

    for part in parts:
        if part in ("CTRL", "CONTROL"):
            modifiers |= win32con.MOD_CONTROL
        elif part == "ALT":
            modifiers |= win32con.MOD_ALT
        elif part == "SHIFT":
            modifiers |= win32con.MOD_SHIFT
        elif part in ("WIN", "WINDOWS"):
            modifiers |= win32con.MOD_WIN
        else:
            key = part

    if not key:
        raise ValueError("실제 키가 없습니다. 예: F8, Ctrl+F8")

    vk = VK_MAP.get(key)

    if vk is None:
        raise ValueError(f"지원하지 않는 키입니다: {key}")

    return modifiers, vk


class HotkeyCaptureLineEdit(QLineEdit):
    """
    직접 타이핑하지 않고 실제 키 입력을 받아 단축키 문자열로 변환하는 입력창.
    예: Ctrl + F8 입력 -> Ctrl+F8
    """
    def __init__(self):
        super().__init__()

        self.capture_mode = False
        self.setReadOnly(True)
        self.setPlaceholderText("단축키 입력 버튼을 누른 뒤 실제 키 조합을 입력")

    def start_capture(self):
        self.capture_mode = True
        self.setText("입력 대기 중...")
        self.setFocus(Qt.OtherFocusReason)
        self.selectAll()

    def stop_capture(self):
        self.capture_mode = False

    def keyPressEvent(self, event):
        if not self.capture_mode:
            return super().keyPressEvent(event)

        key = event.key()
        modifiers = event.modifiers()

        # 수정키만 단독으로 누른 경우는 단축키로 저장하지 않음
        modifier_only_keys = {
            Qt.Key_Control,
            Qt.Key_Shift,
            Qt.Key_Alt,
            Qt.Key_Meta,
        }

        if key in modifier_only_keys:
            return

        key_name = self.qt_key_to_name(key)

        if not key_name:
            self.setText("")
            self.stop_capture()
            QMessageBox.warning(self, "단축키 오류", "지원하지 않는 키입니다. F1~F12, 문자, 숫자, 방향키 등을 사용하세요.")
            return

        parts = []

        if modifiers & Qt.ControlModifier:
            parts.append("Ctrl")

        if modifiers & Qt.AltModifier:
            parts.append("Alt")

        if modifiers & Qt.ShiftModifier:
            parts.append("Shift")

        if modifiers & Qt.MetaModifier:
            parts.append("Win")

        parts.append(key_name)

        hotkey_text = "+".join(parts)

        try:
            parse_hotkey_text(hotkey_text)

        except Exception as e:
            self.setText("")
            self.stop_capture()
            QMessageBox.warning(self, "단축키 오류", str(e))
            return

        self.setText(hotkey_text)
        self.stop_capture()

    def focusOutEvent(self, event):
        if self.capture_mode:
            self.stop_capture()

            if self.text() == "입력 대기 중...":
                self.setText("")

        super().focusOutEvent(event)

    def qt_key_to_name(self, key):
        function_key_map = {
            Qt.Key_F1: "F1",
            Qt.Key_F2: "F2",
            Qt.Key_F3: "F3",
            Qt.Key_F4: "F4",
            Qt.Key_F5: "F5",
            Qt.Key_F6: "F6",
            Qt.Key_F7: "F7",
            Qt.Key_F8: "F8",
            Qt.Key_F9: "F9",
            Qt.Key_F10: "F10",
            Qt.Key_F11: "F11",
            Qt.Key_F12: "F12",
        }

        special_key_map = {
            Qt.Key_Space: "Space",
            Qt.Key_Tab: "Tab",
            Qt.Key_Escape: "Esc",
            Qt.Key_Insert: "Insert",
            Qt.Key_Delete: "Delete",
            Qt.Key_Home: "Home",
            Qt.Key_End: "End",
            Qt.Key_PageUp: "PageUp",
            Qt.Key_PageDown: "PageDown",
            Qt.Key_Left: "Left",
            Qt.Key_Up: "Up",
            Qt.Key_Right: "Right",
            Qt.Key_Down: "Down",
        }

        if key in function_key_map:
            return function_key_map[key]

        if key in special_key_map:
            return special_key_map[key]

        if Qt.Key_0 <= key <= Qt.Key_9:
            return chr(key)

        if Qt.Key_A <= key <= Qt.Key_Z:
            return chr(key)

        return None


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
    def __init__(self, settings):
        super().__init__()

        self.settings = normalize_settings(settings)
        self.is_running = False

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

        self.hide()
        self.overlay_hwnd = int(self.winId())

        self.apply_overlay_window_style()

        self.timer = QTimer()
        self.timer.timeout.connect(self.update_overlay)

    def set_settings(self, settings):
        self.settings = normalize_settings(settings)
        self.update()

    def start_overlay(self):
        self.is_running = True

        # Start 시점에는 이전 위치 캐시를 버린다.
        # 그래야 첫 update_overlay에서 무조건 위치/크기 보정을 수행한다.
        self.last_left = None
        self.last_top = None
        self.last_width = None
        self.last_height = None

        if not self.timer.isActive():
            self.timer.start(TRACK_INTERVAL_MS)

        self.update_overlay()

    def stop_overlay(self):
        self.is_running = False

        if self.timer.isActive():
            self.timer.stop()

        self.target_hwnd = None

        self.last_left = None
        self.last_top = None
        self.last_width = None
        self.last_height = None

        self.hide()

    def toggle_overlay(self):
        if self.is_running:
            self.stop_overlay()
            return False

        self.start_overlay()
        return True

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
        if not self.is_running:
            self.hide()
            return

        target_exe = self.settings["target_exe"]
        self.target_hwnd = find_window_by_process_name(target_exe)

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

        was_hidden = not self.isVisible()

        # Qt 창이 숨김 상태였다면 먼저 표시한다.
        # 숨김 상태에서 native SetWindowPos를 먼저 호출한 뒤 show()를 하면
        # Qt가 초기 geometry를 다시 건드릴 수 있어서 위치가 어긋날 수 있다.
        if was_hidden:
            self.show()
            self.apply_overlay_window_style()

        need_move = (
            was_hidden or
            self.last_left != left or
            self.last_top != top or
            self.last_width != width or
            self.last_height != height
        )

        if need_move:
            self.move_overlay_native(left, top, width, height)

            self.last_left = left
            self.last_top = top
            self.last_width = width
            self.last_height = height

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

        grid_half_value = self.settings["grid_total_value"] / 2

        print("========== Pangya Overlay Debug ==========")
        print(f"Target EXE        : {self.settings['target_exe']}")
        print(f"Target HWND       : {self.target_hwnd}")
        print(f"Overlay HWND      : {self.overlay_hwnd}")
        print(f"Target DPI        : {target_dpi}")
        print(f"Overlay DPI       : {overlay_dpi}")
        print(f"ClientOnScreen    : left={left}, top={top}, right={right}, bottom={bottom}")
        print(f"ClientSize        : width={client_width}, height={client_height}")
        print(f"BASE              : w={self.settings['base_w']}, h={self.settings['base_h']}")
        print(f"NativeLast        : x={self.last_left}, y={self.last_top}, width={self.last_width}, height={self.last_height}")
        print(f"CUP_BASE          : x={self.settings['cup_base_x']}, y={self.settings['cup_base_y']}")
        print(f"GRID              : -{grid_half_value:.2f} ~ +{grid_half_value:.2f}")
        print(f"SLOPE             : x={self.settings['slope_center_base_x']}, y={self.settings['slope_center_base_y']}, half={self.settings['slope_line_half_width']}")
        print("==========================================")

    def draw_wind_angle_area(self, painter, scale_x, scale_y):
        """
        우하단 바람 UI 위에 5도 간격 각도 눈금을 그린다.
        원을 4분할해서 각 사분면마다 0~90으로 표시한다.
        숫자는 원 바깥쪽에 표시해서 화살표 끝을 가리지 않게 한다.
        """
        center_x = int(self.settings["wind_center_base_x"] * scale_x)
        center_y = int(self.settings["wind_center_base_y"] * scale_y)
        radius = int(self.settings["wind_radius"] * scale_x)

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

        base_w = int(self.settings["base_w"])
        base_h = int(self.settings["base_h"])

        if base_w <= 0 or base_h <= 0:
            return

        scale_x = width / base_w
        scale_y = height / base_h

        cup_x = int(self.settings["cup_base_x"] * scale_x)
        cup_y = int(self.settings["cup_base_y"] * scale_y)

        grid_total_value = self.settings["grid_total_value"]
        grid_half_value = grid_total_value / 2
        grid_step = self.settings["grid_step"]

        # 창 전체 너비 기준
        pixels_per_value = width / grid_total_value

        # --------------------------------------------------
        # 1. 컵 중심 표시
        # --------------------------------------------------
        if self.settings["show_cup"]:
            painter.setPen(QPen(QColor(255, 0, 0, 255), 2))
            painter.drawEllipse(cup_x - 8, cup_y - 8, 16, 16)

            # 컵 중심 가로 기준선
            painter.setPen(QPen(QColor(255, 0, 0, 255), 1))
            painter.drawLine(cup_x - 50, cup_y, cup_x + 50, cup_y)

            # 컵 중심 0 기준 세로 짧은 선
            painter.setPen(QPen(QColor(255, 0, 0, 255), 2))
            painter.drawLine(cup_x, cup_y - 30, cup_x, cup_y + 30)

        # --------------------------------------------------
        # 2. 창 전체 기준 0.1 단위 눈금
        # --------------------------------------------------
        if self.settings["show_grid"]:
            painter.setFont(QFont("Arial", 8))

            # 눈금은 또렷하게 보이도록 안티앨리어싱 끔
            painter.setRenderHint(QPainter.Antialiasing, False)

            min_i = int(-grid_half_value / grid_step)
            max_i = int(grid_half_value / grid_step)

            for i in range(min_i, max_i + 1):
                value = round(i * grid_step, 1)
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

            # 화면 좌우 끝 기준선
            painter.setPen(QPen(QColor(255, 255, 255, 255), 1))
            painter.drawLine(0, cup_y - 25, 0, cup_y + 25)
            painter.drawLine(width - 1, cup_y - 25, width - 1, cup_y + 25)

        # --------------------------------------------------
        # 3. 우하단 바람각도 영역 표시
        # --------------------------------------------------
        if self.settings["show_wind"]:
            self.draw_wind_angle_area(painter, scale_x, scale_y)

        # --------------------------------------------------
        # 4. 좌하단 공기울기 영역 표시
        # --------------------------------------------------
        if self.settings["show_slope"]:
            slope_center_x = int(self.settings["slope_center_base_x"] * scale_x)
            slope_center_y = int(self.settings["slope_center_base_y"] * scale_y)
            slope_line_half_width = int(self.settings["slope_line_half_width"] * scale_x)

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
# 설정 GUI 클래스
# =========================================================

class PangyaControlWindow(QWidget):
    def __init__(self, overlay, settings):
        super().__init__()

        self.overlay = overlay
        self.settings = normalize_settings(settings)
        self.hotkey_registered = False

        self.setWindowTitle("Pangya Assist Overlay 설정")
        self.setMinimumWidth(520)

        self.build_ui()
        self.bind_events()
        self.load_settings_to_ui()

        #self.register_hotkey_from_settings()

    def build_ui(self):
        root = QVBoxLayout(self)

        status_group = QGroupBox("실행")
        status_layout = QGridLayout(status_group)

        self.status_label = QLabel("상태: 중지")
        self.start_btn = QPushButton("Start")
        self.stop_btn = QPushButton("Stop")
        self.apply_btn = QPushButton("적용")
        self.save_btn = QPushButton("저장")
        self.reset_btn = QPushButton("기본값")

        status_layout.addWidget(self.status_label, 0, 0, 1, 4)
        status_layout.addWidget(self.start_btn, 1, 0)
        status_layout.addWidget(self.stop_btn, 1, 1)
        status_layout.addWidget(self.apply_btn, 1, 2)
        status_layout.addWidget(self.save_btn, 1, 3)
        status_layout.addWidget(self.reset_btn, 1, 4)

        root.addWidget(status_group)

        basic_group = QGroupBox("기본")
        basic_layout = QGridLayout(basic_group)

        self.target_exe_edit = QLineEdit()
        self.hotkey_edit = HotkeyCaptureLineEdit()
        self.hotkey_capture_btn = QPushButton("단축키 입력")
        self.hotkey_clear_btn = QPushButton("비우기")

        hotkey_button_layout = QHBoxLayout()
        hotkey_button_layout.addWidget(self.hotkey_capture_btn)
        hotkey_button_layout.addWidget(self.hotkey_clear_btn)
        hotkey_button_layout.addStretch(1)

        basic_layout.addWidget(QLabel("대상 EXE"), 0, 0)
        basic_layout.addWidget(self.target_exe_edit, 0, 1)
        basic_layout.addWidget(QLabel("On/Off 단축키"), 1, 0)
        basic_layout.addWidget(self.hotkey_edit, 1, 1)
        basic_layout.addWidget(QLabel(""), 2, 0)
        basic_layout.addLayout(hotkey_button_layout, 2, 1)

        root.addWidget(basic_group)

        coord_group = QGroupBox("좌표 / 크기")
        coord_layout = QGridLayout(coord_group)

        self.base_w_spin = self.create_int_spin(100, 10000)
        self.base_h_spin = self.create_int_spin(100, 10000)

        self.cup_x_spin = self.create_int_spin()
        self.cup_y_spin = self.create_int_spin()

        self.grid_total_spin = self.create_double_spin(0.1, 50.0, 0.1, 1)
        self.grid_step_spin = self.create_double_spin(0.01, 10.0, 0.01, 2)

        self.wind_x_spin = self.create_int_spin()
        self.wind_y_spin = self.create_int_spin()
        self.wind_radius_spin = self.create_int_spin(1, 1000)

        self.slope_x_spin = self.create_int_spin()
        self.slope_y_spin = self.create_int_spin()
        self.slope_half_width_spin = self.create_int_spin(1, 1000)

        row = 0
        coord_layout.addWidget(QLabel("Base W"), row, 0)
        coord_layout.addWidget(self.base_w_spin, row, 1)
        coord_layout.addWidget(QLabel("Base H"), row, 2)
        coord_layout.addWidget(self.base_h_spin, row, 3)

        row += 1
        coord_layout.addWidget(QLabel("컵 X"), row, 0)
        coord_layout.addWidget(self.cup_x_spin, row, 1)
        coord_layout.addWidget(QLabel("컵 Y"), row, 2)
        coord_layout.addWidget(self.cup_y_spin, row, 3)

        row += 1
        coord_layout.addWidget(QLabel("눈금 총 폭"), row, 0)
        coord_layout.addWidget(self.grid_total_spin, row, 1)
        coord_layout.addWidget(QLabel("눈금 간격"), row, 2)
        coord_layout.addWidget(self.grid_step_spin, row, 3)

        row += 1
        coord_layout.addWidget(QLabel("바람 X"), row, 0)
        coord_layout.addWidget(self.wind_x_spin, row, 1)
        coord_layout.addWidget(QLabel("바람 Y"), row, 2)
        coord_layout.addWidget(self.wind_y_spin, row, 3)

        row += 1
        coord_layout.addWidget(QLabel("바람 반지름"), row, 0)
        coord_layout.addWidget(self.wind_radius_spin, row, 1)

        row += 1
        coord_layout.addWidget(QLabel("기울기 선 X"), row, 0)
        coord_layout.addWidget(self.slope_x_spin, row, 1)
        coord_layout.addWidget(QLabel("기울기 선 Y"), row, 2)
        coord_layout.addWidget(self.slope_y_spin, row, 3)

        row += 1
        coord_layout.addWidget(QLabel("기울기 선 반폭"), row, 0)
        coord_layout.addWidget(self.slope_half_width_spin, row, 1)

        root.addWidget(coord_group)

        visible_group = QGroupBox("표시 항목")
        visible_layout = QHBoxLayout(visible_group)

        self.show_cup_check = QCheckBox("컵 중심")
        self.show_grid_check = QCheckBox("눈금")
        self.show_wind_check = QCheckBox("바람 각도")
        self.show_slope_check = QCheckBox("기울기 선")

        visible_layout.addWidget(self.show_cup_check)
        visible_layout.addWidget(self.show_grid_check)
        visible_layout.addWidget(self.show_wind_check)
        visible_layout.addWidget(self.show_slope_check)

        root.addWidget(visible_group)

        help_label = QLabel(
            "Base W/H는 좌표값을 해석하는 기준 해상도입니다. 좌표값은 현재 설정한 Base 해상도 기준이며, 저장하면 다음 실행부터 pangya_overlay_settings.json 값을 사용합니다."
        )
        help_label.setWordWrap(True)

        root.addWidget(help_label)

    def create_int_spin(self, minimum=0, maximum=5000):
        spin = QSpinBox()
        spin.setRange(minimum, maximum)
        spin.setSingleStep(1)
        return spin

    def create_double_spin(self, minimum, maximum, step, decimals):
        spin = QDoubleSpinBox()
        spin.setRange(minimum, maximum)
        spin.setSingleStep(step)
        spin.setDecimals(decimals)
        return spin

    def bind_events(self):
        self.start_btn.clicked.connect(self.on_start_clicked)
        self.stop_btn.clicked.connect(self.on_stop_clicked)
        self.apply_btn.clicked.connect(self.on_apply_clicked)
        self.save_btn.clicked.connect(self.on_save_clicked)
        self.reset_btn.clicked.connect(self.on_reset_clicked)
        self.hotkey_capture_btn.clicked.connect(self.on_hotkey_capture_clicked)
        self.hotkey_clear_btn.clicked.connect(self.on_hotkey_clear_clicked)

    def on_hotkey_capture_clicked(self):
        self.hotkey_edit.start_capture()

    def on_hotkey_clear_clicked(self):
        self.hotkey_edit.stop_capture()
        self.hotkey_edit.setText("")

    def load_settings_to_ui(self):
        s = self.settings

        self.target_exe_edit.setText(str(s["target_exe"]))
        self.hotkey_edit.setText(str(s["toggle_hotkey"]))

        self.base_w_spin.setValue(int(s["base_w"]))
        self.base_h_spin.setValue(int(s["base_h"]))

        self.cup_x_spin.setValue(int(s["cup_base_x"]))
        self.cup_y_spin.setValue(int(s["cup_base_y"]))

        self.grid_total_spin.setValue(float(s["grid_total_value"]))
        self.grid_step_spin.setValue(float(s["grid_step"]))

        self.wind_x_spin.setValue(int(s["wind_center_base_x"]))
        self.wind_y_spin.setValue(int(s["wind_center_base_y"]))
        self.wind_radius_spin.setValue(int(s["wind_radius"]))

        self.slope_x_spin.setValue(int(s["slope_center_base_x"]))
        self.slope_y_spin.setValue(int(s["slope_center_base_y"]))
        self.slope_half_width_spin.setValue(int(s["slope_line_half_width"]))

        self.show_cup_check.setChecked(bool(s["show_cup"]))
        self.show_grid_check.setChecked(bool(s["show_grid"]))
        self.show_wind_check.setChecked(bool(s["show_wind"]))
        self.show_slope_check.setChecked(bool(s["show_slope"]))

    def collect_settings_from_ui(self):
        settings = normalize_settings({
            "target_exe": self.target_exe_edit.text().strip() or DEFAULT_SETTINGS["target_exe"],

            "base_w": self.base_w_spin.value(),
            "base_h": self.base_h_spin.value(),

            "cup_base_x": self.cup_x_spin.value(),
            "cup_base_y": self.cup_y_spin.value(),

            "grid_total_value": self.grid_total_spin.value(),
            "grid_step": self.grid_step_spin.value(),

            "wind_center_base_x": self.wind_x_spin.value(),
            "wind_center_base_y": self.wind_y_spin.value(),
            "wind_radius": self.wind_radius_spin.value(),

            "slope_center_base_x": self.slope_x_spin.value(),
            "slope_center_base_y": self.slope_y_spin.value(),
            "slope_line_half_width": self.slope_half_width_spin.value(),

            "show_cup": self.show_cup_check.isChecked(),
            "show_grid": self.show_grid_check.isChecked(),
            "show_wind": self.show_wind_check.isChecked(),
            "show_slope": self.show_slope_check.isChecked(),

            "toggle_hotkey": self.hotkey_edit.text().strip() or DEFAULT_SETTINGS["toggle_hotkey"],
        })

        return settings

    def apply_settings(self, show_message=False):
        try:
            parse_hotkey_text(self.hotkey_edit.text())

        except Exception as e:
            QMessageBox.warning(self, "단축키 오류", str(e))
            return False

        self.settings = self.collect_settings_from_ui()
        self.overlay.set_settings(self.settings)
        self.register_hotkey_from_settings()

        if show_message:
            QMessageBox.information(self, "적용 완료", "설정이 적용되었습니다.")

        return True

    def on_start_clicked(self):
        if not self.apply_settings(show_message=False):
            return

        self.overlay.start_overlay()
        self.update_status()

    def on_stop_clicked(self):
        self.overlay.stop_overlay()
        self.update_status()

    def on_apply_clicked(self):
        if self.apply_settings(show_message=True):
            self.update_status()

    def on_save_clicked(self):
        if not self.apply_settings(show_message=False):
            return

        try:
            save_settings(self.settings)
            QMessageBox.information(self, "저장 완료", "설정이 저장되었습니다.")

        except Exception as e:
            QMessageBox.critical(self, "저장 실패", str(e))

    def on_reset_clicked(self):
        self.settings = normalize_settings({})
        self.load_settings_to_ui()
        self.apply_settings(show_message=False)
        self.update_status()

    def update_status(self):
        if self.overlay.is_running:
            self.status_label.setText("상태: 실행 중")
        else:
            self.status_label.setText("상태: 중지")

    def register_hotkey_from_settings(self):
        self.unregister_hotkey()

        hotkey_text = self.hotkey_edit.text().strip() or DEFAULT_SETTINGS["toggle_hotkey"]

        try:
            modifiers, vk = parse_hotkey_text(hotkey_text)

            # pywin32의 RegisterHotKey는 성공 시 None을 반환하고,
            # 실패 시 pywintypes.error 예외를 발생시키는 방식으로 동작한다.
            # 따라서 반환값을 if not ok 로 검사하면 성공해도 실패로 판단될 수 있다.
            win32gui.RegisterHotKey(
                int(self.winId()),
                HOTKEY_ID_TOGGLE_OVERLAY,
                modifiers,
                vk
            )

            self.hotkey_registered = True
            print(f"[INFO] 단축키 등록 완료: {hotkey_text}")

        except Exception as e:
            self.hotkey_registered = False
            print(f"[WARN] 단축키 등록 실패: {hotkey_text} / {e}")

    def unregister_hotkey(self):
        if not self.hotkey_registered:
            return

        try:
            win32gui.UnregisterHotKey(
                int(self.winId()),
                HOTKEY_ID_TOGGLE_OVERLAY
            )

        except Exception as e:
            print(f"[WARN] 단축키 해제 실패: {e}")

        self.hotkey_registered = False

    def nativeEvent(self, event_type, message):
        try:
            msg = ctypes.wintypes.MSG.from_address(int(message))

            if msg.message == win32con.WM_HOTKEY and msg.wParam == HOTKEY_ID_TOGGLE_OVERLAY:
                self.apply_settings(show_message=False)
                self.overlay.toggle_overlay()
                self.update_status()
                return True, 0

        except Exception:
            pass

        return False, 0

    def closeEvent(self, event):
        self.unregister_hotkey()
        self.overlay.stop_overlay()
        event.accept()


# =========================================================
# 실행부
# =========================================================

if __name__ == "__main__":
    app = QApplication(sys.argv)

    settings = load_settings()

    overlay = PangyaOverlay(settings)
    control_window = PangyaControlWindow(overlay, settings)
    control_window.show()

    QTimer.singleShot(300, control_window.register_hotkey_from_settings)

    sys.exit(app.exec())
