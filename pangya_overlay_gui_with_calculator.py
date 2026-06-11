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
    QTabWidget,
    QComboBox,
    QPlainTextEdit,
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPainter, QPen, QColor, QFont


try:
    from pangya_acrisio import calc_shot
except Exception as e:
    calc_shot = None
    print(f"[WARN] pangya_acrisio 모듈 로드 실패: {e}")

# try:
#     from pangya_auto_controller import PangyaAutoDetectController
# except Exception as e:
#     PangyaAutoDetectController = None
#     print(f"[WARN] pangya_auto_controller 모듈 로드 실패: {e}")
# 자동 OCR 인식 기능은 현재 보류 상태입니다.
# 빌드 용량 절감을 위해 pangya_auto_controller / pangya_vision / easyocr 계열 import를 막습니다.
PangyaAutoDetectController = None

try:
    from pangya_wind_angle_panel import PangyaWindAnglePanel
except Exception as e:
    PangyaWindAnglePanel = None
    print(f"[WARN] pangya_wind_angle_panel 모듈 로드 실패: {e}")

try:
    from pangya_bounding_panel import PangyaBoundingPanel
except Exception as e:
    PangyaBoundingPanel = None
    print(f"[WARN] pangya_bounding_panel 모듈 로드 실패: {e}")

try:
    from pangya_memory_probe import PangyaMemoryProbe, MemoryProbeError
except Exception as e:
    PangyaMemoryProbe = None
    MemoryProbeError = RuntimeError
    print(f"[WARN] pangya_memory_probe 모듈 로드 실패: {e}")
# =========================================================
# 캡처/녹화 제외 유틸
# =========================================================

WDA_NONE = 0x00000000
WDA_MONITOR = 0x00000001
WDA_EXCLUDEFROMCAPTURE = 0x00000011


def set_window_capture_excluded(hwnd, enabled=True):
    """
    Windows 캡처/녹화에서 특정 창을 제외한다.
    enabled=True  -> 캡처 제외
    enabled=False -> 원상복구
    """
    if not hwnd:
        return False

    affinity = WDA_EXCLUDEFROMCAPTURE if enabled else WDA_NONE

    try:
        result = ctypes.windll.user32.SetWindowDisplayAffinity(
            ctypes.wintypes.HWND(int(hwnd)),
            ctypes.wintypes.DWORD(affinity)
        )

        if result == 0:
            error_code = ctypes.windll.kernel32.GetLastError()
            print(f"[WARN] SetWindowDisplayAffinity 실패: hwnd={hwnd}, error={error_code}")
            return False

        print(f"[INFO] 캡처 제외 적용 완료: hwnd={hwnd}, enabled={enabled}")
        return True

    except Exception as e:
        print(f"[WARN] 캡처 제외 적용 중 예외: hwnd={hwnd}, {e}")
        return False


# =========================================================
# 기본 설정
# =========================================================

BASE_W = 2048
BASE_H = 1152

DEBUG_LOG_INTERVAL_SEC = 2.0
TRACK_INTERVAL_MS = 10
FORCED_CLIENT_LOG_DIR = r"C:\Pangya_US8JP\RELEASE SRV4\@Client EXE\logs"

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

    # 캡처/녹화 제외 옵션
    "capture_exclude_enabled": True,

    # 전역 토글 단축키
    # 예: F8, Ctrl+F8, Ctrl+Alt+F8
    "toggle_hotkey": "F8",

    # GUI 표시 배율
    "ui_scale": 1.0,
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

def safe_float(value, default=1.0):
    try:
        return float(value)
    except Exception:
        return default


def apply_gui_scale(settings):
    app = QApplication.instance()

    if app is None:
        return

    scale = safe_float(settings.get("ui_scale", 1.0), 1.0)

    if scale < 0.8:
        scale = 0.8

    if scale > 3.0:
        scale = 3.0

    # 4K 실사용 기준으로 기본값을 조금 크게 잡음
    font_size = max(10, int(round(12 * scale)))
    control_height = max(28, int(round(30 * scale)))
    tab_height = max(26, int(round(30 * scale)))
    row_height = max(26, int(round(28 * scale)))
    padding_v = max(3, int(round(4 * scale)))
    padding_h = max(6, int(round(8 * scale)))

    font = QFont("Malgun Gothic")
    font.setPointSize(font_size)

    app.setFont(font)

    app.setStyleSheet(f"""
        QWidget {{
            font-family: "Malgun Gothic";
            font-size: {font_size}pt;
        }}

        QLabel,
        QCheckBox,
        QGroupBox {{
            font-size: {font_size}pt;
        }}

        QLineEdit,
        QComboBox,
        QSpinBox,
        QDoubleSpinBox,
        QPushButton {{
            min-height: {control_height}px;
            padding: {padding_v}px {padding_h}px;
            font-size: {font_size}pt;
        }}

        QTabBar::tab {{
            min-height: {tab_height}px;
            padding: {padding_v + 1}px {padding_h + 2}px;
            font-size: {font_size}pt;
        }}

        QHeaderView::section {{
            min-height: {control_height}px;
            padding: {padding_v}px {padding_h}px;
            font-size: {font_size}pt;
        }}

        QTableWidget {{
            font-size: {font_size}pt;
        }}

        QTableWidget::item {{
            padding: {padding_v}px {padding_h}px;
        }}

        QPlainTextEdit {{
            font-size: {font_size}pt;
        }}
    """)

    # 이미 만들어진 위젯에도 강제로 폰트/크기 재적용
    for widget in app.allWidgets():
        try:
            widget.setFont(font)

            if hasattr(widget, "verticalHeader"):
                widget.verticalHeader().setDefaultSectionSize(row_height)

            if hasattr(widget, "horizontalHeader"):
                widget.horizontalHeader().setMinimumHeight(control_height)

            widget.updateGeometry()
            widget.update()

        except Exception:
            pass

    print(f"[INFO] GUI 배율 적용: scale={scale}, font_size={font_size}, control_height={control_height}, row_height={row_height}")

