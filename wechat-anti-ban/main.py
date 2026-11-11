"""
微信防封助手 - 主入口
在微信输入框打字后，按快捷键自动将文字转为纯文字GIF并粘贴回微信
"""
import json
import os
import sys
import time
from pathlib import Path

# 将当前目录加入路径
sys.path.insert(0, str(Path(__file__).parent))

from hotkey import HotkeyManager
from text_capture import TextCapture
from gif_generator import GifGenerator
from injector import Injector
from window_detector import is_wechat_active


def load_config():
    """加载配置文件"""
    config_path = Path(__file__).parent / "config.json"
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def on_hotkey_triggered(config):
    """快捷键触发后的主流程"""
    print("\n[触发] 快捷键被按下")

    # 1. 检测当前窗口是否为微信
    if not is_wechat_active(config["wechat"]):
        print("[跳过] 当前窗口不是微信，不执行")
        return

    print("[步骤1] 检测到微信窗口")

    # 2. 捕获输入框中的文字
    text_capture = TextCapture()
    text = text_capture.capture_selected_text()

    if not text or not text.strip():
        print("[跳过] 未捕获到文字")
        text_capture.restore_clipboard()
        return

    print(f"[步骤2] 捕获到文字: {text[:50]}{'...' if len(text) > 50 else ''}")

    # 3. 生成纯文字GIF
    temp_dir = str(Path(__file__).parent / config["temp_dir"])
    gif_gen = GifGenerator(config["gif"], temp_dir)
    gif_paths = gif_gen.generate(text)

    if not gif_paths:
        print("[错误] GIF生成失败")
        text_capture.restore_clipboard()
        return

    print(f"[步骤3] 生成GIF: {gif_paths}")

    # 4. 粘贴到微信
    injector = Injector(auto_send=config["auto_send"])
    for gif_path in gif_paths:
        injector.paste_file(gif_path)

    print("[步骤4] 已粘贴到微信")

    # 5. 恢复剪贴板
    text_capture.restore_clipboard()
    print("[完成] 剪贴板已恢复")


def main():
    config = load_config()
    print("=" * 50)
    print("  微信防封助手 已启动")
    print(f"  快捷键: {config['hotkey']}")
    print(f"  自动发送: {'开启' if config['auto_send'] else '关闭'}")
    print("  按 Ctrl+C 退出程序")
    print("=" * 50)

    hotkey_mgr = HotkeyManager()
    hotkey_mgr.register(config["hotkey"], lambda: on_hotkey_triggered(config))
    hotkey_mgr.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n程序退出")
        hotkey_mgr.stop()


if __name__ == "__main__":
    main()
