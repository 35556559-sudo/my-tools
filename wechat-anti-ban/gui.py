"""
微信防封助手 - GUI主程序
带系统托盘、设置界面，启动后自动最小化到托盘
"""
import json
import os
import sys
import threading
import time
import traceback
from pathlib import Path

import tkinter as tk
from tkinter import ttk, messagebox, colorchooser, filedialog

# ===== 全局崩溃日志 =====
LOG_PATH = Path(__file__).parent / "temp" / "error.log"
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)


def _excepthook(exc_type, exc_value, exc_tb):
    """全局未捕获异常钩子，把崩溃信息写到日志文件"""
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"\n{'='*60}\n")
            f.write(f"时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            traceback.print_exception(exc_type, exc_value, exc_tb, file=f)
    except Exception:
        pass
    # 调用默认钩子
    sys.__excepthook__(exc_type, exc_value, exc_tb)


sys.excepthook = _excepthook

# 线程未捕获异常也要记录
def _thread_excepthook(args):
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"\n{'='*60}\n")
            f.write(f"线程异常 时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            traceback.print_exception(args.exc_type, args.exc_value, args.exc_traceback, file=f)
    except Exception:
        pass


threading.excepthook = _thread_excepthook


import pystray
from PIL import Image

# 将当前目录加入路径
sys.path.insert(0, str(Path(__file__).parent))

from hotkey import HotkeyManager
from enter_hotkey import EnterHotkey
from text_capture import TextCapture
from gif_generator import GifGenerator
from injector import Injector
from window_detector import is_wechat_active


CONFIG_PATH = Path(__file__).parent / "config.json"
ICON_PATH = Path(__file__).parent / "assets" / "app.ico"
TEMP_DIR = str(Path(__file__).parent / "temp")

# 可选字体列表
FONT_OPTIONS = ["微软雅黑", "黑体", "宋体", "仿宋", "楷体", "Consolas", "Arial"]


class Tooltip:
    """鼠标悬停提示框"""
    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tip_window = None
        widget.bind("<Enter>", self.show_tip)
        widget.bind("<Leave>", self.hide_tip)

    def show_tip(self, event=None):
        if self.tip_window or not self.text:
            return
        x = self.widget.winfo_rootx() + 20
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 5
        self.tip_window = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        label = tk.Label(
            tw, text=self.text, justify="left",
            background="#ffffe0", relief="solid", borderwidth=1,
            font=("微软雅黑", 9), wraplength=250, padx=8, pady=5
        )
        label.pack()

    def hide_tip(self, event=None):
        tw = self.tip_window
        self.tip_window = None
        if tw:
            tw.destroy()


class GifApp:
    # 默认配置
    DEFAULT_CONFIG = {
        "hotkey": "numpad_enter",
        "auto_send": True,
        "auto_start": True,
        "paused": False,
        "keyword_detect_enabled": False,
        "keywords": "",
        "gif": {
            "width": 240,
            "height": 240,
            "font_family": "微软雅黑",
            "font_size": 26,
            "line_height": 27,
            "text_color": "#000000",
            "bg_color": "#FFFFFF",
            "margin_left": 5,
            "margin_right": 5,
            "margin_top": 5,
            "margin_bottom": 5,
            "blink_last_punct": True,
            "blink_interval_ms": 500,
            "max_chars": 64,
            "pagination_enabled": True,
            "title_enabled": True,
            "title_color": "#FF0000",
            "title_font_size": 32,
            "bg_image_path": "",
            "bg_image_opacity": 20
        },
        "temp_dir": "./temp",
        "temp_cleanup_hours": 24,
        "wechat": {
            "process_name": "WeChat.exe",
            "window_title_keyword": "微信"
        }
    }

    def __init__(self):
        self.config = self.load_config()
        self.hotkey_mgr = None
        self.enter_hotkey = None
        self.tray_icon = None
        self.root = None
        self.running = True
        self.paused = self.config.get("paused", False)

        # 启动快捷键监听（后台线程）
        if not self.paused:
            self.start_hotkey_listener()

        # 启动GUI
        self.init_gui()

        # 启动系统托盘
        self.start_tray()

        # 如果配置为暂停状态，更新界面
        if self.paused:
            self._update_pause_ui()

    def load_config(self):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)

    def save_config(self):
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(self.config, f, ensure_ascii=False, indent=2)

    # ========== 快捷键逻辑 ==========
    def on_hotkey_triggered(self):
        """快捷键触发后的主流程（在后台线程执行）"""
        try:
            if not is_wechat_active(self.config["wechat"]):
                return

            text_capture = TextCapture()
            text = text_capture.capture_selected_text()

            if not text or not text.strip():
                text_capture.restore_clipboard()
                return

            gif_gen = GifGenerator(self.config["gif"], TEMP_DIR)
            gif_paths = gif_gen.generate(text)

            if not gif_paths:
                text_capture.restore_clipboard()
                return

            if len(gif_paths) == 1:
                # 单张：按auto_send设置
                injector = Injector(auto_send=self.config["auto_send"])
                injector.paste_file(gif_paths[0])
                time.sleep(0.2)
                text_capture.restore_clipboard()
            else:
                # 多张：自动按顺序一张一张发送
                time.sleep(0.1)
                text_capture.restore_clipboard()
                for i, gif_path in enumerate(gif_paths):
                    injector = Injector(auto_send=True)
                    injector.paste_file(gif_path)
                    time.sleep(0.7)  # 等待发送完成，再发下一张

        except Exception as e:
            print(f"快捷键执行出错: {e}")

    def start_hotkey_listener(self):
        """启动快捷键监听（Enter键用底层钩子，其他用GlobalHotKeys）"""
        # 先停止所有监听
        if self.hotkey_mgr:
            self.hotkey_mgr.stop()
            self.hotkey_mgr = None
        if self.enter_hotkey:
            self.enter_hotkey.stop()
            self.enter_hotkey = None

        hotkey = self.config["hotkey"].strip().lower()

        if hotkey in ("enter", "return", "numpad_enter", "both_enter"):
            # Enter键（主键盘/小键盘/两者）：使用底层键盘钩子，实现第一下转GIF、第二下发送
            self.enter_hotkey = EnterHotkey(self.config, TEMP_DIR)
            self.enter_hotkey.start()
            print(f"[快捷键] 使用Enter键模式（{hotkey}），第一下转GIF，第二下发送")
            # 后台预加载OCR模型（关键词检测用，避免第一次按回车卡顿）
            try:
                from ocr_reader import OcrReader
                threading.Thread(target=OcrReader.preload, daemon=True).start()
            except Exception:
                pass
        else:
            # 普通快捷键：使用GlobalHotKeys
            self.hotkey_mgr = HotkeyManager()
            self.hotkey_mgr.register(self.config["hotkey"], self.on_hotkey_triggered)
            self.hotkey_mgr.start()

    # ========== 系统托盘 ==========
    def start_tray(self):
        """启动系统托盘图标"""
        def on_show(icon, item):
            self.root.after(0, self.show_window)

        def on_quit(icon, item):
            self.running = False
            self.root.after(0, self.quit_app)

        def on_default(icon, item):
            self.root.after(0, self.toggle_window)

        image = Image.open(ICON_PATH)
        menu = pystray.Menu(
            pystray.MenuItem("显示设置", on_show, default=True),
            pystray.MenuItem("退出", on_quit),
        )
        self.tray_icon = pystray.Icon("text_gif_helper", image, "微信防封助手", menu)

        # 托盘在后台线程运行
        tray_thread = threading.Thread(target=self.tray_icon.run, daemon=True)
        tray_thread.start()

    # ========== GUI ==========
    def init_gui(self):
        """初始化GUI界面"""
        self.root = tk.Tk()
        self.root.title("微信防封助手 - 设置")
        self.root.geometry("380x680")
        self.root.resizable(False, False)

        # 设置窗口图标
        try:
            self.root.iconbitmap(str(ICON_PATH))
        except Exception:
            pass

        # 关闭窗口时最小化到托盘，而不是退出
        self.root.protocol("WM_DELETE_WINDOW", self.hide_window)

        self.create_widgets()

        # 启动后自动隐藏窗口（只显示托盘）
        self.root.after(500, self.hide_window)

        # 启动单实例激活信号轮询
        self.root.after(1000, lambda: _check_show_request(self))

    def create_widgets(self):
        """创建所有界面控件"""
        main_frame = ttk.Frame(self.root, padding=6)
        main_frame.pack(fill="both", expand=True)
        scroll_frame = main_frame

        # 存储所有输入控件的引用
        self.entries = {}
        self.check_vars = {}
        self.color_buttons = {}

        # ===== 基本设置 =====
        basic_frame = ttk.LabelFrame(scroll_frame, text="基本设置", padding=8)
        basic_frame.pack(fill="x", padx=8, pady=4)

        # 快捷键
        ttk.Label(basic_frame, text="快捷键:").grid(row=0, column=0, sticky="w", pady=2)
        self.hotkey_var = tk.StringVar(value=self.config["hotkey"])
        self.entries["hotkey"] = ttk.Entry(basic_frame, width=16, textvariable=self.hotkey_var)
        self.entries["hotkey"].grid(row=0, column=1, sticky="w", pady=2, padx=4)
        self._hotkey_capturing = False
        self.entries["hotkey"].bind("<Button-1>", self._start_hotkey_capture)
        self.entries["hotkey"].bind("<KeyPress>", self._on_hotkey_key)
        self.entries["hotkey"].configure(foreground="black")
        ttk.Label(basic_frame, text="(点击后按键)", foreground="gray").grid(row=0, column=2, sticky="w")

        # 自动发送 + 开机启动（同一行）
        self.check_vars["auto_send"] = tk.BooleanVar(value=self.config["auto_send"])
        ttk.Checkbutton(
            basic_frame, text="自动发送",
            variable=self.check_vars["auto_send"]
        ).grid(row=1, column=0, sticky="w", pady=2)

        self.check_vars["auto_start"] = tk.BooleanVar(value=self.config.get("auto_start", True))
        ttk.Checkbutton(
            basic_frame, text="开机启动",
            variable=self.check_vars["auto_start"]
        ).grid(row=1, column=1, sticky="w", pady=2)

        # 关键词检测开关（单独一行）
        self.check_vars["keyword_detect_enabled"] = tk.BooleanVar(value=self.config.get("keyword_detect_enabled", False))
        ttk.Checkbutton(
            basic_frame, text="关键词检测",
            variable=self.check_vars["keyword_detect_enabled"]
        ).grid(row=2, column=0, columnspan=3, sticky="w", pady=2)

        # 关键词输入框（另起一行，340x50）
        self.keyword_text = tk.Text(basic_frame, height=3, width=26, wrap="word")
        self.keyword_text.grid(row=3, column=0, columnspan=3, sticky="we", pady=2)
        self.keyword_text.insert("1.0", self.config.get("keywords", ""))
        basic_frame.columnconfigure(0, weight=1)
        ttk.Label(basic_frame, text="(逗号分隔，含有关键词自动转GIF)", foreground="gray").grid(row=4, column=0, columnspan=3, sticky="w", pady=(0, 2))

        # ===== GIF设置 =====
        gif_frame = ttk.LabelFrame(scroll_frame, text="GIF 图片设置", padding=8)
        gif_frame.pack(fill="x", padx=8, pady=4)

        gif = self.config["gif"]

        # 宽度 + 高度
        ttk.Label(gif_frame, text="宽度:").grid(row=0, column=0, sticky="w", pady=2)
        self.entries["gif.width"] = ttk.Entry(gif_frame, width=6)
        self.entries["gif.width"].insert(0, gif["width"])
        self.entries["gif.width"].grid(row=0, column=1, sticky="w", padx=3)

        ttk.Label(gif_frame, text="高度:").grid(row=0, column=2, sticky="w", pady=2)
        self.entries["gif.height"] = ttk.Entry(gif_frame, width=6)
        self.entries["gif.height"].insert(0, gif["height"])
        self.entries["gif.height"].grid(row=0, column=3, sticky="w", padx=3)

        # 字体 + 字号
        ttk.Label(gif_frame, text="字体:").grid(row=1, column=0, sticky="w", pady=2)
        self.entries["gif.font_family"] = ttk.Combobox(gif_frame, values=FONT_OPTIONS, width=10)
        self.entries["gif.font_family"].set(gif["font_family"])
        self.entries["gif.font_family"].grid(row=1, column=1, sticky="w", padx=3)

        ttk.Label(gif_frame, text="字号:").grid(row=1, column=2, sticky="w", pady=2)
        self.entries["gif.font_size"] = ttk.Entry(gif_frame, width=6)
        self.entries["gif.font_size"].insert(0, gif["font_size"])
        self.entries["gif.font_size"].grid(row=1, column=3, sticky="w", padx=3)

        # 行高
        ttk.Label(gif_frame, text="行高:").grid(row=2, column=0, sticky="w", pady=2)
        self.entries["gif.line_height"] = ttk.Entry(gif_frame, width=6)
        self.entries["gif.line_height"].insert(0, gif["line_height"])
        self.entries["gif.line_height"].grid(row=2, column=1, sticky="w", padx=3)

        # 文字颜色
        ttk.Label(gif_frame, text="文字颜色:").grid(row=3, column=0, sticky="w", pady=2)
        self.color_buttons["gif.text_color"] = tk.Button(
            gif_frame, text="  ", bg=gif["text_color"], width=3,
            command=lambda key="gif.text_color": self.choose_color(key)
        )
        self.color_buttons["gif.text_color"].grid(row=3, column=1, sticky="w", padx=3)
        self.entries["gif.text_color"] = ttk.Entry(gif_frame, width=9)
        self.entries["gif.text_color"].insert(0, gif["text_color"])
        self.entries["gif.text_color"].grid(row=3, column=2, columnspan=2, sticky="w", padx=3)

        # 背景颜色
        ttk.Label(gif_frame, text="背景颜色:").grid(row=4, column=0, sticky="w", pady=2)
        self.color_buttons["gif.bg_color"] = tk.Button(
            gif_frame, text="  ", bg=gif["bg_color"], width=3,
            command=lambda key="gif.bg_color": self.choose_color(key)
        )
        self.color_buttons["gif.bg_color"].grid(row=4, column=1, sticky="w", padx=3)
        self.entries["gif.bg_color"] = ttk.Entry(gif_frame, width=9)
        self.entries["gif.bg_color"].insert(0, gif["bg_color"])
        self.entries["gif.bg_color"].grid(row=4, column=2, columnspan=2, sticky="w", padx=3)

        # 边距（4个一行）
        ttk.Label(gif_frame, text="左边距:").grid(row=5, column=0, sticky="w", pady=2)
        self.entries["gif.margin_left"] = ttk.Entry(gif_frame, width=6)
        self.entries["gif.margin_left"].insert(0, gif["margin_left"])
        self.entries["gif.margin_left"].grid(row=5, column=1, sticky="w", padx=3)

        ttk.Label(gif_frame, text="右边距:").grid(row=5, column=2, sticky="w", pady=2)
        self.entries["gif.margin_right"] = ttk.Entry(gif_frame, width=6)
        self.entries["gif.margin_right"].insert(0, gif["margin_right"])
        self.entries["gif.margin_right"].grid(row=5, column=3, sticky="w", padx=3)

        ttk.Label(gif_frame, text="上边距:").grid(row=6, column=0, sticky="w", pady=2)
        self.entries["gif.margin_top"] = ttk.Entry(gif_frame, width=6)
        self.entries["gif.margin_top"].insert(0, gif["margin_top"])
        self.entries["gif.margin_top"].grid(row=6, column=1, sticky="w", padx=3)

        ttk.Label(gif_frame, text="下边距:").grid(row=6, column=2, sticky="w", pady=2)
        self.entries["gif.margin_bottom"] = ttk.Entry(gif_frame, width=6)
        self.entries["gif.margin_bottom"].insert(0, gif["margin_bottom"])
        self.entries["gif.margin_bottom"].grid(row=6, column=3, sticky="w", padx=3)

        # 标点闪烁 + 闪烁间隔
        self.check_vars["gif.blink_last_punct"] = tk.BooleanVar(value=gif["blink_last_punct"])
        ttk.Checkbutton(
            gif_frame, text="标点闪烁",
            variable=self.check_vars["gif.blink_last_punct"]
        ).grid(row=7, column=0, columnspan=2, sticky="w", pady=2)

        ttk.Label(gif_frame, text="间隔(ms):").grid(row=7, column=2, sticky="w", pady=2)
        self.entries["gif.blink_interval_ms"] = ttk.Entry(gif_frame, width=6)
        self.entries["gif.blink_interval_ms"].insert(0, gif["blink_interval_ms"])
        self.entries["gif.blink_interval_ms"].grid(row=7, column=3, sticky="w", padx=3)

        # 长文分页开关 + 分页字数
        self.check_vars["gif.pagination_enabled"] = tk.BooleanVar(value=gif.get("pagination_enabled", True))
        ttk.Checkbutton(
            gif_frame, text="长文分页",
            variable=self.check_vars["gif.pagination_enabled"]
        ).grid(row=8, column=0, sticky="w", pady=2)
        ttk.Label(gif_frame, text="超").grid(row=8, column=1, sticky="e", pady=2)
        self.entries["gif.max_chars"] = ttk.Entry(gif_frame, width=5)
        self.entries["gif.max_chars"].insert(0, gif["max_chars"])
        self.entries["gif.max_chars"].grid(row=8, column=2, sticky="w", padx=2)
        ttk.Label(gif_frame, text="字分多张").grid(row=8, column=3, sticky="w", pady=2)

        # 标题功能开关 + 标题字号
        self.check_vars["gif.title_enabled"] = tk.BooleanVar(value=gif.get("title_enabled", False))
        ttk.Checkbutton(
            gif_frame, text="标题功能",
            variable=self.check_vars["gif.title_enabled"]
        ).grid(row=9, column=0, sticky="w", pady=2)
        ttk.Label(gif_frame, text="标题字号:").grid(row=9, column=1, sticky="e", pady=2)
        self.entries["gif.title_font_size"] = ttk.Entry(gif_frame, width=5)
        self.entries["gif.title_font_size"].insert(0, gif.get("title_font_size", 32))
        self.entries["gif.title_font_size"].grid(row=9, column=2, sticky="w", padx=2)
        # 帮助问号
        help_label = tk.Label(
            gif_frame, text="?", fg="white", bg="#4A90D9",
            width=2, height=1, font=("Arial", 9, "bold"), cursor="hand2"
        )
        help_label.grid(row=9, column=3, sticky="w", padx=5)
        Tooltip(help_label, "如果想设置标题，在需要设置标题的文字后面加短横线 - 。短横线之前的文字会自动显示标题的颜色、字号和换行。")

        # 标题颜色
        ttk.Label(gif_frame, text="标题颜色:").grid(row=10, column=0, sticky="w", pady=2)
        self.color_buttons["gif.title_color"] = tk.Button(
            gif_frame, text="  ", bg=gif.get("title_color", "#FF0000"), width=3,
            command=lambda key="gif.title_color": self.choose_color(key)
        )
        self.color_buttons["gif.title_color"].grid(row=10, column=1, sticky="w", padx=3)
        self.entries["gif.title_color"] = ttk.Entry(gif_frame, width=9)
        self.entries["gif.title_color"].insert(0, gif.get("title_color", "#FF0000"))
        self.entries["gif.title_color"].grid(row=10, column=2, columnspan=2, sticky="w", padx=3)

        # 底图功能
        ttk.Label(gif_frame, text="底图:").grid(row=11, column=0, sticky="w", pady=2)
        self.bg_image_var = tk.StringVar(value=gif.get("bg_image_path", ""))
        ttk.Button(
            gif_frame, text="选择图片", width=8,
            command=self.choose_bg_image
        ).grid(row=11, column=1, sticky="w", padx=3)
        ttk.Button(
            gif_frame, text="清除", width=5,
            command=self.clear_bg_image
        ).grid(row=11, column=2, sticky="w", padx=3)
        # 底图文件名显示
        self.bg_image_label = ttk.Label(gif_frame, text="", foreground="gray", width=15)
        self.bg_image_label.grid(row=11, column=3, sticky="w", pady=2)
        self._update_bg_image_label()

        # 底图透明度
        ttk.Label(gif_frame, text="不透明度:").grid(row=12, column=0, sticky="w", pady=2)
        self.bg_opacity_var = tk.IntVar(value=gif.get("bg_image_opacity", 50))
        self.bg_opacity_scale = ttk.Scale(
            gif_frame, from_=0, to=100, orient="horizontal",
            variable=self.bg_opacity_var, command=self._on_opacity_change
        )
        self.bg_opacity_scale.grid(row=12, column=1, columnspan=2, sticky="we", padx=3)
        self.bg_opacity_label = ttk.Label(gif_frame, text=f"{gif.get('bg_image_opacity', 50)}%", width=5)
        self.bg_opacity_label.grid(row=12, column=3, sticky="w", pady=2)

        # ===== 按钮区（两排） =====
        btn_frame1 = ttk.Frame(scroll_frame)
        btn_frame1.pack(fill="x", padx=8, pady=(8, 2))

        ttk.Button(btn_frame1, text="保存设置", command=self.save_settings).pack(side="left", padx=3, expand=True, fill="x")
        self.pause_button = ttk.Button(btn_frame1, text="暂停", command=self.toggle_pause)
        self.pause_button.pack(side="left", padx=3, expand=True, fill="x")
        ttk.Button(btn_frame1, text="恢复默认", command=self.reset_to_default).pack(side="left", padx=3, expand=True, fill="x")

        btn_frame2 = ttk.Frame(scroll_frame)
        btn_frame2.pack(fill="x", padx=8, pady=2)

        ttk.Button(btn_frame2, text="最小化到托盘", command=self.hide_window).pack(side="left", padx=3, expand=True, fill="x")
        ttk.Button(btn_frame2, text="退出程序", command=self.quit_app).pack(side="left", padx=3, expand=True, fill="x")

        # 状态提示
        self.status_label = ttk.Label(scroll_frame, text=f"快捷键: {self._format_hotkey_name(self.config['hotkey'])}  |  运行中", foreground="green")
        self.status_label.pack(pady=6)

    def _start_hotkey_capture(self, event):
        """点击快捷键输入框时进入捕获模式"""
        if not self._hotkey_capturing:
            self._hotkey_capturing = True
            self.hotkey_var.set("请按下快捷键...")
            self.entries["hotkey"].configure(foreground="#d9534f")
            return "break"  # 阻止默认的点击行为

    def _on_hotkey_key(self, event):
        """捕获按键事件，格式化为快捷键字符串"""
        if not self._hotkey_capturing:
            return

        # 忽略纯修饰键的按下（等用户按下主键）
        if event.keysym in ("Control_L", "Control_R", "Shift_L", "Shift_R",
                            "Alt_L", "Alt_R", "Super_L", "Super_R"):
            return "break"

        # Esc取消捕获
        if event.keysym == "Escape":
            self._hotkey_capturing = False
            self.hotkey_var.set(self.config["hotkey"])
            self.entries["hotkey"].configure(foreground="black")
            return "break"

        # 组合修饰键
        parts = []
        if event.state & 0x0004:  # Control
            parts.append("ctrl")
        if event.state & 0x0001:  # Shift
            parts.append("shift")
        if event.state & 0x20000:  # Alt
            parts.append("alt")
        if event.state & 0x10000:  # Win/Super (可能因系统而异)
            parts.append("win")

        # 主键
        key = event.keysym.lower()
        if key == "return":
            # 按下Enter：弹出对话框让用户选择主键盘还是小键盘
            self._hotkey_capturing = False
            self.entries["hotkey"].configure(foreground="black")
            self.root.after(50, self._ask_enter_type)
            return "break"
        elif key.startswith("f") and key[1:].isdigit():
            pass  # f1, f2 等保持原样
        elif len(key) == 1:
            pass  # 普通字符
        else:
            # 其他特殊键保持keysym
            pass

        parts.append(key)
        hotkey_str = "+".join(parts)

        self._hotkey_capturing = False
        self.hotkey_var.set(hotkey_str)
        self.entries["hotkey"].configure(foreground="black")
        return "break"

    def _format_hotkey_name(self, hotkey):
        """格式化快捷键显示名称"""
        mapping = {
            "enter": "主键盘Enter",
            "numpad_enter": "小键盘Enter",
            "both_enter": "主键盘+小键盘Enter",
        }
        return mapping.get(hotkey.lower(), hotkey)

    def _ask_enter_type(self):
        """弹出对话框，让用户选择主键盘Enter还是小键盘Enter"""
        dialog = tk.Toplevel(self.root)
        dialog.title("选择Enter键类型")
        dialog.geometry("280x130")
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.grab_set()

        # 居中
        dialog.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() - 280) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - 130) // 2
        dialog.geometry(f"+{x}+{y}")

        ttk.Label(dialog, text="检测到按下 Enter 键，请选择类型：", padding=10).pack()

        btn_frame = ttk.Frame(dialog)
        btn_frame.pack(pady=5)

        def choose_main():
            self.hotkey_var.set("enter")
            dialog.destroy()

        def choose_numpad():
            self.hotkey_var.set("numpad_enter")
            dialog.destroy()

        ttk.Button(btn_frame, text="主键盘 Enter", command=choose_main, width=14).pack(side="left", padx=8)
        ttk.Button(btn_frame, text="小键盘 Enter", command=choose_numpad, width=14).pack(side="left", padx=8)

        dialog.protocol("WM_DELETE_WINDOW", lambda: (self.hotkey_var.set(self.config["hotkey"]), dialog.destroy()))

    def choose_color(self, key):
        """选择颜色"""
        current = self.entries[key].get()
        color = colorchooser.askcolor(color=current, title="选择颜色")
        if color[1]:
            self.entries[key].delete(0, tk.END)
            self.entries[key].insert(0, color[1])
            self.color_buttons[key].configure(bg=color[1])

    def choose_bg_image(self):
        """选择底图图片"""
        filepath = filedialog.askopenfilename(
            title="选择底图图片",
            filetypes=[
                ("图片文件", "*.png *.jpg *.jpeg *.gif *.bmp *.webp"),
                ("所有文件", "*.*")
            ]
        )
        if filepath:
            self.bg_image_var.set(filepath)
            self._update_bg_image_label()

    def clear_bg_image(self):
        """清除底图"""
        self.bg_image_var.set("")
        self._update_bg_image_label()

    def _update_bg_image_label(self):
        """更新底图文件名显示"""
        path = self.bg_image_var.get()
        if path:
            filename = os.path.basename(path)
            if len(filename) > 12:
                filename = filename[:10] + "..."
            self.bg_image_label.config(text=filename)
        else:
            self.bg_image_label.config(text="无")

    def _on_opacity_change(self, value):
        """透明度滑块变化时更新标签"""
        self.bg_opacity_label.config(text=f"{int(float(value))}%")

    def toggle_pause(self):
        """切换暂停/恢复状态"""
        self.paused = not self.paused
        self.config["paused"] = self.paused
        self.save_config()

        if self.paused:
            # 暂停：停止快捷键监听
            if self.hotkey_mgr:
                self.hotkey_mgr.stop()
                self.hotkey_mgr = None
            if self.enter_hotkey:
                self.enter_hotkey.stop()
                self.enter_hotkey = None
        else:
            # 恢复：重新启动快捷键监听
            self.start_hotkey_listener()

        self._update_pause_ui()

    def _update_pause_ui(self):
        """更新暂停状态的界面显示"""
        if self.paused:
            self.pause_button.config(text="恢复")
            self.status_label.config(text=f"快捷键: {self._format_hotkey_name(self.config['hotkey'])}  |  已暂停", foreground="#d9534f")
        else:
            self.pause_button.config(text="暂停")
            self.status_label.config(text=f"快捷键: {self._format_hotkey_name(self.config['hotkey'])}  |  运行中", foreground="green")

    def set_auto_start(self, enable):
        """设置开机启动（写入注册表）"""
        import winreg
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        app_name = "TextGifHelper"
        pythonw = r"C:\Users\Administrator\AppData\Local\Programs\Python\Python311\pythonw.exe"
        script_path = str(Path(__file__).parent / "gui.py")
        command = f'"{pythonw}" "{script_path}"'

        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE)
            if enable:
                winreg.SetValueEx(key, app_name, 0, winreg.REG_SZ, command)
            else:
                try:
                    winreg.DeleteValue(key, app_name)
                except FileNotFoundError:
                    pass
            winreg.CloseKey(key)
            return True
        except Exception as e:
            print(f"设置开机启动失败: {e}")
            return False

    def save_settings(self):
        """保存设置"""
        try:
            # 基本设置
            self.config["hotkey"] = self.hotkey_var.get().strip()
            self.config["auto_send"] = self.check_vars["auto_send"].get()
            self.config["auto_start"] = self.check_vars["auto_start"].get()
            self.config["keyword_detect_enabled"] = self.check_vars["keyword_detect_enabled"].get()
            self.config["keywords"] = self.keyword_text.get("1.0", "end").strip()

            # 设置开机启动
            self.set_auto_start(self.config["auto_start"])

            # GIF设置
            gif = self.config["gif"]
            gif["width"] = int(self.entries["gif.width"].get())
            gif["height"] = int(self.entries["gif.height"].get())
            gif["font_family"] = self.entries["gif.font_family"].get()
            gif["font_size"] = int(self.entries["gif.font_size"].get())
            gif["line_height"] = int(self.entries["gif.line_height"].get())
            gif["max_chars"] = int(self.entries["gif.max_chars"].get())
            gif["text_color"] = self.entries["gif.text_color"].get()
            gif["bg_color"] = self.entries["gif.bg_color"].get()
            gif["margin_left"] = int(self.entries["gif.margin_left"].get())
            gif["margin_right"] = int(self.entries["gif.margin_right"].get())
            gif["margin_top"] = int(self.entries["gif.margin_top"].get())
            gif["margin_bottom"] = int(self.entries["gif.margin_bottom"].get())
            gif["blink_last_punct"] = self.check_vars["gif.blink_last_punct"].get()
            gif["blink_interval_ms"] = int(self.entries["gif.blink_interval_ms"].get())
            gif["pagination_enabled"] = self.check_vars["gif.pagination_enabled"].get()
            gif["title_enabled"] = self.check_vars["gif.title_enabled"].get()
            gif["title_color"] = self.entries["gif.title_color"].get()
            gif["title_font_size"] = int(self.entries["gif.title_font_size"].get())
            gif["bg_image_path"] = self.bg_image_var.get()
            gif["bg_image_opacity"] = self.bg_opacity_var.get()

            self.save_config()

            # 重新注册快捷键（如果未暂停）
            if not self.paused:
                self.start_hotkey_listener()

            self._update_pause_ui()
            self.status_label.config(text=f"已保存！快捷键: {self._format_hotkey_name(self.config['hotkey'])}", foreground="green")
            messagebox.showinfo("成功", "设置已保存！\n快捷键已更新。")

        except ValueError as e:
            messagebox.showerror("错误", f"输入格式有误，请检查数字类型的输入项。\n\n{e}")
        except Exception as e:
            messagebox.showerror("错误", f"保存失败: {e}")

    def reset_to_default(self):
        """恢复默认设置"""
        if not messagebox.askyesno("确认", "确定要恢复所有设置为默认值吗？"):
            return

        # 深拷贝默认配置
        import copy
        self.config = copy.deepcopy(self.DEFAULT_CONFIG)
        self.paused = False

        # 保存配置
        self.save_config()

        # 设置开机启动
        self.set_auto_start(self.config["auto_start"])

        # 重启快捷键监听
        if self.hotkey_mgr:
            self.hotkey_mgr.stop()
            self.hotkey_mgr = None
        if self.enter_hotkey:
            self.enter_hotkey.stop()
            self.enter_hotkey = None
        self.start_hotkey_listener()

        # 刷新界面
        self._refresh_ui()

        messagebox.showinfo("成功", "已恢复默认设置！")

    def _refresh_ui(self):
        """用当前config刷新界面所有控件的值"""
        # 基本设置
        self.hotkey_var.set(self.config["hotkey"])
        self.check_vars["auto_send"].set(self.config["auto_send"])
        self.check_vars["auto_start"].set(self.config.get("auto_start", True))
        self.check_vars["keyword_detect_enabled"].set(self.config.get("keyword_detect_enabled", False))
        self.keyword_text.delete("1.0", tk.END)
        self.keyword_text.insert("1.0", self.config.get("keywords", ""))

        # GIF设置
        gif = self.config["gif"]
        self.entries["gif.width"].delete(0, tk.END)
        self.entries["gif.width"].insert(0, str(gif["width"]))
        self.entries["gif.height"].delete(0, tk.END)
        self.entries["gif.height"].insert(0, str(gif["height"]))
        self.entries["gif.font_family"].set(gif["font_family"])
        self.entries["gif.font_size"].delete(0, tk.END)
        self.entries["gif.font_size"].insert(0, str(gif["font_size"]))
        self.entries["gif.line_height"].delete(0, tk.END)
        self.entries["gif.line_height"].insert(0, str(gif["line_height"]))
        self.entries["gif.max_chars"].delete(0, tk.END)
        self.entries["gif.max_chars"].insert(0, str(gif["max_chars"]))
        self.entries["gif.text_color"].delete(0, tk.END)
        self.entries["gif.text_color"].insert(0, gif["text_color"])
        self.entries["gif.bg_color"].delete(0, tk.END)
        self.entries["gif.bg_color"].insert(0, gif["bg_color"])
        self.color_buttons["gif.text_color"].configure(bg=gif["text_color"])
        self.color_buttons["gif.bg_color"].configure(bg=gif["bg_color"])
        self.entries["gif.margin_left"].delete(0, tk.END)
        self.entries["gif.margin_left"].insert(0, str(gif["margin_left"]))
        self.entries["gif.margin_right"].delete(0, tk.END)
        self.entries["gif.margin_right"].insert(0, str(gif["margin_right"]))
        self.entries["gif.margin_top"].delete(0, tk.END)
        self.entries["gif.margin_top"].insert(0, str(gif["margin_top"]))
        self.entries["gif.margin_bottom"].delete(0, tk.END)
        self.entries["gif.margin_bottom"].insert(0, str(gif["margin_bottom"]))
        self.check_vars["gif.blink_last_punct"].set(gif["blink_last_punct"])
        self.entries["gif.blink_interval_ms"].delete(0, tk.END)
        self.entries["gif.blink_interval_ms"].insert(0, str(gif["blink_interval_ms"]))
        self.check_vars["gif.pagination_enabled"].set(gif.get("pagination_enabled", True))
        self.check_vars["gif.title_enabled"].set(gif.get("title_enabled", False))
        self.entries["gif.title_color"].delete(0, tk.END)
        self.entries["gif.title_color"].insert(0, gif.get("title_color", "#FF0000"))
        self.color_buttons["gif.title_color"].configure(bg=gif.get("title_color", "#FF0000"))
        self.entries["gif.title_font_size"].delete(0, tk.END)
        self.entries["gif.title_font_size"].insert(0, str(gif.get("title_font_size", 32)))
        self.bg_image_var.set(gif.get("bg_image_path", ""))
        self.bg_opacity_var.set(gif.get("bg_image_opacity", 50))
        self.bg_opacity_label.config(text=f"{gif.get('bg_image_opacity', 50)}%")
        self._update_bg_image_label()



        # 暂停按钮和状态
        self._update_pause_ui()

    # ========== 窗口控制 ==========
    def show_window(self):
        """显示主窗口"""
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def hide_window(self):
        """隐藏主窗口（最小化到托盘）"""
        self.root.withdraw()

    def toggle_window(self):
        """切换窗口显示/隐藏"""
        if self.root.state() == "withdrawn":
            self.show_window()
        else:
            self.hide_window()

    def quit_app(self):
        """退出程序"""
        if messagebox.askyesno("确认退出", "确定要退出微信防封助手吗？"):
            self.running = False
            if self.hotkey_mgr:
                self.hotkey_mgr.stop()
            if self.enter_hotkey:
                self.enter_hotkey.stop()
            if self.tray_icon:
                self.tray_icon.stop()
            self.root.quit()
            self.root.destroy()
            sys.exit(0)

    def run(self):
        """运行主循环"""
        self.root.mainloop()


