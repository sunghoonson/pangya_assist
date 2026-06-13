# -*- coding: utf-8 -*-
"""
pangya_overlay_gui_with_calculator.py

분리 후 실행 진입점입니다.
기존처럼 이 파일을 실행하면 Pangya Assist Overlay 설정창이 열립니다.
"""

from pangya_overlay_common import (
    sys,
    QApplication,
    QTimer,
    load_settings,
    apply_gui_scale,
)
from pangya_overlay_widget import PangyaOverlay
from pangya_control_window import PangyaControlWindow


if __name__ == "__main__":
    app = QApplication(sys.argv)

    settings = load_settings()
    apply_gui_scale(settings)

    overlay = PangyaOverlay(settings)
    control_window = PangyaControlWindow(overlay, settings)
    control_window.show()

    QTimer.singleShot(300, control_window.register_hotkey_from_settings)

    sys.exit(app.exec())
