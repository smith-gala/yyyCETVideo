"""PDF 解析与真题缓存服务。"""
import json
import logging
import re
import shutil
from typing import Any, Dict, List, Optional

import fitz  # PyMuPDF

from app.config import CACHE_DIR, PDFS_DIR
from app.models import ExamPaper
from app.services.subtitle_service import normalize_source_text


logger = logging.getLogger(__name__)


class PDFService:
    """负责解析上传的 PDF，并管理本地真题缓存。"""

    def __init__(self):
        self.cache_file = CACHE_DIR / "exam_papers.json"
        self._load_cache()

    def _load_cache(self):
        """加载缓存。"""
        logger.info("正在加载试卷缓存...")
        if self.cache_file.exists():
            try:
                with open(self.cache_file, "r", encoding="utf-8") as file:
                    self.cache = json.load(file)
                logger.info("成功加载 %s 份缓存的试卷", len(self.cache))
            except json.JSONDecodeError as exc:
                corrupt_path = self.cache_file.with_suffix(".corrupt.json")
                shutil.copy2(self.cache_file, corrupt_path)
                self.cache = {}
                logger.error("缓存文件损坏，已备份到 %s: %s", corrupt_path, exc)
                self._save_cache()
        else:
            self.cache = {}
            logger.info("缓存文件不存在，初始化空缓存")

    def _save_cache(self):
        """原子保存缓存。"""
        tmp_file = self.cache_file.with_suffix(".tmp")
        with open(tmp_file, "w", encoding="utf-8") as file:
            json.dump(self.cache, file, ensure_ascii=False, indent=2)
        tmp_file.replace(self.cache_file)

    def get_paper_id(self, exam_type: str, year: int, month: int, set_number: int) -> str:
        """生成试卷 ID。"""
        return f"{exam_type}_{year}_{month}_{set_number}"

    def get_cached_paper(
        self,
        exam_type: str,
        year: int,
        month: int,
        set_number: int,
    ) -> Optional[ExamPaper]:
        """获取一套已缓存试卷。"""
        paper_id = self.get_paper_id(exam_type, year, month, set_number)
        if paper_id in self.cache:
            return ExamPaper(**self.cache[paper_id])
        return None

    def save_paper(self, paper: ExamPaper):
        """保存或覆盖一套试卷。"""
        paper.chinese_text = normalize_source_text(paper.chinese_text)
        self.cache[paper.paper_id] = paper.model_dump(mode="json")
        self._save_cache()

    def delete_paper(self, paper_id: str) -> bool:
        """删除一套试卷缓存；关联 PDF 保留在本地，避免误删原始文件。"""
        if paper_id not in self.cache:
            return False
        del self.cache[paper_id]
        self._save_cache()
        return True

    def list_cached_papers(self) -> List[ExamPaper]:
        """列出所有缓存的试卷。"""
        papers = [ExamPaper(**paper_data) for paper_data in self.cache.values()]
        return sorted(papers, key=lambda paper: (paper.year, paper.month, paper.set_number), reverse=True)

    def extract_translation_text(self, pdf_path: str) -> Optional[str]:
        """从 PDF 最后几页定位并提取 Part IV Translation 中文原文。"""
        logger.info("开始解析 PDF: %s", pdf_path)
        try:
            with fitz.open(pdf_path) as document:
                total_pages = len(document)
                logger.info("PDF 共 %s 页，开始搜索翻译部分", total_pages)

                for page_num in range(total_pages - 1, -1, -1):
                    page = document[page_num]
                    text = page.get_text()
                    if re.search(r"Part\s*IV", text, re.I) and "Translation" in text:
                        chinese_text = self._extract_chinese_from_page(text)
                        if not chinese_text:
                            chinese_text = self._extract_translation_blocks_from_page(page)
                        if chinese_text:
                            logger.info("成功提取中文原文（%s 字符）", len(chinese_text))
                            return normalize_source_text(chinese_text)

                fallback_text = self._extract_chinese_from_bottom_pages(document)
                if fallback_text:
                    logger.info("使用底部中文块兜底提取成功（%s 字符）", len(fallback_text))
                    return normalize_source_text(fallback_text)

            logger.error("未能在 PDF 中找到翻译部分")
            return None
        except Exception as exc:
            logger.error("解析 PDF 时发生异常: %s", exc, exc_info=True)
            return None

    def _extract_chinese_from_page(self, text: str) -> Optional[str]:
        """提取 Part IV Translation 标记后的中文段落。"""
        chinese_lines = []
        found_translation = False

        for raw_line in text.split("\n"):
            line = raw_line.strip()
            if not line:
                continue
            if re.search(r"Part\s*IV", line, re.I) and "Translation" in line:
                found_translation = True
                continue
            if not found_translation:
                continue
            if any(keyword in line for keyword in ["Directions", "translate", "following", "passage"]):
                continue
            if self._contains_chinese(line):
                chinese_lines.append(line)
            if len(chinese_lines) > 5:
                break

        if not chinese_lines:
            return None
        return normalize_source_text("\n".join(chinese_lines))

    def _extract_translation_blocks_from_page(self, page) -> Optional[str]:
        """从含有 Part IV 的页面按坐标提取题干区域。"""
        blocks = page.get_text("blocks")
        marker_y = None
        for _x0, y0, _x1, _y1, text, *_ in blocks:
            if re.search(r"Part\s*IV", text, re.I) and "Translation" in text:
                marker_y = y0
                break

        if marker_y is None:
            return None

        lines = []
        for _x0, y0, _x1, _y1, text, *_ in blocks:
            cleaned = " ".join(text.split()).strip()
            if not cleaned or y0 <= marker_y + 45:
                continue
            if "Directions" in cleaned or "Answer Sheet" in cleaned:
                continue
            if cleaned.startswith(("http", "www.")):
                continue
            if len(cleaned) >= 12:
                lines.append(cleaned)

        if not lines:
            return None

        result = normalize_source_text("\n".join(lines[:8]))
        if "�" in result:
            logger.warning("翻译题区域已定位，但 PDF 中文字体编码可能导致乱码，请手动校正")
        return result

    def _extract_chinese_from_bottom_pages(self, document) -> Optional[str]:
        """从最后几页底部中文文本块兜底提取翻译题原文。"""
        candidates = []
        start_page = max(0, len(document) - 3)
        for page_num in range(len(document) - 1, start_page - 1, -1):
            page = document[page_num]
            page_height = page.rect.height
            for _x0, y0, _x1, _y1, text, *_ in page.get_text("blocks"):
                cleaned = " ".join(text.split())
                if y0 < page_height * 0.45:
                    continue
                if self._contains_chinese(cleaned) and len(cleaned) >= 20:
                    candidates.append((page_num, y0, cleaned))

        if not candidates:
            return None

        candidates.sort(key=lambda item: (item[0], item[1]))
        text = "\n".join(item[2] for item in candidates)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:800] if text else None

    def _contains_chinese(self, text: str) -> bool:
        """检测文本是否包含中文字符。"""
        return any("一" <= char <= "鿿" for char in text)

    def parse_filename(self, filename: str) -> Optional[Dict[str, Any]]:
        """从常见真题 PDF 文件名中识别考试信息。"""
        pattern = r"(\d{4})年(\d{1,2})月.*?(四级|六级).*?第(\d)套"
        match = re.search(pattern, filename)
        if not match:
            return None

        year = int(match.group(1))
        month = int(match.group(2))
        set_number = int(match.group(4))
        if month not in {6, 12} or set_number not in {1, 2, 3}:
            return None
        exam_type = "CET-4" if match.group(3) == "四级" else "CET-6"
        return {
            "exam_type": exam_type,
            "year": year,
            "month": month,
            "set_number": set_number,
        }

    def parse_uploaded_pdf(
        self,
        pdf_file,
        exam_type: str,
        year: int,
        month: int,
        set_number: int,
    ) -> Optional[ExamPaper]:
        """保存并自动解析用户上传的 PDF。"""
        logger.info("开始处理上传的 PDF: %s %s年%s月 第%s套", exam_type, year, month, set_number)
        filename = f"{exam_type}_{year}_{month}_set{set_number}.pdf"
        save_path = PDFS_DIR / filename
        temporary_path = save_path.with_suffix(".uploading.pdf")

        try:
            pdf_file.seek(0)
            with open(temporary_path, "wb") as file:
                file.write(pdf_file.read())

            chinese_text = self.extract_translation_text(str(temporary_path))
            if not chinese_text:
                temporary_path.unlink(missing_ok=True)
                return None

            temporary_path.replace(save_path)
            paper = ExamPaper(
                exam_type=exam_type,
                year=year,
                month=month,
                set_number=set_number,
                chinese_text=chinese_text,
                pdf_path=str(save_path),
            )
            self.save_paper(paper)
            logger.info("试卷处理完成: %s", paper.display_name)
            return paper
        except Exception as exc:
            temporary_path.unlink(missing_ok=True)
            logger.error("保存或解析上传的 PDF 失败: %s", exc, exc_info=True)
            return None
