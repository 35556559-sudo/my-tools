"""
Enter键专用快捷键（低级键盘钩子）
实现：第一下Enter把文字转成GIF，第二下Enter发送GIF
"""
import ctypes
import ctypes.wintypes
import threading
import time
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from text_capture import TextCapture
from gif_generator import GifGenerator
from injector import Injector
from window_detector import is_wechat_active
from ocr_reader import OcrReader


def parse_keywords(raw):
    """把逗号分隔的关键词字符串拆成列表（中英文逗号都支持）"""
    if not raw:
        return []
    raw = raw.replace("，", ",")
    return [k.strip() for k in raw.split(",") if k.strip()]


# Windows API 常量
WH_KEYBOARD_LL = 13
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
VK_RETURN = 0x0D
LLKHF_EXTENDED = 0x01  # 扩展键标志：小键盘Enter的flags会有这个位

# 低级键盘钩子结构体
class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", ctypes.wintypes.DWORD),
        ("scanCode", ctypes.wintypes.DWORD),
        ("flags", ctypes.wintypes.DWORD),
        ("time", ctypes.wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.wintypes.ULONG)),
    ]


class EnterHotkey:
    def __init__(self, config, temp_dir):
        self.config = config
        self.temp_dir = temp_dir
        self.hook = None
        self.running = False
        self._callback = None
        self._lock = threading.Lock()
        self._processing = False  # 防止重复触发
        self._passthrough = False  # 放行模式：模拟发送时让Enter穿过钩子
        self._gif_pending = False  # 状态：上一次粘贴了GIF等待发送
        self._gif_pending_time = 0  # GIF粘贴时间戳
        self._gif_pending_timeout = 10  # 超时秒数，超过则失效
        self._gif_gen = None  # 缓存GifGenerator实例，避免重复加载字体

    def _low_level_keyboard_proc(self, nCode, wParam, lParam):
        """低级键盘钩子回调"""
        try:
            if nCode >= 0 and wParam == WM_KEYDOWN:
                kb = ctypes.cast(lParam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                if kb.vkCode == VK_RETURN:
                    is_numpad = (kb.flags & LLKHF_EXTENDED) != 0
                    hotkey = self.config.get("hotkey", "enter")

                    # 调试日志
                    try:
                        log_path = Path(__file__).parent / "temp" / "key_debug.log"
                        with open(log_path, "a", encoding="utf-8") as f:
                            f.write(f"[Enter] vk={kb.vkCode:#x} scan={kb.scanCode:#x} flags={kb.flags:#x} is_numpad={is_numpad} hotkey={hotkey}\n")
                    except Exception:
                        pass

                    # 根据配置决定是否响应
                    hotkey = self.config.get("hotkey", "enter")
                    keyword_enabled = self.config.get("keyword_detect_enabled", False)

                    # 调试日志
                    try:
                        log_path = Path(__file__).parent / "temp" / "key_debug.log"
                        with open(log_path, "a", encoding="utf-8") as f:
                            f.write(f"[Enter] vk={kb.vkCode:#x} scan={kb.scanCode:#x} flags={kb.flags:#x} is_numpad={is_numpad} hotkey={hotkey} kw_enabled={keyword_enabled}\n")
                    except Exception:
                        pass

                    if is_wechat_active(self.config["wechat"]):
                        # 放行模式：模拟发送时让Enter穿过钩子
                        if self._passthrough:
                            return ctypes.windll.user32.CallNextHookEx(
                                self.hook, nCode, wParam, ctypes.cast(lParam, ctypes.c_void_p)
                            )

                        # 判断本次按键的用途
                        is_hotkey = (hotkey == "enter" and not is_numpad) or (hotkey == "numpad_enter" and is_numpad)
                        is_keyword_check = (not is_numpad) and keyword_enabled and (hotkey != "enter")

                        if is_hotkey or is_keyword_check:
                            if not self._processing:
                                self._processing = True
                                if is_keyword_check:
                                    threading.Thread(target=self._handle_keyword_check, daemon=True).start()
                                else:
                                    threading.Thread(target=self._handle_enter, daemon=True).start()
                            return 1  # 阻止按键传递

            # 传递给下一个钩子
            return ctypes.windll.user32.CallNextHookEx(
                self.hook, nCode, wParam, ctypes.cast(lParam, ctypes.c_void_p)
            )
        except Exception as e:
            # 钩子回调中任何异常都不能崩溃，直接放行
            try:
                import traceback
                log_path = Path(__file__).parent / "temp" / "error.log"
                with open(log_path, "a", encoding="utf-8") as f:
                    f.write(f"\n{'='*60}\n")
                    f.write(f"钩子回调错误 时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                    traceback.print_exc(file=f)
            except Exception:
                pass
            return ctypes.windll.user32.CallNextHookEx(
                self.hook, nCode, wParam, ctypes.cast(lParam, ctypes.c_void_p)
            )

    def _send_enter(self):
        """模拟Enter按键发送（放行模式，确保能穿过钩子）"""
        self._passthrough = True
        ctypes.windll.user32.keybd_event(VK_RETURN, 0, 0, 0)  # 按下
        time.sleep(0.03)
        ctypes.windll.user32.keybd_event(VK_RETURN, 0, 2, 0)  # 释放
        time.sleep(0.1)
        self._passthrough = False

    def _handle_keyword_check(self):
        """大Enter关键词检测：OCR读取输入框，有关键词则转GIF，无则放行发送文字"""
        try:
            time.sleep(0.03)

            # 状态机：如果上一次粘贴了GIF等待发送，这次直接发送
            if self._gif_pending:
                elapsed = time.time() - self._gif_pending_time
                if elapsed < self._gif_pending_timeout:
                    self._gif_pending = False
                    time.sleep(0.05)
                    self._send_enter()
                    return
                else:
                    self._gif_pending = False

            # OCR读取输入框文字（不碰剪贴板）
            keywords = parse_keywords(self.config.get("keywords", ""))
            if not keywords:
                time.sleep(0.05)
                self._send_enter()
                return

            ocr_reader = OcrReader(self.config)
            matched, ocr_text = ocr_reader.contains_keyword(keywords)

            try:
                log_path = Path(__file__).parent / "temp" / "keyword_debug.log"
                with open(log_path, "a", encoding="utf-8") as f:
                    f.write(f"[{time.strftime('%H:%M:%S')}] matched={matched} ocr={ocr_text[:80]}\n")
            except Exception:
                pass

            if matched:
                # 有关键词：转GIF发送（这时才用Ctrl+A/C，发GIF不风控）
                self._convert_to_gif_and_send()
            else:
                # 无关键词：放行Enter，正常发送文字（零复制零注入）
                time.sleep(0.05)
                self._send_enter()

        except Exception as e:
            print(f"关键词检测出错: {e}")
            try:
                import traceback
                log_path = Path(__file__).parent / "temp" / "error.log"
                with open(log_path, "a", encoding="utf-8") as f:
                    f.write(f"\n{'='*60}\n关键词检测错误 {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                    traceback.print_exc(file=f)
            except Exception:
                pass
            self._send_enter()
        finally:
            time.sleep(0.1)
            self._processing = False

    def _convert_to_gif_and_send(self):
        """核心：捕获文字 → 生成GIF → 粘贴 → 发送"""
        text_capture = TextCapture()
        text = text_capture.capture_selected_text()

        if text and text.strip():
            # 复用GifGenerator实例，避免每次加载字体
            if self._gif_gen is None:
                self._gif_gen = GifGenerator(self.config["gif"], self.temp_dir)
            gif_paths = self._gif_gen.generate(text)

            if not gif_paths:
                time.sleep(0.15)
                text_capture.restore_clipboard()
                return

            if len(gif_paths) == 1:
                injector = Injector(auto_send=False)
                injector.paste_file(gif_paths[0])
                time.sleep(0.2)
                text_capture.restore_clipboard()

                if self.config.get("auto_send", False):
                    time.sleep(0.1)
                    self._send_enter()
                else:
                    self._gif_pending = True
                    self._gif_pending_time = time.time()
            else:
                time.sleep(0.08)
                text_capture.restore_clipboard()
                for i, gif_path in enumerate(gif_paths):
                    injector = Injector(auto_send=False)
                    injector.paste_file(gif_path)
                    time.sleep(0.3)
                    self._send_enter()
                    time.sleep(0.5)
        else:
            time.sleep(0.05)
            self._send_enter()

    def _handle_enter(self):
        """处理快捷键Enter：有文字则转GIF，无文字则模拟发送"""
        try:
            time.sleep(0.03)

            if self._gif_pending:
                elapsed = time.time() - self._gif_pending_time
                if elapsed < self._gif_pending_timeout:
                    self._gif_pending = False
                    time.sleep(0.05)
                    self._send_enter()
                    return
                else:
                    self._gif_pending = False

            self._convert_to_gif_and_send()

        except Exception as e:
            print(f"Enter处理出错: {e}")
            try:
                import traceback
                log_path = Path(__file__).parent / "temp" / "error.log"
                with open(log_path, "a", encoding="utf-8") as f:
                    f.write(f"\n{'='*60}\nEnter处理错误 {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                    traceback.print_exc(file=f)
            except Exception:
                pass
        finally:
            time.sleep(0.1)
            self._processing = False

    def start(self):
        """启动钩子"""
        if self.running:
            return

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        # 定义回调函数类型
        HOOKPROC = ctypes.WINFUNCTYPE(
            ctypes.c_long,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.POINTER(KBDLLHOOKSTRUCT)
        )
        self._callback = HOOKPROC(self._low_level_keyboard_proc)

        # 显式设置API参数类型（64位下必须）
        user32.SetWindowsHookExW.restype = ctypes.c_void_p
        user32.SetWindowsHookExW.argtypes = [
            ctypes.c_int,
            HOOKPROC,
            ctypes.c_void_p,
            ctypes.c_ulong
        ]
        kernel32.GetModuleHandleW.restype = ctypes.c_void_p
        kernel32.GetModuleHandleW.argtypes = [ctypes.c_wchar_p]
        user32.CallNextHookEx.restype = ctypes.c_long
        user32.CallNextHookEx.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_void_p]
        user32.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]

        # 设置钩子
        hmodule = kernel32.GetModuleHandleW(None)
        self.hook = user32.SetWindowsHookExW(
            WH_KEYBOARD_LL,
            self._callback,
            hmodule,
            0
        )

        if not self.hook:
            raise ctypes.WinError()

        self.running = True
        print("[Enter快捷键] 低级键盘钩子已启动")

        # 启动消息循环（低级钩子需要消息循环）
        def message_loop():
            msg = ctypes.wintypes.MSG()
            while self.running:
                bRet = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if bRet == 0 or bRet == -1:
                    break
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))

        self._msg_thread = threading.Thread(target=message_loop, daemon=True)
        self._msg_thread.start()

    def stop(self):
        """停止钩子"""
        self.running = False
        if self.hook:
            ctypes.windll.user32.UnhookWindowsHookEx(self.hook)
            self.hook = None
        print("[Enter快捷键] 钩子已停止")


if __name__ == "__main__":
    # 测试
    import json
    with open("config.json", "r", encoding="utf-8") as f:
        config = json.load(f)

    hotkey = EnterHotkey(config, "temp")
    hotkey.start()
    print("Enter快捷键测试中，按Ctrl+C退出...")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        hotkey.stop()
