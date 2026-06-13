# -*- coding: utf-8 -*-
"""Pangya game overlay widget.

분리 전 pangya_overlay_gui_with_calculator.py의 PangyaOverlay 클래스를 옮긴 파일입니다.
"""

from pangya_overlay_common import *

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
        """
        계산기 탭에서 마지막으로 계산한 결과를 게임 화면 좌상단에 표시한다.
        Shot/PS 퀵 선택 패널을 위쪽에 두는 경우, 결과 텍스트는 그 아래로 내려서 겹치지 않게 한다.
        """
        if not self.settings.get("show_result", True):
            return

        if self.calc_state is None:
            return

        lines = []

        # 새 방식: 계산기에서 넘겨주는 dict 기반 표시
        if isinstance(self.calc_state, dict):
            lines = [str(v) for v in self.calc_state.get("lines", []) if str(v).strip()]

        # 구버전 호환: auto_input / shot_results 구조가 들어온 경우
        elif hasattr(self.calc_state, "auto_input") and hasattr(self.calc_state, "shot_results"):
            detected = self.calc_state.auto_input
            lines = [
                f"거리: {detected.distance if detected.distance is not None else '-'}y",
                f"고저: {detected.height if detected.height is not None else '-'}",
                f"바람: {detected.wind if detected.wind is not None else '-'}",
                f"각도: {detected.degree if detected.degree is not None else '-'}",
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

        if not lines:
            return

        scale = max(0.75, min(scale_x, scale_y))
        x = int(28 * scale_x)

        # 퀵 선택 패널이 켜져 있으면 결과 박스 자체가 패널 아래에서 시작하도록 내린다.
        # 기존에는 텍스트 baseline만 내려서 배경 박스 상단이 퀵 패널과 살짝 겹칠 수 있었다.
        quick_enabled = bool(self.settings.get("show_quick_overlay_controls", True))
        quick_h = max(62, int(70 * scale)) if quick_enabled else 0
        quick_gap = max(18, int(22 * scale)) if quick_enabled else 0
        quick_top = int(72 * scale_y)

        line_h = max(18, int(22 * scale))

        font = QFont("Malgun Gothic")
        font.setPixelSize(max(15, int(18 * scale)))
        font.setBold(True)
        painter.setFont(font)
        fm = painter.fontMetrics()

        # y는 텍스트 baseline이다. 배경 박스 top이 quick_bottom + gap보다 아래가 되게 계산한다.
        bg_pad_y = max(6, int(7 * scale))
        y = quick_top + quick_h + quick_gap + fm.ascent() + bg_pad_y

        max_text_w = 0
        for text in lines:
            try:
                max_text_w = max(max_text_w, fm.horizontalAdvance(text))
            except Exception:
                max_text_w = max(max_text_w, len(text) * int(10 * scale))

        bg_pad_x = max(8, int(10 * scale))
        bg_x = max(0, x - bg_pad_x)
        bg_y = max(0, y - fm.ascent() - bg_pad_y)
        bg_w = min(
            max(220, max_text_w + bg_pad_x * 2),
            max(220, self.width() - bg_x - int(10 * scale)),
        )
        bg_h = len(lines) * line_h + bg_pad_y * 2

        # 반투명 배경 박스. 기존보다 조금 더 읽기 쉽게 하되 게임 화면을 많이 가리지 않게 한다.
        painter.setPen(QPen(QColor(255, 255, 255, 55), 1))
        painter.setBrush(QColor(0, 0, 0, 88))
        painter.drawRoundedRect(bg_x, bg_y, bg_w, bg_h, 8, 8)

        # 왼쪽 얇은 강조선
        painter.setPen(QPen(QColor(255, 210, 30, 210), max(2, int(3 * scale))))
        painter.drawLine(bg_x + 2, bg_y + 7, bg_x + 2, bg_y + bg_h - 7)

        for idx, text in enumerate(lines):
            ty = y + idx * line_h

            # 첫 줄은 제목으로 보고 노란색 강조.
            # 계산 실패/대기 상태도 눈에 잘 들어오게 약간 따뜻한 색을 쓴다.
            if idx == 0:
                fg = QColor(255, 225, 80, 255)
            elif "실패" in text or "오류" in text or "대기" in text:
                fg = QColor(255, 230, 145, 255)
            elif "spin/curve" in text or text.startswith("club") or text.startswith("ground"):
                fg = QColor(210, 240, 255, 255)
            else:
                fg = QColor(255, 255, 255, 250)

            # 그림자 2중 처리
            painter.setPen(QPen(QColor(0, 0, 0, 245), 1))
            painter.drawText(x + 2, ty + 2, text)
            painter.drawText(x - 1, ty + 1, text)

            painter.setPen(QPen(fg, 1))
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

        # psutil EnumWindows/process scan은 비용이 크므로 매 프레임 수행하지 않는다.
        # 기존 hwnd가 살아 있으면 재사용하고, 사라졌을 때만 다시 찾는다.
        if not self.target_hwnd or not win32gui.IsWindow(self.target_hwnd):
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

        #디버그 용 주석
        # print("========== Pangya Overlay Debug ==========")
        # print(f"Target EXE        : {self.settings['target_exe']}")
        # print(f"Target HWND       : {self.target_hwnd}")
        # print(f"Overlay HWND      : {self.overlay_hwnd}")
        # print(f"Target DPI        : {target_dpi}")
        # print(f"Overlay DPI       : {overlay_dpi}")
        # print(f"ClientOnScreen    : left={left}, top={top}, right={right}, bottom={bottom}")
        # print(f"ClientSize        : width={client_width}, height={client_height}")
        # print(f"BASE              : w={self.settings['base_w']}, h={self.settings['base_h']}")
        # print(f"NativeLast        : x={self.last_left}, y={self.last_top}, width={self.last_width}, height={self.last_height}")
        # print(f"CUP_BASE          : x={self.settings['cup_base_x']}, y={self.settings['cup_base_y']}")
        # print(f"GRID              : -{grid_half_value:.2f} ~ +{grid_half_value:.2f}")
        # print(f"SLOPE             : x={self.settings['slope_center_base_x']}, y={self.settings['slope_center_base_y']}, half={self.settings['slope_line_half_width']}")
        # print(
        #     f"WIND              : x={self.settings['wind_center_base_x']}, "
        #     f"y={self.settings['wind_center_base_y']}, "
        #     f"radius={self.settings['wind_radius']}")
        # print("==========================================")

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
