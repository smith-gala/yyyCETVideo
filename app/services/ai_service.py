"""
AI翻译和关键词提取服务
"""
import json
import os
from typing import List, Optional
import requests
from anthropic import Anthropic
from app.config import ANTHROPIC_API_KEY, LLM_API_KEY, LLM_BASE_URL, LLM_MODEL
from app.models import KeyExpression, SubtitleSegment
from app.services.subtitle_service import normalize_bilingual_segments


class AIService:
    """AI服务：翻译和关键词提取"""

    def __init__(self, api_key: Optional[str] = None):
        self.llm_api_key = api_key or LLM_API_KEY
        self.llm_base_url = LLM_BASE_URL.rstrip("/")
        self.llm_model = LLM_MODEL
        self.anthropic_api_key = api_key or ANTHROPIC_API_KEY
        if self.anthropic_api_key:
            self.client = Anthropic(api_key=self.anthropic_api_key)
        else:
            self.client = None

    def analyze_translation(self, chinese_text: str, count: int = 5) -> Optional[dict]:
        """
        翻译中文原文，并生成主题关键词、字幕分段和重点表达。
        """
        prompt = f"""你是大学英语四六级翻译题短视频助手。请处理下面的中文翻译题原文，并只返回JSON。

要求：
1. 给出准确、自然、适合朗读的英文翻译。
2. 提取一个适合搜索Pexels背景素材的中文关键词，2到8个汉字，例如“餐桌礼仪”。
3. 生成一个简洁的中文发布文案主题。有核心人物时使用“人物--主题”，例如“袁隆平--杂交水稻”；没有核心人物时直接使用主题。不要添加年份、四六级、套数或其他解释。
4. 把原文与英文翻译拆成语义对应的短字幕片段：英文推荐8到16词、绝对不超过20词；中文建议18到32个汉字。
5. 每个中文 cue 必须是同一个英文 cue 的完整、自然释义；允许调整中文语序或轻微改写，不得把英文当前句的主语或关键意义留到下一个 cue。
6. 切分优先级为句号、分号、逗号、从句边界，禁止用一个片段承载整个长段落；所有文本不得包含换行符。
7. 提取{count}个重点英文表达，优先短语、专有名词或考试高频表达。

返回JSON格式：
{{
  "english_text": "...",
  "topic_keyword": "...",
  "publish_topic": "...",
  "segments": [
    {{"chinese": "...", "english": "..."}}
  ],
  "key_expressions": [
    {{"word": "...", "meaning": "...", "example": "..."}}
  ]
}}

中文原文：
{chinese_text}"""

        data = self._call_llm_json(prompt, max_tokens=2500)
        if not data:
            english = self.translate_to_english(chinese_text)
            if not english:
                return None
            fallback = {
                "english_text": english,
                "topic_keyword": self._guess_keyword(chinese_text),
                "publish_topic": self._guess_keyword(chinese_text),
                "segments": [{"chinese": chinese_text, "english": english}],
                "key_expressions": [
                    exp.model_dump(mode="json")
                    for exp in self.extract_key_expressions(chinese_text, english, count=count)
                ],
            }
            fallback["segments"] = normalize_bilingual_segments(fallback["segments"])
            return fallback

        data.setdefault("topic_keyword", self._guess_keyword(chinese_text))
        data.setdefault("publish_topic", data["topic_keyword"])
        data.setdefault("segments", [{"chinese": chinese_text, "english": data.get("english_text", "")}])
        data["segments"] = normalize_bilingual_segments(data["segments"])
        data.setdefault("key_expressions", [])
        return data

    def translate_to_english(self, chinese_text: str) -> Optional[str]:
        """
        将中文翻译成英文
        """
        if self.llm_base_url and self.llm_api_key:
            prompt = f"""请将以下中文翻译成英文。这是一道四六级英语考试的翻译题，请给出准确、地道、适合朗读的英文翻译。

中文原文：
{chinese_text}

请直接给出英文翻译，不要添加任何解释或说明。"""
            return self._call_llm_text(prompt, max_tokens=2000)

        if not self.client:
            print("错误: Anthropic API Key未配置")
            return None

        try:
            prompt = f"""请将以下中文翻译成英文。这是一道四六级英语考试的翻译题，请给出准确、地道的英文翻译。

中文原文：
{chinese_text}

请直接给出英文翻译，不要添加任何解释或说明。"""

            message = self.client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=2000,
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )

            return message.content[0].text.strip()

        except Exception as e:
            print(f"翻译失败: {e}")
            return None

    def extract_key_expressions(self, chinese_text: str, english_text: str, count: int = 5) -> List[KeyExpression]:
        """
        从翻译中提取重点表达
        """
        if self.llm_base_url and self.llm_api_key:
            prompt = self._key_expression_prompt(chinese_text, english_text, count)
            result = self._call_llm_json(prompt, max_tokens=1500)
            if isinstance(result, list):
                return [KeyExpression(**exp) for exp in result[:count]]
            return []

        if not self.client:
            print("错误: Anthropic API Key未配置")
            return []

        try:
            prompt = self._key_expression_prompt(chinese_text, english_text, count)
            message = self.client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=1500,
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )

            result_text = message.content[0].text.strip()
            expressions_data = self._parse_json_text(result_text)
            return [KeyExpression(**exp) for exp in expressions_data[:count]]

        except Exception as e:
            print(f"提取关键词失败: {e}")
            return []

    def build_subtitle_segments(self, raw_segments: list, durations: Optional[List[float]] = None) -> List[SubtitleSegment]:
        """根据分段音频时长生成字幕时间轴。"""
        raw_segments = normalize_bilingual_segments(raw_segments)
        if not raw_segments:
            return []

        if not durations or len(durations) != len(raw_segments):
            durations = [max(2.0, len(seg.get("english", "").split()) * 0.45) for seg in raw_segments]

        cursor = 0.0
        timeline = []
        for seg, duration in zip(raw_segments, durations):
            end = cursor + max(0.2, float(duration))
            timeline.append(SubtitleSegment(
                start=round(cursor, 3),
                end=round(end, 3),
                english=seg.get("english", "").strip(),
                chinese=seg.get("chinese", "").strip(),
            ))
            cursor = end
        return timeline

    def _key_expression_prompt(self, chinese_text: str, english_text: str, count: int) -> str:
        return f"""请从以下中英文翻译对照中提取{count}个最重要的英文表达（单词或短语）。

中文原文：
{chinese_text}

英文翻译：
{english_text}

请按以下JSON格式返回，每个表达包含：
1. word: 英文词汇或短语
2. meaning: 中文释义
3. example: 在翻译中的实际使用示例或相关搭配

返回格式示例：
[
  {{
    "word": "dining etiquette",
    "meaning": "餐桌礼仪",
    "example": "traditional Chinese dining etiquette"
  }},
  {{
    "word": "hospitality",
    "meaning": "n. 热情好客；款待",
    "example": "show hospitality to guests"
  }}
]

请直接返回JSON数组，不要添加任何其他文字。"""

    def _call_llm_text(self, prompt: str, max_tokens: int = 2000) -> Optional[str]:
        try:
            if self.llm_base_url and self.llm_api_key:
                payload = {
                    "model": self.llm_model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.2,
                    "max_tokens": max_tokens,
                }
                response = requests.post(
                    f"{self.llm_base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.llm_api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                    timeout=90,
                )
                response.raise_for_status()
                result = response.json()
                return result["choices"][0]["message"]["content"].strip()

            if self.client:
                message = self.client.messages.create(
                    model="claude-sonnet-4-20250514",
                    max_tokens=max_tokens,
                    messages=[{"role": "user", "content": prompt}],
                )
                return message.content[0].text.strip()

            return None
        except Exception as e:
            print(f"LLM调用失败: {e}")
            return None

    def _call_llm_json(self, prompt: str, max_tokens: int = 2000):
        text = self._call_llm_text(prompt, max_tokens=max_tokens)
        if not text:
            return None
        try:
            return self._parse_json_text(text)
        except Exception as e:
            print(f"解析LLM JSON失败: {e}")
            return None

    def _parse_json_text(self, text: str):
        result_text = text.strip()
        if "```json" in result_text:
            result_text = result_text.split("```json", 1)[1].split("```", 1)[0].strip()
        elif "```" in result_text:
            result_text = result_text.split("```", 1)[1].split("```", 1)[0].strip()
        else:
            start = min([idx for idx in [result_text.find("{"), result_text.find("[")] if idx >= 0], default=0)
            end = max(result_text.rfind("}"), result_text.rfind("]"))
            if end > start:
                result_text = result_text[start:end + 1]
        return json.loads(result_text)

    def _guess_keyword(self, chinese_text: str) -> str:
        for marker in ["礼仪", "文化", "春节", "旅游", "教育", "科技", "环保", "健康", "城市", "传统"]:
            if marker in chinese_text:
                return marker
        cleaned = "".join(ch for ch in chinese_text if '\u4e00' <= ch <= '\u9fff')
        return cleaned[:6] or "中国文化"
