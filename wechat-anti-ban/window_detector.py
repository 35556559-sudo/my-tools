"""
微信窗口检测
"""
import win32gui
import win32process
import psutil


def is_wechat_active(wechat_config):
    """
    检测当前活动窗口是否为微信
    wechat_config: {"process_name": "WeChat.exe", "window_title_keyword": "微信"}
    """
    try:
        hwnd = win32gui.GetForegroundWindow()
        if not hwnd:
            return False

        # 检查窗口标题
        title = win32gui.GetWindowText(hwnd)
        if wechat_config.get("window_title_keyword") in title:
            return True

        # 检查进程名
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        try:
            process = psutil.Process(pid)
            if process.name().lower() == wechat_config.get("process_name", "").lower():
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

        return False
    except Exception:
        return False


def get_wechat_window():
    """获取微信主窗口句柄"""
    def callback(hwnd, result):
        if win32gui.IsWindowVisible(hwnd):
            title = win32gui.GetWindowText(hwnd)
            if "微信" in title:
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                try:
                    process = psutil.Process(pid)
                    if process.name().lower() == "wechat.exe":
                        result.append(hwnd)
                except Exception:
                    pass
        return True

    result = []
    win32gui.EnumWindows(callback, result)
    return result[0] if result else None
