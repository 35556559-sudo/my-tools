"""
注入器：将GIF文件粘贴到微信输入框
使用 CF_HDROP 剪贴板格式 + Ctrl+V
"""
import time
import pyautogui
from clipboard_utils import ClipboardManager


class Injector:
    def __init__(self, auto_send=False):
        self.auto_send = auto_send
        self.clipboard = ClipboardManager()

    def paste_file(self, file_path):
        """
        将文件粘贴到当前活动窗口
        file_path: GIF文件路径
        """
        # 将文件设置到剪贴板
        success = self.clipboard.set_files(file_path)
        if not success:
            print("设置文件剪贴板失败")
            return False

        time.sleep(0.05)

        # 模拟 Ctrl+V 粘贴
        pyautogui.hotkey("ctrl", "v")
        time.sleep(0.15)

        # 可选：自动发送
        if self.auto_send:
            pyautogui.press("enter")
            time.sleep(0.2)

        return True
