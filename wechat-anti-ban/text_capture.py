"""
文字捕获：从微信输入框中读取选中的文字
通过模拟 Ctrl+A -> Ctrl+C 实现
"""
import time
import pyautogui
from clipboard_utils import ClipboardManager


class TextCapture:
    def __init__(self):
        self.clipboard = ClipboardManager()
        self.captured_text = ""

    def capture_selected_text(self, clear_after=True):
        """
        捕获当前输入框中的文字
        流程：备份剪贴板 -> Ctrl+A全选 -> Ctrl+C复制 -> 读取剪贴板 -> [可选]清空输入框
        clear_after: True则复制后按Delete清空输入框，False则保留文字
        返回捕获的文字
        """
        # 备份剪贴板
        self.clipboard.backup_clipboard()

        # 模拟 Ctrl+A 全选
        pyautogui.hotkey("ctrl", "a")
        time.sleep(0.06)

        # 模拟 Ctrl+C 复制
        pyautogui.hotkey("ctrl", "c")
        time.sleep(0.08)

        # 读取剪贴板
        text = self.clipboard.get_text()
        self.captured_text = text

        # 清空输入框（Delete键）
        if clear_after and text:
            pyautogui.press("delete")
            time.sleep(0.03)

        return text

    def restore_clipboard(self):
        """恢复原剪贴板内容"""
        time.sleep(0.15)  # 等待粘贴完成
        self.clipboard.restore_clipboard()
