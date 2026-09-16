"""中英字幕语义切分；该模块不调用 AI，保证 TTS 与字幕使用同一分段。"""
import re
from difflib import SequenceMatcher
from itertools import combinations
from typing import Iterable, List

from PIL import Image, ImageDraw

from app.renderers.design_tokens import SUBTITLE
from app.renderers.layout_utils import load_font, wrap_text


WORD_RE = re.compile(r"[A-Za-z0-9]+(?:[’'-][A-Za-z0-9]+)*")
STRONG_END = (".", "!", "?", ";")
SOFT_END = (",", ":")
CLAUSE_STARTS = {
    "and", "but", "or", "while", "whereas", "because", "which", "that",
    "who", "when", "if", "although", "though", "making", "allowing",
}
TRAILING_CLOSERS = '"\'”’)]}'
SUBTITLE_PIPELINE_VERSION = 3


def normalize_source_text(text: str) -> str:
    """清理 PDF/文本框中的排版换行，不在被断开的词语中插入空格。"""
    value = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    value = re.sub(r"\s*\n+\s*", "", value)
    value = re.sub(r"[\t\f\v ]+", " ", value).strip()
    # 兼容已经被旧版本保存成“超 级”“共 享”的缓存。
    value = re.sub(r"(?<=[\u3400-\u9fff]) +(?=[\u3400-\u9fff])", "", value)
    value = re.sub(r" +([，。！？；：、）】》”’])", r"\1", value)
    value = re.sub(r"([（【《“‘]) +", r"\1", value)
    return value


def english_word_count(text: str) -> int:
    return len(WORD_RE.findall(text))


def split_english_sentences(text: str) -> List[str]:
    """按完整英文句子切分，并把句号后的引号或括号保留在原句中。"""
    clean = " ".join(str(text or "").split()).strip()
    if not clean:
        return []
    sentences: List[str] = []
    start = 0
    pattern = re.compile(rf"[.!?](?:[{re.escape(TRAILING_CLOSERS)}]+)?(?=\s|$)")
    for match in pattern.finditer(clean):
        value = clean[start:match.end()].strip()
        if value:
            sentences.append(value)
        start = match.end()
    remainder = clean[start:].strip()
    if remainder:
        sentences.append(remainder)
    return sentences


def prepare_translation_units(
    source_chinese: str,
    english_text: str,
    raw_segments: Iterable[dict] = (),
) -> List[dict]:
    """保存句子级语义单元；无可靠上游分段时按两种语言的句长单调对齐。"""
    source = normalize_source_text(source_chinese)
    english = " ".join(str(english_text or "").split()).strip()
    raw = [
        {
            "english": " ".join(str(item.get("english", "")).split()).strip(),
            "chinese": normalize_source_text(item.get("chinese", "")),
        }
        for item in raw_segments or []
        if str(item.get("english", "")).strip()
    ]
    raw_chinese = "".join(item["chinese"] for item in raw)
    if raw and _joined_english(raw) == english and _chinese_similarity(raw_chinese, source) >= 0.78:
        merged = _merge_raw_units_at_sentence_boundaries(raw)
        if merged:
            return merged
    return _align_sentence_lists(source, english)


def sentence_units_from_translation_units(units: Iterable[dict]) -> List[dict]:
    """把语义单元展开成完整英文句子，作为连续 TTS 的最小单位。"""
    result: List[dict] = []
    for unit in units or []:
        english_sentences = split_english_sentences(unit.get("english", ""))
        chinese = normalize_source_text(unit.get("chinese", ""))
        if not english_sentences:
            continue
        chinese_parts = _split_chinese_weighted(
            chinese,
            [max(1, english_word_count(sentence)) for sentence in english_sentences],
        )
        result.extend(
            {"english": sentence, "chinese": chinese_part}
            for sentence, chinese_part in zip(english_sentences, chinese_parts)
        )
    return result


