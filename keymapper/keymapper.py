# -*- coding: utf-8 -*-
# =====================================================================
# keymapper.py — 키 매퍼 (GUI)
#
# 키보드에 없는 키(F1, 숫자패드 등) 대신 쓸 키를 직접 지정하는 리매퍼.
# "누를 키(트리거)" 를 누르면 "나갈 키(타겟)" 가 입력된다.
# 타겟에는 F4~F12 가 미리 들어가 있고, 양쪽 모두 GUI에서 변경 가능.
#
# 사용법:
#   1) pip install keyboard
#   2) python keymapper.py   (게임에서 쓸 거면 관리자 권한으로 실행)
#   3) 각 행의 [설정] 을 눌러 트리거/타겟 키를 지정
#   4) [시작] 을 누르면 매핑 동작, [정지] 로 해제
#
# Windows 전용. 설정은 keymap.json 에 저장된다.
# =====================================================================

import json
import os
import sys
import threading
import tkinter as tk
from tkinter import messagebox, ttk

try:
    import keyboard
except ImportError:
    # tkinter 없이 에러만 보여주고 종료 (메시지박스용 최소 루트)
    _r = tk.Tk()
    _r.withdraw()
    messagebox.showerror(
        "오류",
        "keyboard 패키지가 없습니다.\n\npip install keyboard\n\n위 명령으로 설치 후 다시 실행하세요.",
    )
    sys.exit(1)

APP_DIR = os.path.dirname(os.path.abspath(sys.argv[0]))
CONFIG_PATH = os.path.join(APP_DIR, "keymap.json")
DEFAULT_TARGETS = ["f%d" % i for i in range(4, 13)]  # f4 ~ f12
ROW_COUNT = len(DEFAULT_TARGETS)


