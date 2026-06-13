# -*- coding: utf-8 -*-
"""Main Pangya Assist control window.

분리 전 pangya_overlay_gui_with_calculator.py의 PangyaControlWindow 클래스를 옮긴 파일입니다.
계산기 UI, live JSON 감시, DIFF/LOCK, 설정 저장/적용 로직을 포함합니다.
"""

from pangya_overlay_common import *
from pangya_quick_control_overlay import PangyaQuickControlOverlay

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

        # 거리/고저차도 DLL live JSON 방식으로 읽는다.
        # 기존 Python probe hook은 중지/재연결 문제가 있어서 더 이상 사용하지 않는다.
        self.memory_probe = None
        self.memory_timer = QTimer(self)
        self.memory_timer.timeout.connect(self.update_memory_values_from_game)
        self.last_memory_distance = None
        self.last_memory_height = None
        self.last_memory_live_tick = None
        self.last_memory_live_path = None

        self.ground_live_timer = QTimer(self)
        self.ground_live_timer.timeout.connect(self.update_ground_live_from_file)
        self.last_ground_live_tick = None
        self.last_ground_live_value = None
        self.last_ground_live_path = None

        self.club_live_timer = QTimer(self)
        self.club_live_timer.timeout.connect(self.update_club_live_from_file)
        self.last_club_live_tick = None
        self.last_club_live_value = None
        self.last_club_live_path = None

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

        self.spin_curve_live_timer = QTimer(self)
        self.spin_curve_live_timer.timeout.connect(self.update_spin_curve_live_from_file)
        self.last_spin_curve_live_tick = None
        self.last_spin_curve_live_path = None
        self.last_spin_curve_live_value = None

        # DIFF/LINE live JSON은 조준 중 자주 변하므로 계산 재실행 없이 오버레이 줄만 갱신한다.
        self.diff_live_timer = QTimer(self)
        self.diff_live_timer.timeout.connect(self.update_diff_live_from_file)
        self.last_diff_live_tick = None
        self.last_diff_live_path = None
        self.last_diff_live_value = None
        self.last_overlay_base_lines_no_diff = None
        self.last_overlay_diff_targets = []
        self.last_diff_overlay_signature = None

        # LOCK은 계산 결과/DIFF target을 현재 시점에 고정한다.
        # 조준 중 캐릭터 방향 회전으로 wind degree/slope live 값이 변해도 자동 재계산하지 않고,
        # DIFF만 lock 시점의 장판 기준으로 계속 갱신한다.
        self.calc_lock_enabled = False
        self.calc_lock_snapshot = None
        self.calc_lock_distance = None

        # live JSON 읽기 캐시: 같은 파일/mtime/size이면 json.load를 반복하지 않는다.
        self._live_json_cache = {}
        # live JSON 경로 캐시: 매 tick마다 ProjectG127.exe 경로/후보 경로를 다시 찾지 않는다.
        self._live_path_cache = {}

        # live JSON은 오버레이 Start/Stop이나 메모리 연결 상태와 독립적으로 감시한다.
        # 기존 버전은 메모리 중지/Start 순서에 따라 wind/slope timer가 꺼진 채 남는 문제가 있었다.
        self.live_watchdog_timer = QTimer(self)
        self.live_watchdog_timer.timeout.connect(self.ensure_live_timers)
        self.live_watchdog_timer.start(1000)
        QTimer.singleShot(0, self.ensure_live_timers)

        # 결과 오버레이 자동 갱신
        # 계산 버튼을 누르지 않아도 계산기 입력값 / live JSON 값이 바뀌면
        # 좌상단 결과 오버레이를 자동으로 다시 계산한다.
        self.last_auto_result_signature = None
        self.last_auto_result_error = None
        self._auto_result_refresh_scheduled = False
        self.auto_result_timer = QTimer(self)
        self.auto_result_timer.timeout.connect(self.refresh_auto_result_overlay)
        self.auto_result_timer.start(900)
        QTimer.singleShot(300, self.refresh_auto_result_overlay)

        # 좌상단 Shot / PowerShot 클릭 퀵 오버레이.
        # 일반 오버레이는 마우스 투과 상태를 유지하고, 이 작은 창만 클릭을 받는다.
        self.quick_overlay = PangyaQuickControlOverlay(self)
        self.quick_overlay_timer = QTimer(self)
        self.quick_overlay_timer.timeout.connect(self.update_quick_overlay_position)
        self.quick_overlay_timer.start(250)
        QTimer.singleShot(500, self.update_quick_overlay_position)

        # 숫자 OCR 자동 인식은 현재 보류.
        # 바람각도는 별도 캡처/클릭 방식으로 처리한다.
        # if PangyaAutoDetectController is not None:
        #     self.auto_controller = PangyaAutoDetectController(
        #         overlay=self.overlay,
        #         get_window_rect_func=self.overlay.get_current_window_rect,
        #         parent=self,
        #     )

        #self.register_hotkey_from_settings()

    def schedule_auto_result_refresh(self, delay_ms=20):
        """퀵 버튼 클릭 직후 UI 색상 변경을 먼저 반영하고 계산은 짧게 뒤로 미룬다."""
        if getattr(self, "_auto_result_refresh_scheduled", False):
            return
        self._auto_result_refresh_scheduled = True

        def _run():
            self._auto_result_refresh_scheduled = False
            self.refresh_auto_result_overlay()

        QTimer.singleShot(delay_ms, _run)

    def get_current_distance_float_for_lock(self):
        """LOCK 자동 해제 기준으로 쓸 현재 남은거리 값을 얻는다."""
        try:
            if self.last_memory_distance is not None:
                return float(self.last_memory_distance)
        except Exception:
            pass

        try:
            if hasattr(self, "calc_distance_edit"):
                text = self.calc_distance_edit.text().strip()
                if text:
                    return float(text)
        except Exception:
            pass

        return None

    def lock_current_calc_result(self):
        """현재 계산 결과와 DIFF target을 고정한다."""
        if calc_shot is None:
            return

        # lock을 걸기 직전에 한 번 최신 값으로 계산해서 기준 target을 확정한다.
        was_locked = bool(getattr(self, "calc_lock_enabled", False))
        self.calc_lock_enabled = False
        self.last_auto_result_signature = None
        self.refresh_auto_result_overlay()

        base_lines = list(self.last_overlay_base_lines_no_diff or [])
        diff_targets = [dict(t) for t in (self.last_overlay_diff_targets or [])]

        self.calc_lock_enabled = True
        self.calc_lock_distance = self.get_current_distance_float_for_lock()
        self.calc_lock_snapshot = {
            "base_lines": base_lines,
            "diff_targets": diff_targets,
            "distance": self.calc_lock_distance,
            "created_at": time.time(),
        }
        self.last_diff_overlay_signature = None

        # memory_auto가 꺼져 있어도 lock 자동 해제를 위해 거리 live timer는 켜둔다.
        if hasattr(self, "memory_timer") and not self.memory_timer.isActive():
            self.memory_timer.start(300)

        self.refresh_diff_overlay_only()
        if hasattr(self, "quick_overlay"):
            self.quick_overlay.update()

    def unlock_calc_result(self, reason=None, refresh=True):
        """LOCK을 해제하고 실시간 자동 계산을 다시 허용한다."""
        if not bool(getattr(self, "calc_lock_enabled", False)):
            return

        self.calc_lock_enabled = False
        self.calc_lock_snapshot = None
        self.calc_lock_distance = None
        self.last_auto_result_signature = None
        self.last_diff_overlay_signature = None

        #if reason:
            #print(f"[INFO] 계산 LOCK 해제: {reason}")

        if hasattr(self, "quick_overlay"):
            self.quick_overlay.update()

        if refresh:
            self.schedule_auto_result_refresh(20)

    def toggle_calc_lock(self):
        """좌상단 LOCK 버튼 토글."""
        if bool(getattr(self, "calc_lock_enabled", False)):
            self.unlock_calc_result("manual", refresh=True)
        else:
            self.lock_current_calc_result()

    def maybe_unlock_calc_lock_by_distance(self, current_distance):
        """샷 이후 남은거리가 바뀌면 LOCK을 자동으로 해제한다."""
        if not bool(getattr(self, "calc_lock_enabled", False)):
            return

        try:
            ref_distance = self.calc_lock_distance
            if ref_distance is None:
                snapshot = self.calc_lock_snapshot or {}
                ref_distance = snapshot.get("distance")
            if ref_distance is None:
                return

            delta = abs(float(current_distance) - float(ref_distance))
            if delta >= LOCK_AUTO_UNLOCK_DISTANCE_DELTA:
                self.unlock_calc_result(f"distance changed {float(ref_distance):.2f} -> {float(current_distance):.2f}", refresh=True)
        except Exception as e:
            print(f"[WARN] LOCK 거리 변화 감지 실패: {e}")

    def select_quick_shot(self, shot_value):
        """좌상단 퀵 오버레이에서 Shot을 클릭했을 때 계산기 콤보와 결과를 동기화한다."""
        if not hasattr(self, "calc_shot_combo"):
            return
        idx = self.calc_shot_combo.findData(shot_value)
        if idx >= 0 and self.calc_shot_combo.currentIndex() != idx:
            self.calc_shot_combo.setCurrentIndex(idx)
        self.last_auto_result_signature = None
        self.update_backspin_button_state()
        if hasattr(self, "quick_overlay"):
            self.quick_overlay.update()
        self.schedule_auto_result_refresh(20)

    def select_quick_power_shot(self, power_shot_value):
        """좌상단 퀵 오버레이에서 PowerShot을 클릭했을 때 계산기 콤보와 결과를 동기화한다."""
        if not hasattr(self, "calc_power_shot_combo"):
            return
        idx = self.calc_power_shot_combo.findData(power_shot_value)
        if idx >= 0 and self.calc_power_shot_combo.currentIndex() != idx:
            self.calc_power_shot_combo.setCurrentIndex(idx)
        self.last_auto_result_signature = None
        if hasattr(self, "quick_overlay"):
            self.quick_overlay.update()
        self.schedule_auto_result_refresh(20)

    def on_calc_power_shot_changed(self):
        self.last_auto_result_signature = None
        if hasattr(self, "quick_overlay"):
            self.quick_overlay.update()
        self.schedule_auto_result_refresh(20)

    def update_quick_overlay_position(self):
        """게임창 좌상단 상단부에 클릭 가능한 Shot/PS 창을 붙인다.

        이 함수는 250ms마다 돌지만 비싼 WinAPI 호출은 위치/표시 상태가 바뀔 때만 수행한다.
        """
        qo = getattr(self, "quick_overlay", None)
        if qo is None:
            return

        try:
            enabled = bool(self.settings.get("show_quick_overlay_controls", True))
            if hasattr(self, "show_quick_controls_check"):
                enabled = self.show_quick_controls_check.isChecked()

            if not enabled or not self.overlay.is_running or not self.overlay.target_hwnd:
                if qo.isVisible():
                    qo.hide()
                return

            if not bool(self.settings.get("show_result", True)):
                if qo.isVisible():
                    qo.hide()
                return

            try:
                (
                    left, top, right, bottom,
                    window_left, window_top, window_right, window_bottom,
                    client_left, client_top, client_right, client_bottom
                ) = get_client_rect_on_screen(self.overlay.target_hwnd)
            except Exception:
                if qo.isVisible():
                    qo.hide()
                return

            width = right - left
            height = bottom - top
            if width <= 0 or height <= 0:
                if qo.isVisible():
                    qo.hide()
                return

            base_w = max(1, int(self.settings.get("base_w", BASE_W)))
            base_h = max(1, int(self.settings.get("base_h", BASE_H)))
            scale_x = width / base_w
            scale_y = height / base_h
            scale = max(0.75, min(scale_x, scale_y))

            panel_x = int(28 * scale_x)
            panel_y = int(72 * scale_y)

            qx = left + panel_x
            qy = top + panel_y
            qw = max(500, int(560 * scale))
            qh = max(62, int(70 * scale))
            geom = (int(qx), int(qy), int(qw), int(qh))

            became_visible = False
            if not qo.isVisible():
                qo.setGeometry(*geom)
                qo._last_geometry_tuple = geom
                qo.apply_window_style()
                qo.show()
                qo.apply_capture_exclude_setting(force=True)
                qo.raise_()
                qo.update()
                became_visible = True
            else:
                if qo._last_geometry_tuple != geom:
                    qo.setGeometry(*geom)
                    qo._last_geometry_tuple = geom
                    qo.raise_()
                    qo.update()

            # 표시 중인 상태에서는 매 tick마다 style/affinity/update를 반복하지 않는다.
            # 캡처 제외는 show 직후 1회와 체크박스 변경 시에만 force 적용한다.
            if became_visible:
                QTimer.singleShot(0, lambda: qo.apply_capture_exclude_setting(force=True))

        except Exception as e:
            print(f"[WARN] quick overlay position update 실패: {e}")
            try:
                if qo.isVisible():
                    qo.hide()
            except Exception:
                pass

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
        self.show_result_check = QCheckBox("결과")
        self.show_quick_controls_check = QCheckBox("샷/PS 퀵선택")
        self.capture_exclude_check = QCheckBox("윈도우 캡처/녹화 제외")

        visible_layout.addWidget(self.show_cup_check)
        visible_layout.addWidget(self.show_grid_check)
        visible_layout.addWidget(self.show_wind_check)
        visible_layout.addWidget(self.show_slope_check)
        visible_layout.addWidget(self.show_result_check)
        visible_layout.addWidget(self.show_quick_controls_check)
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

        self.memory_auto_check = QCheckBox("거리/고저차 자동 입력(DLL live)")
        self.ground_live_auto_check = QCheckBox("지면 자동 입력(DLL live)")
        self.club_live_auto_check = QCheckBox("클럽 자동 입력(DLL live)")
        self.wind_live_auto_check = QCheckBox("바람/각도 자동 입력(DLL live)")
        self.slope_live_auto_check = QCheckBox("기울기 단일 후보 자동 입력(DLL live, 저부하)")
        self.spin_curve_live_auto_check = QCheckBox("스핀/커브 자동 입력(DLL live)")
        self.diff_live_auto_check = QCheckBox("DIFF 표시(DLL live)")
        self.diff_live_invert_check = QCheckBox("DIFF 부호 반전")
        self.slope_live_mode_combo = QComboBox()
        self.slope_live_mode_combo.addItem("추천 후보: R0C- = -R0C / 0.00875 (자동/저부하)", "R0C_MINUS")
        self.slope_live_mode_combo.addItem("수동 계산 버튼 전용: X/Y 6개 후보 비교", "XY_COMPARE")
        self.slope_live_mode_combo.addItem("수동 계산 버튼 전용: Result Matrix 8개 후보 비교", "MATRIX_COMPARE")
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
        self.slope_live_mode_combo.addItem("수동 계산 버튼 전용: 구버전 4개 비교", "SIGN_COMPARE")
        self.slope_live_mode_combo.addItem("수동 계산 버튼 전용: 구버전 A/B 비교", "SCALAR_COMPARE")
        self.slope_live_mode_combo.addItem("자동 입력 안 함", "OFF")
        self.memory_connect_btn = QPushButton("거리/고저 live 시작")
        self.memory_disconnect_btn = QPushButton("거리/고저 live 중지")
        self.memory_status_label = QLabel("상태: live 감시 안 됨")
        self.memory_distance_label = QLabel("거리: -")
        self.memory_height_label = QLabel("고저: -")
        self.ground_live_label = QLabel("지면: -")
        self.club_live_label = QLabel("클럽: -")
        self.wind_live_label = QLabel("바람/signed각도: -")
        self.slope_live_label = QLabel("기울기 후보: -")
        self.spin_curve_live_label = QLabel("스핀/커브: -")
        self.diff_live_label = QLabel("DIFF: -")
        # 실사용 단계에서는 메모리/live 디버그 라벨 숨김
        self.memory_distance_label.setVisible(False)
        self.memory_height_label.setVisible(False)
        self.ground_live_label.setVisible(False)
        self.club_live_label.setVisible(False)
        self.wind_live_label.setVisible(False)
        self.slope_live_label.setVisible(False)
        self.spin_curve_live_label.setVisible(False)
        self.diff_live_label.setVisible(False)
        self.distance_height_live_path_edit = QLineEdit()
        self.distance_height_live_path_edit.setPlaceholderText("비워두면 ProjectG127.exe 폴더의 logs\\pangya_distance_height_live.json 자동 탐색")
        self.ground_live_path_edit = QLineEdit()
        self.ground_live_path_edit.setPlaceholderText("비워두면 ProjectG127.exe 폴더의 logs\\pangya_ground_live.json 자동 탐색")
        self.club_live_path_edit = QLineEdit()
        self.club_live_path_edit.setPlaceholderText("비워두면 ProjectG127.exe 폴더의 logs\\pangya_club_live.json 자동 탐색")
        self.wind_live_path_edit = QLineEdit()
        self.wind_live_path_edit.setPlaceholderText("비워두면 ProjectG127.exe 폴더의 logs\\pangya_wind_live.json 자동 탐색")
        self.slope_live_path_edit = QLineEdit()
        self.slope_live_path_edit.setPlaceholderText("비워두면 ProjectG127.exe 폴더의 logs\\pangya_slope_live.json 자동 탐색")
        self.spin_curve_live_path_edit = QLineEdit()
        self.spin_curve_live_path_edit.setPlaceholderText("비워두면 ProjectG127.exe 폴더의 logs\\pangya_spin_curve_live.json 자동 탐색")
        self.diff_live_path_edit = QLineEdit()
        self.diff_live_path_edit.setPlaceholderText("비워두면 ProjectG127.exe 폴더의 logs\\pangya_lateral_offset_live.json 자동 탐색")

        self.memory_disconnect_btn.setEnabled(False)

        memory_layout.addWidget(self.memory_auto_check, 0, 0)
        memory_layout.addWidget(self.ground_live_auto_check, 0, 1)
        memory_layout.addWidget(self.club_live_auto_check, 0, 2)
        memory_layout.addWidget(self.wind_live_auto_check, 0, 3)
        memory_layout.addWidget(self.slope_live_auto_check, 0, 4)
        memory_layout.addWidget(self.spin_curve_live_auto_check, 0, 5)
        memory_layout.addWidget(self.memory_connect_btn, 0, 6)
        memory_layout.addWidget(self.memory_disconnect_btn, 0, 7)
        memory_layout.addWidget(self.memory_status_label, 1, 0, 1, 8)
        memory_layout.addWidget(self.memory_distance_label, 2, 0, 1, 2)
        memory_layout.addWidget(self.memory_height_label, 2, 2, 1, 2)
        memory_layout.addWidget(self.ground_live_label, 2, 4, 1, 1)
        memory_layout.addWidget(self.club_live_label, 2, 5, 1, 2)
        memory_layout.addWidget(self.spin_curve_live_label, 2, 7, 1, 1)
        memory_layout.addWidget(self.wind_live_label, 3, 0, 1, 3)
        memory_layout.addWidget(self.slope_live_label, 3, 3, 1, 5)
        memory_layout.addWidget(QLabel("기울기 모드"), 4, 0)
        memory_layout.addWidget(self.slope_live_mode_combo, 4, 1, 1, 7)
        memory_layout.addWidget(QLabel("거리/고저 live JSON"), 5, 0)
        memory_layout.addWidget(self.distance_height_live_path_edit, 5, 1, 1, 7)
        memory_layout.addWidget(QLabel("지면 live JSON"), 6, 0)
        memory_layout.addWidget(self.ground_live_path_edit, 6, 1, 1, 7)
        memory_layout.addWidget(QLabel("클럽 live JSON"), 7, 0)
        memory_layout.addWidget(self.club_live_path_edit, 7, 1, 1, 7)
        memory_layout.addWidget(QLabel("바람 live JSON"), 8, 0)
        memory_layout.addWidget(self.wind_live_path_edit, 8, 1, 1, 7)
        memory_layout.addWidget(QLabel("기울기 live JSON"), 9, 0)
        memory_layout.addWidget(self.slope_live_path_edit, 9, 1, 1, 7)
        memory_layout.addWidget(QLabel("스핀/커브 live JSON"), 10, 0)
        memory_layout.addWidget(self.spin_curve_live_path_edit, 10, 1, 1, 7)

        memory_layout.addWidget(self.diff_live_auto_check, 11, 0)
        memory_layout.addWidget(self.diff_live_invert_check, 11, 1)
        memory_layout.addWidget(self.diff_live_label, 11, 2, 1, 6)
        memory_layout.addWidget(QLabel("DIFF live JSON"), 12, 0)
        memory_layout.addWidget(self.diff_live_path_edit, 12, 1, 1, 7)

        memory_help = QLabel(
            "거리/고저차는 pangya_distance_height_logger.dll live JSON의 distance/height를 읽어 반영합니다. "
            "지면상태는 pangya_ground_logger.dll live JSON의 ground를 읽어 Ground에 반영합니다. "
            "클럽은 pangya_club_logger.dll live JSON의 club을 읽어 Club 선택에 반영합니다. "
            "바람은 pangya_wind_logger.dll live JSON의 wind를 읽고, 각도는 signed_degree를 읽어 Degree에 반영합니다. "
            "기울기는 pangya_slope_logger.dll live JSON의 후보를 읽어 계산 결과를 비교 출력합니다. "
            "스핀/커브는 pangya_spin_curve_live_logger.dll live JSON의 spin/curve를 읽어 Spin/Curve에 반영합니다. "
            "DIFF는 pangya_lateral_offset_logger.dll live JSON의 current_line_pb만 읽고, 계산 재실행 없이 오버레이 줄만 갱신합니다. "
            "오버레이에는 slope=0 기준 결과와 선택 기울기 반영 결과를 분리해서 표시합니다."
        )
        memory_help.setWordWrap(True)
        memory_layout.addWidget(memory_help, 13, 0, 1, 8)

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
            self.calc_power_shot_combo.currentIndexChanged.connect(self.on_calc_power_shot_changed)

        if hasattr(self, "memory_connect_btn"):
            self.memory_connect_btn.clicked.connect(self.start_memory_probe)
            self.memory_disconnect_btn.clicked.connect(self.stop_memory_probe)

        if hasattr(self, "memory_auto_check"):
            self.memory_auto_check.stateChanged.connect(self.on_memory_auto_changed)

        if hasattr(self, "ground_live_auto_check"):
            self.ground_live_auto_check.stateChanged.connect(self.on_ground_live_auto_changed)

        if hasattr(self, "club_live_auto_check"):
            self.club_live_auto_check.stateChanged.connect(self.on_club_live_auto_changed)

        if hasattr(self, "wind_live_auto_check"):
            self.wind_live_auto_check.stateChanged.connect(self.on_wind_live_auto_changed)

        if hasattr(self, "slope_live_auto_check"):
            self.slope_live_auto_check.stateChanged.connect(self.on_slope_live_auto_changed)
        if hasattr(self, "spin_curve_live_auto_check"):
            self.spin_curve_live_auto_check.stateChanged.connect(self.on_spin_curve_live_auto_changed)
        if hasattr(self, "diff_live_auto_check"):
            self.diff_live_auto_check.stateChanged.connect(self.on_diff_live_auto_changed)
        if hasattr(self, "diff_live_invert_check"):
            self.diff_live_invert_check.stateChanged.connect(self.on_diff_live_invert_changed)
        if hasattr(self, "slope_live_mode_combo"):
            self.slope_live_mode_combo.currentIndexChanged.connect(self.on_slope_live_mode_changed)

        if hasattr(self, "capture_exclude_check"):
            self.capture_exclude_check.stateChanged.connect(self.on_capture_exclude_changed)


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
            "distance_height_live_json_path": self.distance_height_live_path_edit.text().strip() if hasattr(self, "distance_height_live_path_edit") else "",
            "ground_live_auto_input": self.ground_live_auto_check.isChecked() if hasattr(self, "ground_live_auto_check") else False,
            "ground_live_json_path": self.ground_live_path_edit.text().strip() if hasattr(self, "ground_live_path_edit") else "",
            "club_live_auto_input": self.club_live_auto_check.isChecked() if hasattr(self, "club_live_auto_check") else False,
            "club_live_json_path": self.club_live_path_edit.text().strip() if hasattr(self, "club_live_path_edit") else "",
            "wind_live_auto_input": self.wind_live_auto_check.isChecked() if hasattr(self, "wind_live_auto_check") else False,
            "wind_live_json_path": self.wind_live_path_edit.text().strip() if hasattr(self, "wind_live_path_edit") else "",
            "slope_live_auto_input": self.slope_live_auto_check.isChecked() if hasattr(self, "slope_live_auto_check") else False,
            "slope_live_json_path": self.slope_live_path_edit.text().strip() if hasattr(self, "slope_live_path_edit") else "",
            "slope_live_mode": self.slope_live_mode_combo.currentData() if hasattr(self, "slope_live_mode_combo") else "R0C_MINUS",
            "spin_curve_live_auto_input": self.spin_curve_live_auto_check.isChecked() if hasattr(self, "spin_curve_live_auto_check") else False,
            "spin_curve_live_json_path": self.spin_curve_live_path_edit.text().strip() if hasattr(self, "spin_curve_live_path_edit") else "",
            "diff_live_auto_input": self.diff_live_auto_check.isChecked() if hasattr(self, "diff_live_auto_check") else False,
            "diff_live_json_path": self.diff_live_path_edit.text().strip() if hasattr(self, "diff_live_path_edit") else "",
            "diff_live_invert_sign": self.diff_live_invert_check.isChecked() if hasattr(self, "diff_live_invert_check") else False,
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
        if hasattr(self, "distance_height_live_path_edit"):
            self.distance_height_live_path_edit.setText(str(s.get("distance_height_live_json_path", "")))
        if hasattr(self, "ground_live_auto_check"):
            self.ground_live_auto_check.setChecked(bool(s.get("ground_live_auto_input", True)))
        if hasattr(self, "ground_live_path_edit"):
            self.ground_live_path_edit.setText(str(s.get("ground_live_json_path", "")))
        if hasattr(self, "club_live_auto_check"):
            self.club_live_auto_check.setChecked(bool(s.get("club_live_auto_input", False)))
        if hasattr(self, "club_live_path_edit"):
            self.club_live_path_edit.setText(str(s.get("club_live_json_path", "")))
        if hasattr(self, "wind_live_auto_check"):
            self.wind_live_auto_check.setChecked(bool(s.get("wind_live_auto_input", False)))
        if hasattr(self, "wind_live_path_edit"):
            self.wind_live_path_edit.setText(str(s.get("wind_live_json_path", "")))
        if hasattr(self, "slope_live_auto_check"):
            self.slope_live_auto_check.setChecked(bool(s.get("slope_live_auto_input", False)))
        if hasattr(self, "slope_live_path_edit"):
            self.slope_live_path_edit.setText(str(s.get("slope_live_json_path", "")))
        if hasattr(self, "spin_curve_live_auto_check"):
            self.spin_curve_live_auto_check.setChecked(bool(s.get("spin_curve_live_auto_input", True)))
        if hasattr(self, "spin_curve_live_path_edit"):
            self.spin_curve_live_path_edit.setText(str(s.get("spin_curve_live_json_path", "")))
        if hasattr(self, "diff_live_auto_check"):
            self.diff_live_auto_check.setChecked(bool(s.get("diff_live_auto_input", False)))
        if hasattr(self, "diff_live_path_edit"):
            self.diff_live_path_edit.setText(str(s.get("diff_live_json_path", "")))
        if hasattr(self, "diff_live_invert_check"):
            self.diff_live_invert_check.setChecked(bool(s.get("diff_live_invert_sign", False)))
        if hasattr(self, "slope_live_mode_combo"):
            
            mode = s.get("slope_live_mode", "R0C_MINUS")
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
        """거리/고저차 live JSON 감시 시작.

        기존 버전처럼 Python에서 ProjectG127.exe에 직접 hook을 설치하지 않는다.
        pangya_distance_height_logger.dll이 생성하는 logs\\pangya_distance_height_live.json만 읽는다.
        """
        if self.memory_timer.isActive():
            self.set_memory_status("상태: 이미 live 감시 중")
            return

        self.memory_timer.start(250)
        self.memory_connect_btn.setEnabled(False)
        self.memory_disconnect_btn.setEnabled(True)
        self.set_memory_status("상태: DLL live 감시 중 - 거리/고저 대기")
        self.update_memory_values_from_game()


    def read_json_file_retry(self, path, retries=1, delay_ms=0):
        """DLL live JSON 읽기.

        GUI 메인 스레드에서 호출되므로 여기서 sleep/processEvents를 절대 하지 않는다.
        DLL이 파일을 쓰는 순간 반쪽 JSON이 보이면 이전 캐시값을 즉시 반환한다.
        """
        if not path:
            raise FileNotFoundError("live JSON path is empty")

        path = os.path.abspath(path)
        cache = getattr(self, "_live_json_cache", None)
        if cache is None:
            self._live_json_cache = {}
            cache = self._live_json_cache

        cached = cache.get(path)

        try:
            stat = os.stat(path)
            sig = (stat.st_mtime_ns, stat.st_size)
            if cached and cached.get("sig") == sig:
                return cached.get("data")
        except Exception:
            if cached and cached.get("data") is not None:
                return cached.get("data")
            raise

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            cache[path] = {"sig": sig, "data": data}
            return data
        except Exception:
            # DLL write 중 반쪽 파일이면 UI를 멈추지 말고 이전 정상값 사용
            if cached and cached.get("data") is not None:
                return cached.get("data")
            raise

    def find_existing_live_json_path(self, filename):
        """수동 경로가 비어 있을 때 확인할 후보 경로들을 순서대로 검사한다.

        logger DLL 표준 경로는 ProjectG127.exe 폴더의 logs\\ 입니다.
        다만 구버전/테스트 DLL이 plugins\\에 JSON을 만든 경우도 있어서 fallback으로 같이 본다.
        """
        paths = []

        target_exe = self.target_exe_edit.text().strip() if hasattr(self, "target_exe_edit") else "ProjectG127.exe"
        exe_path = self.find_process_exe_path(target_exe or "ProjectG127.exe")
        if exe_path:
            exe_dir = os.path.dirname(exe_path)
            paths.append(os.path.join(exe_dir, "logs", filename))
            paths.append(os.path.join(exe_dir, "plugins", "logs", filename))
            paths.append(os.path.join(exe_dir, "plugins", filename))

        paths.append(os.path.join(FORCED_CLIENT_LOG_DIR, filename))
        paths.append(os.path.join(os.path.dirname(FORCED_CLIENT_LOG_DIR), "plugins", "logs", filename))
        paths.append(os.path.join(os.path.dirname(FORCED_CLIENT_LOG_DIR), "plugins", filename))
        paths.append(os.path.join(get_app_dir(), "logs", filename))
        paths.append(os.path.join(get_app_dir(), filename))

        # 중복 제거, 존재하는 파일 우선
        unique = []
        for path in paths:
            if path and path not in unique:
                unique.append(path)

        for path in unique:
            if os.path.exists(path):
                return path

        return unique[0] if unique else os.path.join(get_app_dir(), "logs", filename)

    def resolve_distance_height_live_json_path(self):
        # 1) 사용자가 직접 지정한 경로
        manual = ""
        if hasattr(self, "distance_height_live_path_edit"):
            manual = self.distance_height_live_path_edit.text().strip().strip('"')

        if manual:
            return manual

        # 2) 실행 중인 ProjectG127.exe 폴더의 logs\pangya_distance_height_live.json
        target_exe = self.target_exe_edit.text().strip() if hasattr(self, "target_exe_edit") else "ProjectG127.exe"
        exe_path = self.find_process_exe_path(target_exe or "ProjectG127.exe")
        if exe_path:
            return os.path.join(os.path.dirname(exe_path), "logs", "pangya_distance_height_live.json")

        # 3) 고정 클라이언트 로그 폴더 / GUI 폴더 fallback
        existing = self.find_existing_live_json_path("pangya_distance_height_live.json")
        return existing


    def ensure_live_timers(self):
        """체크박스가 ON이면 Start 버튼과 독립적으로 live JSON timer를 유지한다.

        기존 코드처럼 watchdog에서 update_*를 매번 직접 호출하면 각 live timer와
        auto_result_timer가 같은 JSON을 중복으로 읽는다. 여기서는 timer 시작/중지만
        관리하고, 최초 시작 시에만 한 번 즉시 갱신한다.
        """
        try:
            def keep_timer(check_attr, timer_attr, update_func=None, interval=300):
                check = getattr(self, check_attr, None)
                timer = getattr(self, timer_attr, None)
                if check is None or timer is None:
                    return

                if check.isChecked():
                    if not timer.isActive():
                        timer.start(interval)
                        if update_func is not None:
                            try:
                                update_func()
                            except Exception:
                                pass
                else:
                    if timer.isActive():
                        timer.stop()

            keep_timer("memory_auto_check", "memory_timer", self.update_memory_values_from_game, 300)
            # LOCK 자동 해제는 남은거리 변화로 판단하므로, 거리 자동 입력 체크가 꺼져 있어도
            # LOCK 중에는 거리 live timer만 유지한다. 입력칸 반영은 기존 체크박스 조건을 그대로 따른다.
            if bool(getattr(self, "calc_lock_enabled", False)) and hasattr(self, "memory_timer"):
                if not self.memory_timer.isActive():
                    self.memory_timer.start(300)
                    try:
                        self.update_memory_values_from_game()
                    except Exception:
                        pass

            keep_timer("ground_live_auto_check", "ground_live_timer", self.update_ground_live_from_file, 300)
            keep_timer("club_live_auto_check", "club_live_timer", self.update_club_live_from_file, 500)
            keep_timer("wind_live_auto_check", "wind_live_timer", self.update_wind_live_from_file, 300)
            keep_timer("slope_live_auto_check", "slope_live_timer", self.update_slope_live_from_file, 555)
            # 스핀/커브는 마우스로 빠르게 변하는 값이라 500ms면 중간 변화가 건너뛰어 보일 수 있다.
            # 기울기 최적화는 유지하고, 스핀/커브 입력 반응만 250ms로 올린다.
            keep_timer("spin_curve_live_auto_check", "spin_curve_live_timer", self.update_spin_curve_live_from_file, 250)

            # DIFF는 조준 중 계속 변하지만, JSON 캐시/mtime 확인 + tick 변화시에만 오버레이 갱신한다.
            # 계산 물리는 다시 돌리지 않고 문자열만 바꿔 렉을 줄인다.
            keep_timer("diff_live_auto_check", "diff_live_timer", self.update_diff_live_from_file, 250)

        except Exception as e:
            print(f"[WARN] live timer watchdog 실패: {e}")


    def on_memory_auto_changed(self):
        self.ensure_live_timers()
        if hasattr(self, "memory_auto_check") and not self.memory_auto_check.isChecked():
            if hasattr(self, "memory_distance_label"):
                self.memory_distance_label.setText("거리: -")
            if hasattr(self, "memory_height_label"):
                self.memory_height_label.setText("고저: -")
            self.set_memory_status("상태: live 감시 안 됨")

    def on_ground_live_auto_changed(self):
        self.ensure_live_timers()
        if hasattr(self, "ground_live_auto_check") and not self.ground_live_auto_check.isChecked():
            if hasattr(self, "ground_live_label"):
                self.ground_live_label.setText("지면: -")

    def resolve_ground_live_json_path(self):
        manual = ""
        if hasattr(self, "ground_live_path_edit"):
            manual = self.ground_live_path_edit.text().strip().strip('"')

        if manual:
            return manual

        target_exe = self.target_exe_edit.text().strip() if hasattr(self, "target_exe_edit") else "ProjectG127.exe"
        exe_path = self.find_process_exe_path(target_exe or "ProjectG127.exe")
        if exe_path:
            return os.path.join(os.path.dirname(exe_path), "logs", "pangya_ground_live.json")

        return self.find_existing_live_json_path("pangya_ground_live.json")

    def update_ground_live_from_file(self):
        """pangya_ground_logger.dll live JSON에서 ground 값을 읽어 Ground 입력칸에 반영한다."""
        if not hasattr(self, "ground_live_auto_check") or not self.ground_live_auto_check.isChecked():
            return

        path = self.resolve_ground_live_json_path()
        self.last_ground_live_path = path

        try:
            if not os.path.exists(path):
                if hasattr(self, "ground_live_label"):
                    self.ground_live_label.setText("지면: live 파일 없음")
                return

            data = self.read_json_file_retry(path)

            if not data.get("ok", False):
                if hasattr(self, "ground_live_label"):
                    self.ground_live_label.setText("지면: live 값 없음")
                return

            ground_ok = bool(data.get("ground_ok", data.get("ok", False)))
            ground = int(round(float(data.get("ground")))) if ground_ok and data.get("ground") is not None else None

            if ground is None:
                if hasattr(self, "ground_live_label"):
                    self.ground_live_label.setText("지면: 값 없음")
                return

            if not 0 <= ground <= 150:
                if hasattr(self, "ground_live_label"):
                    self.ground_live_label.setText(f"지면: 범위 밖 {ground}")
                return

            ground_text = str(ground)
            if self.calc_ground_edit.text().strip() != ground_text:
                self.calc_ground_edit.setText(ground_text)

            self.last_ground_live_value = ground
            self.last_ground_live_tick = data.get("tick")

            if hasattr(self, "ground_live_label"):
                self.ground_live_label.setText(f"지면: {ground_text}% tick={self.last_ground_live_tick}")

        except Exception as e:
            print(f"[WARN] 지면 live 값 읽기 실패: {e}")
            if hasattr(self, "ground_live_label"):
                self.ground_live_label.setText("지면: 읽기 실패")

    def on_club_live_auto_changed(self):
        self.ensure_live_timers()
        if hasattr(self, "club_live_auto_check") and not self.club_live_auto_check.isChecked():
            if hasattr(self, "club_live_label"):
                self.club_live_label.setText("클럽: -")

    def resolve_club_live_json_path(self):
        manual = ""
        if hasattr(self, "club_live_path_edit"):
            manual = self.club_live_path_edit.text().strip().strip('"')

        if manual:
            return manual

        target_exe = self.target_exe_edit.text().strip() if hasattr(self, "target_exe_edit") else "ProjectG127.exe"
        exe_path = self.find_process_exe_path(target_exe or "ProjectG127.exe")
        if exe_path:
            return os.path.join(os.path.dirname(exe_path), "logs", "pangya_club_live.json")

        return self.find_existing_live_json_path("pangya_club_live.json")

    def update_club_live_from_file(self):
        if not hasattr(self, "club_live_auto_check") or not self.club_live_auto_check.isChecked():
            return

        path = self.resolve_club_live_json_path()
        self.last_club_live_path = path

        try:
            if not os.path.exists(path):
                if hasattr(self, "club_live_label"):
                    self.club_live_label.setText("클럽: live 파일 없음")
                return

            data = self.read_json_file_retry(path)

            if not data.get("ok", False) or not data.get("club_ok", False):
                if hasattr(self, "club_live_label"):
                    self.club_live_label.setText("클럽: live 값 없음")
                return

            club = (data.get("club") or "").strip()
            if not club:
                if hasattr(self, "club_live_label"):
                    self.club_live_label.setText("클럽: 값 없음")
                return

            idx = self.calc_club_combo.findData(club) if hasattr(self, "calc_club_combo") else -1
            if idx >= 0 and self.calc_club_combo.currentIndex() != idx:
                self.calc_club_combo.setCurrentIndex(idx)

            self.last_club_live_value = club
            self.last_club_live_tick = data.get("tick")

            club_name = data.get("club_name") or (self.calc_club_combo.currentText() if hasattr(self, "calc_club_combo") else club)
            seq = data.get("seq")

            if hasattr(self, "club_live_label"):
                self.club_live_label.setText(f"클럽: {club_name} ({club}) seq={seq} tick={self.last_club_live_tick}")

        except Exception as e:
            print(f"[WARN] 클럽 live 값 읽기 실패: {e}")
            if hasattr(self, "club_live_label"):
                self.club_live_label.setText("클럽: 읽기 실패")

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
        # 모드 변경 시 한 번만 live 값을 반영하고 결과 갱신 예약.
        # 비교 모드가 선택되어도 자동/live에서는 R0C_MINUS 1개로만 동작한다.
        if hasattr(self, "slope_live_auto_check") and self.slope_live_auto_check.isChecked():
            self.update_slope_live_from_file()
        self.last_auto_result_signature = None
        self.schedule_auto_result_refresh(50)
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
                if hasattr(self, "slope_live_label") and self.slope_live_label.isVisible():
                    self.slope_live_label.setText("기울기 후보: live 파일 없음")
                return

            data = self.read_json_file_retry(path)

            if not data.get("ok", False):
                self.last_slope_live_candidates = None
                if hasattr(self, "slope_live_label") and self.slope_live_label.isVisible():
                    self.slope_live_label.setText("기울기 후보: live 값 없음")
                return

            candidates = self._extract_slope_live_candidates(data)
            tick = data.get("tick")
            seq = data.get("seq")

            usable_keys = [
                "X_PLUS", "X_MINUS", "Y_PLUS", "Y_MINUS", "MAG_PLUS", "MAG_MINUS",
                "R0C_PLUS", "R0C_MINUS", "R04_PLUS", "R04_MINUS",
                "R14_PLUS", "R14_MINUS", "R1C_PLUS", "R1C_MINUS",
                "A_PLUS", "A_MINUS", "B_PLUS", "B_MINUS", "LEGACY_A", "LEGACY_B"
            ]
            if not any(candidates.get(k) is not None for k in usable_keys):
                self.last_slope_live_candidates = None
                if hasattr(self, "slope_live_label") and self.slope_live_label.isVisible():
                    self.slope_live_label.setText("기울기 후보: 후보 필드 없음")
                return

            candidates["tick"] = tick
            candidates["seq"] = seq
            candidates["path"] = path
            self.last_slope_live_candidates = candidates
            self.last_slope_live_tick = tick

            # 자동/live 중에는 비교 모드를 절대 돌리지 않는다.
            # XY_COMPARE/MATRIX_COMPARE가 선택되어 있어도 R0C_MINUS 1개만 입력/계산한다.
            mode = self.slope_live_mode_combo.currentData() if hasattr(self, "slope_live_mode_combo") else "R0C_MINUS"
            chosen_key = self._get_auto_slope_candidate_key(mode)
            chosen = candidates.get(chosen_key) if chosen_key else None

            if chosen is not None:
                new_value = float(chosen)
                new_text = f"{new_value:.4f}"

                # slope 값은 DLL hook 특성상 아주 미세하게 흔들릴 수 있다.
                # 너무 작은 변화까지 setText하면 자동 결과 재계산을 계속 유발하므로
                # 0.005 미만 변화는 GUI 입력칸 갱신을 생략한다.
                old_text = self.calc_slope_edit.text().strip()
                do_update = True
                try:
                    old_value = float(old_text)
                    do_update = abs(old_value - new_value) >= 0.005
                except Exception:
                    do_update = True

                if do_update and old_text != new_text:
                    self.calc_slope_edit.setText(new_text)

            # 디버그 라벨은 기본 숨김이다. 숨겨진 상태에서 긴 문자열을 매 tick 만들지 않는다.
            if hasattr(self, "slope_live_label") and self.slope_live_label.isVisible():
                display_path = path
                if len(display_path) > 65:
                    display_path = "..." + display_path[-62:]

                def fmt(name):
                    value = candidates.get(name)
                    return "-" if value is None else f"{value:.4f}"

                self.slope_live_label.setText(
                    f"auto={chosen_key or '-'} "
                    f"R0C±:{fmt('R0C_PLUS')}/{fmt('R0C_MINUS')}  "
                    f"R1C±:{fmt('R1C_PLUS')}/{fmt('R1C_MINUS')}  "
                    f"seq={seq} tick={tick}  {display_path}"
                )

        except Exception as e:
            print(f"[WARN] 기울기 live 값 읽기 실패: {e}")
            self.last_slope_live_candidates = None
            if hasattr(self, "slope_live_label") and self.slope_live_label.isVisible():
                self.slope_live_label.setText("기울기 후보: 읽기 실패")
    def on_spin_curve_live_auto_changed(self):
        self.ensure_live_timers()
        if hasattr(self, "spin_curve_live_auto_check") and not self.spin_curve_live_auto_check.isChecked():
            self.last_spin_curve_live_value = None
            if hasattr(self, "spin_curve_live_label"):
                self.spin_curve_live_label.setText("스핀/커브: -")

    def resolve_spin_curve_live_json_path(self):
        """스핀/커브 live JSON 경로를 결정한다.

        중요:
        - 이 함수는 v8 기울기 저부하 구조를 건드리지 않는다.
        - spin/curve만 stale plugins JSON을 물지 않도록 logs 표준 경로를 항상 우선한다.
        - logs 파일이 아직 없어도 표준 logs 경로를 반환해서, 예전 plugins\\pangya_spin_curve_live.json을
          실수로 계속 읽는 문제를 막는다.
        """
        manual = ""
        if hasattr(self, "spin_curve_live_path_edit"):
            manual = self.spin_curve_live_path_edit.text().strip().strip('"')

        if manual:
            return manual

        cache = getattr(self, "_live_path_cache", None)
        if cache is None:
            self._live_path_cache = {}
            cache = self._live_path_cache

        def remember(path, *, fallback=False):
            path = os.path.abspath(path)
            old_path = cache.get("spin_curve")
            if old_path != path:
                cache["spin_curve"] = path
                if fallback:
                    print(f"[WARN] spin/curve live JSON fallback path: {path}")
                else:
                    print(f"[INFO] spin/curve live JSON path: {path}")
            return path

        # 1) 실행 중인 ProjectG127.exe 폴더의 logs\pangya_spin_curve_live.json
        #    존재 여부와 상관없이 이 경로를 우선 반환한다.
        #    그래야 과거 테스트 DLL이 만든 plugins\\pangya_spin_curve_live.json stale 파일을 물지 않는다.
        target_exe = self.target_exe_edit.text().strip() if hasattr(self, "target_exe_edit") else "ProjectG127.exe"
        exe_path = self.find_process_exe_path(target_exe or "ProjectG127.exe")
        if exe_path:
            logs_path = os.path.join(os.path.dirname(exe_path), "logs", "pangya_spin_curve_live.json")
            return remember(logs_path, fallback=False)

        # 2) 프로세스 경로를 못 잡은 경우에도 기존 프로젝트 표준 logs 경로를 우선한다.
        forced_logs_path = os.path.join(FORCED_CLIENT_LOG_DIR, "pangya_spin_curve_live.json")
        return remember(forced_logs_path, fallback=False)

        # 아래 fallback은 의도적으로 사용하지 않는다.
        # found = self.find_existing_live_json_path("pangya_spin_curve_live.json")
        # return remember(found, fallback=True)

    def update_spin_curve_live_from_file(self):
        """pangya_spin_curve_live_logger.dll live JSON에서 spin/curve 값을 읽어 입력칸에 반영한다."""
        if not hasattr(self, "spin_curve_live_auto_check") or not self.spin_curve_live_auto_check.isChecked():
            return

        path = self.resolve_spin_curve_live_json_path()
        self.last_spin_curve_live_path = path

        try:
            if not os.path.exists(path):
                if hasattr(self, "spin_curve_live_label"):
                    self.spin_curve_live_label.setText("스핀/커브: live 파일 없음")
                return

            data = self.read_json_file_retry(path)

            if not data.get("ok", False):
                if hasattr(self, "spin_curve_live_label"):
                    self.spin_curve_live_label.setText("스핀/커브: live 값 없음")
                return

            curve_ok = bool(data.get("curve_ok", data.get("ok", False)))
            spin_ok = bool(data.get("spin_ok", data.get("ok", False)))

            curve = float(data.get("curve")) if curve_ok and data.get("curve") is not None else None
            spin = float(data.get("spin")) if spin_ok and data.get("spin") is not None else None
            curve_max = float(data.get("curve_max", 0.0) or 0.0)
            spin_max = float(data.get("spin_max", 0.0) or 0.0)
            tick = data.get("tick")
            seq = data.get("seq")

            if curve is None and spin is None:
                if hasattr(self, "spin_curve_live_label"):
                    self.spin_curve_live_label.setText("스핀/커브: 값 없음")
                return

            # 비정상 base가 잡힌 경우 방어. 캐릭에 따라 max가 다를 수 있어 넉넉히 둔다.
            if curve is not None and not -100.0 <= curve <= 100.0:
                return
            if spin is not None and not -100.0 <= spin <= 100.0:
                return

            changed = False
            curve_text = None
            spin_text = None

            if curve is not None:
                curve_text = f"{curve:.0f}" if abs(curve - round(curve)) < 0.001 else f"{curve:.2f}"
                if self.calc_curve_edit.text().strip() != curve_text:
                    self.calc_curve_edit.setText(curve_text)
                    changed = True

            if spin is not None:
                spin_text = f"{spin:.0f}" if abs(spin - round(spin)) < 0.001 else f"{spin:.2f}"
                if self.calc_spin_edit.text().strip() != spin_text:
                    self.calc_spin_edit.setText(spin_text)
                    changed = True

            self.last_spin_curve_live_tick = tick
            self.last_spin_curve_live_value = {
                "curve": curve,
                "spin": spin,
                "curve_max": curve_max,
                "spin_max": spin_max,
                "seq": seq,
                "tick": tick,
            }

            if hasattr(self, "spin_curve_live_label"):
                c_show = "-" if curve is None else f"{curve:.2f}"
                s_show = "-" if spin is None else f"{spin:.2f}"
                label_text = f"스핀/커브: S{s_show}/{spin_max:.0f} C{c_show}/{curve_max:.0f} seq={seq} tick={tick}"
                if self.spin_curve_live_label.text() != label_text:
                    self.spin_curve_live_label.setText(label_text)

            if changed:
                self.last_auto_result_signature = None

        except Exception as e:
            print(f"[WARN] 스핀/커브 live 값 읽기 실패: {e}")
            if hasattr(self, "spin_curve_live_label"):
                self.spin_curve_live_label.setText("스핀/커브: 읽기 실패")


    def on_diff_live_auto_changed(self):
        """DIFF live 표시 체크 변경.

        체크 ON/OFF만으로는 계산 물리를 다시 돌릴 필요가 없다.
        다만 오버레이 줄 구성은 바뀌므로 signature를 초기화하고 즉시 한 번 갱신한다.
        """
        self.ensure_live_timers()
        self.last_diff_overlay_signature = None

        if hasattr(self, "diff_live_auto_check") and not self.diff_live_auto_check.isChecked():
            if hasattr(self, "diff_live_label") and self.diff_live_label.isVisible():
                self.diff_live_label.setText("DIFF: -")
            # DIFF 줄 제거
            self.refresh_diff_overlay_only()
            return

        # 체크 직후 최신 JSON을 한 번만 읽고, 기존 계산 결과 줄에 붙인다.
        self.update_diff_live_from_file()
        if self.last_overlay_base_lines_no_diff is None:
            self.last_auto_result_signature = None
            self.refresh_auto_result_overlay()
        else:
            self.refresh_diff_overlay_only()

    def on_diff_live_invert_changed(self):
        """DIFF 부호 반전 체크 변경."""
        self.last_diff_overlay_signature = None
        self.refresh_diff_overlay_only()

    def resolve_diff_live_json_path(self):
        """pangya_lateral_offset_logger.dll live JSON 경로를 결정한다.

        표준 경로:
            ProjectG127.exe 폴더\\logs\\pangya_lateral_offset_live.json

        수동 경로가 비어 있으면 기존 DLL live JSON들과 같은 방식으로
        ProjectG127.exe 실행 경로를 우선 사용한다.
        """
        manual = ""
        if hasattr(self, "diff_live_path_edit"):
            manual = self.diff_live_path_edit.text().strip().strip('"')

        if manual:
            return manual

        cache = getattr(self, "_live_path_cache", None)
        if cache is None:
            self._live_path_cache = {}
            cache = self._live_path_cache

        def remember(path, *, fallback=False):
            path = os.path.abspath(path)
            old_path = cache.get("diff")
            if old_path != path:
                cache["diff"] = path
                if fallback:
                    print(f"[WARN] DIFF live JSON fallback path: {path}")
                else:
                    print(f"[INFO] DIFF live JSON path: {path}")
            return path

        target_exe = self.target_exe_edit.text().strip() if hasattr(self, "target_exe_edit") else "ProjectG127.exe"
        exe_path = self.find_process_exe_path(target_exe or "ProjectG127.exe")
        if exe_path:
            return remember(
                os.path.join(os.path.dirname(exe_path), "logs", "pangya_lateral_offset_live.json"),
                fallback=False,
            )

        return remember(
            os.path.join(FORCED_CLIENT_LOG_DIR, "pangya_lateral_offset_live.json"),
            fallback=True,
        )

    def update_diff_live_from_file(self):
        """pangya_lateral_offset_logger.dll live JSON에서 현재 조준선 LINE 값을 읽는다.

        중요:
        - 여기서는 calc_shot을 호출하지 않는다.
        - JSON tick/seq 또는 current_line_pb가 바뀐 경우에만 오버레이 문자열만 갱신한다.
        - GUI 장판 환산값은 현재 GUI의 board_per_pb를 사용한다.
        """
        if not hasattr(self, "diff_live_auto_check") or not self.diff_live_auto_check.isChecked():
            return

        path = self.resolve_diff_live_json_path()
        self.last_diff_live_path = path

        try:
            if not os.path.exists(path):
                self.last_diff_live_value = None
                if hasattr(self, "diff_live_label") and self.diff_live_label.isVisible():
                    self.diff_live_label.setText("DIFF: live 파일 없음")
                self.refresh_diff_overlay_only()
                return

            data = self.read_json_file_retry(path)

            if not data.get("ok", False) or not data.get("line_ok", data.get("ok", False)):
                self.last_diff_live_value = None
                if hasattr(self, "diff_live_label") and self.diff_live_label.isVisible():
                    reason = data.get("reason", "live 값 없음")
                    self.diff_live_label.setText(f"DIFF: {reason}")
                self.refresh_diff_overlay_only()
                return

            raw_line_pb = data.get("current_line_pb")
            if raw_line_pb is None:
                self.last_diff_live_value = None
                if hasattr(self, "diff_live_label") and self.diff_live_label.isVisible():
                    self.diff_live_label.setText("DIFF: current_line_pb 없음")
                self.refresh_diff_overlay_only()
                return

            line_pb = float(raw_line_pb)

            # 비정상 포인터/초기화 값 방어
            if not -10000.0 <= line_pb <= 10000.0:
                return

            tick = data.get("tick")
            seq = data.get("seq")
            pre_hit = data.get("pre_hit")

            old = self.last_diff_live_value or {}
            old_tick = old.get("tick")
            old_seq = old.get("seq")
            old_line = old.get("line_pb")

            # 같은 tick/seq이고 라인 변화도 없으면 오버레이 갱신 생략
            try:
                same_line = old_line is not None and abs(float(old_line) - line_pb) < 0.0005
            except Exception:
                same_line = False

            if old_tick == tick and old_seq == seq and same_line:
                return

            self.last_diff_live_tick = tick
            self.last_diff_live_value = {
                "line_pb": line_pb,
                "tick": tick,
                "seq": seq,
                "pre_hit": pre_hit,
                "path": path,
            }

            if hasattr(self, "diff_live_label") and self.diff_live_label.isVisible():
                try:
                    board_per_pb = self.read_calc_float_silent(self.calc_board_per_pb_edit, 0.2121)
                except Exception:
                    board_per_pb = 0.2121
                shown_pb = -line_pb if self.diff_live_invert_check.isChecked() else line_pb
                self.diff_live_label.setText(
                    f"DIFF LINE: {shown_pb * board_per_pb:+.3f}칸 / PB{shown_pb:+.2f} seq={seq} tick={tick}"
                )

            self.refresh_diff_overlay_only()

        except Exception as e:
            print(f"[WARN] DIFF live 값 읽기 실패: {e}")
            if hasattr(self, "diff_live_label") and self.diff_live_label.isVisible():
                self.diff_live_label.setText("DIFF: 읽기 실패")

    def build_diff_overlay_lines(self, base_lines, diff_targets):
        """기존 계산 결과 줄에 LINE/DIFF 줄을 붙여 반환한다.

        DIFF 정의:
            DIFF = 현재 조준선 LINE - 계산 장판값

        예:
            계산 장판 +3.000, 홀컵 정조준 LINE 0.000 -> DIFF -3.000
            LINE +3.000까지 조준 이동 -> DIFF 0.000
        """
        lines = list(base_lines or [])

        if bool(getattr(self, "calc_lock_enabled", False)):
            lock_distance = self.calc_lock_distance
            try:
                snapshot = self.calc_lock_snapshot or {}
                if lock_distance is None:
                    lock_distance = snapshot.get("distance")
            except Exception:
                pass

            lock_text = "LOCK: ON"
            try:
                if lock_distance is not None:
                    lock_text += f" D{float(lock_distance):.2f}"
            except Exception:
                pass

            if lines:
                lines.insert(1, lock_text)
            else:
                lines.append(lock_text)

        if not hasattr(self, "diff_live_auto_check") or not self.diff_live_auto_check.isChecked():
            return lines

        diff_value = self.last_diff_live_value
        if not diff_value or diff_value.get("line_pb") is None:
            lines.append("LINE/DIFF: live 대기")
            return lines

        try:
            board_per_pb = self.read_calc_float_silent(self.calc_board_per_pb_edit, 0.2121)
        except Exception:
            board_per_pb = 0.2121

        try:
            line_pb = float(diff_value.get("line_pb"))
        except Exception:
            lines.append("LINE/DIFF: 값 오류")
            return lines

        if hasattr(self, "diff_live_invert_check") and self.diff_live_invert_check.isChecked():
            line_pb = -line_pb

        line_board = line_pb * board_per_pb
        #lines.append(f"LINE: {line_board:+.3f}칸 / PB{line_pb:+.2f}")

        targets = list(diff_targets or [])
        # 기본(기울기0) DIFF는 숨기고, 기울기/수동 target만 표시한다.
        if len(targets) > 1:
            targets = [t for t in targets if str(t.get("name", "")) != "기본"]
            
        if not targets:
            lines.append("DIFF: 계산 대기")
            return lines

        # 너무 많은 줄을 만들면 좌상단이 길어지므로 기본 + 선택 기울기 정도만 표시한다.
        for idx, target in enumerate(targets[:3]):
            try:
                target_pb = float(target.get("target_pb", 0.0))
            except Exception:
                continue

            name = str(target.get("name", "") or "기본")
            diff_pb = line_pb - target_pb
            diff_board = diff_pb * board_per_pb

            if len(targets) == 1:
                label = "DIFF"
            elif idx == 0:
                label = "DIFF(기본)"
            else:
                label = f"DIFF({name})"

            lines.append(f"{label}: {diff_board:+.3f}칸 / PB{diff_pb:+.2f}")

        return lines

    def refresh_diff_overlay_only(self):
        """DIFF/LINE만 바뀐 경우 계산 물리를 다시 돌리지 않고 오버레이 문자열만 갱신한다."""
        if bool(getattr(self, "calc_lock_enabled", False)) and self.calc_lock_snapshot is not None:
            base_lines = self.calc_lock_snapshot.get("base_lines")
            diff_targets = self.calc_lock_snapshot.get("diff_targets")
        else:
            base_lines = self.last_overlay_base_lines_no_diff
            diff_targets = self.last_overlay_diff_targets

        if base_lines is None:
            # 아직 자동 계산 결과가 없으면 한 번만 계산 결과를 만들도록 요청한다.
            self.last_auto_result_signature = None
            return

        final_lines = self.build_diff_overlay_lines(base_lines, diff_targets)

        signature = tuple(final_lines)
        if signature == self.last_diff_overlay_signature:
            return

        self.last_diff_overlay_signature = signature
        self.overlay.set_calc_state({"type": "calc_result", "lines": final_lines})

    def stop_memory_probe(self):
        # 거리/고저 live JSON timer만 중지한다.
        # wind/slope live JSON timer는 각 체크박스와 watchdog이 별도로 관리한다.
        if self.memory_timer.isActive():
            self.memory_timer.stop()

        self.memory_probe = None

        if hasattr(self, "memory_connect_btn"):
            self.memory_connect_btn.setEnabled(True)
            self.memory_disconnect_btn.setEnabled(False)

        self.set_memory_status("상태: live 감시 안 됨")
        if hasattr(self, "memory_distance_label"):
            self.memory_distance_label.setText("거리: -")
        if hasattr(self, "memory_height_label"):
            self.memory_height_label.setText("고저: -")

    def update_memory_values_from_game(self):
        """pangya_distance_height_logger.dll live JSON에서 distance/height를 읽어 계산기 입력칸에 반영한다."""
        memory_auto_enabled = bool(hasattr(self, "memory_auto_check") and self.memory_auto_check.isChecked())
        lock_tracking_enabled = bool(getattr(self, "calc_lock_enabled", False))
        if not memory_auto_enabled and not lock_tracking_enabled and self.memory_probe is None:
            return

        path = self.resolve_distance_height_live_json_path()
        self.last_memory_live_path = path

        try:
            if not os.path.exists(path):
                self.set_memory_status("상태: 거리/고저 live 파일 없음")
                return

            data = self.read_json_file_retry(path)

            if not data.get("ok", False):
                self.set_memory_status("상태: 거리/고저 live 값 없음")
                return

            distance_ok = bool(data.get("distance_ok", False))
            height_ok = bool(data.get("height_ok", False))
            distance = float(data.get("distance")) if distance_ok and data.get("distance") is not None else None
            height = float(data.get("height")) if height_ok and data.get("height") is not None else None
            tick = data.get("tick")

            changed = False

            if distance is not None:
                if not 0.0 <= distance <= 2000.0:
                    distance = None
                else:
                    self.last_memory_distance = distance
                    if hasattr(self, "memory_distance_label"):
                        self.memory_distance_label.setText(f"거리: {distance:.2f}y")
                    # LOCK 중에도 distance는 읽지만, 입력칸 자동 반영은 기존 체크박스 조건을 유지한다.
                    if memory_auto_enabled:
                        new_text = f"{distance:.2f}"
                        if self.calc_distance_edit.text().strip() != new_text:
                            self.calc_distance_edit.setText(new_text)
                            changed = True

                    self.maybe_unlock_calc_lock_by_distance(distance)

            if height is not None:
                if not -500.0 <= height <= 500.0:
                    height = None
                else:
                    self.last_memory_height = height
                    if hasattr(self, "memory_height_label"):
                        self.memory_height_label.setText(f"고저: {height:.2f}m")
                    if memory_auto_enabled:
                        new_text = f"{height:.2f}"
                        if self.calc_height_edit.text().strip() != new_text:
                            self.calc_height_edit.setText(new_text)
                            changed = True

            self.last_memory_live_tick = tick

            if distance is not None or height is not None:
                display_path = path
                if len(display_path) > 65:
                    display_path = "..." + display_path[-62:]
                self.set_memory_status(f"상태: DLL live 값 수신 중 tick={tick} {display_path}")
            else:
                self.set_memory_status("상태: DLL live 감시 중 - 샷 화면/값 대기")

        except Exception as e:
            print(f"[WARN] 거리/고저 live 값 읽기 실패: {e}")
            self.set_memory_status("상태: 거리/고저 live 읽기 실패")

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
        self.last_auto_result_signature = None
        self.update_backspin_button_state()
        if hasattr(self, "quick_overlay"):
            self.quick_overlay.update()
        self.refresh_auto_result_overlay()

    def update_overlay_result_from_calc(self, title, result, display, *, extra_lines=None):
        """마지막 계산 결과를 오버레이 좌상단 표시용 상태로 변환한다."""
        if result is None or display is None:
            self.overlay.set_calc_state(None)
            if hasattr(self, "last_auto_result_signature"):
                self.last_auto_result_signature = None
            return

        shot_name = self.calc_shot_combo.currentText()

        lines = [
            str(title),
            f"{shot_name}: {result.power_percent:.1f}% / {result.shot_yards:.1f}y",
            f"장판: {display.get('board_cells_signed', display.get('board_cells', 0.0)):+.3f}칸",
            f"스마트: {display.get('smart_cells_signed', display.get('smart_cells', 0.0)):+.2f}칸",
            f"PB: {result.pb:+.2f} / Real: {result.real_pb:.2f}",
            f"ground : {self.calc_ground_edit.text()}",
            f"spin/curve : S{self.calc_spin_edit.text()} / C{self.calc_curve_edit.text()}",
            f"D{self.calc_distance_edit.text()} H{self.calc_height_edit.text()} W{self.calc_wind_edit.text()} A{self.calc_degree_edit.text()}",
        ]

        if extra_lines:
            lines.extend(extra_lines)

        self.overlay.set_calc_state({
            "type": "calc_result",
            "lines": lines,
        })

    def read_calc_float_silent(self, edit, default=None):
        text = edit.text().strip()
        if text == "":
            if default is None:
                raise ValueError("empty")
            return float(default)
        return float(text)

    def build_display_for_result(self, result, yards_to_pb, yards_to_pba, yards_to_pba_plus, board_per_pb, smart_divisor):
        pb_yards = result.pb * 0.2167
        real_pb_yards = result.real_pb * 0.2167

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
            "custom_pb": pb_yards / yards_to_pb,
            "custom_real_pb": real_pb_yards / yards_to_pb,
            "custom_pba": pb_yards / yards_to_pba,
            "custom_pba_plus": pb_yards / yards_to_pba_plus,
        }

    def run_calc_for_overlay(self, slope_value):
        return calc_shot(
            power=self.read_calc_float_silent(self.calc_power_edit, 31.0),
            auxpart_pwr=self.read_calc_float_silent(self.calc_auxpart_edit, 0.0),
            card_pwr=self.read_calc_float_silent(self.calc_card_edit, 0.0),
            mascot_pwr=self.read_calc_float_silent(self.calc_mascot_edit, 0.0),
            card_ps_pwr=self.read_calc_float_silent(self.calc_card_ps_edit, 0.0),
            club=self.calc_club_combo.currentData(),
            shot=self.calc_shot_combo.currentData(),
            power_shot=self.calc_power_shot_combo.currentData(),
            distance=self.read_calc_float_silent(self.calc_distance_edit, 0.0),
            height=self.read_calc_float_silent(self.calc_height_edit, 0.0),
            wind=self.read_calc_float_silent(self.calc_wind_edit, 0.0),
            degree=self.read_calc_float_silent(self.calc_degree_edit, 0.0),
            ground=self.read_calc_float_silent(self.calc_ground_edit, 100.0),
            spin=self.read_calc_float_silent(self.calc_spin_edit, 0.0),
            curve=self.read_calc_float_silent(self.calc_curve_edit, 0.0),
            slope=str(slope_value),
            line_ball=self.read_calc_float_silent(self.calc_line_ball_edit, 0.0),
            line_ball_random=self.calc_line_ball_random_check.isChecked(),
        )

    def _get_auto_slope_candidate_key(self, mode):
        """자동/live 계산에서 사용할 slope 후보 1개만 고른다.

        비교 모드(XY_COMPARE/MATRIX_COMPARE 등)는 계산 버튼에서만 의미가 있다.
        live 자동 갱신에서는 GUI 렉 방지를 위해 항상 단일 후보로 fallback한다.
        """
        if mode in (None, "", "OFF"):
            return None

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

        if mode in chosen_map:
            return chosen_map[mode]

        # 비교 모드는 자동/live에서는 무조건 가벼운 기본 후보 1개로 대체.
        if mode in ("XY_COMPARE", "MATRIX_COMPARE", "SIGN_COMPARE", "SCALAR_COMPARE", "BOTH_COMPARE"):
            return "R0C_MINUS"

        return "R0C_MINUS"

    def _get_auto_slope_display_name(self, candidate_key):
        name_map = {
            "X_PLUS": "X+",
            "X_MINUS": "X-",
            "Y_PLUS": "Y+",
            "Y_MINUS": "Y-",
            "MAG_PLUS": "MAG+",
            "MAG_MINUS": "MAG-",
            "R0C_PLUS": "R0C+",
            "R0C_MINUS": "R0C-",
            "R04_PLUS": "R04+",
            "R04_MINUS": "R04-",
            "R14_PLUS": "R14+",
            "R14_MINUS": "R14-",
            "R1C_PLUS": "R1C+",
            "R1C_MINUS": "R1C-",
            "A_PLUS": "A+",
            "A_MINUS": "A-",
            "B_PLUS": "B+",
            "B_MINUS": "B-",
            "LEGACY_A": "구A",
            "LEGACY_B": "구B",
        }
        return name_map.get(candidate_key, str(candidate_key or "현재"))

    def get_live_slope_overlay_specs(self):
        """
        결과 오버레이용 slope 후보를 만든다.

        자동/live에서는 후보 비교를 하지 않고 단일 후보 1개만 반환한다.
        후보 전체 비교는 계산 버튼을 눌렀을 때 on_calc_clicked()에서만 수행한다.
        """
        manual_text = self.calc_slope_edit.text().strip() or "0"
        specs = [("현재", manual_text)]

        if not (hasattr(self, "slope_live_auto_check") and self.slope_live_auto_check.isChecked()):
            return specs, "OFF"

        candidates = self.last_slope_live_candidates or {}
        mode = self.slope_live_mode_combo.currentData() if hasattr(self, "slope_live_mode_combo") else "R0C_MINUS"
        candidate_key = self._get_auto_slope_candidate_key(mode)

        if candidate_key:
            value = candidates.get(candidate_key)
            if value is not None:
                return [(self._get_auto_slope_display_name(candidate_key), f"{float(value):.4f}")], mode

        # 아직 live 후보가 없으면 입력칸에 들어온 마지막 값만 사용한다.
        return [("현재", manual_text), ("live대기", None)], mode
    def make_auto_result_signature(self):
        fields = [
            self.calc_power_edit.text(),
            self.calc_auxpart_edit.text(),
            self.calc_card_edit.text(),
            self.calc_mascot_edit.text(),
            self.calc_card_ps_edit.text(),
            self.calc_club_combo.currentData(),
            self.calc_shot_combo.currentData(),
            self.calc_power_shot_combo.currentData(),
            self.calc_distance_edit.text(),
            self.calc_height_edit.text(),
            self.calc_wind_edit.text(),
            self.calc_degree_edit.text(),
            self.calc_ground_edit.text(),
            self.calc_spin_edit.text(),
            self.calc_curve_edit.text(),
            self.calc_slope_edit.text(),
            self.calc_line_ball_edit.text(),
            self.calc_line_ball_random_check.isChecked(),
            self.calc_yards_to_pb_edit.text(),
            self.calc_yards_to_pba_edit.text(),
            self.calc_yards_to_pba_plus_edit.text(),
            self.calc_board_per_pb_edit.text(),
            self.calc_smart_divisor_edit.text(),
            self.show_result_check.isChecked() if hasattr(self, "show_result_check") else True,
            self.slope_live_auto_check.isChecked() if hasattr(self, "slope_live_auto_check") else False,
            self.slope_live_mode_combo.currentData() if hasattr(self, "slope_live_mode_combo") else "R0C_MINUS",
            self.ground_live_auto_check.isChecked() if hasattr(self, "ground_live_auto_check") else False,
            self.club_live_auto_check.isChecked() if hasattr(self, "club_live_auto_check") else False,
            self.spin_curve_live_auto_check.isChecked() if hasattr(self, "spin_curve_live_auto_check") else False,
            self.diff_live_auto_check.isChecked() if hasattr(self, "diff_live_auto_check") else False,
            self.diff_live_invert_check.isChecked() if hasattr(self, "diff_live_invert_check") else False,
        ]

        # 중요: slope 후보 전체를 signature에 넣지 않는다.
        # DLL JSON의 result_matrix/normal 후보가 계속 미세 변화하면 자동 계산이 매번 다시 돌기 때문이다.
        if hasattr(self, "slope_live_auto_check") and self.slope_live_auto_check.isChecked():
            mode = self.slope_live_mode_combo.currentData() if hasattr(self, "slope_live_mode_combo") else "R0C_MINUS"
            candidate_key = self._get_auto_slope_candidate_key(mode)
            candidates = self.last_slope_live_candidates or {}
            value = candidates.get(candidate_key) if candidate_key else None
            fields.append(candidate_key)
            fields.append(None if value is None else round(float(value), 3))

        return tuple(fields)
    def refresh_auto_result_overlay(self):
        """계산 버튼 없이도 좌상단 결과 오버레이를 계속 갱신한다.

        중요:
        - 기본 결과는 항상 slope_break=0 기준으로 계산한다.
        - 기울기 live가 켜져 있으면 선택/후보 기울기 결과를 별도 줄로 추가한다.
        """
        if calc_shot is None:
            return

        if not hasattr(self, "show_result_check") or not self.show_result_check.isChecked():
            if self.overlay.calc_state is not None:
                self.overlay.set_calc_state(None)
            self.last_auto_result_signature = None
            return

        # LOCK 중에는 wind degree/slope/거리 입력칸이 live로 변해도 계산 target을 다시 만들지 않는다.
        # DIFF/LINE만 현재 조준선 기준으로 갱신한다.
        if bool(getattr(self, "calc_lock_enabled", False)):
            self.refresh_diff_overlay_only()
            return

        try:
            # live JSON 입력칸 갱신은 각 live timer에서만 수행한다.
            # 여기서 다시 update_*를 호출하면 JSON 읽기와 setText가 중복되어 GUI가 끊긴다.

            signature = self.make_auto_result_signature()
            if signature == self.last_auto_result_signature:
                return
            self.last_auto_result_signature = signature

            yards_to_pb = self.read_calc_float_silent(self.calc_yards_to_pb_edit, 0.2167)
            yards_to_pba = self.read_calc_float_silent(self.calc_yards_to_pba_edit, 0.8668)
            yards_to_pba_plus = self.read_calc_float_silent(self.calc_yards_to_pba_plus_edit, 1.032)
            board_per_pb = self.read_calc_float_silent(self.calc_board_per_pb_edit, 0.2121)
            smart_divisor = self.read_calc_float_silent(self.calc_smart_divisor_edit, 4.0)

            if yards_to_pb == 0 or yards_to_pba == 0 or yards_to_pba_plus == 0 or smart_divisor == 0:
                raise ValueError("표시 단위 0")

            slope_specs, slope_mode = self.get_live_slope_overlay_specs()
            shot_name = self.calc_shot_combo.currentText()

            valid_results = []
            diff_targets = []

            base_result = self.run_calc_for_overlay("0")
            if not base_result.ok:
                lines = ["실시간 결과", f"계산 실패: {base_result.message}"]
            else:
                base_display = self.build_display_for_result(
                    base_result,
                    yards_to_pb,
                    yards_to_pba,
                    yards_to_pba_plus,
                    board_per_pb,
                    smart_divisor,
                )
                valid_results.append((base_result, base_display))
                diff_targets.append({
                    "name": "기본",
                    "target_pb": float(base_result.pb),
                    "target_board": float(base_display.get("board_cells_signed", 0.0)),
                })

                lines = [
                    "실시간 결과",
                    f"{shot_name}  D{self.calc_distance_edit.text()} H{self.calc_height_edit.text()} W{self.calc_wind_edit.text()} A{self.calc_degree_edit.text()}",
                    f"club : {self.calc_club_combo.currentText()}",
                    f"ground : {self.calc_ground_edit.text()}",
                    f"spin/curve : S{self.calc_spin_edit.text()} / C{self.calc_curve_edit.text()}",
                    f"기본(기울기0): {base_result.power_percent:.1f}% / {base_result.shot_yards:.1f}y / {base_display['board_cells_signed']:+.3f}칸 / PB{base_result.pb:+.2f}",
                ]

                live_values = [(n, v) for n, v in slope_specs if v is not None]
                live_enabled = hasattr(self, "slope_live_auto_check") and self.slope_live_auto_check.isChecked()

                if live_enabled and live_values:
                    for name, slope_value in live_values:
                        # 같은 0값을 중복으로 보여줄 필요는 없다.
                        try:
                            if abs(float(slope_value)) < 0.00005:
                                continue
                        except Exception:
                            pass

                        result = self.run_calc_for_overlay(slope_value)
                        if result.ok:
                            display = self.build_display_for_result(
                                result,
                                yards_to_pb,
                                yards_to_pba,
                                yards_to_pba_plus,
                                board_per_pb,
                                smart_divisor,
                            )
                            valid_results.append((result, display))
                            diff_targets.append({
                                "name": str(name),
                                "target_pb": float(result.pb),
                                "target_board": float(display.get("board_cells_signed", 0.0)),
                            })
                            lines.append(
                                f"{name}(기울기): {result.power_percent:.1f}% / {result.shot_yards:.1f}y / "
                                f"{display['board_cells_signed']:+.3f}칸 / PB{result.pb:+.2f} / S{float(slope_value):+.4f}"
                            )
                        else:
                            lines.append(f"{name}(기울기): 실패")
                elif live_enabled:
                    lines.append(f"Slope live 대기: {slope_mode}")
                else:
                    manual_slope = self.calc_slope_edit.text().strip() or "0"
                    try:
                        manual_is_zero = abs(float(manual_slope)) < 0.00005
                    except Exception:
                        manual_is_zero = False

                    if not manual_is_zero:
                        result = self.run_calc_for_overlay(manual_slope)
                        if result.ok:
                            display = self.build_display_for_result(
                                result,
                                yards_to_pb,
                                yards_to_pba,
                                yards_to_pba_plus,
                                board_per_pb,
                                smart_divisor,
                            )
                            valid_results.append((result, display))
                            diff_targets.append({
                                "name": "수동",
                                "target_pb": float(result.pb),
                                "target_board": float(display.get("board_cells_signed", 0.0)),
                            })
                            lines.append(
                                f"수동기울기: {result.power_percent:.1f}% / {result.shot_yards:.1f}y / "
                                f"{display['board_cells_signed']:+.3f}칸 / PB{result.pb:+.2f} / S{float(manual_slope):+.4f}"
                            )

            if valid_results:
                # BackSpin 버튼 호환을 위해 마지막 자동 계산 결과도 보관한다.
                # 기본 결과를 우선값으로 둔다.
                self.last_calc_result, self.last_calc_display = valid_results[0]
                self.last_calc_shot_type = self.calc_shot_combo.currentData()
                self.update_backspin_button_state()

            # DIFF는 조준 중 자주 바뀌므로 계산 결과 기본 줄과 target만 보관한다.
            # 이후 DIFF timer는 이 기본 줄에 LINE/DIFF 줄만 붙여서 오버레이를 갱신한다.
            self.last_overlay_base_lines_no_diff = list(lines)
            self.last_overlay_diff_targets = list(diff_targets)
            final_lines = self.build_diff_overlay_lines(lines, diff_targets)
            self.overlay.set_calc_state({"type": "calc_result", "lines": final_lines})
            self.last_diff_overlay_signature = None
            self.last_auto_result_error = None

        except Exception as e:
            # 입력 중에는 숫자가 비는 순간이 자주 있으므로 팝업을 띄우지 않고 짧게만 표시한다.
            err = str(e)
            if err != self.last_auto_result_error:
                self.overlay.set_calc_state({"type": "calc_result", "lines": ["실시간 결과", "입력값 대기/오류", err[:48]]})
                self.last_auto_result_error = err

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
            base_slope_text = "0"
            result = run_calc_with_slope(base_slope_text)

            if not result.ok:
                self.last_calc_result = None
                self.last_calc_display = None
                self.last_calc_shot_type = None
                self.update_backspin_button_state()
                self.calc_result_box.setPlainText(result.message)
                self.overlay.set_calc_state({"type": "calc_result", "lines": ["계산 실패", result.message]})
                return

            display = build_display(result)

            self.last_calc_result = result
            self.last_calc_display = display
            self.last_calc_shot_type = self.calc_shot_combo.currentData()
            self.update_backspin_button_state()

            output = []
            append_result_block(output, "[기본 Slope 0]", result, display, base_slope_text)

            try:
                manual_is_zero = abs(float(manual_slope_text)) < 0.00005
            except Exception:
                manual_is_zero = False

            if not manual_is_zero:
                manual_result = run_calc_with_slope(manual_slope_text)
                manual_display = build_display(manual_result) if manual_result.ok else {}
                append_result_block(output, "[수동/현재 Slope]", manual_result, manual_display, manual_slope_text)

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
                f"ground : {self.calc_ground_edit.text()}",
            ])

            self.calc_result_box.setPlainText("\n".join(output))
            self.update_overlay_result_from_calc("계산 결과", result, display, extra_lines=[f"Slope: 기본 0", f"현재 Slope 입력: {manual_slope_text}"])
            self.last_auto_result_signature = None
            self.refresh_auto_result_overlay()

        except Exception as e:
            self.overlay.set_calc_state({"type": "calc_result", "lines": ["계산 실패", str(e)]})
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
                f"ground : {self.calc_ground_edit.text()}",
            ]

            self.calc_result_box.setPlainText("\n".join(output))
            self.update_overlay_result_from_calc("계산 결과", result, display)

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
        self.overlay.set_calc_state(None)
        if hasattr(self, "quick_overlay"):
            self.quick_overlay.update()
        

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

    def on_capture_exclude_changed(self):
        """윈도우 캡처/녹화 제외 체크를 누르는 즉시 메인/퀵 오버레이에 반영한다."""
        try:
            enabled = bool(self.capture_exclude_check.isChecked()) if hasattr(self, "capture_exclude_check") else True
            self.settings["capture_exclude_enabled"] = enabled
            self.overlay.set_settings(self.settings)
            self.apply_control_window_capture_exclude()
            if hasattr(self, "quick_overlay"):
                self.quick_overlay.apply_window_style(force=True)
                self.quick_overlay.apply_capture_exclude_setting(force=True)
        except Exception as e:
            print(f"[WARN] 캡처 제외 즉시 반영 실패: {e}")

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
        self.show_result_check.setChecked(bool(s.get("show_result", True)))
        if hasattr(self, "show_quick_controls_check"):
            self.show_quick_controls_check.setChecked(bool(s.get("show_quick_overlay_controls", True)))
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
            "show_result": self.show_result_check.isChecked(),
            "show_quick_overlay_controls": self.show_quick_controls_check.isChecked() if hasattr(self, "show_quick_controls_check") else True,
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
        if hasattr(self, "quick_overlay"):
            self.quick_overlay.apply_window_style(force=True)
            self.quick_overlay.apply_capture_exclude_setting(force=True)
            QTimer.singleShot(0, lambda: self.quick_overlay.apply_capture_exclude_setting(force=True))
            self.update_quick_overlay_position()
        self.register_hotkey_from_settings()

        if show_message:
            QMessageBox.information(self, "적용 완료", "설정이 적용되었습니다.")

        return True

    def on_start_clicked(self):
        if not self.apply_settings(show_message=False):
            return

        self.overlay.start_overlay()
        self.update_quick_overlay_position()

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
        if hasattr(self, "quick_overlay"):
            self.quick_overlay.hide()
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
                if hasattr(self, "quick_overlay"):
                    if is_started:
                        self.update_quick_overlay_position()
                    else:
                        self.quick_overlay.hide()

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

        if hasattr(self, "quick_overlay"):
            try:
                self.quick_overlay.hide()
                self.quick_overlay.close()
            except Exception:
                pass

        self.overlay.stop_overlay()
        event.accept()