def split_bilingual_subtitle_cues(english: str, chinese: str) -> List[dict]:
    """按实际字幕字体宽度拆分句内短 cue，英文硬限制为最多两行。"""
    english_chunks = split_english_subtitle_cues(english)
    display_chinese = subtitle_display_chinese(chinese)
    chinese_chunks = _split_chinese_weighted(
        display_chinese,
        [max(1, english_word_count(chunk)) for chunk in english_chunks],
    )
    return [
        {"english": english_chunk, "chinese": chinese_chunk}
        for english_chunk, chinese_chunk in zip(english_chunks, chinese_chunks)
    ]


def split_english_subtitle_cues(text: str) -> List[str]:
    """生成适合正文画面的英文短 cue；可交给模型逐条配对中文。"""
    return _split_english_for_display(text)


def subtitle_display_chinese(text: str) -> str:
    """移除中文题源中仅作释义提示的英文括注，得到实际显示文本。"""
    return re.sub(
        r"\s*[（(]\s*[A-Za-z][^()（）]*[)）]",
        "",
        normalize_source_text(text),
    )


def subtitle_cue_fits(english: str, chinese: str) -> bool:
    """检查模型给出的双语 cue 是否都能在正文安全区内显示两行。"""
    image = Image.new("RGB", (SUBTITLE.width, 300), "white")
    draw = ImageDraw.Draw(image)
    max_width = SUBTITLE.width - SUBTITLE.padding_x * 2
    english_lines = wrap_text(
        draw,
        english.strip(),
        load_font(SUBTITLE.english_font_size, "bold"),
        max_width,
        prefer_words=True,
    )
    chinese_lines = wrap_text(
        draw,
        chinese.strip(),
        load_font(SUBTITLE.chinese_font_size, "regular"),
        max_width,
        prefer_words=False,
    )
    return bool(english_lines and chinese_lines) and len(english_lines) <= 2 and len(chinese_lines) <= 2


def split_english_semantically(text: str, target_words: int = 14, max_words: int = 20) -> List[str]:
    """优先在句号、分号、逗号和从句边界切开，硬上限为 max_words。"""
    tokens = " ".join(text.split()).split()
    chunks: List[str] = []
    while tokens:
        if english_word_count(" ".join(tokens)) <= max_words:
            chunks.append(" ".join(tokens))
            break

        limit = _token_index_for_word_limit(tokens, max_words)
        target = _token_index_for_word_limit(tokens, target_words)
        minimum = _token_index_for_word_limit(tokens, 8)
        candidates = []
        for index in range(max(1, minimum), limit + 1):
            token = tokens[index - 1]
            next_word = _bare_word(tokens[index]).lower() if index < len(tokens) else ""
            priority = 0
            if re.search(rf"[{re.escape(''.join(STRONG_END))}][{re.escape(TRAILING_CLOSERS)}]*$", token):
                priority = 4
            elif token.endswith(SOFT_END):
                priority = 3
            elif next_word in CLAUSE_STARTS:
                priority = 2
            candidates.append((priority, -abs(index - target), index))
        cut = max(candidates)[2] if candidates else limit
        chunks.append(" ".join(tokens[:cut]).strip())
        tokens = tokens[cut:]
    chunks = [chunk for chunk in chunks if chunk]
    if len(chunks) >= 2 and english_word_count(chunks[-1]) < 6:
        previous_tokens = chunks[-2].split()
        last_tokens = chunks[-1].split()
        while english_word_count(" ".join(last_tokens)) < 8 and english_word_count(" ".join(previous_tokens)) > 8:
            last_tokens.insert(0, previous_tokens.pop())
        chunks[-2] = " ".join(previous_tokens)
        chunks[-1] = " ".join(last_tokens)
    return chunks