class KeyMapperApp:
    def __init__(self, root):
        self.root = root
        root.title("키 매퍼 (F4~F12)")
        root.resizable(False, False)

        self.running = False
        self.hotkeys = []  # keyboard.add_hotkey() 가 돌려준 핸들 목록
        self.rows = []     # {"trig_var","tgt_var","buttons":[...]} 목록

        self._build_ui()
        self.load_config(silent=True)
        self._refresh_status("대기 중 — 키를 설정하고 [시작] 을 누르세요")
        root.protocol("WM_DELETE_WINDOW", self.on_close)

    # ---------------- UI 구성 ----------------
    def _build_ui(self):
        main = ttk.Frame(self.root, padding=10)
        main.grid(row=0, column=0, sticky="nsew")

        ttk.Label(
            main,
            text="누를 키(트리거) → 나갈 키(타겟)  |  [설정] 을 누른 뒤 원하는 키를 누르세요",
        ).grid(row=0, column=0, pady=(0, 8))

        self.rows_frame = ttk.Frame(main)
        self.rows_frame.grid(row=1, column=0)

        for i in range(ROW_COUNT):
            self._add_row(i, DEFAULT_TARGETS[i])

        btns = ttk.Frame(main)
        btns.grid(row=2, column=0, pady=(10, 4))

        self.start_btn = ttk.Button(btns, text="시작", width=10, command=self.start)
        self.start_btn.grid(row=0, column=0, padx=3)
        self.stop_btn = ttk.Button(
            btns, text="정지", width=10, command=self.stop, state="disabled"
        )
        self.stop_btn.grid(row=0, column=1, padx=3)
        ttk.Button(btns, text="저장", width=10, command=self.save_config).grid(
            row=0, column=2, padx=3
        )
        ttk.Button(btns, text="불러오기", width=10,
                   command=lambda: self.load_config()).grid(row=0, column=3, padx=3)
        ttk.Button(btns, text="초기화", width=10, command=self.reset_rows).grid(
            row=0, column=4, padx=3
        )

        self.status_var = tk.StringVar()
        ttk.Label(main, textvariable=self.status_var, foreground="blue").grid(
            row=3, column=0, pady=(6, 0)
        )
        ttk.Label(
            main,
            text="※ 게임에서 동작하지 않으면 이 프로그램을 관리자 권한으로 실행하세요.",
            foreground="gray",
        ).grid(row=4, column=0, pady=(2, 0))

    def _add_row(self, idx, target_default=""):
        frm = ttk.Frame(self.rows_frame)
        frm.grid(row=idx, column=0, sticky="ew", pady=2)

        trig_var = tk.StringVar()
        tgt_var = tk.StringVar(value=target_default)

        ttk.Label(frm, text="%d." % (idx + 1), width=3).grid(row=0, column=0)
        ttk.Label(frm, text="누를 키").grid(row=0, column=1)
        ttk.Entry(
            frm, textvariable=trig_var, width=16, state="readonly", justify="center"
        ).grid(row=0, column=2, padx=2)
        trig_btn = ttk.Button(frm, text="설정", width=6)
        trig_btn.grid(row=0, column=3, padx=2)

        ttk.Label(frm, text="→", font=("", 12, "bold")).grid(row=0, column=4, padx=4)

        ttk.Label(frm, text="나갈 키").grid(row=0, column=5)
        ttk.Entry(
            frm, textvariable=tgt_var, width=16, state="readonly", justify="center"
        ).grid(row=0, column=6, padx=2)
        tgt_btn = ttk.Button(frm, text="설정", width=6)
        tgt_btn.grid(row=0, column=7, padx=2)

        clear_btn = ttk.Button(
            frm, text="지우기", width=6,
            command=lambda: (trig_var.set(""), tgt_var.set("")),
        )
        clear_btn.grid(row=0, column=8, padx=2)

        # 람다 클로저 주의: 버튼 생성 후 command 연결
        trig_btn.config(command=lambda v=trig_var, b=trig_btn: self.capture_key(v, b))
        tgt_btn.config(command=lambda v=tgt_var, b=tgt_btn: self.capture_key(v, b))

        self.rows.append(
            {
                "trig_var": trig_var,
                "tgt_var": tgt_var,
                "buttons": [trig_btn, tgt_btn, clear_btn],
            }
        )

    # ---------------- 키 캡처 ----------------
    def capture_key(self, var, button):
        """[설정] 클릭 후 다음에 눌리는 키(조합)를 읽어 var 에 넣는다."""
        if self.running:
            return
        button.config(state="disabled", text="대기중")

        def _worker():
            try:
                hk = keyboard.read_hotkey(suppress=False)  # 예: 'ctrl+q', 'caps lock'
            except Exception:
                hk = ""
            self.root.after(0, self._capture_done, var, button, hk or "")

        threading.Thread(target=_worker, daemon=True).start()

    def _capture_done(self, var, button, hk):
        button.config(state="normal", text="설정")
        if hk:
            var.set(hk)

    # ---------------- 시작 / 정지 ----------------
    def start(self):
        if self.running:
            return
        pairs = []
        seen = {}
        for row in self.rows:
            trig = row["trig_var"].get().strip()
            tgt = row["tgt_var"].get().strip()
            if not trig or not tgt:
                continue  # 빈 행은 건너뜀
            if trig.lower() == tgt.lower():
                messagebox.showwarning(
                    "경고", "'%s' → '%s' : 같은 키끼리는 매핑할 수 없습니다." % (trig, tgt)
                )
                return
            if trig.lower() in seen:
                messagebox.showwarning("경고", "누를 키 '%s' 가 중복됩니다." % trig)
                return
            seen[trig.lower()] = tgt
            pairs.append((trig, tgt))

        if not pairs:
            messagebox.showinfo("알림", "매핑이 비어 있습니다. 먼저 키를 설정하세요.")
            return

        try:
            for trig, tgt in pairs:
                h = keyboard.add_hotkey(
                    trig, lambda t=tgt: keyboard.send(t), suppress=True
                )
                self.hotkeys.append(h)
        except Exception as e:
            self.stop(silent=True)
            messagebox.showerror("오류", "핫키 등록 실패: %s" % e)
            return

        self.running = True
        self._set_editing(False)
        self.start_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self._refresh_status("%d개 매핑 동작 중 — [정지] 를 누르면 해제됩니다" % len(pairs))

    def stop(self, silent=False):
        for h in self.hotkeys:
            try:
                keyboard.remove_hotkey(h)
            except Exception:
                pass
        self.hotkeys = []
        self.running = False
        self._set_editing(True)
        self.start_btn.config(state="normal")
        self.stop_btn.config(state="disabled")
        if not silent:
            self._refresh_status("정지됨")

    def _set_editing(self, enabled):
        state = "normal" if enabled else "disabled"
        for row in self.rows:
            for b in row["buttons"]:
                b.config(state=state)

    # ---------------- 저장 / 불러오기 / 초기화 ----------------
    def save_config(self, silent=False):
        data = {
            "mappings": [
                {"trigger": r["trig_var"].get(), "target": r["tgt_var"].get()}
                for r in self.rows
            ]
        }
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            if not silent:
                messagebox.showinfo("저장", "keymap.json 에 저장했습니다.")
        except Exception as e:
            messagebox.showerror("오류", "저장 실패: %s" % e)

    def load_config(self, silent=False):
        if not os.path.exists(CONFIG_PATH):
            if not silent:
                messagebox.showinfo("알림", "저장된 설정(keymap.json)이 없습니다.")
            return
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                data = json.load(f)
            maps = data.get("mappings", [])
            for i, row in enumerate(self.rows):
                if i < len(maps):
                    row["trig_var"].set(maps[i].get("trigger", ""))
                    row["tgt_var"].set(maps[i].get("target", ""))
            if not silent:
                messagebox.showinfo("불러오기", "설정을 불러왔습니다.")
        except Exception as e:
            messagebox.showerror("오류", "불러오기 실패: %s" % e)

    def reset_rows(self):
        if self.running:
            return
        for i, row in enumerate(self.rows):
            row["trig_var"].set("")
            row["tgt_var"].set(DEFAULT_TARGETS[i] if i < len(DEFAULT_TARGETS) else "")

    # ---------------- 기타 ----------------
    def _refresh_status(self, text):
        self.status_var.set(text)

    def on_close(self):
        self.stop(silent=True)
        self.root.destroy()


def main():
    root = tk.Tk()
    KeyMapperApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
