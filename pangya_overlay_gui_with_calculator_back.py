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
from PySide6.QtCore import Qt, QTimer, QPointF, QRectF
from PySide6.QtGui import QPainter, QPen, QColor, QFont, QPainterPath


try:
    # 바운드/롤 실험 함수가 추가된 버전을 우선 사용한다.
    # 없으면 기존 pangya_acrisio.py로 fallback한다.
    from pangya_acrisio import (
        calc_shot,
        simulate_trajectory_from_result,
        SurfacePhysics,
        Vector3D,
        get_material_type_bounce_factor,
        get_material_type_roll_factor,
        get_material_type_name,
        MATERIAL_TYPE_NAME,
        simulate_bounce_from_result,
    )
except Exception as e:
    try:
        from pangya_acrisio import calc_shot, simulate_trajectory_from_result
    except Exception as e2:
        calc_shot = None
        simulate_trajectory_from_result = None
        print(f"[WARN] pangya_acrisio 모듈 로드 실패: {e2}")

    SurfacePhysics = None
    Vector3D = None
    get_material_type_bounce_factor = None
    get_material_type_roll_factor = None
    get_material_type_name = None
    MATERIAL_TYPE_NAME = {}
    simulate_bounce_from_result = None
    print(f"[WARN] pangya_acrisio_with_bounce 모듈 로드 실패. 바운드/롤 실험 기능 비활성화: {e}")

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

    # 착지 후 바운드/롤 실험값
    # 실제 지면명 매핑 전에는 material_type을 바꿔가며 비교한다.
    "bounce_enabled": False,
    "bounce_material_type": "2",
    "bounce_material_bounce": "1.0",
    "bounce_material_roll": "1.0",
    "bounce_command_bounce": "1.0",
    "bounce_command_roll": "1.0",
    "bounce_mix_index": "3.0",
    "bounce_normal_x": "0",
    "bounce_normal_y": "1",
    "bounce_normal_z": "0",
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

        self.draw_calc_result_panel(painter, scale_x, scale_y)


# =========================================================
# 공 궤적 시각화 위젯
# =========================================================