def normalize_bilingual_segments(raw_segments: Iterable[dict], max_words: int = 20) -> List[dict]:
    """把任意上游分段收紧为短语义 cue，并在各 cue 间分配中文，不重复整段。"""
    normalized: List[dict] = []
    for raw in raw_segments or []:
        english = " ".join(str(raw.get("english", "")).split())
        chinese = normalize_source_text(raw.get("chinese", ""))
        if not english:
            continue
        english_chunks = split_english_semantically(english, max_words=max_words)
        chinese_chunks = _split_chinese_to_count(chinese, len(english_chunks))
        for index, english_chunk in enumerate(english_chunks):
            normalized.append({
                "english": english_chunk,
                "chinese": chinese_chunks[index] if index < len(chinese_chunks) else "",
            })
    return normalized


def realign_bilingual_segments(source_chinese: str, raw_segments: Iterable[dict]) -> List[dict]:
    """先按完整句对齐，再在句内分 cue，避免中英文跨句错位。"""
    cues = normalize_bilingual_segments(raw_segments, max_words=20)
    if not cues:
        return []

    chinese_sentences = _split_chinese_sentences(normalize_source_text(source_chinese))
    english_groups: List[List[dict]] = []
    current: List[dict] = []
    for cue in cues:
        current.append(cue)
        if cue["english"].rstrip('"\'”’)]}').endswith((".", "!", "?")):
            english_groups.append(current)
            current = []
    if current:
        english_groups.append(current)

    # 句数不一致时保留 AI/上游给出的配对，不做可能破坏语义的强行映射。
    if len(chinese_sentences) != len(english_groups):
        return cues

    aligned: List[dict] = []
    for chinese_sentence, group in zip(chinese_sentences, english_groups):
        weights = [max(1, english_word_count(cue["english"])) for cue in group]
        chinese_cues = _split_chinese_weighted(chinese_sentence, weights)
        aligned.extend(
            {"english": cue["english"], "chinese": chinese_cue}
            for cue, chinese_cue in zip(group, chinese_cues)
        )
    return aligned


def _token_index_for_word_limit(tokens: List[str], word_limit: int) -> int:
    count = 0
    for index, token in enumerate(tokens, start=1):
        count += english_word_count(token)
        if count >= word_limit:
            return index
    return len(tokens)


def _bare_word(token: str) -> str:
    match = WORD_RE.search(token)
    return match.group(0) if match else token


def _joined_english(items: Iterable[dict]) -> str:
    return " ".join(item["english"] for item in items if item.get("english")).strip()


def _chinese_similarity(left: str, right: str) -> float:
    def normalized(value: str) -> str:
        return re.sub(r"[^0-9A-Za-z\u3400-\u9fff]", "", str(value)).lower()

    first, second = normalized(left), normalized(right)
    if not first or not second:
        return 0.0
    return SequenceMatcher(None, first, second).ratio()


def _merge_raw_units_at_sentence_boundaries(raw: List[dict]) -> List[dict]:
    merged: List[dict] = []
    english_parts: List[str] = []
    chinese_parts: List[str] = []
    for item in raw:
        # 一个旧 cue 内已经跨越多个句子，说明它不是可靠的语义单元。
        if len(split_english_sentences(item["english"])) > 1:
            return []
        english_parts.append(item["english"])
        chinese_parts.append(item["chinese"])
        combined = " ".join(english_parts)
        if len(split_english_sentences(combined)) == 1 and re.search(
            rf"[.!?][{re.escape(TRAILING_CLOSERS)}]*$", combined
        ):
            merged.append({"english": combined, "chinese": "".join(chinese_parts)})
            english_parts, chinese_parts = [], []
    if english_parts:
        merged.append({"english": " ".join(english_parts), "chinese": "".join(chinese_parts)})
    return merged


