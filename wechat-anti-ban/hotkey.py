"""
全局快捷键监听（使用pynput自带的GlobalHotKeys，支持功能键F1-F12）
"""
from pynput import keyboard


class HotkeyManager:
    def __init__(self):
        self.listener = None
        self.hotkey_map = {}

    def _convert_format(self, hotkey_str):
        """
        将用户配置的快捷键格式转换为pynput GlobalHotKeys格式
        例如: "ctrl+shift+g" -> "<ctrl>+<shift>+g"
              "f12" -> "<f12>"
              "ctrl+f5" -> "<ctrl>+<f5>"
        """
        parts = [p.strip().lower() for p in hotkey_str.split("+")]
        converted = []
        for part in parts:
            if part in ("ctrl", "control"):
                converted.append("<ctrl>")
            elif part == "shift":
                converted.append("<shift>")
            elif part == "alt":
                converted.append("<alt>")
            elif part in ("win", "cmd", "super"):
                converted.append("<cmd>")
            elif part.startswith("f") and part[1:].isdigit():
                # 功能键 F1-F12
                converted.append(f"<{part}>")
            elif len(part) == 1:
                converted.append(part)
            else:
                # 其他特殊键尝试用尖括号包裹
                converted.append(f"<{part}>")
        return "+".join(converted)

    def register(self, hotkey_str, callback):
        """
        注册快捷键
        hotkey_str: 如 "ctrl+shift+g" 或 "f12"
        callback: 回调函数
        """
        pynput_format = self._convert_format(hotkey_str)
        print(f"[快捷键] 注册: {hotkey_str} -> {pynput_format}")
        self.hotkey_map[pynput_format] = callback

    def start(self):
        """启动监听"""
        if not self.hotkey_map:
            print("[快捷键] 没有注册任何快捷键")
            return

        self.listener = keyboard.GlobalHotKeys(self.hotkey_map)
        self.listener.start()
        print("[快捷键] 监听已启动")

    def stop(self):
        """停止监听"""
        if self.listener:
            self.listener.stop()
            print("[快捷键] 监听已停止")
