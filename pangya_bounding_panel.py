import os
import sys
import json

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QLineEdit,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QMessageBox,
    QFileDialog,
    QHeaderView,
    QInputDialog,
)


BOUNDING_COLUMNS = ["홀", "홀컵", "거리/값", "좌", "우", "비고"]


def get_app_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)

    return os.path.dirname(os.path.abspath(__file__))


def get_bounding_json_path():
    return os.path.join(get_app_dir(), "pangya_bounding_data.json")


def get_default_source_txt_path():
    return os.path.join(get_app_dir(), "pangya_bounding_source.txt")


def normalize_cell(value):
    if value is None:
        return ""

    return str(value).strip()


def is_map_header(cols):
    """
    원본 텍스트 예:
        로스    홀컵    좌    우    비고
        라군    홀컵    좌    우
    split 결과:
        ["", "로스", "홀컵", "좌", "우", "비고"]
    """
    if len(cols) < 5:
        return False

    if normalize_cell(cols[1]) == "":
        return False

    return normalize_cell(cols[2]) == "홀컵"


def parse_bounding_text(text):
    """
    탭으로 복사된 엑셀형 텍스트를 맵별 데이터로 변환한다.

    반환 구조:
    {
        "로스": [
            {"hole": "1홀", "cup": "LS011", "distance": "360", "left": "0.3", "right": "-0.4", "note": "Fighting!"},
            ...
        ],
        "스파": [...]
    }
    """
    maps = {}
    current_map = None
    current_hole = ""

    for raw_line in text.splitlines():
        line = raw_line.rstrip("\r\n")

        if line.strip() == "":
            continue

        cols = line.split("\t")

        # 혹시 탭이 깨진 경우를 대비해서 최소 길이를 맞춘다.
        while len(cols) < 6:
            cols.append("")

        if is_map_header(cols):
            current_map = normalize_cell(cols[1])
            current_hole = ""

            if current_map not in maps:
                maps[current_map] = []

            continue

        if current_map is None:
            continue

        hole = normalize_cell(cols[0])

        if hole:
            current_hole = hole
        else:
            hole = current_hole

        cup = normalize_cell(cols[1])

        # 홀컵 코드가 없고 나머지도 다 비어 있으면 무시
        if not cup and not normalize_cell(cols[2]) and not normalize_cell(cols[3]) and not normalize_cell(cols[4]) and not normalize_cell(cols[5]):
            continue

        row = {
            "hole": hole,
            "cup": cup,
            "distance": normalize_cell(cols[2]),
            "left": normalize_cell(cols[3]),
            "right": normalize_cell(cols[4]),
            "note": normalize_cell(cols[5]),
        }

        maps[current_map].append(row)

    return maps


def load_bounding_data():
    json_path = get_bounding_json_path()

    if os.path.exists(json_path):
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[WARN] 바운딩 JSON 로드 실패: {e}")

    source_path = get_default_source_txt_path()

    if os.path.exists(source_path):
        try:
            with open(source_path, "r", encoding="utf-8-sig") as f:
                text = f.read()

            return parse_bounding_text(text)

        except Exception as e:
            print(f"[WARN] 바운딩 원본 TXT 로드 실패: {e}")

    return {}


def save_bounding_data(data):
    path = get_bounding_json_path()

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

    print(f"[INFO] 바운딩 데이터 저장 완료: {path}")


class PangyaBoundingPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.data = load_bounding_data()
        self.map_tabs = None
        self.search_edit = None
        self.search_matches = []
        self.search_index = -1

        self.build_ui()
        self.reload_tabs()

    def on_add_map_clicked(self):
        self.data = self.collect_data_from_tables()

        map_name, ok = QInputDialog.getText(
            self,
            "맵 추가",
            "추가할 맵 이름을 입력하세요."
        )

        if not ok:
            return

        map_name = map_name.strip()

        if not map_name:
            QMessageBox.warning(self, "맵 추가 불가", "맵 이름이 비어 있습니다.")
            return

        if map_name in self.data:
            QMessageBox.warning(self, "맵 추가 불가", "이미 존재하는 맵 이름입니다.")
            return

        prefix, prefix_ok = QInputDialog.getText(
            self,
            "홀컵 코드 prefix",
            "홀컵 코드 앞 2글자를 입력하세요.\n예: AE 입력 시 AE011 ~ AE183 자동 생성\n비워두면 홀컵 코드는 빈 값으로 생성됩니다."
        )

        if not prefix_ok:
            prefix = ""

        prefix = prefix.strip().upper()

        self.data[map_name] = self.make_empty_map_rows(prefix)
        self.reload_tabs()

        for tab_idx in range(self.map_tabs.count()):
            if self.map_tabs.tabText(tab_idx) == map_name:
                self.map_tabs.setCurrentIndex(tab_idx)
                break

    def build_ui(self):
        root = QVBoxLayout(self)

        top_layout = QHBoxLayout()

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("검색어 입력: 맵명, 홀, 홀컵코드, 거리, 좌/우, 비고")

        self.search_btn = QPushButton("검색")
        self.next_btn = QPushButton("다음")
        self.save_btn = QPushButton("저장")
        self.import_btn = QPushButton("TXT 가져오기")
        self.export_btn = QPushButton("TXT 내보내기")
        self.add_row_btn = QPushButton("행 추가")
        self.delete_row_btn = QPushButton("선택 행 삭제")
        self.add_map_btn = QPushButton("맵 추가")
        self.rename_map_btn = QPushButton("맵 이름변경")
        self.delete_map_btn = QPushButton("맵 삭제")

        top_layout.addWidget(QLabel("검색"))
        top_layout.addWidget(self.search_edit, 1)
        top_layout.addWidget(self.search_btn)
        top_layout.addWidget(self.next_btn)
        top_layout.addWidget(self.save_btn)
        top_layout.addWidget(self.import_btn)
        top_layout.addWidget(self.export_btn)
        top_layout.addWidget(self.add_row_btn)
        top_layout.addWidget(self.delete_row_btn)
        top_layout.addWidget(self.add_map_btn)
        top_layout.addWidget(self.rename_map_btn)
        top_layout.addWidget(self.delete_map_btn)

        root.addLayout(top_layout)

        self.info_label = QLabel(
            "셀을 직접 수정한 뒤 저장을 누르면 pangya_bounding_data.json에 저장됩니다. "
            "처음 1회는 TXT 가져오기로 엑셀 복사 텍스트를 불러오면 됩니다."
        )
        self.info_label.setWordWrap(True)
        root.addWidget(self.info_label)

        self.map_tabs = QTabWidget()
        root.addWidget(self.map_tabs, 1)

        self.search_btn.clicked.connect(self.on_search_clicked)
        self.next_btn.clicked.connect(self.on_next_clicked)
        self.save_btn.clicked.connect(self.on_save_clicked)
        self.import_btn.clicked.connect(self.on_import_clicked)
        self.export_btn.clicked.connect(self.on_export_clicked)

        self.add_row_btn.clicked.connect(self.on_add_row_clicked)
        self.delete_row_btn.clicked.connect(self.on_delete_row_clicked)

        self.add_map_btn.clicked.connect(self.on_add_map_clicked)
        self.rename_map_btn.clicked.connect(self.on_rename_map_clicked)
        self.delete_map_btn.clicked.connect(self.on_delete_map_clicked)

        self.search_edit.returnPressed.connect(self.on_search_clicked)
        self.search_edit.textChanged.connect(self.on_search_text_changed)

    def make_table(self, rows):
        table = QTableWidget()
        table.setColumnCount(len(BOUNDING_COLUMNS))
        table.setHorizontalHeaderLabels(BOUNDING_COLUMNS)
        table.setRowCount(len(rows))

        table.setAlternatingRowColors(True)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setSelectionMode(QTableWidget.SingleSelection)
        table.setEditTriggers(
            QTableWidget.DoubleClicked |
            QTableWidget.SelectedClicked |
            QTableWidget.EditKeyPressed |
            QTableWidget.AnyKeyPressed
        )

        for row_idx, row in enumerate(rows):
            values = [
                row.get("hole", ""),
                row.get("cup", ""),
                row.get("distance", ""),
                row.get("left", ""),
                row.get("right", ""),
                row.get("note", ""),
            ]

            for col_idx, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setTextAlignment(Qt.AlignCenter if col_idx < 5 else Qt.AlignLeft | Qt.AlignVCenter)
                table.setItem(row_idx, col_idx, item)

        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.Stretch)

        table.verticalHeader().setDefaultSectionSize(24)

        return table

    def reload_tabs(self):
        self.map_tabs.clear()

        if not self.data:
            empty = QWidget()
            layout = QVBoxLayout(empty)
            label = QLabel(
                "바운딩 데이터가 없습니다.\n"
                "TXT 가져오기 버튼으로 엑셀에서 복사한 탭 구분 텍스트를 불러오세요.\n\n"
                "또는 프로그램 폴더에 pangya_bounding_source.txt 파일을 두고 다시 실행해도 됩니다."
            )
            label.setAlignment(Qt.AlignCenter)
            layout.addWidget(label)
            self.map_tabs.addTab(empty, "데이터 없음")
            return

        for map_name, rows in self.data.items():
            table = self.make_table(rows)
            self.map_tabs.addTab(table, map_name)

    def collect_data_from_tables(self):
        data = {}

        for tab_idx in range(self.map_tabs.count()):
            map_name = self.map_tabs.tabText(tab_idx)
            table = self.map_tabs.widget(tab_idx)

            if not isinstance(table, QTableWidget):
                continue

            rows = []

            for row_idx in range(table.rowCount()):
                row_values = []

                for col_idx in range(table.columnCount()):
                    item = table.item(row_idx, col_idx)
                    row_values.append(item.text().strip() if item else "")

                # 완전히 빈 행은 저장하지 않는다.
                if not any(row_values):
                    continue

                rows.append({
                    "hole": row_values[0],
                    "cup": row_values[1],
                    "distance": row_values[2],
                    "left": row_values[3],
                    "right": row_values[4],
                    "note": row_values[5],
                })

            data[map_name] = rows

        return data

    def current_table(self):
        widget = self.map_tabs.currentWidget()

        if isinstance(widget, QTableWidget):
            return widget

        return None

    def on_save_clicked(self):
        try:
            self.data = self.collect_data_from_tables()
            save_bounding_data(self.data)
            QMessageBox.information(self, "저장 완료", "바운딩 데이터가 저장되었습니다.")

        except Exception as e:
            QMessageBox.critical(self, "저장 실패", str(e))

    def on_import_clicked(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "바운딩 TXT 가져오기",
            get_app_dir(),
            "Text Files (*.txt);;All Files (*.*)"
        )

        if not path:
            return

        reply = QMessageBox.question(
            self,
            "가져오기 확인",
            "TXT를 가져오면 현재 바운딩 데이터가 교체됩니다.\n계속할까요?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        if reply != QMessageBox.Yes:
            return

        try:
            with open(path, "r", encoding="utf-8-sig") as f:
                text = f.read()

            parsed = parse_bounding_text(text)

            if not parsed:
                QMessageBox.warning(self, "가져오기 실패", "가져온 TXT에서 바운딩 데이터를 찾지 못했습니다.")
                return

            self.data = parsed
            self.reload_tabs()
            save_bounding_data(self.data)

            QMessageBox.information(self, "가져오기 완료", "바운딩 TXT를 가져오고 저장했습니다.")

        except Exception as e:
            QMessageBox.critical(self, "가져오기 실패", str(e))

    def on_export_clicked(self):
        self.data = self.collect_data_from_tables()

        path, _ = QFileDialog.getSaveFileName(
            self,
            "바운딩 TXT 내보내기",
            os.path.join(get_app_dir(), "pangya_bounding_export.txt"),
            "Text Files (*.txt);;All Files (*.*)"
        )

        if not path:
            return

        try:
            lines = []

            for map_name, rows in self.data.items():
                lines.append("\t".join(["", map_name, "홀컵", "좌", "우", "비고"]))

                last_hole = None

                for row in rows:
                    hole = row.get("hole", "")
                    display_hole = hole if hole != last_hole else ""

                    lines.append("\t".join([
                        display_hole,
                        row.get("cup", ""),
                        row.get("distance", ""),
                        row.get("left", ""),
                        row.get("right", ""),
                        row.get("note", ""),
                    ]))

                    last_hole = hole

            with open(path, "w", encoding="utf-8-sig") as f:
                f.write("\n".join(lines))

            QMessageBox.information(self, "내보내기 완료", "바운딩 TXT를 내보냈습니다.")

        except Exception as e:
            QMessageBox.critical(self, "내보내기 실패", str(e))

    def on_rename_map_clicked(self):
        table = self.current_table()

        if table is None:
            QMessageBox.warning(self, "이름변경 불가", "변경할 맵 탭을 선택하세요.")
            return

        current_index = self.map_tabs.currentIndex()
        old_name = self.map_tabs.tabText(current_index)

        if old_name == "데이터 없음":
            return

        self.data = self.collect_data_from_tables()

        new_name, ok = QInputDialog.getText(
            self,
            "맵 이름변경",
            "새 맵 이름을 입력하세요.",
            text=old_name
        )

        if not ok:
            return

        new_name = new_name.strip()

        if not new_name:
            QMessageBox.warning(self, "이름변경 불가", "맵 이름이 비어 있습니다.")
            return

        if new_name != old_name and new_name in self.data:
            QMessageBox.warning(self, "이름변경 불가", "이미 존재하는 맵 이름입니다.")
            return

        if new_name == old_name:
            return

        # dict 순서를 유지하면서 key 이름만 변경
        new_data = {}

        for key, value in self.data.items():
            if key == old_name:
                new_data[new_name] = value
            else:
                new_data[key] = value

        self.data = new_data
        self.reload_tabs()

        for tab_idx in range(self.map_tabs.count()):
            if self.map_tabs.tabText(tab_idx) == new_name:
                self.map_tabs.setCurrentIndex(tab_idx)
                break

    def on_delete_map_clicked(self):
        table = self.current_table()

        if table is None:
            QMessageBox.warning(self, "삭제 불가", "삭제할 맵 탭을 선택하세요.")
            return

        current_index = self.map_tabs.currentIndex()
        map_name = self.map_tabs.tabText(current_index)

        if map_name == "데이터 없음":
            return

        reply = QMessageBox.question(
            self,
            "맵 삭제 확인",
            f"'{map_name}' 맵 탭을 삭제할까요?\n저장 전까지는 파일에 반영되지 않지만, 화면에서는 즉시 사라집니다.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        if reply != QMessageBox.Yes:
            return

        self.data = self.collect_data_from_tables()

        if map_name in self.data:
            del self.data[map_name]

        self.reload_tabs()

    def make_empty_map_rows(self, prefix=""):
        """
        새 맵 추가 시 기본 18홀 × 3핀 구조를 만든다.
        prefix를 입력하면 홀컵 코드도 자동 생성한다.
        예: prefix="AE" -> AE011, AE012, AE013 ...
        """
        rows = []

        prefix = (prefix or "").strip().upper()

        for hole_no in range(1, 19):
            for pin_no in range(1, 4):
                cup = ""

                if prefix:
                    cup = f"{prefix}{hole_no:02d}{pin_no}"

                rows.append({
                    "hole": f"{hole_no}홀",
                    "cup": cup,
                    "distance": "",
                    "left": "",
                    "right": "",
                    "note": "",
                })

        return rows
          
    def on_add_row_clicked(self):
        table = self.current_table()

        if table is None:
            return

        row = table.currentRow()

        if row < 0:
            row = table.rowCount() - 1

        insert_at = row + 1
        table.insertRow(insert_at)

        for col_idx in range(table.columnCount()):
            item = QTableWidgetItem("")
            item.setTextAlignment(Qt.AlignCenter if col_idx < 5 else Qt.AlignLeft | Qt.AlignVCenter)
            table.setItem(insert_at, col_idx, item)

        table.setCurrentCell(insert_at, 0)

    def on_delete_row_clicked(self):
        table = self.current_table()

        if table is None:
            return

        row = table.currentRow()

        if row < 0:
            QMessageBox.warning(self, "삭제 불가", "삭제할 행을 선택하세요.")
            return

        table.removeRow(row)

    def on_search_text_changed(self):
        self.search_matches = []
        self.search_index = -1

    def on_search_clicked(self):
        keyword = self.search_edit.text().strip().lower()

        self.search_matches = []
        self.search_index = -1

        if not keyword:
            return

        for tab_idx in range(self.map_tabs.count()):
            map_name = self.map_tabs.tabText(tab_idx)
            table = self.map_tabs.widget(tab_idx)

            if not isinstance(table, QTableWidget):
                continue

            # 맵명 검색도 허용
            if keyword in map_name.lower():
                self.search_matches.append((tab_idx, 0, 0))

            for row_idx in range(table.rowCount()):
                for col_idx in range(table.columnCount()):
                    item = table.item(row_idx, col_idx)

                    if item is None:
                        continue

                    if keyword in item.text().lower():
                        self.search_matches.append((tab_idx, row_idx, col_idx))

        if not self.search_matches:
            QMessageBox.information(self, "검색 결과 없음", "검색 결과가 없습니다.")
            return

        self.search_index = 0
        self.focus_search_match()

    def on_next_clicked(self):
        if not self.search_matches:
            self.on_search_clicked()
            return

        self.search_index += 1

        if self.search_index >= len(self.search_matches):
            self.search_index = 0

        self.focus_search_match()

    def focus_search_match(self):
        if not self.search_matches:
            return

        tab_idx, row_idx, col_idx = self.search_matches[self.search_index]

        self.map_tabs.setCurrentIndex(tab_idx)

        table = self.map_tabs.widget(tab_idx)

        if not isinstance(table, QTableWidget):
            return

        table.setCurrentCell(row_idx, col_idx)
        table.scrollToItem(table.item(row_idx, col_idx))

        self.info_label.setText(
            f"검색 결과 {self.search_index + 1} / {len(self.search_matches)}"
        )