class ShotTrajectoryCanvas(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.points = []
        self.bounce_points = []
        self.summary = "계산 버튼을 누르면 이곳에 공 궤적이 표시됩니다."
        self.setMinimumHeight(420)

    def set_trajectory(self, points, result=None, bounce_result=None):
        self.points = points or []
        self.bounce_points = list(getattr(bounce_result, "points", []) or [])

        if result is not None and getattr(result, "ok", False):
            summary = (
                f"Power {result.power_percent:.2f}% / "
                f"Carry {result.shot_yards:.2f}y / "
                f"PB {result.pb:.2f} / "
                f"Desvio {result.desvio_yards:.4f}y / "
                f"Air Points {len(self.points)}"
            )

            if self.bounce_points:
                last = self.bounce_points[-1]
                summary += (
                    f" / Bounce+Roll {len(self.bounce_points)} pts"
                    f" / End {float(last.forward_yards):.2f}y, {float(last.lateral_yards):.2f}y"
                )

            self.summary = summary
        else:
            self.summary = "계산 결과 없음"

        self.update()

    def clear_trajectory(self, message="계산 버튼을 누르면 이곳에 공 궤적이 표시됩니다."):
        self.points = []
        self.bounce_points = []
        self.summary = message
        self.update()

    def get_point_value(self, point, key):
        if isinstance(point, dict):
            return float(point[key])
        return float(getattr(point, key))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.fillRect(self.rect(), QColor(24, 24, 24))

        painter.setFont(QFont("Malgun Gothic", 10))
        painter.setPen(QPen(QColor(235, 235, 235), 1))
        painter.drawText(16, 24, self.summary)

        if not self.points and not self.bounce_points:
            painter.setPen(QPen(QColor(180, 180, 180), 1))
            painter.drawText(self.rect(), Qt.AlignCenter, "표시할 궤적 데이터가 없습니다.")
            return

        if self.bounce_points:
            painter.setFont(QFont("Malgun Gothic", 9))
            painter.setPen(QPen(QColor(70, 190, 255), 3))
            painter.drawLine(16, 48, 48, 48)
            painter.setPen(QPen(QColor(235, 235, 235), 1))
            painter.drawText(56, 53, "기존 공중 궤적")

            painter.setPen(QPen(QColor(255, 190, 70), 3))
            painter.drawLine(170, 48, 202, 48)
            painter.setPen(QPen(QColor(235, 235, 235), 1))
            painter.drawText(210, 53, "바운드/롤 예상")

        # 요약 문구와 그래프 제목이 겹치지 않도록 그래프 시작 위치를 충분히 내린다.
        margin = 42
        top_offset = 92 if self.bounce_points else 82
        gap = 34
        available_h = self.height() - top_offset - 32
        plot_h = max(140, int((available_h - gap) / 2))
        plot_w = max(200, self.width() - margin * 2)

        side_rect = QRectF(margin, top_offset, plot_w, plot_h)
        top_rect = QRectF(margin, top_offset + plot_h + gap, plot_w, plot_h)

        self.draw_plot(
            painter,
            side_rect,
            title="측면 궤적: 진행거리(y) / 높이(m)",
            x_key="forward_yards",
            y_key="height_m",
            y_zero=True,
        )
        self.draw_plot(
            painter,
            top_rect,
            title="상단 궤적: 진행거리(y) / 좌우편차(y)",
            x_key="forward_yards",
            y_key="lateral_yards",
            y_zero=True,
        )

    def draw_series(self, painter, rect, series, x_key, y_key, line_color, start_color=None, end_color=None, width=2):
        if not series:
            return

        xs = [self.get_point_value(p, x_key) for p in self.all_plot_points(x_key, y_key)]
        ys = [self.get_point_value(p, y_key) for p in self.all_plot_points(x_key, y_key)]

        min_x = min(xs)
        max_x = max(xs)
        min_y = min(ys)
        max_y = max(ys)

        if abs(max_x - min_x) < 0.000001:
            max_x = min_x + 1.0

        if abs(max_y - min_y) < 0.000001:
            max_y = min_y + 1.0

        pad_y = (max_y - min_y) * 0.12
        min_y -= pad_y
        max_y += pad_y

        def map_x(value):
            return rect.left() + (value - min_x) / (max_x - min_x) * rect.width()

        def map_y(value):
            return rect.bottom() - (value - min_y) / (max_y - min_y) * rect.height()

        path = QPainterPath()
        first = True
        for p in series:
            px = map_x(self.get_point_value(p, x_key))
            py = map_y(self.get_point_value(p, y_key))
            if first:
                path.moveTo(px, py)
                first = False
            else:
                path.lineTo(px, py)

        painter.setPen(QPen(line_color, width))
        painter.drawPath(path)

        start = series[0]
        end = series[-1]

        if start_color is not None:
            painter.setPen(QPen(start_color, 6))
            painter.drawPoint(QPointF(map_x(self.get_point_value(start, x_key)), map_y(self.get_point_value(start, y_key))))

        if end_color is not None:
            painter.setPen(QPen(end_color, 6))
            painter.drawPoint(QPointF(map_x(self.get_point_value(end, x_key)), map_y(self.get_point_value(end, y_key))))

    def all_plot_points(self, x_key, y_key):
        merged = []
        merged.extend(self.points or [])
        merged.extend(self.bounce_points or [])
        return [p for p in merged if p is not None]

    def draw_plot(self, painter, rect, title, x_key, y_key, y_zero=False):
        painter.setPen(QPen(QColor(230, 230, 230), 1))
        painter.drawText(int(rect.left()), int(rect.top()) - 8, title)

        painter.setPen(QPen(QColor(95, 95, 95), 1))
        painter.drawRect(rect)

        all_points = self.all_plot_points(x_key, y_key)
        if not all_points:
            return

        xs = [self.get_point_value(p, x_key) for p in all_points]
        ys = [self.get_point_value(p, y_key) for p in all_points]

        min_x = min(xs)
        max_x = max(xs)
        min_y = min(ys)
        max_y = max(ys)

        if y_zero:
            min_y = min(min_y, 0.0)
            max_y = max(max_y, 0.0)

        if abs(max_x - min_x) < 0.000001:
            max_x = min_x + 1.0

        if abs(max_y - min_y) < 0.000001:
            max_y = min_y + 1.0

        pad_y = (max_y - min_y) * 0.12
        min_y -= pad_y
        max_y += pad_y

        def map_x(value):
            return rect.left() + (value - min_x) / (max_x - min_x) * rect.width()

        def map_y(value):
            return rect.bottom() - (value - min_y) / (max_y - min_y) * rect.height()

        # 격자선
        painter.setPen(QPen(QColor(60, 60, 60), 1))
        for i in range(1, 5):
            x = rect.left() + rect.width() * i / 5.0
            y = rect.top() + rect.height() * i / 5.0
            painter.drawLine(int(x), int(rect.top()), int(x), int(rect.bottom()))
            painter.drawLine(int(rect.left()), int(y), int(rect.right()), int(y))

        # 0 기준선
        if min_y <= 0.0 <= max_y:
            zero_y = map_y(0.0)
            painter.setPen(QPen(QColor(130, 130, 130), 1))
            painter.drawLine(int(rect.left()), int(zero_y), int(rect.right()), int(zero_y))

        def draw_one_series(series, line_color, start_color=None, end_color=None, width=2):
            if not series:
                return

            path = QPainterPath()
            first = True
            for p in series:
                px = map_x(self.get_point_value(p, x_key))
                py = map_y(self.get_point_value(p, y_key))
                if first:
                    path.moveTo(px, py)
                    first = False
                else:
                    path.lineTo(px, py)

            painter.setPen(QPen(line_color, width))
            painter.drawPath(path)

            start = series[0]
            end = series[-1]
            if start_color is not None:
                painter.setPen(QPen(start_color, 6))
                painter.drawPoint(QPointF(map_x(self.get_point_value(start, x_key)), map_y(self.get_point_value(start, y_key))))
            if end_color is not None:
                painter.setPen(QPen(end_color, 6))
                painter.drawPoint(QPointF(map_x(self.get_point_value(end, x_key)), map_y(self.get_point_value(end, y_key))))

        # 기존 공중 궤적
        draw_one_series(
            self.points,
            QColor(70, 190, 255),
            QColor(120, 255, 120),
            QColor(255, 120, 120),
            2,
        )

        # 바운드/롤 예상 궤적
        draw_one_series(
            self.bounce_points,
            QColor(255, 190, 70),
            QColor(255, 230, 120),
            QColor(255, 120, 80),
            2,
        )

        # phase 표시: 2차 착지 / 롤 정지
        if self.bounce_points:
            painter.setFont(QFont("Malgun Gothic", 8))
            for p in self.bounce_points:
                phase = getattr(p, "phase", "")
                if phase not in ("second_landing", "roll_stop"):
                    continue

                px = map_x(self.get_point_value(p, x_key))
                py = map_y(self.get_point_value(p, y_key))
                label = "2차착지" if phase == "second_landing" else "롤정지"
                painter.setPen(QPen(QColor(0, 0, 0), 3))
                painter.drawText(int(px) + 5, int(py) - 5, label)
                painter.setPen(QPen(QColor(255, 255, 255), 1))
                painter.drawText(int(px) + 4, int(py) - 6, label)

        # 축 값
        painter.setFont(QFont("Malgun Gothic", 8))
        painter.setPen(QPen(QColor(210, 210, 210), 1))
        painter.drawText(int(rect.left()), int(rect.bottom()) + 16, f"{min_x:.1f}")
        painter.drawText(int(rect.right()) - 42, int(rect.bottom()) + 16, f"{max_x:.1f}y")
        painter.drawText(int(rect.left()) - 38, int(rect.top()) + 10, f"{max_y:.2f}")
        painter.drawText(int(rect.left()) - 38, int(rect.bottom()), f"{min_y:.2f}")

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
        self.last_bounce_result = None

        self.setWindowTitle("Pangya Assist Overlay 설정")
        self.setWindowTitle("Pangya Assist Overlay 설정")
        self.setMinimumWidth(900)
        self.setMinimumHeight(700)

        self.build_ui()
        self.bind_events()
        self.load_settings_to_ui()

        set_window_capture_excluded

        self.auto_controller = None

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
        self.trajectory_tab = QWidget()
        self.wind_angle_tab = QWidget()
        self.bounding_tab = QWidget()

        self.tabs.addTab(self.overlay_tab, "오버레이")
        self.tabs.addTab(self.calc_tab, "계산기")
        self.tabs.addTab(self.trajectory_tab, "공궤적")
        self.tabs.addTab(self.wind_angle_tab, "바람각도")
        self.tabs.addTab(self.bounding_tab, "바운딩")

        overlay_root = QVBoxLayout(self.overlay_tab)
        calc_root = QVBoxLayout(self.calc_tab)
        trajectory_root = QVBoxLayout(self.trajectory_tab)
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
        self.build_trajectory_tab(trajectory_root)
        self.build_wind_angle_tab(wind_angle_root)
        self.build_bounding_tab(bounding_root)

    def build_trajectory_tab(self, root):
        desc = QLabel(
            "계산기 탭에서 계산 버튼을 누르면 이 탭의 공 궤적만 갱신됩니다. "
            "계산 후 화면이 자동으로 이동하지 않으므로, 필요할 때 공궤적 탭을 눌러 확인하세요. "
            "위 그래프는 측면 궤적, 아래 그래프는 상단 기준 좌우 휘어짐입니다."
        )
        desc.setWordWrap(True)
        root.addWidget(desc)

        self.trajectory_canvas = ShotTrajectoryCanvas()
        root.addWidget(self.trajectory_canvas, 1)

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

        bounce_group = QGroupBox("착지 후 바운드 / 롤 실험")
        bounce_layout = QGridLayout(bounce_group)

        self.bounce_enabled_check = QCheckBox("계산 결과에 1바운드 + 롤 예상값 추가")

        self.bounce_material_type_combo = QComboBox()
        material_type_items = [
            (0, "Tee"),
            (1, "Fairway"),
            (2, "Green"),
            (3, "Bunker"),
            (4, "Rough"),
            (5, "Snow"),
            (6, "Road"),
            (7, "Ice"),
            (8, "Vector"),
            (9, "Water"),
            (11, "Sand"),
            (12, "Special"),
            (13, "Booster"),
            (14, "OB"),
            (15, "FunObj"),
        ]
        for mt, name in material_type_items:
            self.bounce_material_type_combo.addItem(f"type {mt} - {name}", str(mt))
        self.set_combo_by_data(self.bounce_material_type_combo, "2")

        self.bounce_material_bounce_edit = self.create_calc_line("1.0")
        self.bounce_material_roll_edit = self.create_calc_line("1.0")
        self.bounce_command_bounce_edit = self.create_calc_line("1.0")
        self.bounce_command_roll_edit = self.create_calc_line("1.0")
        self.bounce_mix_index_edit = self.create_calc_line("3.0")

        self.bounce_normal_x_edit = self.create_calc_line("0")
        self.bounce_normal_y_edit = self.create_calc_line("1")
        self.bounce_normal_z_edit = self.create_calc_line("0")

        row = 0
        bounce_layout.addWidget(self.bounce_enabled_check, row, 0, 1, 6)

        row += 1
        bounce_layout.addWidget(QLabel("착지 material type"), row, 0)
        bounce_layout.addWidget(self.bounce_material_type_combo, row, 1)
        bounce_layout.addWidget(QLabel("material bounce(+0x00)"), row, 2)
        bounce_layout.addWidget(self.bounce_material_bounce_edit, row, 3)
        bounce_layout.addWidget(QLabel("material roll(+0x04)"), row, 4)
        bounce_layout.addWidget(self.bounce_material_roll_edit, row, 5)

        row += 1
        bounce_layout.addWidget(QLabel("command bounce"), row, 0)
        bounce_layout.addWidget(self.bounce_command_bounce_edit, row, 1)
        bounce_layout.addWidget(QLabel("command roll"), row, 2)
        bounce_layout.addWidget(self.bounce_command_roll_edit, row, 3)
        bounce_layout.addWidget(QLabel("mix index"), row, 4)
        bounce_layout.addWidget(self.bounce_mix_index_edit, row, 5)

        row += 1
        bounce_layout.addWidget(QLabel("normal x"), row, 0)
        bounce_layout.addWidget(self.bounce_normal_x_edit, row, 1)
        bounce_layout.addWidget(QLabel("normal y"), row, 2)
        bounce_layout.addWidget(self.bounce_normal_y_edit, row, 3)
        bounce_layout.addWidget(QLabel("normal z"), row, 4)
        bounce_layout.addWidget(self.bounce_normal_z_edit, row, 5)

        row += 1
        bounce_help = QLabel(
            "주의: material type별 terrain 계수는 exe에서 확인된 값이지만, "
            "type 번호가 그린/페어웨이/러프/벙커 중 무엇인지는 아직 미확정입니다. "
            "material bounce/roll은 재질 테이블 실측 전이면 1.0으로 두고 type만 바꿔 비교하세요."
        )
        bounce_help.setWordWrap(True)
        bounce_layout.addWidget(bounce_help, row, 0, 1, 6)

        root.addWidget(bounce_group)

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
            "mycella_shot_degree": self.mycella_shot_degree_edit.text().strip(),
            "mycella_align_degree": self.mycella_align_degree_edit.text().strip(),
            "mycella_slope_break": self.mycella_slope_break_edit.text().strip(),
            "yards_to_pb": self.calc_yards_to_pb_edit.text().strip(),
            "yards_to_pba": self.calc_yards_to_pba_edit.text().strip(),
            "yards_to_pba_plus": self.calc_yards_to_pba_plus_edit.text().strip(),
            "board_per_pb": self.calc_board_per_pb_edit.text().strip(),
            "smart_divisor": self.calc_smart_divisor_edit.text().strip(),
            "bounce_enabled": self.bounce_enabled_check.isChecked(),
            "bounce_material_type": self.bounce_material_type_combo.currentData(),
            "bounce_material_bounce": self.bounce_material_bounce_edit.text().strip(),
            "bounce_material_roll": self.bounce_material_roll_edit.text().strip(),
            "bounce_command_bounce": self.bounce_command_bounce_edit.text().strip(),
            "bounce_command_roll": self.bounce_command_roll_edit.text().strip(),
            "bounce_mix_index": self.bounce_mix_index_edit.text().strip(),
            "bounce_normal_x": self.bounce_normal_x_edit.text().strip(),
            "bounce_normal_y": self.bounce_normal_y_edit.text().strip(),
            "bounce_normal_z": self.bounce_normal_z_edit.text().strip(),
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

        self.mycella_shot_degree_edit.setText(str(s["mycella_shot_degree"]))
        self.mycella_align_degree_edit.setText(str(s["mycella_align_degree"]))
        self.mycella_slope_break_edit.setText(str(s["mycella_slope_break"]))

        self.calc_yards_to_pb_edit.setText(str(s["yards_to_pb"]))
        self.calc_yards_to_pba_edit.setText(str(s["yards_to_pba"]))
        self.calc_yards_to_pba_plus_edit.setText(str(s["yards_to_pba_plus"]))
        self.calc_board_per_pb_edit.setText(str(s["board_per_pb"]))
        self.calc_smart_divisor_edit.setText(str(s["smart_divisor"]))

        self.bounce_enabled_check.setChecked(bool(s.get("bounce_enabled", False)))
        self.set_combo_by_data(self.bounce_material_type_combo, str(s.get("bounce_material_type", "7")))
        self.bounce_material_bounce_edit.setText(str(s.get("bounce_material_bounce", "1.0")))
        self.bounce_material_roll_edit.setText(str(s.get("bounce_material_roll", "1.0")))
        self.bounce_command_bounce_edit.setText(str(s.get("bounce_command_bounce", "1.0")))
        self.bounce_command_roll_edit.setText(str(s.get("bounce_command_roll", "1.0")))
        self.bounce_mix_index_edit.setText(str(s.get("bounce_mix_index", "3.0")))
        self.bounce_normal_x_edit.setText(str(s.get("bounce_normal_x", "0")))
        self.bounce_normal_y_edit.setText(str(s.get("bounce_normal_y", "1")))
        self.bounce_normal_z_edit.setText(str(s.get("bounce_normal_z", "0")))

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

    def build_bounce_surface_from_ui(self):
        if SurfacePhysics is None or Vector3D is None:
            raise RuntimeError("pangya_acrisio_with_bounce.py를 불러오지 못해 바운드/롤 실험을 사용할 수 없습니다.")

        material_type = int(self.bounce_material_type_combo.currentData())

        terrain_bounce_factor = get_material_type_bounce_factor(material_type)
        terrain_roll_factor = get_material_type_roll_factor(material_type)

        surface = SurfacePhysics(
            material_bounce=self.read_calc_float(self.bounce_material_bounce_edit, "material bounce", 1.0),
            material_roll=self.read_calc_float(self.bounce_material_roll_edit, "material roll", 1.0),
            terrain_bounce_factor=terrain_bounce_factor,
            terrain_roll_factor=terrain_roll_factor,
            command_bounce=self.read_calc_float(self.bounce_command_bounce_edit, "command bounce", 1.0),
            command_roll=self.read_calc_float(self.bounce_command_roll_edit, "command roll", 1.0),
            bounce_mix_index=self.read_calc_float(self.bounce_mix_index_edit, "mix index", 3.0),
        )

        normal = Vector3D(
            self.read_calc_float(self.bounce_normal_x_edit, "normal x", 0.0),
            self.read_calc_float(self.bounce_normal_y_edit, "normal y", 1.0),
            self.read_calc_float(self.bounce_normal_z_edit, "normal z", 0.0),
        )

        return material_type, surface, normal

    def make_bounce_output_lines(self, result):
        self.last_bounce_result = None

        if not self.bounce_enabled_check.isChecked():
            return []

        if simulate_bounce_from_result is None:
            return [
                "",
                "바운드/롤 실험",
                "pangya_acrisio_with_bounce.py를 찾지 못해 바운드/롤 실험을 건너뜁니다.",
            ]

        material_type, surface, normal = self.build_bounce_surface_from_ui()
        bounce_result = simulate_bounce_from_result(
            result,
            surface=surface,
            normal=normal,
        )
        self.last_bounce_result = bounce_result

        lines = [
            "",
            "바운드/롤 실험",
            f"material type: {material_type} ({get_material_type_name(material_type) if get_material_type_name else '-'})",
            f"terrain bounce/roll: {surface.terrain_bounce_factor:.3f} / {surface.terrain_roll_factor:.3f}",
            f"material bounce/roll: {surface.material_bounce:.3f} / {surface.material_roll:.3f}",
            f"command bounce/roll: {surface.command_bounce:.3f} / {surface.command_roll:.3f}",
            f"최종 bounce_k: {surface.bounce_k:.3f}",
            f"최종 roll_k_base: {surface.roll_k_base:.3f}",
        ]

        if not bounce_result.ok:
            lines.append(f"실패: {bounce_result.message}")
            return lines

        if bounce_result.landing_velocity is not None:
            v = bounce_result.landing_velocity
            lines.append(f"착지 직전 velocity: x={v.x:.4f}, y={v.y:.4f}, z={v.z:.4f}")

        if bounce_result.bounced_velocity is not None:
            v = bounce_result.bounced_velocity
            lines.append(f"바운드 직후 velocity: x={v.x:.4f}, y={v.y:.4f}, z={v.z:.4f}")

        second_landing = None
        roll_stop = None

        for point in bounce_result.points:
            if point.phase == "second_landing":
                second_landing = point
            elif point.phase == "roll_stop":
                roll_stop = point

        last_point = bounce_result.points[-1] if bounce_result.points else None

        if second_landing is not None:
            lines.append(
                f"2차 착지 예상: forward={second_landing.forward_yards:.3f}y, "
                f"lateral={second_landing.lateral_yards:.3f}y"
            )

        if roll_stop is not None:
            lines.append(
                f"롤 정지 예상: forward={roll_stop.forward_yards:.3f}y, "
                f"lateral={roll_stop.lateral_yards:.3f}y"
            )
        elif last_point is not None:
            lines.append(
                f"마지막 계산점: phase={last_point.phase}, "
                f"forward={last_point.forward_yards:.3f}y, lateral={last_point.lateral_yards:.3f}y"
            )

        lines.append(f"시뮬레이션 포인트 수: {len(bounce_result.points)}")
        lines.append("주의: material +0x00/+0x04 실측 전에는 비교/튜닝용 결과입니다.")

        return lines

    def on_calc_clicked(self):
        if calc_shot is None:
            QMessageBox.warning(self, "계산기 오류", "pangya_acrisio.py 모듈을 불러오지 못했습니다.")
            return

        try:
            result = calc_shot(
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
                slope=self.calc_slope_edit.text().strip() or "0",
                line_ball=self.read_calc_float(self.calc_line_ball_edit, "Line ball", 0.0),
                line_ball_random=self.calc_line_ball_random_check.isChecked(),
            )

            if not result.ok:
                self.last_calc_result = None
                self.last_calc_display = None
                self.last_calc_shot_type = None
                self.last_bounce_result = None
                self.update_backspin_button_state()
                if hasattr(self, "trajectory_canvas"):
                    self.trajectory_canvas.clear_trajectory(result.message)
                self.calc_result_box.setPlainText(result.message)
                return

            yards_to_pb = self.read_calc_float(self.calc_yards_to_pb_edit, "YARDS_TO_PB", 0.2167)
            yards_to_pba = self.read_calc_float(self.calc_yards_to_pba_edit, "YARDS_TO_PBA", 0.8668)
            yards_to_pba_plus = self.read_calc_float(self.calc_yards_to_pba_plus_edit, "YARDS_TO_PBA+", 1.032)
            board_per_pb = self.read_calc_float(self.calc_board_per_pb_edit, "장판 환산값(PB당)", 0.2121)
            smart_divisor = self.read_calc_float(self.calc_smart_divisor_edit, "스마트 나눗값", 4.0)

            if yards_to_pb == 0 or yards_to_pba == 0 or yards_to_pba_plus == 0 or smart_divisor == 0:
                raise ValueError("표시 단위 값은 0이 될 수 없습니다.")

            # pangya_acrisio.py의 result.pb/result.real_pb는 원본 JS 기본값 0.2167 기준 결과다.
            # GUI에서 상수를 조정할 수 있도록, 먼저 다시 yard 단위로 되돌린 뒤 사용자가 입력한 상수로 재환산한다.
            pb_yards = result.pb * 0.2167
            real_pb_yards = result.real_pb * 0.2167

            custom_pb = pb_yards / yards_to_pb
            custom_real_pb = real_pb_yards / yards_to_pb
            custom_pba = pb_yards / yards_to_pba
            custom_pba_plus = pb_yards / yards_to_pba_plus

            # 기존 한국어 계산기/오버레이 장판값에 맞추기 위한 표시용 값.
            # 예: PB=8.41, board_per_pb=0.2121이면 장판=1.784
            board_cells = abs(result.pb) * board_per_pb
            smart_cells = board_cells / smart_divisor

            self.last_calc_result = result
            self.last_calc_display = {
                "board_cells": board_cells,
                "smart_cells": smart_cells,
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
            self.last_calc_shot_type = self.calc_shot_combo.currentData()
            self.update_backspin_button_state()

            trajectory_points = []
            if simulate_trajectory_from_result is not None:
                trajectory_points = simulate_trajectory_from_result(result)

            if hasattr(self, "trajectory_canvas"):
                self.trajectory_canvas.set_trajectory(trajectory_points, result, None)
                # 계산 결과는 공궤적 탭에 업데이트만 한다.
                # 사용자가 계산기 탭에서 결과를 먼저 확인할 수 있도록 자동 탭 이동은 하지 않는다.

            output = [                
                f"권장 파워: {result.power_percent:.1f}%",
                f"샷 거리: {result.shot_yards:.1f}y",
                "",
                "실사용 표시",
                f"장판: {board_cells:.3f}칸",
                f"스마트: {smart_cells:.2f}칸",
                "",
                "Acrisio 원본 기준",
                f"조준 PB: {result.pb:.2f}pb",
                f"Real PB: {result.real_pb:.2f}pb",
                f"Smart: {result.smart}",
                f"Desvio: {result.desvio_yards:.6f}y",
                "",
                "사용자 환산 기준",
                f"Custom PB: {custom_pb:.2f}pb  (YARDS_TO_PB={yards_to_pb})",
                f"Custom Real PB: {custom_real_pb:.2f}pb",
                f"Custom PBA: {custom_pba:.2f}pba  (YARDS_TO_PBA={yards_to_pba})",
                f"Custom PBA+: {custom_pba_plus:.2f}pba+  (YARDS_TO_PBA+={yards_to_pba_plus})",
                f"장판 환산값(PB당): {board_per_pb}",
                f"스마트 나눗값: {smart_divisor}",
                f"Aim 반복: {result.aim_iterations}",
                "",
                "입력 요약",
                f"Club={self.calc_club_combo.currentText()}, Shot={self.calc_shot_combo.currentText()}, PowerShot={self.calc_power_shot_combo.currentText()}",
                f"Distance={self.calc_distance_edit.text()}, Height={self.calc_height_edit.text()}, Wind={self.calc_wind_edit.text()}, Degree={self.calc_degree_edit.text()}",
                f"Ground={self.calc_ground_edit.text()}, Spin={self.calc_spin_edit.text()}, Curve={self.calc_curve_edit.text()}, Slope={self.calc_slope_edit.text()}",
            ]

            output.extend(self.make_bounce_output_lines(result))

            if hasattr(self, "trajectory_canvas"):
                self.trajectory_canvas.set_trajectory(trajectory_points, result, self.last_bounce_result)

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

            original_board_cells = display["board_cells"]
            original_smart_cells = display["smart_cells"]
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
                f"장판: {backspin_board_cells:.3f}칸",
                f"스마트: {backspin_smart_cells:.2f}칸",
                "",
                "보정 전 Dunk 계산값",
                f"기존 권장 파워: {original_power_percent:.1f}%",
                f"기존 샷 거리: {original_shot_yards:.1f}y",
                f"기존 장판: {original_board_cells:.3f}칸",
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

        self.update_status()

    def on_stop_clicked(self):
        if self.auto_controller is not None:
            self.auto_controller.stop()

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
