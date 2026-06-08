import subprocess
import tkinter as tk
from tkinter import messagebox
from datetime import datetime
from pathlib import Path
import threading
import os


# Pangya server folder
BASE_DIR = Path(r"C:\Pangya_US8JP\RELEASE SRV4")

# UwAmp web/db server
WEB_SERVER_NAME = "UwAmp Web/DB Server"
WEB_SERVER_EXE = "UwAmp.exe"
WEB_SERVER_DIR = BASE_DIR / "@WebServer"
WEB_SERVER_PATH = WEB_SERVER_DIR / WEB_SERVER_EXE

# Start order. Stop order is reverse.
SERVERS = [
    ("Auth Server", "AuthServer.exe"),
    ("Login Server", "LoginServer.exe"),
    ("Game Server 01", "GameServer-01.exe"),
    ("Game Server 02", "GameServer-02.exe"),
    ("Message Server", "MessageServer.exe"),
]

START_INTERVAL_MS = 2000

# 로그 폴더
LOG_DIR = BASE_DIR / "server_gui_logs"

# 로그 저장 사용 여부
# False로 바꾸면 서버 stdout/stderr를 전부 버린다.
LOG_ENABLED = True

# 서버 하나당 최근 로그 크기 제한
# 현재 .log 최대 2MB + 이전 .old 최대 2MB 정도만 유지한다.
MAX_LOG_BYTES = 2 * 1024 * 1024

# 한 번에 읽을 stdout/stderr 크기
LOG_READ_CHUNK_SIZE = 4096


class LimitedLogWriter:
    """
    서버 출력 로그를 무한정 누적하지 않고 제한된 크기만 보관한다.

    예:
    AuthServer.log      현재 로그
    AuthServer.log.old  직전 로그

    최대 사용량은 서버 1개당 대략 MAX_LOG_BYTES * 2 정도다.
    """
    def __init__(self, log_path, max_bytes=MAX_LOG_BYTES):
        self.log_path = Path(log_path)
        self.old_path = Path(str(log_path) + ".old")
        self.max_bytes = max_bytes
        self.lock = threading.Lock()
        self.file = None
        self.current_size = 0

        self.open_new_file()

    def open_new_file(self):
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

        # GUI 실행마다 현재 로그는 새로 시작한다.
        # 기존 로그는 .old로 넘긴다.
        try:
            if self.log_path.exists():
                if self.old_path.exists():
                    self.old_path.unlink()
                self.log_path.rename(self.old_path)
        except Exception:
            pass

        self.file = open(self.log_path, "w", encoding="utf-8", errors="ignore")
        self.current_size = 0

    def rotate(self):
        try:
            if self.file:
                self.file.close()
        except Exception:
            pass

        try:
            if self.old_path.exists():
                self.old_path.unlink()
        except Exception:
            pass

        try:
            if self.log_path.exists():
                self.log_path.rename(self.old_path)
        except Exception:
            pass

        self.file = open(self.log_path, "w", encoding="utf-8", errors="ignore")
        self.current_size = 0

    def write_bytes(self, data):
        if not data:
            return

        try:
            text = data.decode("utf-8", errors="ignore")
        except Exception:
            text = str(data)

        if not text:
            return

        with self.lock:
            try:
                text_bytes_len = len(text.encode("utf-8", errors="ignore"))

                if self.current_size + text_bytes_len > self.max_bytes:
                    self.rotate()

                self.file.write(text)
                self.file.flush()
                self.current_size += text_bytes_len

            except Exception:
                # 로그 저장 실패가 서버 실행 자체를 막으면 안 되므로 무시한다.
                pass

    def close(self):
        with self.lock:
            try:
                if self.file:
                    self.file.close()
            except Exception:
                pass
            self.file = None


