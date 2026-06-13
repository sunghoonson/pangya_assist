# -*- coding: utf-8 -*-
"""Clickable quick Shot / PowerShot / LOCK overlay.

분리 전 pangya_overlay_gui_with_calculator.py의 PangyaQuickControlOverlay 클래스를 옮긴 파일입니다.
"""

from pangya_overlay_common import *

class PangyaQuickControlOverlay(QWidget):
    """
    게임 오버레이 전체를 클릭 가능하게 만들면 게임 입력을 막게 된다.
    그래서 일반 오버레이는 그대로 마우스 투과 상태로 두고,
    좌상단 결과 아래에 작은 별도 topmost 창만 올려 Shot / PowerShot 선택을 받는다.
    """
    SHOT_ITEMS = [
        ("Dunk", "DUNK"),
        ("Tomahawk", "TOMAHAWK"),
        ("Spike", "SPIKE"),
        ("Cobra", "COBRA"),
    ]
    POWER_SHOT_ITEMS = [
        ("No PS", "NO_POWER_SHOT"),
        ("1 PS", "ONE_POWER_SHOT"),
        ("2 PS", "TWO_POWER_SHOT"),
        ("15y", "ITEM_15_POWER_SHOT"),
    ]

    def __init__(self, control_window):
        super().__init__(None)
        self.control_window = control_window
        self.hit_items = []
        self.hover_item = None
        self.quick_hwnd = None
        self._style_applied_key = None
        self._capture_exclude_key = None
        self._last_geometry_tuple = None

        self.setWindowFlags(
            Qt.FramelessWindowHint |
            Qt.WindowStaysOnTopHint |
            Qt.Tool |
            Qt.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setMouseTracking(True)
        self.hide()

        self.quick_hwnd = int(self.winId())
        self.apply_window_style()
        self.apply_capture_exclude_setting()

    def apply_window_style(self, force=False):
        try:
            self.quick_hwnd = int(self.winId())
        except Exception:
            pass
        if not self.quick_hwnd:
            return False

        key = int(self.quick_hwnd)
        if not force and self._style_applied_key == key:
            return True

        try:
            ex_style = win32gui.GetWindowLong(self.quick_hwnd, win32con.GWL_EXSTYLE)
            ex_style |= win32con.WS_EX_LAYERED
            ex_style |= win32con.WS_EX_TOOLWINDOW
            ex_style |= win32con.WS_EX_TOPMOST
            if hasattr(win32con, "WS_EX_NOACTIVATE"):
                ex_style |= win32con.WS_EX_NOACTIVATE
            # 중요: WS_EX_TRANSPARENT는 넣지 않는다. 이 작은 창은 클릭을 받아야 한다.
            win32gui.SetWindowLong(self.quick_hwnd, win32con.GWL_EXSTYLE, ex_style)
            self._style_applied_key = key
            return True
        except Exception as e:
            print(f"[WARN] quick overlay style 적용 실패: {e}")
            return False

    def apply_capture_exclude_setting(self, force=False):
        # SetWindowDisplayAffinity는 생각보다 비용이 있으므로 매 위치 갱신마다 호출하지 않는다.
        # HWND/설정값이 바뀌었거나 show 직후 1회만 적용한다.
        try:
            self.quick_hwnd = int(self.winId())
        except Exception:
            pass
        if not self.quick_hwnd:
            return False

        settings = getattr(self.control_window, "settings", {}) or {}
        enabled = bool(settings.get("capture_exclude_enabled", True))
        key = (int(self.quick_hwnd), enabled)
        if not force and self._capture_exclude_key == key:
            return True

        ok = set_window_capture_excluded(self.quick_hwnd, enabled)
        if ok:
            self._capture_exclude_key = key
        return ok

    def current_shot(self):
        cw = self.control_window
        if hasattr(cw, "calc_shot_combo"):
            return cw.calc_shot_combo.currentData()
        return None

    def current_power_shot(self):
        cw = self.control_window
        if hasattr(cw, "calc_power_shot_combo"):
            return cw.calc_power_shot_combo.currentData()
        return None

    def current_lock_enabled(self):
        cw = self.control_window
        return bool(getattr(cw, "calc_lock_enabled", False))

    def _draw_lock_button(self, painter, y, row_h, gap_y):
        scale = max(0.85, min(self.width() / 520.0, 1.6))
        locked = self.current_lock_enabled()
        text = "LOCKED" if locked else "LOCK"

        font = QFont("Malgun Gothic")
        font.setPixelSize(max(13, int(15 * scale)))
        font.setBold(True)
        painter.setFont(font)
        fm = painter.fontMetrics()

        w = max(int(82 * scale), fm.horizontalAdvance(text) + int(22 * scale))
        h = row_h * 2 + gap_y
        x = max(int(8 * scale), self.width() - w - int(8 * scale))

        is_hover = self.hover_item == ("lock", "TOGGLE")

        if locked:
            bg = QColor(255, 215, 35, 235)
            fg = QColor(20, 20, 20, 255)
            border = QColor(255, 250, 150, 255)
        elif is_hover:
            bg = QColor(255, 255, 255, 105)
            fg = QColor(255, 255, 255, 255)
            border = QColor(255, 255, 255, 180)
        else:
            bg = QColor(0, 0, 0, 135)
            fg = QColor(245, 245, 245, 240)
            border = QColor(255, 255, 255, 125)

        painter.setPen(QPen(border, 1))
        painter.setBrush(bg)
        painter.drawRoundedRect(x, y, w, h, 6, 6)

        tx = x + max(8, (w - fm.horizontalAdvance(text)) // 2)
        ty = y + (h + fm.ascent() - fm.descent()) // 2

        painter.setPen(QPen(QColor(0, 0, 0, 190), 1))
        painter.drawText(tx + 1, ty + 1, text)
        painter.setPen(QPen(fg, 1))
        painter.drawText(tx, ty, text)

        self.hit_items.append((x, y, w, h, "lock", "TOGGLE"))

    def _draw_button_row(self, painter, label, items, selected_value, y, row_kind):
        self.hit_items = [item for item in self.hit_items if item[4] != row_kind]

        scale = max(0.85, min(self.width() / 520.0, 1.6))
        font = QFont("Malgun Gothic")
        font.setPixelSize(max(13, int(15 * scale)))
        font.setBold(True)
        painter.setFont(font)
        fm = painter.fontMetrics()

        x = int(8 * scale)
        label_w = int(48 * scale)
        row_h = max(22, int(26 * scale))
        gap = max(4, int(6 * scale))

        painter.setPen(QPen(QColor(0, 0, 0, 230), 1))
        painter.drawText(x + 1, y + row_h - 7 + 1, label)
        painter.setPen(QPen(QColor(235, 235, 235, 250), 1))
        painter.drawText(x, y + row_h - 7, label)
        x += label_w

        for text, value in items:
            text_w = fm.horizontalAdvance(text)
            w = max(int(52 * scale), text_w + int(18 * scale))
            h = row_h
            is_selected = value == selected_value
            is_hover = self.hover_item == (row_kind, value)

            if is_selected:
                bg = QColor(255, 215, 35, 235)
                fg = QColor(20, 20, 20, 255)
                border = QColor(255, 250, 150, 255)
            elif is_hover:
                bg = QColor(255, 255, 255, 105)
                fg = QColor(255, 255, 255, 255)
                border = QColor(255, 255, 255, 180)
            else:
                bg = QColor(0, 0, 0, 135)
                fg = QColor(245, 245, 245, 240)
                border = QColor(255, 255, 255, 125)

            painter.setPen(QPen(border, 1))
            painter.setBrush(bg)
            painter.drawRoundedRect(x, y, w, h, 5, 5)

            painter.setPen(QPen(QColor(0, 0, 0, 190), 1))
            painter.drawText(x + 10 + 1, y + h - 7 + 1, text)
            painter.setPen(QPen(fg, 1))
            painter.drawText(x + 10, y + h - 7, text)

            self.hit_items.append((x, y, w, h, row_kind, value))
            x += w + gap

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        # 아주 옅은 배경만 둬서 텍스트 가독성을 확보한다.
        painter.setPen(QPen(QColor(255, 255, 255, 85), 1))
        painter.setBrush(QColor(0, 0, 0, 92))
        painter.drawRoundedRect(0, 0, max(1, self.width() - 1), max(1, self.height() - 1), 8, 8)

        self.hit_items = []
        scale = max(0.85, min(self.width() / 520.0, 1.6))
        row_h = max(22, int(26 * scale))
        top = max(5, int(6 * scale))
        gap_y = max(4, int(5 * scale))

        self._draw_button_row(
            painter,
            "Shot",
            self.SHOT_ITEMS,
            self.current_shot(),
            top,
            "shot",
        )
        self._draw_button_row(
            painter,
            "PS",
            self.POWER_SHOT_ITEMS,
            self.current_power_shot(),
            top + row_h + gap_y,
            "power_shot",
        )
        self._draw_lock_button(painter, top, row_h, gap_y)

    def _hit_test(self, pos):
        px = pos.x()
        py = pos.y()
        for x, y, w, h, kind, value in self.hit_items:
            if x <= px <= x + w and y <= py <= y + h:
                return kind, value
        return None

    def mouseMoveEvent(self, event):
        hit = self._hit_test(event.position().toPoint())
        if hit != self.hover_item:
            self.hover_item = hit
            self.setCursor(Qt.PointingHandCursor if hit else Qt.ArrowCursor)
            self.update()

    def leaveEvent(self, event):
        if self.hover_item is not None:
            self.hover_item = None
            self.setCursor(Qt.ArrowCursor)
            self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        hit = self._hit_test(event.position().toPoint())
        if not hit:
            return

        kind, value = hit
        if kind == "shot":
            self.control_window.select_quick_shot(value)
        elif kind == "power_shot":
            self.control_window.select_quick_power_shot(value)
        elif kind == "lock":
            self.control_window.toggle_calc_lock()
        self.update()