def _align_sentence_lists(chinese: str, english: str) -> List[dict]:
    chinese_sentences = _split_chinese_sentences(chinese) or ([chinese] if chinese else [])
    english_sentences = split_english_sentences(english) or ([english] if english else [])
    if not english_sentences:
        return []
    if not chinese_sentences:
        return [{"english": sentence, "chinese": ""} for sentence in english_sentences]
    if len(english_sentences) == len(chinese_sentences):
        return [
            {"english": en, "chinese": zh}
            for zh, en in zip(chinese_sentences, english_sentences)
        ]

    if len(english_sentences) > len(chinese_sentences):
        grouped_english = _partition_by_relative_lengths(
            english_sentences,
            [english_word_count(value) for value in english_sentences],
            [len(value) for value in chinese_sentences],
        )
        return [
            {"english": " ".join(group), "chinese": chinese_sentence}
            for chinese_sentence, group in zip(chinese_sentences, grouped_english)
        ]

    grouped_chinese = _partition_by_relative_lengths(
        chinese_sentences,
        [len(value) for value in chinese_sentences],
        [english_word_count(value) for value in english_sentences],
    )
    return [
        {"english": english_sentence, "chinese": "".join(group)}
        for english_sentence, group in zip(english_sentences, grouped_chinese)
    ]


def _partition_by_relative_lengths(items: List[str], weights: List[int], target_weights: List[int]) -> List[List[str]]:
    """把较长的句子列表单调分组，使各组长度比例接近另一种语言。"""
    group_count = len(target_weights)
    if group_count <= 1:
        return [items]
    total = max(1, sum(weights))
    target_total = max(1, sum(target_weights))
    best = None
    for cuts in combinations(range(1, len(items)), group_count - 1):
        points = (0, *cuts, len(items))
        groups = [items[points[index]:points[index + 1]] for index in range(group_count)]
        group_weights = [sum(weights[points[index]:points[index + 1]]) for index in range(group_count)]
        cost = sum(
            abs(group_weight / total - target_weight / target_total)
            for group_weight, target_weight in zip(group_weights, target_weights)
        )
        candidate = (cost, cuts, groups)
        if best is None or candidate[:2] < best[:2]:
            best = candidate
    return best[2] if best else [items]


def _split_english_for_display(text: str, target_words: int = 9, max_words: int = 14) -> List[str]:
    tokens = " ".join(str(text or "").split()).split()
    if not tokens:
        return [""]
    chunks: List[str] = []
    while tokens:
        remaining = " ".join(tokens)
        if len(tokens) <= max_words and _english_line_count(remaining) <= 2:
            chunks.append(remaining)
            break

        upper = min(max_words, len(tokens) - 1)
        lower = min(5, upper)
        candidates = []
        for index in range(lower, upper + 1):
            first = " ".join(tokens[:index])
            if _english_line_count(first) > 2 or _inside_open_quote(tokens[:index]):
                continue
            token = tokens[index - 1]
            bare_token = _bare_word(token).lower()
            next_word = _bare_word(tokens[index]).lower() if index < len(tokens) else ""
            priority = 0
            if re.search(rf"[,;:][{re.escape(TRAILING_CLOSERS)}]*$", token):
                priority = 3
            elif next_word in CLAUSE_STARTS:
                priority = 2
            # 不在连字符数字、打开的引号或明显尚未完成的专名中间切断。
            if "-" in token or token.count('"') % 2 == 1:
                priority -= 5
            if bare_token in {"a", "an", "the", "of", "to", "in", "on", "at", "by", "for", "from", "with", "within"}:
                priority -= 4
            candidates.append((priority, -abs(index - target_words), index))
        cut = max(candidates)[2] if candidates else max(1, min(target_words, upper))
        chunks.append(" ".join(tokens[:cut]))
        tokens = tokens[cut:]

    if len(chunks) >= 2 and english_word_count(chunks[-1]) < 4:
        previous = chunks[-2].split()
        last = chunks[-1].split()
        while len(last) < 4 and len(previous) > 5:
            last.insert(0, previous.pop())
        if _english_line_count(" ".join(previous)) <= 2 and _english_line_count(" ".join(last)) <= 2:
            chunks[-2], chunks[-1] = " ".join(previous), " ".join(last)
    return chunks


def _inside_open_quote(tokens: List[str]) -> bool:
    return " ".join(tokens).count('"') % 2 == 1