def save_settings(settings):
    path = get_settings_path()

    with open(path, "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False, indent=4)

    print(f"[INFO] 설정 저장 완료: {path}")


DEFAULT_CALCULATOR_SETTINGS = {
    "power": "31",
    "auxpart_pwr": "0",
    "card_pwr": "4",
    "mascot_pwr": "4",
    "card_ps_pwr": "8",
    "club": "_1W",
    "shot": "TOMAHAWK",
    "power_shot": "NO_POWER_SHOT",
    "distance": "240",
    "height": "0",
    "wind": "6",
    "degree": "30",
    "ground": "100",
    "spin": "0",
    "curve": "0",
    "slope": "0",
    "line_ball": "0",
    "line_ball_random": False,

    # ProjectG127.exe 메모리에서 남은거리/고저차 자동 입력
    "memory_auto_input": False,

    # pangya_wind_logger.dll live JSON에서 바람세기/각도 자동 입력
    "wind_live_auto_input": False,
    "wind_live_json_path": "",

    # pangya_slope_logger.dll live JSON에서 공기울기 후보 자동 입력/비교 계산
    # OFF          : 사용 안 함
    # NORMAL_X     : 후보 A = -normal.x / 0.00875
    # AXIS_Z_X     : 후보 B = -axis_z.x / 0.00875
    # BOTH_COMPARE : 후보 A/B 둘 다 계산 결과 출력
    "slope_live_auto_input": False,
    "slope_live_json_path": "",
    "slope_live_mode": "XY_COMPARE",

    "mycella_shot_degree": "0",
    "mycella_align_degree": "0",
    "mycella_slope_break": "0",

    # 표시/환산 보정값
    # Acrisio 원본 JS 기본값: 1pb = 0.2167y, 1pba = 0.8668y, 1pba+ = 1.032y
    "yards_to_pb": "0.2167",
    "yards_to_pba": "0.8668",
    "yards_to_pba_plus": "1.032",

    # 한국어 계산기/오버레이 장판 표시용.
    # 예: 기존 계산기 장판이 PB * 0.2121에 가깝다면 0.2121 사용
    "board_per_pb": "0.2121",
    "smart_divisor": "4",
}


def get_calculator_settings_path():
    return os.path.join(get_app_dir(), "pangya_calculator_settings.json")


def normalize_calculator_settings(settings):
    normalized = deepcopy(DEFAULT_CALCULATOR_SETTINGS)
    normalized.update(settings or {})
    return normalized


def load_calculator_settings():
    path = get_calculator_settings_path()

    if not os.path.exists(path):
        return normalize_calculator_settings({})

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        return normalize_calculator_settings(data)

    except Exception as e:
        print(f"[WARN] 계산기 설정 파일 로드 실패. 기본값 사용: {e}")
        return normalize_calculator_settings({})


def save_calculator_settings(settings):
    path = get_calculator_settings_path()

    with open(path, "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False, indent=4)

    print(f"[INFO] 계산기 설정 저장 완료: {path}")


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
        self.calc_state = None

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

        self.hide()
        self.overlay_hwnd = int(self.winId())

        self.apply_overlay_window_style()
        self.apply_capture_exclude_setting()

        self.timer = QTimer()
        self.timer.timeout.connect(self.update_overlay)

        self.timer = QTimer()
        self.timer.timeout.connect(self.update_overlay)

    def set_settings(self, settings):
        self.settings = normalize_settings(settings)
        self.apply_capture_exclude_setting()
        self.update()
    
    def apply_capture_exclude_setting(self):
        enabled = bool(self.settings.get("capture_exclude_enabled", True))
        set_window_capture_excluded(self.overlay_hwnd, enabled)

    def set_calc_state(self, calc_state):
        self.calc_state = calc_state
        self.update()

    def get_current_window_rect(self):
        if not self.target_hwnd:
            return None

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

            width = right - left
            height = bottom - top

            if width <= 0 or height <= 0:
                return None

            from pangya_models import GameWindowRect

            return GameWindowRect(
                left=left,
                top=top,
                right=right,
                bottom=bottom,
                width=width,
                height=height,
            )

        except Exception as e:
            print(f"[WARN] get_current_window_rect 실패: {e}")
            return None

    def draw_calc_result_panel(self, painter, scale_x, scale_y):
        if self.calc_state is None:
            return

        x = int(40 * scale_x)
        y = int(120 * scale_y)
        line_h = int(24 * scale_y)

        painter.setFont(QFont("Arial", 11))

        # 배경
        panel_w = int(360 * scale_x)
        panel_h = int(170 * scale_y)

        painter.setPen(QPen(QColor(0, 0, 0, 180), 1))
        painter.setBrush(QColor(0, 0, 0, 130))
        painter.drawRect(x - 10, y - 25, panel_w, panel_h)

        painter.setBrush(Qt.NoBrush)

        detected = self.calc_state.auto_input

        lines = [
            f"거리: {detected.distance if detected.distance is not None else '-'}y",
            f"고저: {detected.height if detected.height is not None else '-'}",
            f"바람: {detected.wind if detected.wind is not None else '-'}",
            f"각도: {detected.degree if detected.degree is not None else '-'}",
            "",
        ]

        for shot_name in ["DUNK", "TOMAHAWK", "SPIKE", "COBRA"]:
            result = self.calc_state.shot_results.get(shot_name)

            if result is None:
                continue

            if result.ok:
                lines.append(
                    f"{shot_name}: {result.power_percent:.1f}% / {result.shot_yards:.1f}y / {result.board_cells:.3f}칸"
                )
            else:
                lines.append(f"{shot_name}: 실패 - {result.message}")

        for idx, text in enumerate(lines):
            ty = y + idx * line_h

            painter.setPen(QPen(QColor(0, 0, 0, 230), 1))
            painter.drawText(x + 1, ty + 1, text)

            painter.setPen(QPen(QColor(255, 255, 255, 240), 1))
            painter.drawText(x, ty, text)

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
            self.apply_capture_exclude_setting()

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
        print(
            f"WIND              : x={self.settings['wind_center_base_x']}, "
            f"y={self.settings['wind_center_base_y']}, "
            f"radius={self.settings['wind_radius']}")
        print("==========================================")

    def draw_wind_angle_area(self, painter, scale_x, scale_y):
        """
        우하단 바람 UI 위에 5도 간격 각도 눈금을 그린다.
        원을 4분할해서 각 사분면마다 0~90으로 표시한다.
        숫자는 원 바깥쪽에 표시해서 화살표 끝을 가리지 않게 한다.
        """
        center_x = int(self.settings["wind_center_base_x"] * scale_x)
        center_y = int(self.settings["wind_center_base_y"] * scale_y)

        scale = min(scale_x, scale_y)
        radius = int(self.settings["wind_radius"] * scale)

        # print(
        #     f"[INFO] WIND_DRAW center=({center_x},{center_y}), "
        #     f"base_radius={self.settings['wind_radius']}, "
        #     f"scale_x={scale_x:.4f}, scale_y={scale_y:.4f}, "
        #     f"scale={scale:.4f}, draw_radius={radius}"
        # )

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
                    text_radius = radius + int(WIND_TEXT_RADIUS_OFFSET * scale)

                    # 접선 방향 벡터
                    tangent_x = -math.sin(rad)
                    tangent_y = math.cos(rad)

                    # 0과 90은 같은 축에 몰리므로 접선 방향으로 살짝 벌려줌
                    tangent_offset = 0
                    if local_deg == 0:
                        tangent_offset = -int(WIND_TEXT_TANGENT_OFFSET * scale)
                    elif local_deg == 90:
                        tangent_offset = int(WIND_TEXT_TANGENT_OFFSET * scale)

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

        self.draw_calc_result_panel(painter, scale_x, scale_y)

# =========================================================
# 설정 GUI 클래스
# =========================================================

class PangyaControlWindow(QWidget):
    def __init__(self, overlay, settings):
        super().__init__()

        self.overlay = overlay
        self.settings = normalize_settings(settings)
        self.hotkey_registered = False

        self.last_calc_result = None
        self.last_calc_display = None
        self.last_calc_shot_type = None

        self.setWindowTitle("Pangya Assist Overlay 설정")
        self.setWindowTitle("Pangya Assist Overlay 설정")
        self.setMinimumWidth(900)
        self.setMinimumHeight(700)

        self.build_ui()
        self.bind_events()
        self.load_settings_to_ui()

        set_window_capture_excluded

        self.auto_controller = None

        self.memory_probe = None
        self.memory_timer = QTimer(self)
        self.memory_timer.timeout.connect(self.update_memory_values_from_game)
        self.last_memory_distance = None
        self.last_memory_height = None

        self.wind_live_timer = QTimer(self)
        self.wind_live_timer.timeout.connect(self.update_wind_live_from_file)
        self.last_wind_live_tick = None
        self.last_wind_live_value = None
        self.last_wind_live_path = None

        self.slope_live_timer = QTimer(self)
        self.slope_live_timer.timeout.connect(self.update_slope_live_from_file)
        self.last_slope_live_tick = None
        self.last_slope_live_path = None
        self.last_slope_live_candidates = None

        # live JSON은 오버레이 Start/Stop이나 메모리 연결 상태와 독립적으로 감시한다.
        # 기존 버전은 메모리 중지/Start 순서에 따라 wind/slope timer가 꺼진 채 남는 문제가 있었다.
        self.live_watchdog_timer = QTimer(self)
        self.live_watchdog_timer.timeout.connect(self.ensure_live_timers)
        self.live_watchdog_timer.start(1000)
        QTimer.singleShot(0, self.ensure_live_timers)

        # 숫자 OCR 자동 인식은 현재 보류.
        # 바람각도는 별도 캡처/클릭 방식으로 처리한다.
        # if PangyaAutoDetectController is not None:
        #     self.auto_controller = PangyaAutoDetectController(
        #         overlay=self.overlay,
        #         get_window_rect_func=self.overlay.get_current_window_rect,
        #         parent=self,
        #     )

        #self.register_hotkey_from_settings()

    def apply_control_window_capture_exclude(self):
        enabled = bool(self.settings.get("capture_exclude_enabled", True))
        set_window_capture_excluded(int(self.winId()), enabled)

    def build_ui(self):
        root = QVBoxLayout(self)

        self.tabs = QTabWidget()
        root.addWidget(self.tabs)

        self.overlay_tab = QWidget()
        self.calc_tab = QWidget()
        self.wind_angle_tab = QWidget()
        self.bounding_tab = QWidget()

        self.tabs.addTab(self.overlay_tab, "오버레이")
        self.tabs.addTab(self.calc_tab, "계산기")
        self.tabs.addTab(self.wind_angle_tab, "바람각도")
        self.tabs.addTab(self.bounding_tab, "바운딩")

        overlay_root = QVBoxLayout(self.overlay_tab)
        calc_root = QVBoxLayout(self.calc_tab)
        wind_angle_root = QVBoxLayout(self.wind_angle_tab)
        bounding_root = QVBoxLayout(self.bounding_tab)

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

        overlay_root.addWidget(status_group)

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

        # GUI 배율
        self.ui_scale_spin = QDoubleSpinBox()
        self.ui_scale_spin.setRange(0.8, 3.0)
        self.ui_scale_spin.setSingleStep(0.05)
        self.ui_scale_spin.setDecimals(2)
        self.ui_scale_spin.setValue(float(self.settings.get("ui_scale", 1.0)))

        basic_layout.addWidget(QLabel("GUI 배율"), 3, 0)
        basic_layout.addWidget(self.ui_scale_spin, 3, 1)

        overlay_root.addWidget(basic_group)

        coord_group = QGroupBox("좌표 / 크기")
        coord_layout = QGridLayout(coord_group)

        self.base_w_spin = self.create_int_spin(100, 10000)
        self.base_h_spin = self.create_int_spin(100, 10000)

        self.cup_x_spin = self.create_int_spin()
        self.cup_y_spin = self.create_int_spin()

        self.grid_total_spin = self.create_double_spin(0.1, 50.0, 0.1, 2)
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

        overlay_root.addWidget(coord_group)

        visible_group = QGroupBox("표시 항목")
        visible_layout = QHBoxLayout(visible_group)

        self.show_cup_check = QCheckBox("컵 중심")
        self.show_grid_check = QCheckBox("눈금")
        self.show_wind_check = QCheckBox("바람 각도")
        self.show_slope_check = QCheckBox("기울기 선")
        self.capture_exclude_check = QCheckBox("윈도우 캡처/녹화 제외")

        visible_layout.addWidget(self.show_cup_check)
        visible_layout.addWidget(self.show_grid_check)
        visible_layout.addWidget(self.show_wind_check)
        visible_layout.addWidget(self.show_slope_check)
        visible_layout.addWidget(self.capture_exclude_check)

        overlay_root.addWidget(visible_group)

        help_label = QLabel(
            "Base W/H는 좌표값을 해석하는 기준 해상도입니다. 좌표값은 현재 설정한 Base 해상도 기준이며, 저장하면 다음 실행부터 pangya_overlay_settings.json 값을 사용합니다."
        )
        help_label.setWordWrap(True)
        overlay_root.addWidget(help_label)
        overlay_root.addStretch(1)

        self.build_calculator_tab(calc_root)
        self.build_wind_angle_tab(wind_angle_root)
        self.build_bounding_tab(bounding_root)

    def build_calculator_tab(self, root):
        if calc_shot is None:
            warn = QLabel("pangya_acrisio.py를 찾을 수 없습니다. pangya_overlay_gui_with_calculator.py와 같은 폴더에 pangya_acrisio.py를 두세요.")
            warn.setWordWrap(True)
            root.addWidget(warn)
            return

        desc = QLabel("Acrisio smart_calculator.js 입력 항목을 PySide6 GUI로 옮긴 계산기 탭입니다. 값 입력 후 계산 버튼을 누르세요.")
        desc.setWordWrap(True)
        root.addWidget(desc)

        char_group = QGroupBox("캐릭터 / 파워 설정")
        char_layout = QGridLayout(char_group)

        self.calc_power_edit = self.create_calc_line("31")
        self.calc_auxpart_edit = self.create_calc_line("0")
        self.calc_card_edit = self.create_calc_line("4")
        self.calc_mascot_edit = self.create_calc_line("4")
        self.calc_card_ps_edit = self.create_calc_line("8")

        char_layout.addWidget(QLabel("Power"), 0, 0)
        char_layout.addWidget(self.calc_power_edit, 0, 1)
        char_layout.addWidget(QLabel("Ring Power"), 0, 2)
        char_layout.addWidget(self.calc_auxpart_edit, 0, 3)
        char_layout.addWidget(QLabel("Card Power"), 1, 0)
        char_layout.addWidget(self.calc_card_edit, 1, 1)
        char_layout.addWidget(QLabel("Mascot Power"), 1, 2)
        char_layout.addWidget(self.calc_mascot_edit, 1, 3)
        char_layout.addWidget(QLabel("Card Power Shot Power"), 2, 0)
        char_layout.addWidget(self.calc_card_ps_edit, 2, 1)

        root.addWidget(char_group)

        shot_group = QGroupBox("샷 조건")
        shot_layout = QGridLayout(shot_group)

        self.calc_club_combo = QComboBox()
        for text, value in [
            ("1W", "_1W"), ("2W", "_2W"), ("3W", "_3W"),
            ("2I", "_2I"), ("3I", "_3I"), ("4I", "_4I"), ("5I", "_5I"),
            ("6I", "_6I"), ("7I", "_7I"), ("8I", "_8I"), ("9I", "_9I"),
            ("PW", "PW"), ("SW", "SW"),
        ]:
            self.calc_club_combo.addItem(text, value)

        self.calc_shot_combo = QComboBox()
        for text, value in [("Dunk", "DUNK"), ("Tomahawk", "TOMAHAWK"), ("Spike", "SPIKE"), ("Cobra", "COBRA")]:
            self.calc_shot_combo.addItem(text, value)
        self.calc_shot_combo.setCurrentIndex(1)

        self.calc_power_shot_combo = QComboBox()
        for text, value in [
            ("No Power Shot", "NO_POWER_SHOT"),
            ("1 Power Shot", "ONE_POWER_SHOT"),
            ("2 Power Shot", "TWO_POWER_SHOT"),
            ("15y Power Shot", "ITEM_15_POWER_SHOT"),
        ]:
            self.calc_power_shot_combo.addItem(text, value)

        self.calc_distance_edit = self.create_calc_line("240")
        self.calc_height_edit = self.create_calc_line("0")
        self.calc_wind_edit = self.create_calc_line("6")
        self.calc_degree_edit = self.create_calc_line("30")
        self.calc_ground_edit = self.create_calc_line("100")
        self.calc_spin_edit = self.create_calc_line("0")
        self.calc_curve_edit = self.create_calc_line("0")
        self.calc_slope_edit = self.create_calc_line("0")
        self.calc_line_ball_edit = self.create_calc_line("0")
        self.calc_line_ball_random_check = QCheckBox("line_ball 랜덤 사용")

        row = 0
        shot_layout.addWidget(QLabel("Club"), row, 0)
        shot_layout.addWidget(self.calc_club_combo, row, 1)
        shot_layout.addWidget(QLabel("Shot"), row, 2)
        shot_layout.addWidget(self.calc_shot_combo, row, 3)
        shot_layout.addWidget(QLabel("Power Shot"), row, 4)
        shot_layout.addWidget(self.calc_power_shot_combo, row, 5)

        row += 1
        shot_layout.addWidget(QLabel("Distance"), row, 0)
        shot_layout.addWidget(self.calc_distance_edit, row, 1)
        shot_layout.addWidget(QLabel("Height"), row, 2)
        shot_layout.addWidget(self.calc_height_edit, row, 3)
        shot_layout.addWidget(QLabel("Ground"), row, 4)
        shot_layout.addWidget(self.calc_ground_edit, row, 5)

        row += 1
        shot_layout.addWidget(QLabel("Wind"), row, 0)
        shot_layout.addWidget(self.calc_wind_edit, row, 1)
        shot_layout.addWidget(QLabel("Degree"), row, 2)
        shot_layout.addWidget(self.calc_degree_edit, row, 3)
        shot_layout.addWidget(QLabel("Slope break"), row, 4)
        shot_layout.addWidget(self.calc_slope_edit, row, 5)

        row += 1
        shot_layout.addWidget(QLabel("Spin"), row, 0)
        shot_layout.addWidget(self.calc_spin_edit, row, 1)
        shot_layout.addWidget(QLabel("Curve"), row, 2)
        shot_layout.addWidget(self.calc_curve_edit, row, 3)
        shot_layout.addWidget(QLabel("Line ball"), row, 4)
        shot_layout.addWidget(self.calc_line_ball_edit, row, 5)

        row += 1
        shot_layout.addWidget(QLabel(""), row, 0)
        shot_layout.addWidget(self.calc_line_ball_random_check, row, 1, 1, 2)

        root.addWidget(shot_group)

        memory_group = QGroupBox("메모리 자동 입력")
        memory_layout = QGridLayout(memory_group)

        self.memory_auto_check = QCheckBox("거리/고저차 자동 입력")
        self.wind_live_auto_check = QCheckBox("바람/각도 자동 입력(DLL live)")
        self.slope_live_auto_check = QCheckBox("기울기 후보 자동 계산(DLL live)")
        self.slope_live_mode_combo = QComboBox()
        self.slope_live_mode_combo.addItem("Slope X/Y 6개 비교: X/Y/MAG +/-", "XY_COMPARE")
        self.slope_live_mode_combo.addItem("Result Matrix 8개 비교: R0C/R04/R14/R1C +/-", "MATRIX_COMPARE")
        self.slope_live_mode_combo.addItem("추천 후보: -R0C / 0.00875", "R0C_MINUS")
        self.slope_live_mode_combo.addItem("후보 R1C+ = R1C / 0.00875", "R1C_PLUS")
        self.slope_live_mode_combo.addItem("후보 R14- = -R14 / 0.00875", "R14_MINUS")
        self.slope_live_mode_combo.addItem("후보 R04- = -R04 / 0.00875", "R04_MINUS")
        self.slope_live_mode_combo.addItem("후보 R0C+ = R0C / 0.00875", "R0C_PLUS")
        self.slope_live_mode_combo.addItem("후보 R04+ = R04 / 0.00875", "R04_PLUS")
        self.slope_live_mode_combo.addItem("후보 R14+ = R14 / 0.00875", "R14_PLUS")
        self.slope_live_mode_combo.addItem("후보 R1C- = -R1C / 0.00875", "R1C_MINUS")
        self.slope_live_mode_combo.addItem("추천 후보: -MAG / 0.00875", "MAG_MINUS")
        self.slope_live_mode_combo.addItem("추천 후보: +MAG / 0.00875", "MAG_PLUS")
        self.slope_live_mode_combo.addItem("후보 X+ = X / 0.00875", "X_PLUS")
        self.slope_live_mode_combo.addItem("후보 X- = -X / 0.00875", "X_MINUS")
        self.slope_live_mode_combo.addItem("후보 Y+ = Y / 0.00875", "Y_PLUS")
        self.slope_live_mode_combo.addItem("후보 Y- = -Y / 0.00875", "Y_MINUS")
        self.slope_live_mode_combo.addItem("구버전 4개 비교: scalar70/78 +/-", "SIGN_COMPARE")
        self.slope_live_mode_combo.addItem("구버전 A/B 둘 다 계산", "SCALAR_COMPARE")
        self.slope_live_mode_combo.addItem("자동 입력 안 함", "OFF")
        self.memory_connect_btn = QPushButton("메모리 연결")
        self.memory_disconnect_btn = QPushButton("메모리 중지")
        self.memory_status_label = QLabel("상태: 연결 안 됨")
        self.memory_distance_label = QLabel("거리: -")
        self.memory_height_label = QLabel("고저: -")
        self.wind_live_label = QLabel("바람/signed각도: -")
        self.slope_live_label = QLabel("기울기 후보: -")
        self.wind_live_path_edit = QLineEdit()
        self.wind_live_path_edit.setPlaceholderText("비워두면 ProjectG127.exe 폴더의 logs\\pangya_wind_live.json 자동 탐색")
        self.slope_live_path_edit = QLineEdit()
        self.slope_live_path_edit.setPlaceholderText("비워두면 ProjectG127.exe 폴더의 logs\\pangya_slope_live.json 자동 탐색")

        self.memory_disconnect_btn.setEnabled(False)

        memory_layout.addWidget(self.memory_auto_check, 0, 0)
        memory_layout.addWidget(self.wind_live_auto_check, 0, 1)
        memory_layout.addWidget(self.slope_live_auto_check, 0, 2)
        memory_layout.addWidget(self.memory_connect_btn, 0, 3)
        memory_layout.addWidget(self.memory_disconnect_btn, 0, 4)
        memory_layout.addWidget(self.memory_status_label, 0, 5)
        memory_layout.addWidget(self.memory_distance_label, 1, 0, 1, 2)
        memory_layout.addWidget(self.memory_height_label, 1, 2, 1, 2)
        memory_layout.addWidget(self.wind_live_label, 1, 4, 1, 2)
        memory_layout.addWidget(self.slope_live_label, 2, 0, 1, 3)
        memory_layout.addWidget(QLabel("기울기 모드"), 2, 3)
        memory_layout.addWidget(self.slope_live_mode_combo, 2, 4, 1, 2)
        memory_layout.addWidget(QLabel("바람 live JSON"), 3, 0)
        memory_layout.addWidget(self.wind_live_path_edit, 3, 1, 1, 5)
        memory_layout.addWidget(QLabel("기울기 live JSON"), 4, 0)
        memory_layout.addWidget(self.slope_live_path_edit, 4, 1, 1, 5)

        memory_help = QLabel(
            "거리/고저차는 기존 ProjectG127.exe 메모리 hook으로 읽고, "
            "바람은 pangya_wind_logger.dll live JSON의 wind를 읽고, 각도는 signed_degree를 읽어 Degree에 반영합니다. "
            "기울기는 pangya_slope_logger.dll live JSON의 후보 A/B를 읽어 계산 결과를 비교 출력합니다. "
            "관리자 권한으로 실행해야 하며, Cheat Engine 디버거 창은 닫고 사용하세요."
        )
        memory_help.setWordWrap(True)
        memory_layout.addWidget(memory_help, 5, 0, 1, 6)

        root.addWidget(memory_group)

        mycella_group = QGroupBox("Mycella 기울기 보조")
        mycella_layout = QGridLayout(mycella_group)

        self.mycella_shot_degree_edit = self.create_calc_line("0")
        self.mycella_align_degree_edit = self.create_calc_line("0")
        self.mycella_slope_break_edit = self.create_calc_line("0")
        self.mycella_btn = QPushButton("Slope break 계산 후 입력칸에 반영")

        mycella_layout.addWidget(QLabel("Shot degree"), 0, 0)
        mycella_layout.addWidget(self.mycella_shot_degree_edit, 0, 1)
        mycella_layout.addWidget(QLabel("Align degree"), 0, 2)
        mycella_layout.addWidget(self.mycella_align_degree_edit, 0, 3)
        mycella_layout.addWidget(QLabel("Slope break"), 1, 0)
        mycella_layout.addWidget(self.mycella_slope_break_edit, 1, 1)
        mycella_layout.addWidget(self.mycella_btn, 1, 2, 1, 2)

        root.addWidget(mycella_group)

        convert_group = QGroupBox("표시 단위 / 장판 보정")
        convert_layout = QGridLayout(convert_group)

        self.calc_yards_to_pb_edit = self.create_calc_line("0.2167")
        self.calc_yards_to_pba_edit = self.create_calc_line("0.8668")
        self.calc_yards_to_pba_plus_edit = self.create_calc_line("1.032")
        self.calc_board_per_pb_edit = self.create_calc_line("0.2121")
        self.calc_smart_divisor_edit = self.create_calc_line("4")

        convert_layout.addWidget(QLabel("YARDS_TO_PB"), 0, 0)
        convert_layout.addWidget(self.calc_yards_to_pb_edit, 0, 1)
        convert_layout.addWidget(QLabel("YARDS_TO_PBA"), 0, 2)
        convert_layout.addWidget(self.calc_yards_to_pba_edit, 0, 3)
        convert_layout.addWidget(QLabel("YARDS_TO_PBA+"), 0, 4)
        convert_layout.addWidget(self.calc_yards_to_pba_plus_edit, 0, 5)

        convert_layout.addWidget(QLabel("장판 환산값(PB당)"), 1, 0)
        convert_layout.addWidget(self.calc_board_per_pb_edit, 1, 1)
        convert_layout.addWidget(QLabel("스마트 나눗값"), 1, 2)
        convert_layout.addWidget(self.calc_smart_divisor_edit, 1, 3)

        convert_help = QLabel("Acrisio 기본 PB 환산은 0.2167입니다. 기존 한국어 계산기 장판값에 맞추려면 '장판 환산값(PB당)'을 조정하세요. 예: 8.41pb에서 장판 1.784를 맞추려면 1.784 / 8.41 = 0.2121")
        convert_help.setWordWrap(True)
        convert_layout.addWidget(convert_help, 2, 0, 1, 6)

        root.addWidget(convert_group)

        button_layout = QHBoxLayout()
        self.calc_btn = QPushButton("계산")
        self.backspin_btn = QPushButton("BackSpin")
        self.calc_reset_btn = QPushButton("예시값")
        self.calc_save_btn = QPushButton("입력 저장")
        self.calc_load_btn = QPushButton("입력 불러오기")

        self.backspin_btn.setVisible(False)
        self.backspin_btn.setEnabled(False)

        button_layout.addWidget(self.calc_btn)
        button_layout.addWidget(self.backspin_btn)
        button_layout.addWidget(self.calc_reset_btn)
        button_layout.addWidget(self.calc_save_btn)
        button_layout.addWidget(self.calc_load_btn)
        button_layout.addStretch(1)
        root.addLayout(button_layout)

        self.calc_result_box = QPlainTextEdit()
        self.calc_result_box.setReadOnly(True)
        self.calc_result_box.setMinimumHeight(170)
        root.addWidget(self.calc_result_box)

        hint = QLabel("원본 JS는 기본적으로 YARDS_TO_PB=0.2167, YARDS_TO_PBA=0.8668, YARDS_TO_PBA_PLUS=1.032를 사용합니다. 아래 표시 단위 입력값은 계산 물리 자체가 아니라 결과 표시/장판 환산값을 보정하는 용도입니다.")
        hint.setWordWrap(True)
        root.addWidget(hint)
        root.addStretch(1)

        self.load_calculator_settings_to_ui(load_calculator_settings())

    def build_wind_angle_tab(self, root):
        if PangyaWindAnglePanel is None:
            warn = QLabel("pangya_wind_angle_panel.py를 불러오지 못했습니다.")
            warn.setWordWrap(True)
            root.addWidget(warn)
            return

        self.wind_angle_panel = PangyaWindAnglePanel(
            get_window_rect_func=self.overlay.get_current_window_rect,
            get_overlay_settings_func=self.collect_settings_from_ui,
            on_apply_degree=self.apply_wind_degree_to_calculator,
            parent=self,
        )

        root.addWidget(self.wind_angle_panel)

    def build_bounding_tab(self, root):
        if PangyaBoundingPanel is None:
            warn = QLabel("pangya_bounding_panel.py를 불러오지 못했습니다.")
            warn.setWordWrap(True)
            root.addWidget(warn)
            return

        self.bounding_panel = PangyaBoundingPanel(parent=self)
        root.addWidget(self.bounding_panel)
        
    def apply_wind_degree_to_calculator(self, degree):
        if not hasattr(self, "calc_degree_edit"):
            return

        self.calc_degree_edit.setText(f"{degree:.2f}")

        # 계산기 탭으로 이동
        if hasattr(self, "tabs"):
            for i in range(self.tabs.count()):
                if self.tabs.tabText(i) == "계산기":
                    self.tabs.setCurrentIndex(i)
                    break

        # Degree 입력칸으로 포커스 이동 + 값 전체 선택
        self.calc_degree_edit.setFocus(Qt.OtherFocusReason)
        self.calc_degree_edit.selectAll()

    def create_calc_line(self, default_text=""):
        edit = QLineEdit()
        edit.setText(str(default_text))
        return edit

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

        if hasattr(self, "calc_btn"):
            self.calc_btn.clicked.connect(self.on_calc_clicked)
            self.backspin_btn.clicked.connect(self.on_backspin_clicked)
            self.calc_reset_btn.clicked.connect(self.on_calc_reset_clicked)
            self.calc_save_btn.clicked.connect(self.on_calc_save_clicked)
            self.calc_load_btn.clicked.connect(self.on_calc_load_clicked)
            self.mycella_btn.clicked.connect(self.on_mycella_clicked)
            self.calc_shot_combo.currentIndexChanged.connect(self.on_calc_shot_changed)

        if hasattr(self, "memory_connect_btn"):
            self.memory_connect_btn.clicked.connect(self.start_memory_probe)
            self.memory_disconnect_btn.clicked.connect(self.stop_memory_probe)

        if hasattr(self, "wind_live_auto_check"):
            self.wind_live_auto_check.stateChanged.connect(self.on_wind_live_auto_changed)

        if hasattr(self, "slope_live_auto_check"):
            self.slope_live_auto_check.stateChanged.connect(self.on_slope_live_auto_changed)
        if hasattr(self, "slope_live_mode_combo"):
            self.slope_live_mode_combo.currentIndexChanged.connect(self.on_slope_live_mode_changed)


    def set_combo_by_data(self, combo, value):
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    def collect_calculator_settings_from_ui(self):
        return normalize_calculator_settings({
            "power": self.calc_power_edit.text().strip(),
            "auxpart_pwr": self.calc_auxpart_edit.text().strip(),
            "card_pwr": self.calc_card_edit.text().strip(),
            "mascot_pwr": self.calc_mascot_edit.text().strip(),
            "card_ps_pwr": self.calc_card_ps_edit.text().strip(),
            "club": self.calc_club_combo.currentData(),
            "shot": self.calc_shot_combo.currentData(),
            "power_shot": self.calc_power_shot_combo.currentData(),
            "distance": self.calc_distance_edit.text().strip(),
            "height": self.calc_height_edit.text().strip(),
            "wind": self.calc_wind_edit.text().strip(),
            "degree": self.calc_degree_edit.text().strip(),
            "ground": self.calc_ground_edit.text().strip(),
            "spin": self.calc_spin_edit.text().strip(),
            "curve": self.calc_curve_edit.text().strip(),
            "slope": self.calc_slope_edit.text().strip(),
            "line_ball": self.calc_line_ball_edit.text().strip(),
            "line_ball_random": self.calc_line_ball_random_check.isChecked(),
            "memory_auto_input": self.memory_auto_check.isChecked() if hasattr(self, "memory_auto_check") else False,
            "wind_live_auto_input": self.wind_live_auto_check.isChecked() if hasattr(self, "wind_live_auto_check") else False,
            "wind_live_json_path": self.wind_live_path_edit.text().strip() if hasattr(self, "wind_live_path_edit") else "",
            "slope_live_auto_input": self.slope_live_auto_check.isChecked() if hasattr(self, "slope_live_auto_check") else False,
            "slope_live_json_path": self.slope_live_path_edit.text().strip() if hasattr(self, "slope_live_path_edit") else "",
            "slope_live_mode": self.slope_live_mode_combo.currentData() if hasattr(self, "slope_live_mode_combo") else "XY_COMPARE",
            "mycella_shot_degree": self.mycella_shot_degree_edit.text().strip(),
            "mycella_align_degree": self.mycella_align_degree_edit.text().strip(),
            "mycella_slope_break": self.mycella_slope_break_edit.text().strip(),
            "yards_to_pb": self.calc_yards_to_pb_edit.text().strip(),
            "yards_to_pba": self.calc_yards_to_pba_edit.text().strip(),
            "yards_to_pba_plus": self.calc_yards_to_pba_plus_edit.text().strip(),
            "board_per_pb": self.calc_board_per_pb_edit.text().strip(),
            "smart_divisor": self.calc_smart_divisor_edit.text().strip(),
        })

    def load_calculator_settings_to_ui(self, settings):
        s = normalize_calculator_settings(settings)

        self.calc_power_edit.setText(str(s["power"]))
        self.calc_auxpart_edit.setText(str(s["auxpart_pwr"]))
        self.calc_card_edit.setText(str(s["card_pwr"]))
        self.calc_mascot_edit.setText(str(s["mascot_pwr"]))
        self.calc_card_ps_edit.setText(str(s["card_ps_pwr"]))

        self.set_combo_by_data(self.calc_club_combo, s["club"])
        self.set_combo_by_data(self.calc_shot_combo, s["shot"])
        self.set_combo_by_data(self.calc_power_shot_combo, s["power_shot"])

        self.calc_distance_edit.setText(str(s["distance"]))
        self.calc_height_edit.setText(str(s["height"]))
        self.calc_wind_edit.setText(str(s["wind"]))
        self.calc_degree_edit.setText(str(s["degree"]))
        self.calc_ground_edit.setText(str(s["ground"]))
        self.calc_spin_edit.setText(str(s["spin"]))
        self.calc_curve_edit.setText(str(s["curve"]))
        self.calc_slope_edit.setText(str(s["slope"]))
        self.calc_line_ball_edit.setText(str(s["line_ball"]))
        self.calc_line_ball_random_check.setChecked(bool(s["line_ball_random"]))
        if hasattr(self, "memory_auto_check"):
            self.memory_auto_check.setChecked(bool(s.get("memory_auto_input", False)))
        if hasattr(self, "wind_live_auto_check"):
            self.wind_live_auto_check.setChecked(bool(s.get("wind_live_auto_input", False)))
        if hasattr(self, "wind_live_path_edit"):
            self.wind_live_path_edit.setText(str(s.get("wind_live_json_path", "")))
        if hasattr(self, "slope_live_auto_check"):
            self.slope_live_auto_check.setChecked(bool(s.get("slope_live_auto_input", False)))
        if hasattr(self, "slope_live_path_edit"):
            self.slope_live_path_edit.setText(str(s.get("slope_live_json_path", "")))
        if hasattr(self, "slope_live_mode_combo"):
            
            mode = s.get("slope_live_mode", "XY_COMPARE")
            legacy_map = {
                "BOTH_COMPARE": "SCALAR_COMPARE",
                "NORMAL_X": "SCALAR70_PLUS",
                "AXIS_Z_X": "SCALAR78_PLUS",
                "SCALAR70": "SCALAR70_PLUS",
                "SCALAR78": "SCALAR78_PLUS",
                "SIGN_COMPARE": "XY_COMPARE",
            }
            mode = legacy_map.get(mode, mode)
            self.set_combo_by_data(self.slope_live_mode_combo, mode)

        self.mycella_shot_degree_edit.setText(str(s["mycella_shot_degree"]))
        self.mycella_align_degree_edit.setText(str(s["mycella_align_degree"]))
        self.mycella_slope_break_edit.setText(str(s["mycella_slope_break"]))

        self.calc_yards_to_pb_edit.setText(str(s["yards_to_pb"]))
        self.calc_yards_to_pba_edit.setText(str(s["yards_to_pba"]))
        self.calc_yards_to_pba_plus_edit.setText(str(s["yards_to_pba_plus"]))
        self.calc_board_per_pb_edit.setText(str(s["board_per_pb"]))
        self.calc_smart_divisor_edit.setText(str(s["smart_divisor"]))

    def on_calc_save_clicked(self):
        try:
            save_calculator_settings(self.collect_calculator_settings_from_ui())
            QMessageBox.information(self, "계산기 입력 저장", "계산기 입력값이 저장되었습니다.")
        except Exception as e:
            QMessageBox.critical(self, "계산기 입력 저장 실패", str(e))

    def on_calc_load_clicked(self):
        try:
            self.load_calculator_settings_to_ui(load_calculator_settings())
            QMessageBox.information(self, "계산기 입력 불러오기", "저장된 계산기 입력값을 불러왔습니다.")
        except Exception as e:
            QMessageBox.critical(self, "계산기 입력 불러오기 실패", str(e))

    def set_memory_status(self, text):
        if hasattr(self, "memory_status_label"):
            self.memory_status_label.setText(text)

    def start_memory_probe(self):
        if PangyaMemoryProbe is None:
            QMessageBox.warning(
                self,
                "메모리 자동 입력 오류",
                "pangya_memory_probe.py를 불러오지 못했습니다. 같은 폴더에 파일이 있는지 확인하세요."
            )
            return

        if self.memory_probe is not None:
            self.set_memory_status("상태: 이미 연결됨")
            return

        try:
            probe = PangyaMemoryProbe(self.target_exe_edit.text().strip() or "ProjectG127.exe")
            probe.attach()
            probe.install_height_hook()
            probe.install_distance_final_hook()

            self.memory_probe = probe
            self.memory_timer.start(250)

            self.memory_connect_btn.setEnabled(False)
            self.memory_disconnect_btn.setEnabled(True)
            self.set_memory_status("상태: 연결됨 - 거리/고저차 대기 중")
            print(f"[INFO] 메모리 자동 입력 연결 완료: {probe.debug_info()}")

        except Exception as e:
            try:
                probe.close()
            except Exception:
                pass

            self.memory_probe = None
            self.memory_timer.stop()
            self.memory_connect_btn.setEnabled(True)
            self.memory_disconnect_btn.setEnabled(False)
            self.set_memory_status("상태: 연결 실패")
            QMessageBox.critical(
                self,
                "메모리 자동 입력 연결 실패",
                f"{e}\n\n관리자 권한으로 실행했는지, Cheat Engine 디버거 창이 닫혀 있는지 확인하세요."
            )


    def read_json_file_retry(self, path, retries=3, delay_ms=25):
        """DLL이 JSON을 쓰는 순간 GUI가 읽으면 반쪽 파일이 될 수 있어서 짧게 재시도한다."""
        last_error = None
        for _ in range(max(1, retries)):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                last_error = e
                try:
                    QApplication.processEvents()
                except Exception:
                    pass
                time.sleep(delay_ms / 1000.0)
        raise last_error

    def find_existing_live_json_path(self, filename):
        """수동 경로가 비어 있을 때 확인할 후보 경로들을 순서대로 검사한다."""
        paths = []

        target_exe = self.target_exe_edit.text().strip() if hasattr(self, "target_exe_edit") else "ProjectG127.exe"
        exe_path = self.find_process_exe_path(target_exe or "ProjectG127.exe")
        if exe_path:
            paths.append(os.path.join(os.path.dirname(exe_path), "logs", filename))

        paths.append(os.path.join(FORCED_CLIENT_LOG_DIR, filename))
        paths.append(os.path.join(get_app_dir(), "logs", filename))

        # 중복 제거, 존재하는 파일 우선
        unique = []
        for path in paths:
            if path and path not in unique:
                unique.append(path)

        for path in unique:
            if os.path.exists(path):
                return path

        return unique[0] if unique else os.path.join(get_app_dir(), "logs", filename)

    def ensure_live_timers(self):
        """체크박스가 ON이면 Start 버튼을 누르지 않아도 live JSON 감시를 유지한다."""
        try:
            if hasattr(self, "wind_live_auto_check") and self.wind_live_auto_check.isChecked():
                if not self.wind_live_timer.isActive():
                    self.wind_live_timer.start(250)
                self.update_wind_live_from_file()
            elif hasattr(self, "wind_live_timer") and self.wind_live_timer.isActive():
                self.wind_live_timer.stop()

            if hasattr(self, "slope_live_auto_check") and self.slope_live_auto_check.isChecked():
                if not self.slope_live_timer.isActive():
                    self.slope_live_timer.start(250)
                self.update_slope_live_from_file()
            elif hasattr(self, "slope_live_timer") and self.slope_live_timer.isActive():
                self.slope_live_timer.stop()
        except Exception as e:
            print(f"[WARN] live timer watchdog 실패: {e}")


    def on_wind_live_auto_changed(self):
        self.ensure_live_timers()
        if hasattr(self, "wind_live_auto_check") and not self.wind_live_auto_check.isChecked():
            if hasattr(self, "wind_live_label"):
                self.wind_live_label.setText("바람/signed각도: -")

    def find_process_exe_path(self, process_name):
        try:
            target = (process_name or "ProjectG127.exe").lower()
            for proc in psutil.process_iter(["name", "exe"]):
                try:
                    if (proc.info.get("name") or "").lower() == target:
                        exe = proc.info.get("exe")
                        if exe:
                            return exe
                except Exception:
                    continue
        except Exception:
            pass
        return None

    def resolve_wind_live_json_path(self):
        # 1) 사용자가 직접 지정한 경로
        manual = ""
        if hasattr(self, "wind_live_path_edit"):
            manual = self.wind_live_path_edit.text().strip().strip('"')

        if manual:
            return manual

        # 2) 실행 중인 ProjectG127.exe 폴더의 logs\\pangya_wind_live.json
        target_exe = self.target_exe_edit.text().strip() if hasattr(self, "target_exe_edit") else "ProjectG127.exe"
        exe_path = self.find_process_exe_path(target_exe or "ProjectG127.exe")
        if exe_path:
            return os.path.join(os.path.dirname(exe_path), "logs", "pangya_wind_live.json")

        # 3) GUI와 같은 폴더 기준. DLL/클라와 같은 폴더에서 실행하는 경우 대비
        return os.path.join(get_app_dir(), "logs", "pangya_wind_live.json")

    def update_wind_live_from_file(self):
        if not hasattr(self, "wind_live_auto_check") or not self.wind_live_auto_check.isChecked():
            return

        path = self.resolve_wind_live_json_path()
        self.last_wind_live_path = path

        try:
            if not os.path.exists(path):
                if hasattr(self, "wind_live_label"):
                    self.wind_live_label.setText("바람/각도: live 파일 없음")
                return

            data = self.read_json_file_retry(path)

            if not data.get("ok", False):
                if hasattr(self, "wind_live_label"):
                    self.wind_live_label.setText("바람/각도: live 값 없음")
                return

            wind_ok = bool(data.get("wind_ok", data.get("ok", False)))
            degree_ok = bool(data.get("degree_ok", False))

            wind = float(data.get("wind")) if wind_ok and data.get("wind") is not None else None

            # 중요:
            # DLL은 degree(0~360, 계속 증가/랩되는 카메라/UI 기준값)와
            # signed_degree(-180~180, 우리가 계산기에 쓰는 기준값)를 같이 제공한다.
            # 계산기 Degree에는 degree가 아니라 signed_degree를 넣는다.
            raw_degree = float(data.get("degree")) if degree_ok and data.get("degree") is not None else None
            signed_degree = float(data.get("signed_degree")) if degree_ok and data.get("signed_degree") is not None else None
            radian = data.get("radian")
            tick = data.get("tick")

            wind_text = "-"
            signed_text = "-"

            if wind is not None:
                if not 0.0 <= wind <= 20.0:
                    if hasattr(self, "wind_live_label"):
                        self.wind_live_label.setText(f"바람: 범위 밖 {wind}")
                    return

                wind_text = f"{wind:.0f}" if abs(wind - round(wind)) < 0.001 else f"{wind:.2f}"
                if self.calc_wind_edit.text().strip() != wind_text:
                    self.calc_wind_edit.setText(wind_text)

                self.last_wind_live_value = wind

            if signed_degree is not None:
                # 계산기 입력값은 signed 기준 그대로 사용한다.
                # 예: -0.20, 45.00, -90.00
                signed_text = f"{signed_degree:.2f}"
                if self.calc_degree_edit.text().strip() != signed_text:
                    self.calc_degree_edit.setText(signed_text)
            elif raw_degree is not None:
                # signed_degree가 없는 구버전 JSON을 읽을 경우에만 fallback.
                # 이 경우는 검증용으로만 표시하고, 가능한 한 DLL을 최신 combined 버전으로 교체해야 한다.
                fallback = ((raw_degree + 180.0) % 360.0) - 180.0
                signed_text = f"{fallback:.2f}"
                if self.calc_degree_edit.text().strip() != signed_text:
                    self.calc_degree_edit.setText(signed_text)

            self.last_wind_live_tick = tick

            if hasattr(self, "wind_live_label"):
                display_path = path
                if len(display_path) > 65:
                    display_path = "..." + display_path[-62:]

                extra = ""
                try:
                    if raw_degree is not None:
                        extra += f"  raw={raw_degree:.2f}°"
                    if radian is not None:
                        extra += f"  rad={float(radian):.4f}"
                except Exception:
                    pass

                self.wind_live_label.setText(
                    f"바람: {wind_text}  각도: {signed_text}°{extra}  tick={tick}  {display_path}"
                )

        except Exception as e:
            print(f"[WARN] 바람 live 값 읽기 실패: {e}")
            if hasattr(self, "wind_live_label"):
                self.wind_live_label.setText("바람/각도: 읽기 실패")

    def on_slope_live_auto_changed(self):
        self.ensure_live_timers()
        if hasattr(self, "slope_live_auto_check") and not self.slope_live_auto_check.isChecked():
            self.last_slope_live_candidates = None
            if hasattr(self, "slope_live_label"):
                self.slope_live_label.setText("기울기 후보: -")

    def on_slope_live_mode_changed(self):
        if hasattr(self, "slope_live_auto_check") and self.slope_live_auto_check.isChecked():
            self.update_slope_live_from_file()

    def resolve_slope_live_json_path(self):
        manual = ""
        if hasattr(self, "slope_live_path_edit"):
            manual = self.slope_live_path_edit.text().strip().strip('"')

        if manual:
            return manual

        target_exe = self.target_exe_edit.text().strip() if hasattr(self, "target_exe_edit") else "ProjectG127.exe"
        exe_path = self.find_process_exe_path(target_exe or "ProjectG127.exe")
        if exe_path:
            return os.path.join(os.path.dirname(exe_path), "logs", "pangya_slope_live.json")

        return os.path.join(get_app_dir(), "logs", "pangya_slope_live.json")

    def _extract_slope_live_candidates(self, data):
        """
        pangya_slope_live.json에서 slope 후보를 추출한다.

        중요:
        - Acrisio scalar slope 입력은 내부에서 다시 x = slope_break * 0.00875 * -1 로 변환된다.
        - 그래서 DLL raw 값이 이미 클라이언트 내부 slope.x 계열이면 부호가 반대로 들어갈 수 있다.
        - 이번 버전은 scalar70/78의 + / - 부호 후보를 모두 GUI 계산 결과로 비교한다.
        """
        scalar = data.get("slope_scalar_candidates", {}) or {}
        raw_scalars = data.get("raw_scalars", {}) or {}

        def to_float_or_none(value):
            if value is None:
                return None
            try:
                return float(value)
            except Exception:
                return None

        scalar70_raw = to_float_or_none(scalar.get("scalar70_raw"))
        scalar78_raw = to_float_or_none(scalar.get("scalar78_raw"))

        if scalar70_raw is None:
            scalar70_raw = to_float_or_none(raw_scalars.get("f70"))
        if scalar78_raw is None:
            scalar78_raw = to_float_or_none(raw_scalars.get("f78"))

        scalar70_plus = to_float_or_none(scalar.get("scalar70_break"))
        scalar78_plus = to_float_or_none(scalar.get("scalar78_div_00875"))

        if scalar70_plus is None and scalar70_raw is not None:
            scalar70_plus = scalar70_raw / 0.00875
        if scalar78_plus is None and scalar78_raw is not None:
            scalar78_plus = scalar78_raw / 0.00875

        candidates = {
            "A_PLUS": scalar70_plus,
            "A_MINUS": -scalar70_plus if scalar70_plus is not None else None,
            "B_PLUS": scalar78_plus,
            "B_MINUS": -scalar78_plus if scalar78_plus is not None else None,
            "scalar70_raw": scalar70_raw,
            "scalar78_raw": scalar78_raw,
        }

        # 새 CE 확정 경로: 006E1DFC/006E1E0C에서 읽은 Slope X/Y raw pair.
        slope_xy = data.get("slope_xy", {}) or {}
        break_candidates = data.get("break_candidates", {}) or {}

        slope_x = to_float_or_none(slope_xy.get("x"))
        slope_y = to_float_or_none(slope_xy.get("y"))
        slope_mag = to_float_or_none(slope_xy.get("mag"))

        x_plus = to_float_or_none(break_candidates.get("x_pos"))
        x_minus = to_float_or_none(break_candidates.get("x_neg"))
        y_plus = to_float_or_none(break_candidates.get("y_pos"))
        y_minus = to_float_or_none(break_candidates.get("y_neg"))
        mag_plus = to_float_or_none(break_candidates.get("mag_pos"))
        mag_minus = to_float_or_none(break_candidates.get("mag_neg"))

        if x_plus is None and slope_x is not None:
            x_plus = slope_x / 0.00875
        if x_minus is None and x_plus is not None:
            x_minus = -x_plus

        if y_plus is None and slope_y is not None:
            y_plus = slope_y / 0.00875
        if y_minus is None and y_plus is not None:
            y_minus = -y_plus

        if mag_plus is None and slope_mag is not None:
            mag_plus = slope_mag / 0.00875
        if mag_minus is None and mag_plus is not None:
            mag_minus = -mag_plus

        candidates.update({
            "X_PLUS": x_plus,
            "X_MINUS": x_minus,
            "Y_PLUS": y_plus,
            "Y_MINUS": y_minus,
            "MAG_PLUS": mag_plus,
            "MAG_MINUS": mag_minus,
            "slope_x_raw": slope_x,
            "slope_y_raw": slope_y,
            "slope_mag_raw": slope_mag,
        })

        # 006E1F68 return 직전 result matrix 후보.
        # 클라이언트가 raw normal에 회전을 적용한 뒤 반환하는 3x3 basis/matrix에서
        # 작은 성분들을 /0.00875 해서 slope_break 후보로 비교한다.
        result_matrix = data.get("result_matrix", {}) or {}
        result_div = data.get("result_div_00875_candidates", {}) or {}

        def read_matrix_break(field):
            value = to_float_or_none(result_div.get(field))
            if value is not None:
                return value
            raw = to_float_or_none(result_matrix.get(field))
            if raw is not None:
                return raw / 0.00875
            return None

        for field in ("r04", "r0c", "r14", "r1c"):
            plus = read_matrix_break(field)
            key_base = field.upper()
            candidates[f"{key_base}_PLUS"] = plus
            candidates[f"{key_base}_MINUS"] = -plus if plus is not None else None
            raw = to_float_or_none(result_matrix.get(field))
            candidates[f"{key_base}_RAW"] = raw

        candidates["hook_return_installed"] = bool(data.get("hook_return_installed", False))
        counts = data.get("counts", {}) or {}
        candidates["return_count"] = to_float_or_none(counts.get("return"))

        # 구버전 matrix logger fallback. 이번 실전 후보로는 낮은 우선순위지만 참고 계산용으로 유지한다.
        legacy = data.get("slope_break_candidates", {}) or {}
        reference = data.get("matrix_candidates_reference_only", {}) or {}

        def read_legacy(*names):
            for name in names:
                value = legacy.get(name, None)
                if value is None:
                    value = reference.get(name, None)
                value = to_float_or_none(value)
                if value is not None:
                    return value
            return None

        legacy_a = read_legacy("side_from_normal_x", "side_break_from_normal_x")
        legacy_b = read_legacy("side_from_axis_z_x", "side_break_from_axis_z_x")

        # 정말 필드가 없을 때만 matrix에서 즉석 계산한다.
        normal = data.get("normal_candidate", {}) or {}
        axis_z = data.get("axis_z", {}) or {}
        if legacy_a is None and normal.get("x") is not None:
            legacy_a = -float(normal.get("x")) / 0.00875
        if legacy_b is None and axis_z.get("x") is not None:
            legacy_b = -float(axis_z.get("x")) / 0.00875

        candidates["LEGACY_A"] = legacy_a
        candidates["LEGACY_B"] = legacy_b
        return candidates

    def update_slope_live_from_file(self):
        if not hasattr(self, "slope_live_auto_check") or not self.slope_live_auto_check.isChecked():
            return

        path = self.resolve_slope_live_json_path()
        self.last_slope_live_path = path

        try:
            if not os.path.exists(path):
                self.last_slope_live_candidates = None
                if hasattr(self, "slope_live_label"):
                    self.slope_live_label.setText("기울기 후보: live 파일 없음")
                return

            data = self.read_json_file_retry(path)

            if not data.get("ok", False):
                self.last_slope_live_candidates = None
                if hasattr(self, "slope_live_label"):
                    self.slope_live_label.setText("기울기 후보: live 값 없음")
                return

            candidates = self._extract_slope_live_candidates(data)
            tick = data.get("tick")
            seq = data.get("seq")

            usable_keys = ["X_PLUS", "X_MINUS", "Y_PLUS", "Y_MINUS", "MAG_PLUS", "MAG_MINUS", "R0C_PLUS", "R0C_MINUS", "R04_PLUS", "R04_MINUS", "R14_PLUS", "R14_MINUS", "R1C_PLUS", "R1C_MINUS", "A_PLUS", "A_MINUS", "B_PLUS", "B_MINUS", "LEGACY_A", "LEGACY_B"]
            if not any(candidates.get(k) is not None for k in usable_keys):
                self.last_slope_live_candidates = None
                if hasattr(self, "slope_live_label"):
                    self.slope_live_label.setText("기울기 후보: 후보 필드 없음")
                return

            candidates["tick"] = tick
            candidates["seq"] = seq
            candidates["path"] = path
            self.last_slope_live_candidates = candidates
            self.last_slope_live_tick = tick

            mode = self.slope_live_mode_combo.currentData() if hasattr(self, "slope_live_mode_combo") else "XY_COMPARE"

            chosen_map = {
                "X_PLUS": "X_PLUS",
                "X_MINUS": "X_MINUS",
                "Y_PLUS": "Y_PLUS",
                "Y_MINUS": "Y_MINUS",
                "MAG_PLUS": "MAG_PLUS",
                "MAG_MINUS": "MAG_MINUS",
                "R0C_PLUS": "R0C_PLUS",
                "R0C_MINUS": "R0C_MINUS",
                "R04_PLUS": "R04_PLUS",
                "R04_MINUS": "R04_MINUS",
                "R14_PLUS": "R14_PLUS",
                "R14_MINUS": "R14_MINUS",
                "R1C_PLUS": "R1C_PLUS",
                "R1C_MINUS": "R1C_MINUS",
                "SCALAR70_PLUS": "A_PLUS",
                "SCALAR70_MINUS": "A_MINUS",
                "SCALAR78_PLUS": "B_PLUS",
                "SCALAR78_MINUS": "B_MINUS",
                "SCALAR70": "A_PLUS",
                "SCALAR78": "B_PLUS",
                "NORMAL_X": "LEGACY_A",
                "AXIS_Z_X": "LEGACY_B",
            }
            chosen_key = chosen_map.get(mode)
            chosen = candidates.get(chosen_key) if chosen_key else None

            if chosen is not None:
                new_text = f"{chosen:.4f}"
                if self.calc_slope_edit.text().strip() != new_text:
                    self.calc_slope_edit.setText(new_text)

            if hasattr(self, "slope_live_label"):
                display_path = path
                if len(display_path) > 65:
                    display_path = "..." + display_path[-62:]

                def fmt(name):
                    value = candidates.get(name)
                    return "-" if value is None else f"{value:.4f}"

                self.slope_live_label.setText(
                    f"SlopeX±:{fmt('X_PLUS')}/{fmt('X_MINUS')}  "
                    f"SlopeY±:{fmt('Y_PLUS')}/{fmt('Y_MINUS')}  "
                    f"MAG±:{fmt('MAG_PLUS')}/{fmt('MAG_MINUS')}  "
                    f"R0C±:{fmt('R0C_PLUS')}/{fmt('R0C_MINUS')}  "
                    f"R1C±:{fmt('R1C_PLUS')}/{fmt('R1C_MINUS')}  "
                    f"seq={seq} tick={tick}  {display_path}"
                )

        except Exception as e:
            print(f"[WARN] 기울기 live 값 읽기 실패: {e}")
            self.last_slope_live_candidates = None
            if hasattr(self, "slope_live_label"):
                self.slope_live_label.setText("기울기 후보: 읽기 실패")

    def stop_memory_probe(self):
        # wind/slope live JSON timer는 메모리 hook과 독립적이다.
        # 여기서 끄면 체크박스는 ON인데 라벨은 '-'로 멈추는 문제가 생긴다.

        if self.memory_timer.isActive():
            self.memory_timer.stop()

        if self.memory_probe is not None:
            try:
                self.memory_probe.close()
                print("[INFO] 메모리 자동 입력 hook 복구/종료 완료")
            except Exception as e:
                print(f"[WARN] 메모리 자동 입력 종료 실패: {e}")
            finally:
                self.memory_probe = None

        if hasattr(self, "memory_connect_btn"):
            self.memory_connect_btn.setEnabled(True)
            self.memory_disconnect_btn.setEnabled(False)

        self.set_memory_status("상태: 연결 안 됨")
        if hasattr(self, "memory_distance_label"):
            self.memory_distance_label.setText("거리: -")
        if hasattr(self, "memory_height_label"):
            self.memory_height_label.setText("고저: -")
        if hasattr(self, "wind_live_label"):
            self.wind_live_label.setText("바람/각도: -")

    def update_memory_values_from_game(self):
        if self.memory_probe is None:
            return

        try:
            distance = self.memory_probe.read_distance_final()
            height = self.memory_probe.read_height()

            changed = False

            if distance is not None:
                self.last_memory_distance = distance
                if hasattr(self, "memory_distance_label"):
                    self.memory_distance_label.setText(f"거리: {distance:.2f}y")
                if hasattr(self, "memory_auto_check") and self.memory_auto_check.isChecked():
                    current = self.calc_distance_edit.text().strip()
                    new_text = f"{distance:.2f}"
                    if current != new_text:
                        self.calc_distance_edit.setText(new_text)
                        changed = True

            if height is not None:
                self.last_memory_height = height
                if hasattr(self, "memory_height_label"):
                    self.memory_height_label.setText(f"고저: {height:.2f}m")
                if hasattr(self, "memory_auto_check") and self.memory_auto_check.isChecked():
                    current = self.calc_height_edit.text().strip()
                    new_text = f"{height:.2f}"
                    if current != new_text:
                        self.calc_height_edit.setText(new_text)
                        changed = True

            if distance is not None or height is not None:
                self.set_memory_status("상태: 연결됨 - 값 수신 중")
            else:
                self.set_memory_status("상태: 연결됨 - 샷 화면/값 대기 중")

        except Exception as e:
            print(f"[WARN] 메모리 값 읽기 실패: {e}")
            self.set_memory_status("상태: 읽기 실패 - 재연결 필요")
            self.stop_memory_probe()

    def read_calc_float(self, edit, name, default=0.0):
        text = edit.text().strip()
        if text == "":
            return default
        try:
            return float(text)
        except ValueError:
            raise ValueError(f"{name} 값이 숫자가 아닙니다: {text}")

    def update_backspin_button_state(self):
        is_dunk = self.calc_shot_combo.currentData() == "DUNK"
        has_dunk_result = (
            self.last_calc_result is not None and
            self.last_calc_display is not None and
            self.last_calc_shot_type == "DUNK"
        )

        self.backspin_btn.setVisible(is_dunk)
        self.backspin_btn.setEnabled(is_dunk and has_dunk_result)

    def on_calc_shot_changed(self):
        self.last_calc_result = None
        self.last_calc_display = None
        self.last_calc_shot_type = None
        self.update_backspin_button_state()

    def on_calc_clicked(self):
        if calc_shot is None:
            QMessageBox.warning(self, "계산기 오류", "pangya_acrisio.py 모듈을 불러오지 못했습니다.")
            return

        try:
            yards_to_pb = self.read_calc_float(self.calc_yards_to_pb_edit, "YARDS_TO_PB", 0.2167)
            yards_to_pba = self.read_calc_float(self.calc_yards_to_pba_edit, "YARDS_TO_PBA", 0.8668)
            yards_to_pba_plus = self.read_calc_float(self.calc_yards_to_pba_plus_edit, "YARDS_TO_PBA+", 1.032)
            board_per_pb = self.read_calc_float(self.calc_board_per_pb_edit, "장판 환산값(PB당)", 0.2121)
            smart_divisor = self.read_calc_float(self.calc_smart_divisor_edit, "스마트 나눗값", 4.0)

            if yards_to_pb == 0 or yards_to_pba == 0 or yards_to_pba_plus == 0 or smart_divisor == 0:
                raise ValueError("표시 단위 값은 0이 될 수 없습니다.")

            def run_calc_with_slope(slope_value):
                return calc_shot(
                    power=self.read_calc_float(self.calc_power_edit, "Power", 31.0),
                    auxpart_pwr=self.read_calc_float(self.calc_auxpart_edit, "Ring Power", 0.0),
                    card_pwr=self.read_calc_float(self.calc_card_edit, "Card Power", 0.0),
                    mascot_pwr=self.read_calc_float(self.calc_mascot_edit, "Mascot Power", 0.0),
                    card_ps_pwr=self.read_calc_float(self.calc_card_ps_edit, "Card Power Shot Power", 0.0),
                    club=self.calc_club_combo.currentData(),
                    shot=self.calc_shot_combo.currentData(),
                    power_shot=self.calc_power_shot_combo.currentData(),
                    distance=self.read_calc_float(self.calc_distance_edit, "Distance", 0.0),
                    height=self.read_calc_float(self.calc_height_edit, "Height", 0.0),
                    wind=self.read_calc_float(self.calc_wind_edit, "Wind", 0.0),
                    degree=self.read_calc_float(self.calc_degree_edit, "Degree", 0.0),
                    ground=self.read_calc_float(self.calc_ground_edit, "Ground", 100.0),
                    spin=self.read_calc_float(self.calc_spin_edit, "Spin", 0.0),
                    curve=self.read_calc_float(self.calc_curve_edit, "Curve", 0.0),
                    slope=str(slope_value),
                    line_ball=self.read_calc_float(self.calc_line_ball_edit, "Line ball", 0.0),
                    line_ball_random=self.calc_line_ball_random_check.isChecked(),
                )

            def build_display(result):
                # pangya_acrisio.py의 result.pb/result.real_pb는 원본 JS 기본값 0.2167 기준 결과다.
                pb_yards = result.pb * 0.2167
                real_pb_yards = result.real_pb * 0.2167

                custom_pb = pb_yards / yards_to_pb
                custom_real_pb = real_pb_yards / yards_to_pb
                custom_pba = pb_yards / yards_to_pba
                custom_pba_plus = pb_yards / yards_to_pba_plus

                # 기존 버전은 abs(result.pb)를 써서 장판 방향 부호가 사라졌다.
                # 방향 판단을 위해 PB 부호를 그대로 유지한 signed 장판을 기본 표시값으로 둔다.
                board_cells_signed = result.pb * board_per_pb
                board_cells_abs = abs(board_cells_signed)
                smart_cells_signed = board_cells_signed / smart_divisor
                smart_cells_abs = board_cells_abs / smart_divisor

                return {
                    "board_cells": board_cells_signed,
                    "smart_cells": smart_cells_signed,
                    "board_cells_signed": board_cells_signed,
                    "board_cells_abs": board_cells_abs,
                    "smart_cells_signed": smart_cells_signed,
                    "smart_cells_abs": smart_cells_abs,
                    "board_per_pb": board_per_pb,
                    "smart_divisor": smart_divisor,
                    "yards_to_pb": yards_to_pb,
                    "yards_to_pba": yards_to_pba,
                    "yards_to_pba_plus": yards_to_pba_plus,
                    "custom_pb": custom_pb,
                    "custom_real_pb": custom_real_pb,
                    "custom_pba": custom_pba,
                    "custom_pba_plus": custom_pba_plus,
                }

            def append_result_block(lines, title, result, display, slope_text):
                lines.append(title)
                lines.append(f"Slope break: {slope_text}")

                if not result.ok:
                    lines.append(f"계산 실패: {result.message}")
                    lines.append("")
                    return

                lines.extend([
                    f"권장 파워: {result.power_percent:.1f}%",
                    f"샷 거리: {result.shot_yards:.1f}y",
                    f"장판(부호): {display['board_cells_signed']:+.3f}칸",
                    f"장판(abs): {display['board_cells_abs']:.3f}칸",
                    f"스마트(부호): {display['smart_cells_signed']:+.2f}칸",
                    f"스마트(abs): {display['smart_cells_abs']:.2f}칸",
                    f"조준 PB: {result.pb:+.2f}pb",
                    f"Real PB: {result.real_pb:.2f}pb",
                    f"Smart: {result.smart}",
                    f"Desvio: {result.desvio_yards:.6f}y",
                    f"Custom PB: {display['custom_pb']:.2f}pb",
                    f"Custom Real PB: {display['custom_real_pb']:.2f}pb",
                    f"Custom PBA: {display['custom_pba']:.2f}pba",
                    f"Custom PBA+: {display['custom_pba_plus']:.2f}pba+",
                    f"Aim 반복: {result.aim_iterations}",
                    "",
                ])

            manual_slope_text = self.calc_slope_edit.text().strip() or "0"
            result = run_calc_with_slope(manual_slope_text)

            if not result.ok:
                self.last_calc_result = None
                self.last_calc_display = None
                self.last_calc_shot_type = None
                self.update_backspin_button_state()
                self.calc_result_box.setPlainText(result.message)
                return

            display = build_display(result)

            self.last_calc_result = result
            self.last_calc_display = display
            self.last_calc_shot_type = self.calc_shot_combo.currentData()
            self.update_backspin_button_state()

            output = []
            append_result_block(output, "[수동/현재 Slope]", result, display, manual_slope_text)

            slope_mode = self.slope_live_mode_combo.currentData() if hasattr(self, "slope_live_mode_combo") else "OFF"
            slope_live_enabled = hasattr(self, "slope_live_auto_check") and self.slope_live_auto_check.isChecked()

            if slope_live_enabled:
                # 계산 버튼을 누르는 순간 최신 JSON을 한 번 더 읽는다.
                self.update_slope_live_from_file()
                candidates = self.last_slope_live_candidates or {}

                xy_candidate_specs = [
                    ("X+", "X_PLUS", "Slope X / 0.00875"),
                    ("X-", "X_MINUS", "-Slope X / 0.00875"),
                    ("Y+", "Y_PLUS", "Slope Y / 0.00875"),
                    ("Y-", "Y_MINUS", "-Slope Y / 0.00875"),
                    ("MAG+", "MAG_PLUS", "sqrt(X^2+Y^2) / 0.00875"),
                    ("MAG-", "MAG_MINUS", "-sqrt(X^2+Y^2) / 0.00875"),
                ]
                sign_candidate_specs = [
                    ("A+", "A_PLUS", "구버전 scalar70 = raw f70 / 0.00875"),
                    ("A-", "A_MINUS", "구버전 scalar70 반대부호 = -raw f70 / 0.00875"),
                    ("B+", "B_PLUS", "구버전 scalar78 = raw f78 / 0.00875"),
                    ("B-", "B_MINUS", "구버전 scalar78 반대부호 = -raw f78 / 0.00875"),
                ]
                matrix_candidate_specs = [
                    ("R0C+", "R0C_PLUS", "result r0c / 0.00875"),
                    ("R0C-", "R0C_MINUS", "-result r0c / 0.00875"),
                    ("R04+", "R04_PLUS", "result r04 / 0.00875"),
                    ("R04-", "R04_MINUS", "-result r04 / 0.00875"),
                    ("R14+", "R14_PLUS", "result r14 / 0.00875"),
                    ("R14-", "R14_MINUS", "-result r14 / 0.00875"),
                    ("R1C+", "R1C_PLUS", "result r1c / 0.00875"),
                    ("R1C-", "R1C_MINUS", "-result r1c / 0.00875"),
                ]
                legacy_candidate_specs = [
                    ("구버전 A", "LEGACY_A", "matrix/reference normal.x 계열"),
                    ("구버전 B", "LEGACY_B", "matrix/reference axis_z.x 계열"),
                ]

                if slope_mode in ("XY_COMPARE", "MATRIX_COMPARE", "SIGN_COMPARE", "SCALAR_COMPARE", "BOTH_COMPARE"):
                    output.extend([
                        "==============================",
                        "[DLL live Slope 후보 비교]",
                    ])

                    if slope_mode == "XY_COMPARE":
                        specs = xy_candidate_specs
                        output.append("CE로 확정한 Slope X/Y raw pair 기반 후보를 비교합니다.")
                        output.append("raw slope에 0.2167을 곱하지 않습니다. raw / 0.00875로 slope_break 후보를 만든 뒤 Acrisio 물리에 넣고, 최종 PB에만 장판 환산값을 적용합니다.")
                        output.append("")
                    elif slope_mode == "MATRIX_COMPARE":
                        specs = matrix_candidate_specs
                        output.append("006E1F68 return 직전 result matrix 기반 후보를 비교합니다.")
                        output.append("클라이언트가 raw normal에 회전을 적용한 뒤 만든 작은 matrix 성분을 /0.00875 해서 slope_break 후보로 사용합니다.")
                        output.append("우선 관찰 후보: -R0C, R1C+, R14-, R04-")
                        output.append("")
                    elif slope_mode == "SIGN_COMPARE":
                        specs = sign_candidate_specs
                        output.append("구버전 scalar70/78의 +부호와 반대부호를 모두 비교합니다.")
                        output.append("")
                    else:
                        specs = legacy_candidate_specs
                        output.append("구버전 matrix 후보 비교입니다. 현재는 참고용입니다.")
                        output.append("")

                    rendered = 0
                    for short_name, key, desc in specs:
                        value = candidates.get(key)
                        if value is None:
                            continue
                        r_live = run_calc_with_slope(value)
                        d_live = build_display(r_live) if r_live.ok else {}
                        append_result_block(output, f"[후보 {short_name}: {desc}]", r_live, d_live, f"{value:.4f}")
                        rendered += 1

                    if rendered == 0:
                        output.append("DLL live slope 후보가 아직 없습니다.")
                        output.append("")

                elif slope_mode in ("X_PLUS", "X_MINUS", "Y_PLUS", "Y_MINUS", "MAG_PLUS", "MAG_MINUS", "R0C_PLUS", "R0C_MINUS", "R04_PLUS", "R04_MINUS", "R14_PLUS", "R14_MINUS", "R1C_PLUS", "R1C_MINUS", "SCALAR70_PLUS", "SCALAR70_MINUS", "SCALAR78_PLUS", "SCALAR78_MINUS", "SCALAR70", "SCALAR78", "NORMAL_X", "AXIS_Z_X"):
                    chosen_map = {
                        "X_PLUS": ("X+ Slope X / 0.00875", "X_PLUS"),
                        "X_MINUS": ("X- -Slope X / 0.00875", "X_MINUS"),
                        "Y_PLUS": ("Y+ Slope Y / 0.00875", "Y_PLUS"),
                        "Y_MINUS": ("Y- -Slope Y / 0.00875", "Y_MINUS"),
                        "MAG_PLUS": ("MAG+ sqrt(X²+Y²) / 0.00875", "MAG_PLUS"),
                        "MAG_MINUS": ("MAG- -sqrt(X²+Y²) / 0.00875", "MAG_MINUS"),
                        "R0C_PLUS": ("R0C+ result r0c / 0.00875", "R0C_PLUS"),
                        "R0C_MINUS": ("R0C- -result r0c / 0.00875", "R0C_MINUS"),
                        "R04_PLUS": ("R04+ result r04 / 0.00875", "R04_PLUS"),
                        "R04_MINUS": ("R04- -result r04 / 0.00875", "R04_MINUS"),
                        "R14_PLUS": ("R14+ result r14 / 0.00875", "R14_PLUS"),
                        "R14_MINUS": ("R14- -result r14 / 0.00875", "R14_MINUS"),
                        "R1C_PLUS": ("R1C+ result r1c / 0.00875", "R1C_PLUS"),
                        "R1C_MINUS": ("R1C- -result r1c / 0.00875", "R1C_MINUS"),
                        "SCALAR70_PLUS": ("A+ scalar70", "A_PLUS"),
                        "SCALAR70_MINUS": ("A- scalar70 반대부호", "A_MINUS"),
                        "SCALAR78_PLUS": ("B+ scalar78", "B_PLUS"),
                        "SCALAR78_MINUS": ("B- scalar78 반대부호", "B_MINUS"),
                        "SCALAR70": ("A+ scalar70", "A_PLUS"),
                        "SCALAR78": ("B+ scalar78", "B_PLUS"),
                        "NORMAL_X": ("구버전 A matrix", "LEGACY_A"),
                        "AXIS_Z_X": ("구버전 B matrix", "LEGACY_B"),
                    }
                    chosen_name, chosen_key = chosen_map.get(slope_mode, ("unknown", None))
                    chosen = candidates.get(chosen_key) if chosen_key else None

                    output.extend([
                        "==============================",
                        f"[DLL live Slope 적용 모드: 후보 {chosen_name}]",
                    ])

                    if chosen is not None:
                        r_live = run_calc_with_slope(chosen)
                        d_live = build_display(r_live) if r_live.ok else {}
                        append_result_block(output, f"[후보 {chosen_name} 적용 계산]", r_live, d_live, f"{chosen:.4f}")
                    else:
                        output.append("선택한 DLL live slope 후보가 아직 없습니다.")
                        output.append("")

            output.extend([
                "==============================",
                "표시 단위 / 환산 설정",
                f"YARDS_TO_PB={yards_to_pb}",
                f"YARDS_TO_PBA={yards_to_pba}",
                f"YARDS_TO_PBA+={yards_to_pba_plus}",
                f"장판 환산값(PB당): {board_per_pb}",
                f"스마트 나눗값: {smart_divisor}",
                "",
                "입력 요약",
                f"Club={self.calc_club_combo.currentText()}, Shot={self.calc_shot_combo.currentText()}, PowerShot={self.calc_power_shot_combo.currentText()}",
                f"Distance={self.calc_distance_edit.text()}, Height={self.calc_height_edit.text()}, Wind={self.calc_wind_edit.text()}, Degree={self.calc_degree_edit.text()}",
                f"Ground={self.calc_ground_edit.text()}, Spin={self.calc_spin_edit.text()}, Curve={self.calc_curve_edit.text()}, Slope={self.calc_slope_edit.text()}",
            ])

            self.calc_result_box.setPlainText("\n".join(output))

        except Exception as e:
            QMessageBox.critical(self, "계산 실패", str(e))

    def on_backspin_clicked(self):
        try:
            if self.last_calc_result is None or self.last_calc_display is None:
                QMessageBox.warning(self, "BackSpin 오류", "먼저 Dunk 계산을 실행하세요.")
                return

            if self.last_calc_shot_type != "DUNK":
                QMessageBox.warning(self, "BackSpin 오류", "BackSpin 보정은 Dunk 계산 결과에서만 사용할 수 있습니다.")
                return

            result = self.last_calc_result
            display = self.last_calc_display

            backspin_board_multiplier = 1.08
            backspin_distance_minus = 14.0
            backspin_max_range = 284.0

            original_board_cells = display.get("board_cells_signed", display["board_cells"])
            original_smart_cells = display.get("smart_cells_signed", display["smart_cells"])
            original_shot_yards = result.shot_yards
            original_power_percent = result.power_percent

            backspin_board_cells = original_board_cells * backspin_board_multiplier
            backspin_smart_cells = backspin_board_cells / display["smart_divisor"]

            backspin_shot_yards = original_shot_yards - backspin_distance_minus

            if backspin_shot_yards <= 0:
                raise ValueError("BackSpin 보정 후 샷 거리가 0 이하가 됩니다.")

            backspin_power_percent = backspin_shot_yards / backspin_max_range * 100.0

            output = [
                "BackSpin 보정 결과",
                "",
                f"권장 파워: {backspin_power_percent:.1f}%",
                f"샷 거리: {backspin_shot_yards:.1f}y",
                "",
                "실사용 표시",
                f"장판(부호): {backspin_board_cells:+.3f}칸",
                f"장판(abs): {abs(backspin_board_cells):.3f}칸",
                f"스마트(부호): {backspin_smart_cells:+.2f}칸",
                f"스마트(abs): {abs(backspin_smart_cells):.2f}칸",
                "",
                "보정 전 Dunk 계산값",
                f"기존 권장 파워: {original_power_percent:.1f}%",
                f"기존 샷 거리: {original_shot_yards:.1f}y",
                f"기존 장판(부호): {original_board_cells:+.3f}칸",
                f"기존 장판(abs): {abs(original_board_cells):.3f}칸",
                f"기존 스마트: {original_smart_cells:.2f}칸",
                "",
                "BackSpin 보정식",
                f"장판 = 기존 장판 × {backspin_board_multiplier}",
                f"샷 거리 = 기존 샷 거리 - {backspin_distance_minus:.1f}y",
                f"권장 파워 = 보정 샷 거리 / {backspin_max_range:.1f}y × 100",
                "",
                "입력 요약",
                f"Club={self.calc_club_combo.currentText()}, Shot={self.calc_shot_combo.currentText()}, PowerShot={self.calc_power_shot_combo.currentText()}",
                f"Distance={self.calc_distance_edit.text()}, Height={self.calc_height_edit.text()}, Wind={self.calc_wind_edit.text()}, Degree={self.calc_degree_edit.text()}",
                f"Ground={self.calc_ground_edit.text()}, Spin={self.calc_spin_edit.text()}, Curve={self.calc_curve_edit.text()}, Slope={self.calc_slope_edit.text()}",
            ]

            self.calc_result_box.setPlainText("\n".join(output))

        except Exception as e:
            QMessageBox.critical(self, "BackSpin 계산 실패", str(e))

    def on_calc_reset_clicked(self):
        self.calc_power_edit.setText("31")
        self.calc_auxpart_edit.setText("0")
        self.calc_card_edit.setText("4")
        self.calc_mascot_edit.setText("4")
        self.calc_card_ps_edit.setText("8")
        self.calc_club_combo.setCurrentIndex(0)
        self.calc_shot_combo.setCurrentIndex(1)
        self.calc_power_shot_combo.setCurrentIndex(0)
        self.calc_distance_edit.setText("240")
        self.calc_height_edit.setText("0")
        self.calc_wind_edit.setText("6")
        self.calc_degree_edit.setText("30")
        self.calc_ground_edit.setText("100")
        self.calc_spin_edit.setText("0")
        self.calc_curve_edit.setText("0")
        self.calc_slope_edit.setText("0")
        self.calc_line_ball_edit.setText("0")
        self.calc_line_ball_random_check.setChecked(False)
        self.calc_yards_to_pb_edit.setText("0.2167")
        self.calc_yards_to_pba_edit.setText("0.8668")
        self.calc_yards_to_pba_plus_edit.setText("1.032")
        self.calc_board_per_pb_edit.setText("0.2121")
        self.calc_smart_divisor_edit.setText("4")
        self.last_calc_result = None
        self.last_calc_display = None
        self.last_calc_shot_type = None
        self.update_backspin_button_state()
        self.calc_result_box.clear()
        

    def on_mycella_clicked(self):
        try:
            shot_degree = self.read_calc_float(self.mycella_shot_degree_edit, "Shot degree", 0.0)
            align_degree = self.read_calc_float(self.mycella_align_degree_edit, "Align degree", 0.0)
            slope_break = self.read_calc_float(self.mycella_slope_break_edit, "Slope break", 0.0)
            slope_real = abs(math.cos(math.radians(abs(shot_degree - align_degree)))) * slope_break
            self.calc_degree_edit.setText(f"{shot_degree:.3f}")
            self.calc_slope_edit.setText(f"{slope_real:.3f}")
        except Exception as e:
            QMessageBox.warning(self, "Mycella 계산 실패", str(e))

    def on_hotkey_capture_clicked(self):
        self.hotkey_edit.start_capture()

    def on_hotkey_clear_clicked(self):
        self.hotkey_edit.stop_capture()
        self.hotkey_edit.setText("")

    def load_settings_to_ui(self):
        s = self.settings

        self.target_exe_edit.setText(str(s["target_exe"]))
        self.hotkey_edit.setText(str(s["toggle_hotkey"]))
        self.ui_scale_spin.setValue(float(s.get("ui_scale", 1.0)))

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
        self.capture_exclude_check.setChecked(bool(s.get("capture_exclude_enabled", True)))

    def collect_settings_from_ui(self):
        settings = normalize_settings({
            "target_exe": self.target_exe_edit.text().strip() or DEFAULT_SETTINGS["target_exe"],
            
             # GUI 배율
            "ui_scale": self.ui_scale_spin.value(),

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
            "capture_exclude_enabled": self.capture_exclude_check.isChecked(),

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

        # GUI 배율 즉시 적용
        apply_gui_scale(self.settings)

        # 현재 설정창 레이아웃 재계산
        self.updateGeometry()
        self.adjustSize()

        self.overlay.set_settings(self.settings)
        self.apply_control_window_capture_exclude()
        self.register_hotkey_from_settings()

        if show_message:
            QMessageBox.information(self, "적용 완료", "설정이 적용되었습니다.")

        return True

    def on_start_clicked(self):
        if not self.apply_settings(show_message=False):
            return

        self.overlay.start_overlay()

        if self.auto_controller is not None:
            self.auto_controller.start()

        if hasattr(self, "memory_auto_check") and self.memory_auto_check.isChecked() and self.memory_probe is None:
            self.start_memory_probe()

        self.ensure_live_timers()

        self.update_status()

    def on_stop_clicked(self):
        if self.auto_controller is not None:
            self.auto_controller.stop()

        self.stop_memory_probe()

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
                if not self.apply_settings(show_message=False):
                    return True, 0

                is_started = self.overlay.toggle_overlay()

                if self.auto_controller is not None:
                    if is_started:
                        self.auto_controller.start()
                    else:
                        self.auto_controller.stop()

                self.update_status()
                return True, 0

        except Exception:
            pass

        return False, 0

    def closeEvent(self, event):
        self.unregister_hotkey()

        if self.auto_controller is not None:
            self.auto_controller.stop()

        self.stop_memory_probe()

        self.overlay.stop_overlay()
        event.accept()


# =========================================================
# 실행부
# =========================================================

if __name__ == "__main__":
    app = QApplication(sys.argv)

    settings = load_settings()
    apply_gui_scale(settings)

    overlay = PangyaOverlay(settings)
    control_window = PangyaControlWindow(overlay, settings)
    control_window.show()

    QTimer.singleShot(300, control_window.register_hotkey_from_settings)

    sys.exit(app.exec())
