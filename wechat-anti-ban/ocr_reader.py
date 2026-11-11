# -*- coding: utf-8 -*-
"""
OCR读取微信输入框文字（不碰剪贴板、不模拟按键）
通过截图微信输入框区域 + OCR识别，用于关键词检测
优化：边框缓存、图片缩小、关闭方向分类
"""
import time
import win32gui
import win32con
from PIL import Image
import mss


class OcrReader:
    """OCR读取器：单例预加载模型，边框坐标缓存，避免每次重复检测"""
    _ocr_instance = None

    def __init__(self, config=None):
        self.config = config or {}
        self.ocr = self._get_ocr()
        # 缓存：窗口句柄、窗口位置、最终截图区域、mss实例
        self._cached_hwnd = None
        self._cached_rect = None
        self._cached_final_box = None
        self._mss = mss.mss()

    @classmethod
    def _get_ocr(cls):
        if cls._ocr_instance is None:
            from rapidocr_onnxruntime import RapidOCR
            try:
                # 关闭方向分类（文字都是正的，省一步推理）
                cls._ocr_instance = RapidOCR(use_text_cls=False)
            except TypeError:
                cls._ocr_instance = RapidOCR()
        return cls._ocr_instance

    @classmethod
    def preload(cls):
        """预加载OCR模型（软件启动时调用，避免第一次按回车卡顿）"""
        cls._get_ocr()

    def _find_wechat_window(self):
        """找到微信窗口句柄（带缓存，避免每次遍历所有窗口）"""
        # 先验证缓存的句柄是否还有效
        if self._cached_hwnd is not None:
            try:
                if win32gui.IsWindow(self._cached_hwnd):
                    cn = win32gui.GetClassName(self._cached_hwnd)
                    title = win32gui.GetWindowText(self._cached_hwnd)
                    if cn == "Qt51514QWindowIcon" and "微信" in title:
                        return self._cached_hwnd
            except Exception:
                pass

        # 缓存失效，重新查找
        result = []

        def cb(hwnd, _):
            try:
                cn = win32gui.GetClassName(hwnd)
                title = win32gui.GetWindowText(hwnd)
                if cn == "Qt51514QWindowIcon" and "微信" in title:
                    result.append(hwnd)
            except Exception:
                pass

        win32gui.EnumWindows(cb, None)
        if result:
            self._cached_hwnd = result[0]
            return result[0]
        return None

    def _detect_input_box_top(self, img):
        """检测输入框顶部边框的y坐标（相对于截图顶部），失败返回None"""
        try:
            import numpy as np
            gray = np.array(img.convert("L"))
            h, w = gray.shape
            search_start = int(h * 0.2)
            row_dark = np.sum(gray[search_start:] < 235, axis=1)
            if len(row_dark) == 0:
                return None
            best_rel = int(np.argmax(row_dark))
            best_y = search_start + best_rel
            if row_dark[best_rel] < w * 0.40:
                return None
            return best_y
        except Exception:
            return None

    def _detect_vertical_separator(self, img):
        """检测会话列表与聊天区之间的垂直分隔线x坐标，失败返回None"""
        try:
            import numpy as np
            gray = np.array(img.convert("L"))
            h, w = gray.shape
            search_start = 150
            search_end = min(400, w - 50)
            if search_end <= search_start:
                return None
            col_dark = np.sum(gray[:, search_start:search_end] < 235, axis=0)
            if len(col_dark) == 0:
                return None
            best_rel = int(np.argmax(col_dark))
            best_x = search_start + best_rel
            if col_dark[best_rel] < h * 0.50:
                return None
            return best_x
        except Exception:
            return None

    def _grab(self, box):
        """用mss截图并转PIL Image，box=(left, top, right, bottom)"""
        left, top, right, bottom = box
        monitor = {"left": left, "top": top, "width": right - left, "height": bottom - top}
        sct_img = self._mss.grab(monitor)
        return Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")

    def capture_input_box(self):
        """截图微信输入框区域，带最终区域缓存，返回PIL Image"""
        hwnd = self._find_wechat_window()
        if not hwnd:
            return None

        try:
            if win32gui.IsIconic(hwnd):
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                time.sleep(0.3)
        except Exception:
            pass

        try:
            left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        except Exception:
            return None

        w = right - left
        h = bottom - top
        if w < 100 or h < 100:
            return None

        current_rect = (left, top, right, bottom)

        # 窗口没变且有缓存的最终区域：直接截小区域，跳过边框检测和裁剪
        if current_rect == self._cached_rect and self._cached_final_box is not None:
            try:
                return self._grab(self._cached_final_box)
            except Exception:
                pass  # 缓存失效，重新检测

        # 截大区域（底部40%-96%，从左边缘开始）
        crop_top = top + int(h * 0.40)
        crop_bottom = top + int(h * 0.96)
        big_box = (left, crop_top, right, crop_bottom)

        try:
            img = self._grab(big_box)
        except Exception:
            return None

        # 检测垂直分隔线，裁剪左侧
        sep_x = self._detect_vertical_separator(img)
        if sep_x is None or sep_x <= 0:
            sep_x = 280
        chat_left = min(sep_x + 10, img.width - 50)
        img = img.crop((chat_left, 0, img.width, img.height))

        # 检测顶部边框，裁剪顶部
        input_top = self._detect_input_box_top(img)
        if input_top is not None and input_top > 0:
            img = img.crop((0, input_top, img.width, img.height))

        # 计算最终区域的屏幕绝对坐标并缓存
        final_left = left + chat_left
        final_top = crop_top + (input_top if (input_top is not None and input_top > 0) else 0)
        final_right = right
        final_bottom = crop_bottom
        self._cached_final_box = (final_left, final_top, final_right, final_bottom)
        self._cached_rect = current_rect

        return img

    def _fast_ocr(self, img):
        """
        快速OCR：跳过文本检测模型（4秒），用简单行分割+逐行识别
        输入框文字是水平排列的，适合用水平投影找文字行
        """
        import numpy as np

        # 裁掉底部工具栏（微信输入框工具栏约35px高）
        toolbar_height = 35
        if img.height > toolbar_height + 20:
            img = img.crop((0, 0, img.width, img.height - toolbar_height))

        # 转灰度
        gray = img.convert('L')
        arr = np.array(gray)

        # 水平投影找文字行（深色像素超过8个算有文字，避免小字行被漏掉）
        row_has_text = np.sum(arr < 180, axis=1) > 8

        # 找连续的文字行（间隔<=3px的合并为同一行）
        rows = []
        in_row = False
        row_start = 0
        last_text_y = 0
        for y in range(len(row_has_text)):
            if row_has_text[y]:
                if not in_row:
                    row_start = y
                    in_row = True
                last_text_y = y
            else:
                if in_row and (y - last_text_y) > 3:
                    rows.append((row_start, last_text_y + 1))
                    in_row = False
        if in_row:
            rows.append((row_start, last_text_y + 1))

        if not rows:
            return ""

        # 逐行裁剪识别
        all_text = []
        rec = self.ocr.text_rec
        for (y1, y2) in rows:
            line_h = y2 - y1
            if line_h < 8 or line_h > 60:  # 跳过太矮的噪点行和太高的混合行
                continue
            # 上下加边距
            y1e = max(0, y1 - 3)
            y2e = min(gray.height, y2 + 3)
            line_img = gray.crop((0, y1e, gray.width, y2e))

            # 左右裁剪空白（合并间隔<=8px的文字段，过滤<10px的噪点段）
            line_arr = np.array(line_img)
            col_dark = np.sum(line_arr < 180, axis=0)
            col_has_text = col_dark > 3
            text_cols = np.where(col_has_text)[0]
            if len(text_cols) > 0:
                # 合并间隔<=8px的文字段
                segments = []
                seg_start = text_cols[0]
                seg_prev = text_cols[0]
                for c in text_cols[1:]:
                    if c - seg_prev > 8:
                        segments.append((seg_start, seg_prev))
                        seg_start = c
                    seg_prev = c
                segments.append((seg_start, seg_prev))
                # 过滤掉长度<10px的噪点段
                segments = [s for s in segments if s[1] - s[0] >= 10]
                if segments:
                    # 取所有有效段的并集
                    x1 = max(0, segments[0][0] - 10)
                    x2 = min(gray.width, segments[-1][1] + 10)
                    line_img = line_img.crop((x1, 0, x2, line_img.height))

            # 缩放到高度48px（识别模型对小字识别率低，放大后识别率大幅提升）
            target_h = 48
            if line_img.height < target_h:
                ratio = target_h / line_img.height
                new_w = max(1, int(line_img.width * ratio))
                line_img = line_img.resize((new_w, target_h), Image.LANCZOS)

            # 识别（转RGB，识别模型需要3通道）
            line_rgb = line_img.convert('RGB')
            result = rec([np.array(line_rgb)])
            text = result[0][0][0] if result and result[0] else ''
            if text:
                all_text.append(text)

        return "".join(all_text)

    def read_text(self):
        """读取输入框文字，返回识别到的全文"""
        img = self.capture_input_box()
        if img is None:
            return ""
        try:
            # 快速OCR：跳过检测模型，直接行分割+识别（从4秒降到200ms）
            return self._fast_ocr(img)
        except Exception as e:
            print(f"[OCR] 识别出错: {e}")
            return ""

    def contains_keyword(self, keywords):
        """检查输入框是否包含关键词，返回 (是否匹配, 识别到的文字)"""
        text = self.read_text()
        if not text or not keywords:
            return False, text
        for kw in keywords:
            kw = kw.strip()
            if kw and kw in text:
                return True, text
        return False, text