# 全局互斥体句柄，防止被垃圾回收
_single_instance_mutex = None
# 激活信号文件路径（第二个实例请求显示窗口）
_SHOW_REQUEST_FILE = Path(__file__).parent / "temp" / "show_request.flag"


def _is_already_running():
    """检测是否已有实例在运行。
    如果已有实例：写一个激活信号文件，让第一个实例自己显示窗口，然后返回True。
    如果没有：创建互斥体，返回False继续启动。
    """
    global _single_instance_mutex
    import ctypes

    mutex_name = "TextGifAssistant_SingleInstance_Mutex_v1"
    _single_instance_mutex = ctypes.windll.kernel32.CreateMutexW(None, False, mutex_name)
    last_error = ctypes.windll.kernel32.GetLastError()

    if last_error == 183:  # ERROR_ALREADY_EXISTS
        # 已有实例运行，写信号文件让它自己显示窗口
        try:
            os.makedirs(_SHOW_REQUEST_FILE.parent, exist_ok=True)
            _SHOW_REQUEST_FILE.touch()
        except Exception:
            pass
        return True

    return False


def _check_show_request(self):
    """定时检查激活信号文件，如果存在就显示窗口并删除文件"""
    try:
        if _SHOW_REQUEST_FILE.exists():
            try:
                _SHOW_REQUEST_FILE.unlink()
            except Exception:
                pass
            # 用tkinter自己的方法显示窗口，状态一致
            self.show_window()
    except Exception:
        pass
    # 每500ms检查一次
    self.root.after(500, lambda: _check_show_request(self))


if __name__ == "__main__":
    # 单实例检测：已有实例运行则直接退出
    if _is_already_running():
        sys.exit(0)

    app = GifApp()
    app.run()




