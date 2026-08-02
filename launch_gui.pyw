"""数据分析 Agent 平台 · 图形化启动器（零基础用户用）

双击本文件即可使用（.pyw 后缀会用 pythonw 运行，不弹黑色命令行窗口）：
- 【正式模式】后端 + 正式前端：需要注册/登录（走 .env 认证配置）
- 【演示模式】后端 + 演示前端：免登录，打开页面自动加载示例数据，适合现场演示
- 启动后自动打开浏览器，访问 http://127.0.0.1:8000

只需要 Python（已装本项目依赖），不需要 Node / npm。
"""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path

import tkinter as tk
from tkinter import messagebox, ttk

PROJECT_ROOT = Path(__file__).resolve().parent
PORT = "8000"
URL = f"http://127.0.0.1:{PORT}"

# 桌面快捷方式传 --autostart：打开窗口后自动启动正式模式（跳转登录页），无需再点按钮
AUTOSTART = "--autostart" in sys.argv


class LauncherApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.proc: subprocess.Popen | None = None
        self.log_q: queue.Queue = queue.Queue()

        root.title("数据分析 Agent 平台 · 启动器")
        root.geometry("680x560")
        root.minsize(600, 480)
        root.configure(bg="#F7F8FA")

        # 应用图标（logo.ico，与桌面快捷方式一致）
        try:
            root.iconbitmap(str(PROJECT_ROOT / "logo.ico"))
        except tk.TclError:
            pass

        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(120, self._poll_logs)
        if AUTOSTART:
            # 快捷方式双击场景：自动启动正式模式，跳转登录页
            self.root.after(400, lambda: self.start("normal"))

    # ── UI ──────────────────────────────────────────────
    def _build_ui(self):
        pad = {"padx": 16, "pady": 8}
        header = tk.Frame(self.root, bg="#F7F8FA")
        header.pack(fill="x", **pad)
        # Logo 图片（logo.png，subsample 缩小显示；缺失时优雅降级为纯文字）
        self.logo_img = None
        logo_path = PROJECT_ROOT / "logo.png"
        if logo_path.exists():
            try:
                self.logo_img = tk.PhotoImage(file=str(logo_path)).subsample(2)
                tk.Label(header, image=self.logo_img, bg="#F7F8FA").pack(side="left", padx=(0, 12))
            except tk.TclError:
                self.logo_img = None
        title_box = tk.Frame(header, bg="#F7F8FA")
        title_box.pack(side="left", anchor="w")
        tk.Label(title_box, text="数据分析 Agent 平台", font=("Microsoft YaHei", 15, "bold"),
                 bg="#F7F8FA", fg="#111827").pack(anchor="w")
        tk.Label(title_box, text="选择一个模式启动，浏览器会自动打开", font=("Microsoft YaHei", 9),
                 bg="#F7F8FA", fg="#6B7280").pack(anchor="w", pady=(2, 0))

        btns = tk.Frame(self.root, bg="#F7F8FA")
        btns.pack(fill="x", **pad)
        self.btn_normal = tk.Button(
            btns, text="🚀  正式模式启动", command=lambda: self.start("normal"),
            font=("Microsoft YaHei", 11), bg="#111827", fg="white", relief="flat",
            activebackground="#1F2937", activeforeground="white", cursor="hand2",
            padx=14, pady=10, width=16)
        self.btn_normal.pack(side="left", padx=(0, 8))
        self.btn_demo = tk.Button(
            btns, text="🎁  演示模式启动（免登录）", command=lambda: self.start("demo"),
            font=("Microsoft YaHei", 11), bg="#4F46E5", fg="white", relief="flat",
            activebackground="#4338CA", activeforeground="white", cursor="hand2",
            padx=14, pady=10, width=20)
        self.btn_demo.pack(side="left", padx=(0, 8))
        self.btn_stop = tk.Button(
            btns, text="⏹  停止", command=self.stop,
            font=("Microsoft YaHei", 11), bg="#DC2626", fg="white", relief="flat",
            activebackground="#B91C1C", activeforeground="white", cursor="hand2",
            padx=14, pady=10, width=10, state="disabled")
        self.btn_stop.pack(side="left")

        status = tk.Frame(self.root, bg="#F7F8FA")
        status.pack(fill="x", **pad)
        tk.Label(status, text="状态：", font=("Microsoft YaHei", 10), bg="#F7F8FA",
                 fg="#374151").pack(side="left")
        self.lbl_status = tk.Label(status, text="已停止", font=("Microsoft YaHei", 10, "bold"),
                                   bg="#F7F8FA", fg="#9CA3AF")
        self.lbl_status.pack(side="left")
        tk.Label(status, text=f"访问地址：{URL}", font=("Microsoft YaHei", 9),
                 bg="#F7F8FA", fg="#6B7280").pack(side="right")

        # 启动等待进度条（indeterminate：后端就绪前滚动，就绪后停止）
        self.progress = ttk.Progressbar(self.root, mode="indeterminate", length=420)

        log_frame = tk.Frame(self.root, bg="#F7F8FA")
        log_frame.pack(fill="both", expand=True, padx=16, pady=(0, 16))
        self.txt_log = tk.Text(log_frame, height=12, font=("Consolas", 9), bg="#111827",
                               fg="#D1D5DB", relief="flat", state="disabled", wrap="word")
        self.txt_log.pack(fill="both", expand=True)
        self._log("欢迎使用数据分析 Agent 平台 🎉\n"
                  "· 正式模式：需要注册/登录账号\n"
                  "· 演示模式：免登录，自动加载示例数据\n"
                  f"· 端口 {PORT}，如被占用请先关闭占用程序\n")

    # ── 核心逻辑 ────────────────────────────────────────
    def start(self, mode: str):
        if self.proc and self.proc.poll() is None:
            messagebox.showinfo("提示", "服务已在运行，请先点击【停止】")
            return
        if self._port_in_use():
            messagebox.showerror("端口被占用", f"端口 {PORT} 已被占用。\n"
                                "可能已经有实例在运行，或其它程序占用了 8000 端口。\n"
                                "请关闭占用程序后重试。")
            return

        env = dict(os.environ)
        if mode == "demo":
            env.update({
                "AUTH_ENABLED": "false",                       # 后端免登录
                "FRONTEND_DIST": str(PROJECT_ROOT / "frontend" / "dist-demo"),  # 演示前端
                "DAA_SQLITE_PATH": str(PROJECT_ROOT / "data" / "demo.db"),      # 独立演示库
            })
            label, dist = "演示模式", PROJECT_ROOT / "frontend" / "dist-demo"
        else:
            env.update({"FRONTEND_DIST": str(PROJECT_ROOT / "frontend" / "dist")})
            label, dist = "正式模式", PROJECT_ROOT / "frontend" / "dist"

        if not dist.is_dir():
            messagebox.showerror("前端未构建",
                                 f"{label}的前端产物不存在：\n{dist}\n\n"
                                 "请先在 frontend 目录执行 npm run build 构建。")
            return

        self._log(f"\n=== 启动（{label}）===")
        try:
            self.proc = subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "api.main:app",
                 "--host", "127.0.0.1", "--port", PORT, "--log-level", "info"],
                cwd=str(PROJECT_ROOT), env=env,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace",
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except Exception as exc:
            self._log(f"启动失败：{exc}")
            messagebox.showerror("启动失败", str(exc))
            return

        threading.Thread(target=self._read_output, args=(self.proc,), daemon=True).start()
        self.lbl_status.config(text=f"正在启动（{label}）…", fg="#D97706")
        self.progress.pack(fill="x", padx=16, pady=(0, 8))
        self.progress.start(12)
        self.btn_normal.config(state="disabled")
        self.btn_demo.config(state="disabled")
        self.btn_stop.config(state="normal")
        # 探测就绪后自动打开浏览器
        threading.Thread(target=self._wait_ready_and_open, args=(label,), daemon=True).start()

    def _wait_ready_and_open(self, label: str):
        import time
        import urllib.request
        for _ in range(60):
            if self.proc is None or self.proc.poll() is not None:
                return
            try:
                with urllib.request.urlopen(f"{URL}/health", timeout=1) as resp:
                    if resp.status == 200:
                        self.log_q.put(("ready", f"运行中（{label}）"))
                        self.log_q.put(("log", f"✅ 启动完成，正在打开浏览器：{URL}\n"))
                        webbrowser.open(URL)
                        return
            except Exception:
                pass
            time.sleep(0.5)
        self.log_q.put(("done", "已停止"))
        self.log_q.put(("log", "⚠ 等待后端就绪超时，请查看下方日志。\n"))

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
            self._log("⏹ 已停止。\n")
        self.proc = None
        self.progress.stop()
        self.progress.pack_forget()
        self.lbl_status.config(text="已停止", fg="#9CA3AF")
        self.btn_normal.config(state="normal")
        self.btn_demo.config(state="normal")
        self.btn_stop.config(state="disabled")

    def _read_output(self, proc: subprocess.Popen):
        for line in proc.stdout:
            self.log_q.put(("log", line.rstrip("\n")))

    def _poll_logs(self):
        try:
            while True:
                kind, text = self.log_q.get_nowait()
                if kind == "status":
                    self.lbl_status.config(text=text, fg="#059669")
                elif kind == "ready":
                    # 后端就绪：进度条完成并收起
                    self.progress.stop()
                    self.progress.pack_forget()
                    self.lbl_status.config(text=text, fg="#059669")
                elif kind == "done":
                    self.progress.stop()
                    self.progress.pack_forget()
                    self.lbl_status.config(text=text, fg="#9CA3AF")
                else:
                    self._log(text)
        except queue.Empty:
            pass
        self.root.after(120, self._poll_logs)

    def _log(self, text: str):
        self.txt_log.config(state="normal")
        self.txt_log.insert("end", text + "\n")
        self.txt_log.see("end")
        self.txt_log.config(state="disabled")

    @staticmethod
    def _port_in_use() -> bool:
        import socket
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            return s.connect_ex(("127.0.0.1", int(PORT))) == 0

    def _on_close(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
        self.root.destroy()


def main():
    root = tk.Tk()
    try:
        ttk.Style().theme_use("vista")
    except tk.TclError:
        pass
    LauncherApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
