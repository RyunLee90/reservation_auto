"""
reservation_auto GUI
- 계정 선택, PMS 로그인 정보 입력, 실행/중지, 실시간 로그
"""
import os
import sys
import threading
import tkinter as tk
from tkinter import ttk, scrolledtext
from pathlib import Path

# src 폴더를 path에 추가
BASE_DIR = Path(__file__).resolve().parent
SRC_DIR = BASE_DIR / "src"
sys.path.insert(0, str(SRC_DIR))


ACCOUNTS = ["히카리글로벌", "아고다", "씨트립", "여기어때", "야놀자"]


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("예약 자동화")
        self.resizable(False, False)
        self._running = False
        self._thread = None
        self._build_ui()

    # ── UI 구성 ──────────────────────────────────────────
    def _build_ui(self):
        pad = {"padx": 10, "pady": 5}

        # ── PMS 로그인 ──
        login_frame = ttk.LabelFrame(self, text="PMS 로그인")
        login_frame.grid(row=0, column=0, sticky="ew", **pad)

        ttk.Label(login_frame, text="회사코드").grid(row=0, column=0, sticky="w", padx=5, pady=3)
        self.company_var = tk.StringVar(value=os.getenv("PMS_COMPANY", ""))
        ttk.Entry(login_frame, textvariable=self.company_var, width=20).grid(row=0, column=1, padx=5, pady=3)

        ttk.Label(login_frame, text="ID").grid(row=1, column=0, sticky="w", padx=5, pady=3)
        self.id_var = tk.StringVar(value=os.getenv("PMS_ID", ""))
        ttk.Entry(login_frame, textvariable=self.id_var, width=20).grid(row=1, column=1, padx=5, pady=3)

        ttk.Label(login_frame, text="PW").grid(row=2, column=0, sticky="w", padx=5, pady=3)
        self.pw_var = tk.StringVar(value=os.getenv("PMS_PW", ""))
        ttk.Entry(login_frame, textvariable=self.pw_var, width=20, show="*").grid(row=2, column=1, padx=5, pady=3)

        # ── 계정 선택 ──
        account_frame = ttk.LabelFrame(self, text="처리할 계정 선택")
        account_frame.grid(row=1, column=0, sticky="ew", **pad)

        self.account_vars = {}
        for i, name in enumerate(ACCOUNTS):
            var = tk.BooleanVar(value=True)
            self.account_vars[name] = var
            ttk.Checkbutton(account_frame, text=name, variable=var).grid(
                row=i // 3, column=i % 3, sticky="w", padx=8, pady=2
            )

        # ── 옵션 ──
        option_frame = ttk.LabelFrame(self, text="옵션")
        option_frame.grid(row=2, column=0, sticky="ew", **pad)

        self.dry_run_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            option_frame, text="DRY RUN (저장 안 함 — 테스트용)", variable=self.dry_run_var
        ).grid(row=0, column=0, sticky="w", padx=8, pady=3)

        self.headless_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            option_frame, text="헤드리스 모드 (크롬 창 숨기기)", variable=self.headless_var
        ).grid(row=1, column=0, sticky="w", padx=8, pady=3)

        # ── 실행/중지 버튼 ──
        btn_frame = ttk.Frame(self)
        btn_frame.grid(row=3, column=0, **pad)

        self.run_btn = ttk.Button(btn_frame, text="▶ 실행", command=self._start, width=15)
        self.run_btn.grid(row=0, column=0, padx=5)

        self.stop_btn = ttk.Button(btn_frame, text="■ 중지", command=self._stop, width=15, state="disabled")
        self.stop_btn.grid(row=0, column=1, padx=5)

        # ── 실시간 로그 ──
        log_frame = ttk.LabelFrame(self, text="실시간 로그")
        log_frame.grid(row=4, column=0, sticky="nsew", **pad)

        self.log_box = scrolledtext.ScrolledText(log_frame, width=70, height=20, state="disabled", font=("Consolas", 9))
        self.log_box.pack(fill="both", expand=True, padx=5, pady=5)

        # ── 상태바 ──
        self.status_var = tk.StringVar(value="대기 중")
        ttk.Label(self, textvariable=self.status_var, foreground="gray").grid(row=5, column=0, sticky="w", padx=10)

    # ── 로그 출력 ──────────────────────────────────────
    def log(self, msg: str):
        self.log_box.configure(state="normal")
        self.log_box.insert("end", msg + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    # ── 실행 ───────────────────────────────────────────
    def _start(self):
        selected = [name for name, var in self.account_vars.items() if var.get()]
        if not selected:
            self.log("⚠ 계정을 하나 이상 선택해주세요.")
            return
        if not self.company_var.get() or not self.id_var.get() or not self.pw_var.get():
            self.log("⚠ 회사코드 / ID / PW 를 모두 입력해주세요.")
            return

        # 환경변수 설정
        os.environ["PMS_COMPANY"] = self.company_var.get()
        os.environ["PMS_ID"] = self.id_var.get()
        os.environ["PMS_PW"] = self.pw_var.get()
        os.environ["ACCOUNTS"] = ",".join(selected)
        os.environ["DRY_RUN"] = "1" if self.dry_run_var.get() else "0"
        os.environ["HEADLESS"] = "1" if self.headless_var.get() else "0"

        self._running = True
        self.run_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.status_var.set("실행 중...")
        self.log("=" * 50)
        self.log(f"실행 시작 — 계정: {', '.join(selected)}" + (" [DRY RUN]" if self.dry_run_var.get() else ""))
        self.log("=" * 50)

        # 별도 스레드에서 main.run() 실행 (UI 멈춤 방지)
        self._thread = threading.Thread(target=self._run_main, daemon=True)
        self._thread.start()

    def _run_main(self):
        try:
            import logging
            import builtins

            # print 리디렉션
            _orig = builtins.print
            def _gui_print(*args, **kwargs):
                msg = " ".join(str(a) for a in args)
                self.after(0, self.log, msg)
                _orig(*args, **kwargs)
            builtins.print = _gui_print

            # logging 도 GUI 로그창으로 리디렉션
            class GUILogHandler(logging.Handler):
                def __init__(self, app):
                    super().__init__()
                    self.app = app
                def emit(self, record):
                    msg = self.format(record)
                    self.app.after(0, self.app.log, msg)

            gui_handler = GUILogHandler(self)
            gui_handler.setFormatter(logging.Formatter("%(asctime)s %(message)s", datefmt="%H:%M:%S"))
            logging.getLogger().addHandler(gui_handler)

            import main as main_module
            main_module.run()
        except Exception as e:
            self.after(0, self.log, f"오류 발생: {e}")
        finally:
            self.after(0, self._on_finished)

    def _on_finished(self):
        self._running = False
        self.run_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")
        self.status_var.set("완료")
        self.log("=" * 50)
        self.log("자동화 종료.")
        self.log("=" * 50)

    # ── 중지 ───────────────────────────────────────────
    def _stop(self):
        self.log("중지 요청 — 현재 예약 처리 완료 후 종료됩니다.")
        self.status_var.set("중지 중...")
        # main.py 의 _driver_alive 체크로 자연스럽게 종료됨
        # 강제 종료가 필요하면 아래 주석 해제
        # if self._thread and self._thread.is_alive():
        #     os._exit(0)


if __name__ == "__main__":
    app = App()
    app.protocol("WM_DELETE_WINDOW", lambda: os._exit(0))
    app.mainloop()
