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
from app.services.subtitle_service import (
    normalize_bilingual_segments,
    normalize_source_text,
    prepare_translation_units,
    sentence_units_from_translation_units,
    split_bilingual_subtitle_cues,
    subtitle_cue_fits,
    subtitle_display_chinese,
)


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
4. 把原文与英文翻译拆成语义对应的句子级单元。每个英文单元必须在完整句末结束，不得在短语或句子中间切断。
5. 每个中文单元必须是对应英文单元的完整、自然释义；一个中文长句可以对应连续两个英文完整句，但不得让中英文含义跨单元错位。
6. 分段优先尊重原文语义和完整英文句子；所有文本不得包含换行符。短字幕会由程序在句内另行生成。
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
            fallback["segments"] = prepare_translation_units(
                chinese_text,
                fallback["english_text"],
                fallback["segments"],
            )
            return fallback

        data.setdefault("topic_keyword", self._guess_keyword(chinese_text))
        data.setdefault("publish_topic", data["topic_keyword"])
        data.setdefault("segments", [{"chinese": chinese_text, "english": data.get("english_text", "")}])
        data["segments"] = prepare_translation_units(
            chinese_text,
            data.get("english_text", ""),
            data["segments"],
        )
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

    def align_subtitle_cues(self, translation_units: List[dict]) -> Optional[List[dict]]:
        """保留中英文原文不变，让模型共同决定语义一致且适合画面的切点。"""
        sentences = sentence_units_from_translation_units(translation_units)
        if not sentences:
            return None

        requests_payload = []
        for sentence_index, sentence in enumerate(sentences, start=1):
            requests_payload.append({
                "sentence_id": sentence_index,
                "english": sentence["english"],
                "chinese": subtitle_display_chinese(sentence["chinese"]),
            })

        prompt = f"""你是四六级汉译英视频的双语字幕对齐助手。中英文内容都已经定稿，你只决定两种语言各自在什么位置切分。

任务：把每个完整句切成若干组双语短字幕，使同一组的 english 和 chinese 表达同一含义，适合跟随英文朗读依次显示。

硬性要求：
1. 只返回 JSON，不要解释。
2. sentence_id 必须且只能出现一次，顺序与输入一致。
3. 只能切分，绝对不得翻译、改写、增字、漏字或调整中英文词序；标点也必须保留。
4. 同一句所有 english 按顺序用单个空格拼接后，必须与输入 english 完全一致；所有 chinese 直接拼接后必须与输入 chinese 完全一致。
5. 每组英文建议 5 至 12 个词，最多 14 个词；中英文在当前竖屏上都应适合一至两行。
6. 必须在完整语义短语边界切分。禁止切开专有名词、固定搭配、介词短语以及 ice and snow resources 这类并列名词短语。
7. 不要把只有“近年来、例如、如今”等状语单独成组；它们应与后面的主语或主要语义组合。
8. 当两种语言语序不同时，以每屏整体含义相同为目标，不要求逐词机械对应。

输入：
{json.dumps(requests_payload, ensure_ascii=False, indent=2)}

返回格式：
{{
  "sentences": [
    {{
      "sentence_id": 1,
      "cues": [
        {{"english": "连续英文原文片段", "chinese": "对应的连续中文原文片段"}}
      ]
    }}
  ]
}}"""
        result = self._call_llm_json(prompt, max_tokens=3000)
        raw_sentences = result.get("sentences") if isinstance(result, dict) else None
        if not isinstance(raw_sentences, list):
            print("字幕语义对齐失败: 模型未返回 sentences 数组")
            return None

        returned_by_id = {}
        for item in raw_sentences:
            if not isinstance(item, dict) or not isinstance(item.get("sentence_id"), int):
                return None
            sentence_id = item["sentence_id"]
            if sentence_id in returned_by_id or not 1 <= sentence_id <= len(sentences):
                print("字幕语义对齐失败: sentence_id 重复或越界")
                return None
            returned_by_id[sentence_id] = item.get("cues")
        if set(returned_by_id) != set(range(1, len(sentences) + 1)):
            print("字幕语义对齐失败: 句子数量或 id 与请求不一致")
            return None

        aligned_sentences = []
        for sentence_index, (sentence, source) in enumerate(zip(sentences, requests_payload), start=1):
            raw_cues = returned_by_id[sentence_index]
            sentence_cues, failure = self._validate_subtitle_cues(raw_cues, source)
            if failure == "content":
                print(f"字幕语义对齐失败: 第{sentence_index}句中英文被增删、改写或调序")
                return None
            if failure:
                print(f"第{sentence_index}句存在空白或超过两行的 cue，正在单独重新切分")
                repaired_cues = self._repair_subtitle_sentence(
                    source,
                    raw_cues,
                    sentence_index,
                )
                sentence_cues, repair_failure = self._validate_subtitle_cues(
                    repaired_cues,
                    source,
                )
                if repair_failure:
                    # 模型偶尔会连续忽略行宽要求。本地切分只使用已定稿原文，
                    # 不会重新翻译，保证按钮不会因一次不合格响应永久卡住。
                    fallback_cues = split_bilingual_subtitle_cues(
                        source["english"],
                        source["chinese"],
                    )
                    sentence_cues, fallback_failure = self._validate_subtitle_cues(
                        fallback_cues,
                        source,
                    )
                    if fallback_failure:
                        print(f"字幕语义对齐失败: 第{sentence_index}句单独重切后仍无法放入两行")
                        return None
                    print(f"第{sentence_index}句模型重切仍不合格，已使用安全切分兜底")
            aligned_sentences.append({**sentence, "subtitle_cues": sentence_cues})
        return aligned_sentences

    @staticmethod
    def _validate_subtitle_cues(raw_cues, source: dict) -> tuple[Optional[List[dict]], Optional[str]]:
        """校验单句 cue；区分原文被改动与单纯的排版超限。"""
        if not isinstance(raw_cues, list) or not raw_cues:
            return None, "structure"

        normalized = []
        for cue in raw_cues:
            if not isinstance(cue, dict):
                return None, "structure"
            normalized.append({
                "english": " ".join(str(cue.get("english", "")).split()).strip(),
                "chinese": normalize_source_text(cue.get("chinese", "")),
            })

        # 空 cue 本身属于可修复的排版错误，不应因为它额外引入的连接空格
        # 被误判成“英文原文遭到改写”。
        joined_english = " ".join(
            cue["english"] for cue in normalized if cue["english"]
        ).strip()
        joined_chinese = normalize_source_text("".join(cue["chinese"] for cue in normalized))
        if joined_english != source["english"] or joined_chinese != source["chinese"]:
            return None, "content"
        if any(
            not cue["english"]
            or not cue["chinese"]
            or not subtitle_cue_fits(cue["english"], cue["chinese"])
            for cue in normalized
        ):
            return None, "layout"
        return normalized, None

    def _repair_subtitle_sentence(self, source: dict, raw_cues, sentence_index: int):
        """只把排版不合格的单句交给模型重切，避免重做整篇对齐。"""
        prompt = f"""你是四六级汉译英视频的双语字幕修复助手。第{sentence_index}句的字幕存在空白或显示超过两行，请只重新切分这一句。

硬性要求：
1. 只返回 JSON，不要解释，格式为 {{"cues": [{{"english": "...", "chinese": "..."}}]}}。
2. 只能切分，绝对不得翻译、改写、增字、漏字或调序；标点也必须保留。
3. 所有 english 按顺序用单个空格拼接后必须与英文原文完全一致；所有 chinese 直接拼接后必须与中文原文完全一致。
4. 每个 cue 的英文和中文都必须能显示在一至两行内；宁可增加 cue 数量，也不要让任何 cue 超过两行。
5. 同一 cue 的中英文应表达同一含义，并优先在自然短语边界切分。

英文原文：{source["english"]}
中文原文：{source["chinese"]}
上次不合格的切分：{json.dumps(raw_cues, ensure_ascii=False)}"""
        result = self._call_llm_json(prompt, max_tokens=1600)
        if not isinstance(result, dict):
            return None
        if isinstance(result.get("cues"), list):
            return result["cues"]
        # 容忍模型沿用首次请求的 sentences 包装格式。
        sentences = result.get("sentences")
        if isinstance(sentences, list) and len(sentences) == 1 and isinstance(sentences[0], dict):
            return sentences[0].get("cues")
        return None

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