def _english_line_count(text: str) -> int:
    image = Image.new("RGB", (SUBTITLE.width, 200), "white")
    draw = ImageDraw.Draw(image)
    font = load_font(SUBTITLE.english_font_size, "bold")
    lines = wrap_text(
        draw,
        text,
        font,
        SUBTITLE.width - SUBTITLE.padding_x * 2,
        prefer_words=True,
    )
    return len(lines)


def _split_chinese_to_count(text: str, count: int) -> List[str]:
    if count <= 1:
        return [text]
    if not text:
        return [""] * count

    units = [part.strip() for part in re.findall(r"[^。！？；，]+[。！？；，]?", text) if part.strip()]
    expanded: List[str] = []
    for unit in units or [text]:
        if len(unit) <= 32:
            expanded.append(unit)
            continue
        while len(unit) > 32:
            cut = _chinese_cut(unit, 28)
            expanded.append(unit[:cut].strip())
            unit = unit[cut:].strip()
        if unit:
            expanded.append(unit)

    while len(expanded) < count:
        index = max(range(len(expanded)), key=lambda i: len(expanded[i]))
        value = expanded.pop(index)
        cut = _chinese_cut(value, max(1, len(value) // 2))
        expanded[index:index] = [value[:cut].strip(), value[cut:].strip()]

    groups: List[str] = []
    remaining = expanded[:]
    for group_index in range(count - 1):
        groups_left = count - group_index
        target = max(1, round(sum(len(item) for item in remaining) / groups_left))
        current: List[str] = []
        current_len = 0
        while remaining and len(remaining) > groups_left - 1:
            candidate = remaining[0]
            if current and current_len + len(candidate) > target:
                break
            current.append(remaining.pop(0))
            current_len += len(candidate)
        if not current:
            current.append(remaining.pop(0))
        groups.append("".join(current).strip())
    groups.append("".join(remaining).strip())
    return groups


def _split_chinese_sentences(text: str) -> List[str]:
    return [
        part.strip()
        for part in re.findall(r"[^。！？]+[。！？]?", text)
        if part.strip()
    ]


def _split_chinese_weighted(text: str, weights: List[int]) -> List[str]:
    if len(weights) <= 1:
        return [text]
    remaining = text
    remaining_weights = list(weights)
    chunks: List[str] = []
    for weight in weights[:-1]:
        total_weight = max(1, sum(remaining_weights))
        preferred = max(1, round(len(remaining) * weight / total_weight))
        cut = _chinese_semantic_cut(remaining, preferred)
        chunks.append(remaining[:cut].strip())
        remaining = remaining[cut:].strip()
        remaining_weights.pop(0)
    chunks.append(remaining.strip())
    return chunks


def _chinese_semantic_cut(text: str, preferred: int) -> int:
    """优先在标点或自然连接词前切分，避免按字符数切断主谓结构。"""
    candidates: List[tuple[int, int]] = []
    for index, char in enumerate(text[:-1], start=1):
        if char in "，；、：":
            candidates.append((index, 0))
    for connector in (
        "同时", "通过", "随着", "其中", "目前", "如今", "此外", "着力", "能够", "可以",
        "更好地", "显著", "和", "并", "但", "而",
    ):
        start = 0
        while True:
            found = text.find(connector, start)
            if found < 1:
                break
            candidates.append((found, 1))
            start = found + len(connector)

    nearby = [item for item in candidates if max(1, preferred - 32) <= item[0] <= preferred + 24]
    if nearby:
        return min(nearby, key=lambda item: (abs(item[0] - preferred), item[1]))[0]
    return min(max(1, preferred), len(text) - 1)


def _chinese_cut(text: str, preferred: int) -> int:
    punctuation = "，；。！？、"
    candidates = [i + 1 for i, char in enumerate(text) if char in punctuation]
    nearby = [index for index in candidates if max(1, preferred - 10) <= index <= preferred + 10]
    if nearby:
        return min(nearby, key=lambda index: abs(index - preferred))
    return min(max(1, preferred), len(text) - 1)
