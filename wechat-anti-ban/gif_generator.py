"""
纯文字GIF生成器
- 基于参考图参数：240x240，字号26px，行高26px
- 最后一个标点闪烁效果
- 标题功能：短横线 - 前的文字作为标题，可单独设置颜色和字号
"""
import os
import time
from PIL import Image, ImageDraw, ImageFont


class GifGenerator:
    def __init__(self, config, temp_dir):
        self.width = config["width"]
        self.height = config["height"]
        self.font_family = config["font_family"]
        self.font_size = config["font_size"]
        self.line_height = config["line_height"]
        self.text_color = config["text_color"]
        self.bg_color = config["bg_color"]
        self.margin_left = config["margin_left"]
        self.margin_right = config["margin_right"]
        self.margin_top = config["margin_top"]
        self.margin_bottom = config["margin_bottom"]
        self.blink_last_punct = config.get("blink_last_punct", True)
        self.blink_interval_ms = config.get("blink_interval_ms", 500)
        self.max_chars = config.get("max_chars", 64)
        self.pagination_enabled = config.get("pagination_enabled", True)
        # 标题功能
        self.title_enabled = config.get("title_enabled", False)
        self.title_color = config.get("title_color", "#FF0000")
        self.title_font_size = config.get("title_font_size", 32)
        # 底图功能
        self.bg_image_path = config.get("bg_image_path", "")
        self.bg_image_opacity = config.get("bg_image_opacity", 50)
        self.temp_dir = temp_dir

        # 加载字体
        self.font = self._load_font(self.font_size)
        self.title_font = self._load_font(self.title_font_size)

        # 加载底图（如果有）
        self.bg_image = self._load_bg_image()

        # 标点符号集合
        self.punctuations = set("，。！？、；：""''（）【】《》…—·,.!?;:\"'()[]<>")
        # 标题分隔符：短横线（半角 - 和全角 －）
        self.title_seps = set("-－")

    def _load_font(self, size):
        """加载中文字体"""
        font_paths = [
            r"C:\Windows\Fonts\msyh.ttc",      # 微软雅黑
            r"C:\Windows\Fonts\msyhbd.ttc",    # 微软雅黑粗体
            r"C:\Windows\Fonts\simhei.ttf",     # 黑体
            r"C:\Windows\Fonts\simsun.ttc",     # 宋体
        ]
        for fp in font_paths:
            if os.path.exists(fp):
                try:
                    return ImageFont.truetype(fp, size)
                except Exception:
                    continue
        return ImageFont.load_default()

    def _load_bg_image(self):
        """
        加载底图，调整到GIF尺寸，并根据透明度设置alpha通道
        返回RGBA格式的Image对象，或None（没有底图时）
        """
        if not self.bg_image_path or not os.path.exists(self.bg_image_path):
            return None

        try:
            img = Image.open(self.bg_image_path)
            # 调整大小到GIF尺寸（拉伸填充）
            img = img.resize((self.width, self.height), Image.LANCZOS)
            # 转成RGBA
            img = img.convert("RGBA")

            # 根据不透明度调整alpha通道
            # opacity: 0-100，0完全透明，100完全不透明
            opacity = max(0, min(100, self.bg_image_opacity))
            if opacity < 100:
                alpha = img.split()[3]
                alpha = alpha.point(lambda p: int(p * opacity / 100))
                img.putalpha(alpha)

            return img
        except Exception as e:
            print(f"[底图] 加载失败: {e}")
            return None

    def _parse_title(self, text):
        """
        解析标题：找到第一个短横线 -，短横线前是标题，短横线后是正文
        返回 (title_text, body_text)，如果没有短横线或未开启标题功能，返回 (None, text)
        """
        if not self.title_enabled:
            return None, text

        for i, char in enumerate(text):
            if char in self.title_seps:
                title = text[:i].strip()
                body = text[i + 1:].strip()
                if title:
                    return title, body
                else:
                    # 短横线在开头，没有标题
                    return None, text
        return None, text

    def _wrap_text(self, text, font):
        """
        自动换行：根据可用宽度计算每行能放多少字
        返回行列表
        """
        max_width = self.width - self.margin_left - self.margin_right
        lines = []
        current_line = ""

        for char in text:
            if char == "\n":
                lines.append(current_line)
                current_line = ""
                continue

            test_line = current_line + char
            bbox = font.getbbox(test_line)
            text_width = bbox[2] - bbox[0]

            if text_width <= max_width:
                current_line = test_line
            else:
                if current_line:
                    lines.append(current_line)
                current_line = char

        if current_line:
            lines.append(current_line)

        return lines

    def _build_styled_lines(self, text):
        """
        构建带样式的行列表
        返回 [(line_text, font, color), ...]
        """
        title, body = self._parse_title(text)
        styled_lines = []

        if title:
            # 标题换行
            title_lines = self._wrap_text(title, self.title_font)
            for tl in title_lines:
                styled_lines.append((tl, self.title_font, self.title_color))
            # 标题和正文之间加一个空行（用正文字体高度）
            styled_lines.append(("", self.font, self.text_color))

        # 正文换行
        body_lines = self._wrap_text(body, self.font)
        for bl in body_lines:
            styled_lines.append((bl, self.font, self.text_color))

        return styled_lines

    def _find_last_punct_pos(self, styled_lines):
        """
        找到最后一个标点符号所在的行和位置（只在正文中找，标题不参与闪烁）
        返回 (行索引, 字符索引) 或 None
        """
        for i in range(len(styled_lines) - 1, -1, -1):
            line_text, font, color = styled_lines[i]
            # 只在正文行（颜色等于正文颜色）中找
            if color != self.text_color:
                continue
            for j in range(len(line_text) - 1, -1, -1):
                if line_text[j] in self.punctuations:
                    return (i, j)
        return None

    def _draw_frame(self, styled_lines):
        """
        绘制完整一帧，返回 (img, punct_rect)
        punct_rect: 最后一个标点的位置 (x, y, w, h)，没有则None
        """
        img = Image.new("RGB", (self.width, self.height), self.bg_color)

        # 绘制底图（如果有）
        if self.bg_image is not None:
            img = img.convert("RGBA")
            img = Image.alpha_composite(img, self.bg_image)
            img = img.convert("RGB")

        draw = ImageDraw.Draw(img)

        # 计算文字总高度
        total_height = 0
        line_heights = []
        for line_text, font, color in styled_lines:
            if not line_text:
                lh = int(self.font_size * 0.2)
            elif font == self.title_font:
                lh = self.title_font_size + 4
            else:
                lh = self.line_height
            line_heights.append(lh)
            total_height += lh

        available_height = self.height - self.margin_top - self.margin_bottom
        first_line_is_title = (len(styled_lines) > 0 and styled_lines[0][1] == self.title_font and styled_lines[0][0])
        if first_line_is_title:
            y = self.margin_top + 5
        elif total_height < available_height:
            y = self.margin_top + (available_height - total_height) // 2
        else:
            y = self.margin_top

        # 找最后一个标点位置
        punct_pos = self._find_last_punct_pos(styled_lines)
        punct_rect = None

        for line_idx, (line_text, font, color) in enumerate(styled_lines):
            lh = line_heights[line_idx]

            if not line_text:
                y += lh
                continue

            # 正常绘制整行，水平居中
            bbox = font.getbbox(line_text)
            text_width = bbox[2] - bbox[0]
            x = (self.width - text_width) // 2
            draw.text((x, y), line_text, fill=color, font=font)

            # 记录最后一个标点的位置（用于第二帧快速覆盖）
            if punct_pos and punct_pos[0] == line_idx:
                punct_j = punct_pos[1]
                part1 = line_text[:punct_j]
                if part1:
                    part1_bbox = font.getbbox(part1)
                    part1_w = part1_bbox[2] - part1_bbox[0]
                else:
                    part1_w = 0
                punct_char = line_text[punct_j]
                punct_bbox = font.getbbox(punct_char)
                punct_w = punct_bbox[2] - punct_bbox[0]
                punct_h = punct_bbox[3] - punct_bbox[1]
                punct_x = x + part1_w
                punct_y = y
                punct_rect = (punct_x, punct_y, punct_w, punct_h)

            y += lh

        return img, punct_rect

    def _hide_punct_on_frame(self, img, punct_rect):
        """在已有帧上覆盖标点位置（快速生成第二帧，不用重画所有文字）"""
        if not punct_rect:
            return img
        x, y, w, h = punct_rect
        draw = ImageDraw.Draw(img)
        if self.bg_image is not None:
            # 有底图时：用底图对应区域覆盖
            crop_box = (max(0, x - 2), max(0, y - 2), min(self.width, x + w + 2), min(self.height, y + h + 2))
            bg_crop = self.bg_image.crop(crop_box).convert("RGB")
            img.paste(bg_crop, crop_box[:2])
        else:
            # 无底图时：用背景色覆盖，扩大2px避免抗锯齿边缘
            draw.rectangle([x - 2, y - 2, x + w + 2, y + h + 2], fill=self.bg_color)
        return img

    def _split_long_paragraph(self, text, max_lines):
        """
        把一个超长段落按行数拆分成多个子段落
        （用于没有换行符、但字数太多导致行数超标的情况）
        """
        lines = self._wrap_text(text, self.font)
        if len(lines) <= max_lines:
            return [text]

        chunks = []
        for i in range(0, len(lines), max_lines):
            chunk_lines = lines[i:i + max_lines]
            chunks.append("".join(chunk_lines))

        return chunks

    def _split_text(self, text):
        """
        将长文本按行数分页（考虑换行符占用的行）
        每张图最多放 max_lines 行，空行也算一行
        返回文本页列表
        """
        # 计算每张图最多能放多少行
        available_height = self.height - self.margin_top - self.margin_bottom
        max_lines = available_height // self.line_height
        if max_lines < 1:
            max_lines = 1

        # 按换行符分割段落（保留空段落）
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        raw_paragraphs = text.split("\n")

        # 处理超长段落：单个段落行数超过max_lines时，拆分成多个子段落
        paragraphs = []
        for para in raw_paragraphs:
            if para == "":
                paragraphs.append("")
            else:
                sub_paras = self._split_long_paragraph(para, max_lines)
                paragraphs.extend(sub_paras)

        # 预计算每个段落需要多少行
        para_line_counts = []
        for para in paragraphs:
            if para == "":
                para_line_counts.append(1)  # 空行占1行
            else:
                lines = self._wrap_text(para, self.font)
                para_line_counts.append(max(1, len(lines)))

        # 按行数累加分页
        pages = []
        current_paras = []
        current_lines = 0

        for i, para in enumerate(paragraphs):
            plines = para_line_counts[i]

            # 如果当前页已有内容，加上这个段落会超行数，就先保存当前页
            if current_paras and current_lines + plines > max_lines:
                pages.append("\n".join(current_paras))
                current_paras = [para]
                current_lines = plines
            else:
                current_paras.append(para)
                current_lines += plines

        # 保存最后一页
        if current_paras:
            pages.append("\n".join(current_paras))

        return pages

    def _generate_single(self, text, index=0, total=1):
        """生成单张GIF"""
        styled_lines = self._build_styled_lines(text)

        if not styled_lines:
            return None

        # 绘制第一帧（同时返回最后一个标点的位置）
        frame1, punct_rect = self._draw_frame(styled_lines)

        # 生成第二帧：复制第一帧，覆盖标点位置（不重画所有文字，大幅提速）
        if self.blink_last_punct and punct_rect:
            frame2 = frame1.copy()
            self._hide_punct_on_frame(frame2, punct_rect)
            frames = [frame1, frame2]
        else:
            frames = [frame1]

        # 保存GIF
        timestamp = int(time.time() * 1000)
        if total > 1:
            filename = f"text_{timestamp}_{index + 1}of{total}.gif"
        else:
            filename = f"text_{timestamp}.gif"

        filepath = os.path.join(self.temp_dir, filename)
        os.makedirs(self.temp_dir, exist_ok=True)

        if len(frames) > 1:
            frames[0].save(
                filepath,
                save_all=True,
                append_images=frames[1:],
                duration=self.blink_interval_ms,
                loop=0,
                disposal=2
            )
        else:
            frames[0].save(filepath, format="GIF")

        return filepath

    def generate(self, text):
        """
        生成纯文字GIF（支持分页，按行数自动分成多张）
        text: 输入文字
        返回: GIF文件路径列表（按顺序）
        """
        if not text or not text.strip():
            return []

        text = text.strip()

        if self.pagination_enabled:
            pages = self._split_text(text)
        else:
            # 关闭分页：只取第一页（按行数截断，保证不超出图片）
            pages = self._split_text(text)
            pages = [pages[0]] if pages else []

        total = len(pages)
        gif_paths = []
        for i, page_text in enumerate(pages):
            path = self._generate_single(page_text, index=i, total=total)
            if path:
                gif_paths.append(path)

        return gif_paths


if __name__ == "__main__":
    import json
    with open("config.json", "r", encoding="utf-8") as f:
        config = json.load(f)
    gen = GifGenerator(config["gif"], "temp")
    # 测试标题功能
    test_text = "重要通知：明天下午三点开会，请大家准时参加，不要迟到。"
    paths = gen.generate(test_text)
    print(f"生成了{len(paths)}张GIF:")
    for p in paths:
        print(f"  {p}")
