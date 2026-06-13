# -*- coding: utf-8 -*-
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

# 거리/고저차 자동 입력은 pangya_distance_height_logger.dll live JSON 방식으로 전환했습니다.
# 기존 Python PangyaMemoryProbe hook은 더 이상 import/사용하지 않습니다.
PangyaMemoryProbe = None
MemoryProbeError = RuntimeError
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

        #print(f"[INFO] 캡처 제외 적용 완료: hwnd={hwnd}, enabled={enabled}")
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
TRACK_INTERVAL_MS = 50
LOCK_AUTO_UNLOCK_DISTANCE_DELTA = 0.50
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
    "show_result": True,
    # 좌상단 오버레이 하단에 Shot / PowerShot 클릭 선택 영역 표시
    "show_quick_overlay_controls": True,

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

    # pangya_distance_height_logger.dll live JSON에서 남은거리/고저차 자동 입력
    "memory_auto_input": False,
    "distance_height_live_json_path": "",

    # pangya_ground_logger.dll live JSON에서 현재 지면상태 자동 입력
    "ground_live_auto_input": True,
    "ground_live_json_path": "",

    # pangya_club_logger.dll live JSON에서 현재 선택 클럽 자동 입력
    "club_live_auto_input": False,
    "club_live_json_path": "",

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
    "slope_live_mode": "R0C_MINUS",

    # pangya_spin_curve_live_logger.dll live JSON에서 스핀/커브 자동 입력
    "spin_curve_live_auto_input": True,
    "spin_curve_live_json_path": "",

    # pangya_lateral_offset_logger.dll live JSON에서 현재 조준선 LINE/DIFF 표시
    # DIFF는 GUI에서만 계산한다: DIFF = LINE - 계산 장판값
    "diff_live_auto_input": False,
    "diff_live_json_path": "",
    "diff_live_invert_sign": False,

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