class PangyaServerGui(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title("Pangya Server Controller")
        self.geometry("620x430")
        self.resizable(False, False)

        self.processes = {}
        self.log_writers = {}
        self.log_threads = {}

        self.status_labels = {}
        self.start_index = 0
        self.is_starting = False
        self._refresh_job = None

        self._build_ui()
        self.start_web_server_on_launch()
        self.refresh_status()

    def _build_ui(self):
        top = tk.Frame(self)
        top.pack(fill="x", padx=12, pady=10)

        tk.Label(top, text="Server Folder:", anchor="w").pack(anchor="w")
        tk.Label(top, text=str(BASE_DIR), anchor="w", fg="#555").pack(anchor="w", pady=(0, 4))
        tk.Label(top, text="Web/DB Server:", anchor="w").pack(anchor="w")
        tk.Label(top, text=str(WEB_SERVER_PATH), anchor="w", fg="#555").pack(anchor="w", pady=(0, 8))

        button_frame = tk.Frame(self)
        button_frame.pack(fill="x", padx=12)

        self.btn_start_all = tk.Button(button_frame, text="SERVER ON", width=16, command=self.start_all)
        self.btn_start_all.pack(side="left", padx=(0, 8))

        self.btn_stop_all = tk.Button(button_frame, text="SERVER OFF", width=16, command=self.stop_all)
        self.btn_stop_all.pack(side="left", padx=(0, 8))

        self.btn_start_web = tk.Button(button_frame, text="WEB/DB ON", width=16, command=self.start_web_server)
        self.btn_start_web.pack(side="left", padx=(0, 8))

        self.btn_stop_web = tk.Button(button_frame, text="WEB/DB OFF", width=16, command=self.stop_web_server)
        self.btn_stop_web.pack(side="left", padx=(0, 8))

        self.btn_refresh = tk.Button(button_frame, text="REFRESH", width=12, command=self.refresh_status)
        self.btn_refresh.pack(side="left")

        list_frame = tk.LabelFrame(self, text="Server Status")
        list_frame.pack(fill="both", expand=True, padx=12, pady=12)

        # UwAmp row
        web_row = tk.Frame(list_frame)
        web_row.pack(fill="x", padx=8, pady=5)

        tk.Label(web_row, text=WEB_SERVER_NAME, width=20, anchor="w").pack(side="left")
        tk.Label(web_row, text=WEB_SERVER_EXE, width=22, anchor="w", fg="#666").pack(side="left")

        web_status = tk.Label(web_row, text="UNKNOWN", width=12, anchor="center")
        web_status.pack(side="left", padx=(8, 8))
        self.status_labels[WEB_SERVER_EXE] = web_status

        tk.Button(web_row, text="Start", width=8, command=self.start_web_server).pack(side="left", padx=(0, 4))
        tk.Button(web_row, text="Stop", width=8, command=self.stop_web_server).pack(side="left")

        separator = tk.Frame(list_frame, height=1, bg="#ddd")
        separator.pack(fill="x", padx=8, pady=4)

        for name, exe in SERVERS:
            row = tk.Frame(list_frame)
            row.pack(fill="x", padx=8, pady=5)

            tk.Label(row, text=name, width=20, anchor="w").pack(side="left")
            tk.Label(row, text=exe, width=22, anchor="w", fg="#666").pack(side="left")

            status = tk.Label(row, text="UNKNOWN", width=12, anchor="center")
            status.pack(side="left", padx=(8, 8))
            self.status_labels[exe] = status

            tk.Button(row, text="Start", width=8, command=lambda e=exe: self.start_one(e)).pack(side="left", padx=(0, 4))
            tk.Button(row, text="Stop", width=8, command=lambda e=exe: self.stop_one(e)).pack(side="left")

        self.log_text = tk.Text(self, height=7, state="disabled")
        self.log_text.pack(fill="x", padx=12, pady=(0, 10))

        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def log(self, msg):
        now = datetime.now().strftime("%H:%M:%S")
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"[{now}] {msg}\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def exe_path(self, exe):
        return BASE_DIR / exe

    def is_running(self, exe):
        # Uses tasklist so status still works even if the process was started outside this GUI.
        try:
            result = subprocess.run(
                ["tasklist", "/FI", f"IMAGENAME eq {exe}", "/NH"],
                capture_output=True,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            return exe.lower() in result.stdout.lower()
        except Exception:
            return False

    def set_status(self, exe, running):
        label = self.status_labels.get(exe)

        if not label:
            return

        if running:
            label.config(text="RUNNING", fg="green")
        else:
            label.config(text="STOPPED", fg="red")

    def refresh_status(self):
        self.set_status(WEB_SERVER_EXE, self.is_running(WEB_SERVER_EXE))

        for name, exe in SERVERS:
            self.set_status(exe, self.is_running(exe))

        if self._refresh_job is not None:
            self.after_cancel(self._refresh_job)

        self._refresh_job = self.after(3000, self.refresh_status)

    def read_process_output_to_limited_log(self, exe_name, proc, writer):
        """
        서버 stdout/stderr를 계속 읽어서 파이프가 막히지 않게 하고,
        제한된 크기의 로그 파일에만 저장한다.
        """
        try:
            while True:
                if proc.stdout is None:
                    break

                data = proc.stdout.read(LOG_READ_CHUNK_SIZE)

                if not data:
                    break

                if writer is not None:
                    writer.write_bytes(data)

        except Exception:
            pass

        finally:
            try:
                if proc.stdout:
                    proc.stdout.close()
            except Exception:
                pass

            if writer is not None:
                writer.close()

    def start_process(self, exe_path, cwd_path, exe_name):
        if not cwd_path.exists():
            messagebox.showerror("Error", f"실행 폴더가 없습니다.\n{cwd_path}")
            return False

        if not exe_path.exists():
            messagebox.showerror("Error", f"EXE 파일이 없습니다.\n{exe_path}")
            return False

        if self.is_running(exe_name):
            self.log(f"이미 실행 중: {exe_name}")
            return True

        try:
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0  # SW_HIDE

            proc = subprocess.Popen(
                [str(exe_path)],
                cwd=str(cwd_path),

                # 중요:
                # DEVNULL로 닫으면 서버가 빈 명령을 계속 읽고 Unknown Command를 반복할 수 있음.
                # PIPE로 열어두되 아무것도 쓰지 않으면 서버는 입력 대기 상태가 된다.
                stdin=subprocess.PIPE,

                # 서버 출력은 저장하지 않고 버린다.
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,

                shell=False,
                startupinfo=startupinfo,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )

            self.processes[exe_name] = proc
            self.log(f"실행 완료: {exe_name} / 로그 저장 안 함")
            return True

        except Exception as e:
            messagebox.showerror("Start Error", f"{exe_name} 실행 실패\n{e}")
            return False

    def start_web_server_on_launch(self):
        # GUI가 켜질 때 UwAmp를 자동 실행한다.
        self.log("GUI 시작: UwAmp Web/DB 자동 실행 확인")
        self.start_web_server()

    def start_web_server(self):
        return self.start_process(WEB_SERVER_PATH, WEB_SERVER_DIR, WEB_SERVER_EXE)

    def stop_web_server(self):
        self.stop_process(WEB_SERVER_EXE)

    def start_one(self, exe):
        return self.start_process(self.exe_path(exe), BASE_DIR, exe)

    def start_all(self):
        if self.is_starting:
            return

        self.is_starting = True
        self.start_index = 0
        self.btn_start_all.config(state="disabled")
        self.log("서버 전체 실행 시작")

        # DB/Web 서버가 꺼져 있으면 서버 EXE 시작 전에 먼저 켠다.
        self.start_web_server()
        self.after(START_INTERVAL_MS, self._start_next)

    def _start_next(self):
        if self.start_index >= len(SERVERS):
            self.is_starting = False
            self.btn_start_all.config(state="normal")
            self.log("서버 전체 실행 완료")
            self.refresh_status()
            return

        name, exe = SERVERS[self.start_index]
        self.start_one(exe)
        self.start_index += 1
        self.after(START_INTERVAL_MS, self._start_next)

    def stop_process(self, exe):
        if not self.is_running(exe):
            self.log(f"이미 종료됨: {exe}")
            return

        try:
            proc = self.processes.get(exe)

            if proc is not None:
                try:
                    if proc.stdin:
                        proc.stdin.close()
                except Exception:
                    pass

            subprocess.run(
                ["taskkill", "/F", "/T", "/IM", exe],
                capture_output=True,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )

            if exe in self.processes:
                del self.processes[exe]

            self.log(f"종료 완료: {exe}")

        except Exception as e:
            messagebox.showerror("Stop Error", f"{exe} 종료 실패\n{e}")

    def stop_one(self, exe):
        self.stop_process(exe)

    def stop_all(self):
        self.log("서버 전체 종료 시작")

        for name, exe in reversed(SERVERS):
            self.stop_one(exe)

        # UwAmp도 같이 종료한다.
        self.stop_web_server()

        self.log("서버 전체 종료 완료")
        self.refresh_status()

    def on_close(self):
        # GUI만 닫을지, 서버도 끌지 선택
        if messagebox.askyesno("Exit", "GUI를 닫으면서 게임 서버와 UwAmp도 종료할까요?"):
            self.stop_all()

        self.destroy()


if __name__ == "__main__":
    app = PangyaServerGui()
    app.mainloop()