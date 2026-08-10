"""数据分析 Agent 平台 · 图形化启动器（零基础用户用）

双击本文件即可使用（.pyw 后缀会用 pythonw 运行，不弹黑色命令行窗口）：
- 【正式模式】后端 + 正式前端：需要注册/登录（走 .env 认证配置）
- 【演示模式】后端 + 演示前端：免登录，打开页面自动加载示例数据，适合现场演示
- 启动后自动打开浏览器，访问 http://127.0.0.1:8000

构建说明：本启动器不自动构建——dist 产物需在 frontend 目录执行 npm run build
生成（或使用「启动.ps1」一键启动）。未构建时应用会提示先构建。
提示手动构建，或沿用现有旧版产物。
"""

from __future__ import annotations

import os
import queue
import shutil
import subprocess
import sys
import threading
import webbrowser
from datetime import datetime
from pathlib import Path

import tkinter as tk
from tkinter import messagebox, ttk

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_PORT = 8000  # 端口被占时自动向后找空闲端口（8000→8001→…）

# 桌面快捷方式传 --autostart：打开窗口后自动启动正式模式（跳转登录页），无需再点按钮
AUTOSTART = "--autostart" in sys.argv

# 静默模式（--silent [--demo]）：无窗口启动——直接起后端 → 打开浏览器启动页。
# 配套使用「一键启动-正式.bat / 一键启动-演示.bat」。
SILENT = "--silent" in sys.argv
SILENT_MODE = "demo" if "--demo" in sys.argv else "normal"


def _写日志(file_path: Path, msg: str) -> None:
    """静默模式日志（无窗口可看，统一落到 .reasonix/run/launcher_silent.log）。"""
    try:
        with file_path.open("a", encoding="utf-8") as f:
            f.write(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}\n")
    except Exception:
        pass


def _健康检查(url: str, timeout: float = 1.5) -> bool:
    import urllib.request
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


class LauncherApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.proc: subprocess.Popen | None = None
        self.log_q: queue.Queue = queue.Queue()
        self.port = DEFAULT_PORT
        self.url = f"http://127.0.0.1:{self.port}"

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
        self.lbl_url = tk.Label(status, text=f"访问地址：{self.url}", font=("Microsoft YaHei", 9),
                 bg="#F7F8FA", fg="#6B7280")
        self.lbl_url.pack(side="right")

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
                  f"· 端口 {DEFAULT_PORT}，如被占用将自动改用空闲端口\n")

    # ── 核心逻辑 ────────────────────────────────────────
    @staticmethod
    def _find_free_port(start: int) -> int:
        """从 start 开始找第一个空闲端口（最多往后找 20 个）。"""
        import socket
        for p in range(start, start + 20):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                if s.connect_ex(("127.0.0.1", p)) != 0:
                    return p
        return start

    @staticmethod
    def _启动后端(mode: str, port: int) -> subprocess.Popen:
        """启动 uvicorn 后端进程（UI 模式与静默模式共用）。

        Args:
            mode: "normal"（正式，走 .env 认证）或 "demo"（免登录演示库）
            port: 目标端口（已确认空闲）
        """
        env = dict(os.environ)
        if mode == "demo":
            env.update({
                "AUTH_ENABLED": "false",                       # 后端免登录
                "FRONTEND_DIST": str(PROJECT_ROOT / "frontend" / "dist-demo"),  # 演示前端
                "DAA_SQLITE_PATH": str(PROJECT_ROOT / "data" / "demo.db"),      # 独立演示库
            })
        else:
            env.update({"FRONTEND_DIST": str(PROJECT_ROOT / "frontend" / "dist")})
        return subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "api.main:app",
             "--host", "127.0.0.1", "--port", str(port), "--log-level", "info"],
            cwd=str(PROJECT_ROOT), env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW,
        )

    def start(self, mode: str):
        if self.proc and self.proc.poll() is None:
            messagebox.showinfo("提示", "服务已在运行，请先点击【停止】")
            return
        # 端口自动漂移：被残留进程/其他程序占用时自动用下一个空闲端口，
        # 而不是拒绝启动——确保双击启动器后打开的永远是新实例（新构建）
        self.port = self._find_free_port(DEFAULT_PORT)
        self.url = f"http://127.0.0.1:{self.port}"
        if self.port != DEFAULT_PORT:
            self._log(f"端口 {DEFAULT_PORT} 被占用，自动改用端口 {self.port}")
        self.lbl_url.config(text=f"访问地址：{self.url}")

        label, dist = ("演示模式", PROJECT_ROOT / "frontend" / "dist-demo") if mode == "demo" else ("正式模式", PROJECT_ROOT / "frontend" / "dist")

        if not dist.is_dir():
            messagebox.showerror("前端未构建",
                                 f"{label}的前端产物不存在：\n{dist}\n\n"
                                 "请先在 frontend 目录执行 npm run build 构建。")
            return

        self._log(f"\n=== 启动（{label}）===")
        try:
            self.proc = self._启动后端(mode, self.port)
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
                with urllib.request.urlopen(f"{self.url}/health", timeout=1) as resp:
                    if resp.status == 200:
                        self.log_q.put(("ready", f"运行中（{label}）"))
                        self.log_q.put(("log", f"✅ 启动完成，正在打开启动页：{self.url}/launch.html\n"))
                        # 打开品牌启动页（动画 + 就绪探测），自动跳转登录/数据页
                        webbrowser.open(f"{self.url}/launch.html")
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

    def _on_close(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
        self.root.destroy()


def _run_silent(mode: str) -> None:
    """静默启动（无窗口）：
    已在运行 → 直接打开启动页；否则起后端 → 就绪后打开启动页 → 挂起等待后端退出。
    """
    import json
    import time
    import urllib.request

    log_dir = PROJECT_ROOT / ".reasonix" / "run"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_f = log_dir / "launcher_silent.log"
    _写日志(log_f, f"=== 静默启动（{mode}）===")

    # 1) 已在运行 → 直接打开启动页（演示与正式共用后端，不重复启动）
    if _健康检查(f"http://127.0.0.1:{DEFAULT_PORT}/health"):
        _写日志(log_f, f"服务已在运行，打开启动页 http://127.0.0.1:{DEFAULT_PORT}/launch.html")
        webbrowser.open(f"http://127.0.0.1:{DEFAULT_PORT}/launch.html")
        return

    # 2) 前端构建产物检查
    dist = PROJECT_ROOT / "frontend" / ("dist-demo" if mode == "demo" else "dist")
    if not dist.is_dir():
        _写日志(log_f, f"前端未构建：{dist}，请先执行 npm run build")
        return
    _写日志(log_f, f"前端产物：{dist}")

    # 3) 端口漂移 + 启动后端
    port = LauncherApp._find_free_port(DEFAULT_PORT)
    url = f"http://127.0.0.1:{port}"
    if port != DEFAULT_PORT:
        _写日志(log_f, f"端口 {DEFAULT_PORT} 被占用，改用 {port}")
    try:
        proc = LauncherApp._启动后端(mode, port)
        _写日志(log_f, f"后端进程 pid={proc.pid} @ {url}")
    except Exception as exc:
        _写日志(log_f, f"启动失败：{exc}")
        return

    # 4) 等待就绪（最多 90 秒）
    ok = False
    for _ in range(180):
        if proc.poll() is not None:
            _写日志(log_f, f"后端进程提前退出 rc={proc.returncode}")
            break
        if _健康检查(f"{url}/health"):
            ok = True
            break
        time.sleep(0.5)
    _写日志(log_f, "后端就绪 ✅" if ok else "后端启动超时 ⚠（打开启动页查看提示）")

    # 5) 记录 pid 供「停止服务.bat」使用
    try:
        (log_dir / "silent_pid.json").write_text(
            json.dumps({"mode": mode, "backend_pid": proc.pid, "port": port,
                        "started": datetime.now().isoformat()}),
            encoding="utf-8")
    except Exception as exc:
        _写日志(log_f, f"pid 记录失败（停止脚本将按命令行匹配兜底）：{exc}")

    # 6) 打开启动页（超时也打开——页面自身会显示"后端启动超时，请查看启动器日志"）
    webbrowser.open(f"{url}/launch.html")

    # 7) 挂起：后端退出时本进程随之退出（生命周期一致，不残留 pythonw）
    try:
        proc.wait()
    except Exception:
        pass
    _写日志(log_f, "后端已停止，静默进程退出")


def main():
    if SILENT:
        _run_silent(SILENT_MODE)
        return
    root = tk.Tk()
    try:
        ttk.Style().theme_use("vista")
    except tk.TclError:
        pass
    LauncherApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
