"""
剪贴板工具：备份、恢复、设置文件
"""
import win32clipboard
import win32con
import ctypes
from ctypes import wintypes


class ClipboardManager:
    def __init__(self):
        self.backup = {}

    def backup_clipboard(self):
        """备份当前剪贴板的所有格式内容"""
        self.backup = {}
        try:
            win32clipboard.OpenClipboard()
            format = 0
            while True:
                format = win32clipboard.EnumClipboardFormats(format)
                if format == 0:
                    break
                try:
                    data = win32clipboard.GetClipboardData(format)
                    self.backup[format] = data
                except Exception:
                    pass
            win32clipboard.CloseClipboard()
        except Exception:
            try:
                win32clipboard.CloseClipboard()
            except Exception:
                pass

    def restore_clipboard(self):
        """恢复剪贴板内容"""
        if not self.backup:
            return
        try:
            win32clipboard.OpenClipboard()
            win32clipboard.EmptyClipboard()
            for format, data in self.backup.items():
                try:
                    win32clipboard.SetClipboardData(format, data)
                except Exception:
                    pass
            win32clipboard.CloseClipboard()
        except Exception:
            try:
                win32clipboard.CloseClipboard()
            except Exception:
                pass

    def get_text(self):
        """从剪贴板读取文本"""
        try:
            win32clipboard.OpenClipboard()
            data = win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
            win32clipboard.CloseClipboard()
            return data
        except Exception:
            try:
                win32clipboard.CloseClipboard()
            except Exception:
                pass
            return ""

    def set_files(self, file_paths):
        """
        将文件列表设置到剪贴板（CF_HDROP格式）
        这样Ctrl+V粘贴时会作为文件粘贴
        """
        import struct

        if isinstance(file_paths, str):
            file_paths = [file_paths]

        # 构造文件路径列表（UTF-16LE，双null结尾）
        files_str = "\0".join(file_paths) + "\0\0"
        files_bytes = files_str.encode("utf-16-le")

        # DROPFILES结构体（20字节）:
        #   pFiles: DWORD = 20 (文件列表偏移量)
        #   pt: POINT = (0, 0)
        #   fNC: BOOL = 0
        #   fWide: BOOL = 1 (Unicode)
        header = struct.pack("IiiII", 20, 0, 0, 0, 1)
        dropfiles_data = header + files_bytes

        CF_HDROP = 15
        GMEM_MOVEABLE = 0x0002
        GMEM_ZEROINIT = 0x0040

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        # 设置64位下正确的函数原型，防止句柄被截断
        kernel32.GlobalAlloc.restype = ctypes.c_void_p
        kernel32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
        kernel32.GlobalLock.restype = ctypes.c_void_p
        kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
        kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
        kernel32.GlobalFree.argtypes = [ctypes.c_void_p]
        user32.OpenClipboard.restype = ctypes.c_bool
        user32.OpenClipboard.argtypes = [ctypes.c_void_p]
        user32.EmptyClipboard.restype = ctypes.c_bool
        user32.SetClipboardData.restype = ctypes.c_void_p
        user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
        user32.CloseClipboard.restype = ctypes.c_bool

        try:
            # 打开剪贴板
            if not user32.OpenClipboard(0):
                raise ctypes.WinError()

            # 清空剪贴板
            user32.EmptyClipboard()

            # 分配全局内存
            hglob = kernel32.GlobalAlloc(GMEM_MOVEABLE | GMEM_ZEROINIT, len(dropfiles_data))
            if not hglob:
                user32.CloseClipboard()
                raise ctypes.WinError()

            # 锁定内存并拷贝数据
            pglob = kernel32.GlobalLock(hglob)
            if not pglob:
                kernel32.GlobalFree(hglob)
                user32.CloseClipboard()
                raise ctypes.WinError()

            ctypes.memmove(pglob, dropfiles_data, len(dropfiles_data))
            kernel32.GlobalUnlock(hglob)

            # 设置到剪贴板
            result = user32.SetClipboardData(CF_HDROP, hglob)
            if not result:
                kernel32.GlobalFree(hglob)
                user32.CloseClipboard()
                raise ctypes.WinError()

            # 关闭剪贴板
            user32.CloseClipboard()
            return True
        except Exception as e:
            print(f"设置文件剪贴板失败: {e}")
            try:
                user32.CloseClipboard()
            except Exception:
                pass
            return False
