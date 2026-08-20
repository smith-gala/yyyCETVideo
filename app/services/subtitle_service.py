"""中英字幕语义切分；该模块不调用 AI，保证 TTS 与字幕使用同一分段。"""
import re
from typing import Iterable, List


WORD_RE = re.compile(r"[A-Za-z0-9]+(?:[’'-][A-Za-z0-9]+)*")
STRONG_END = (".", "!", "?", ";")
SOFT_END = (",", ":")
CLAUSE_STARTS = {
    "and", "but", "or", "while", "whereas", "because", "which", "that",
    "who", "when", "if", "although", "though", "making", "allowing",
}


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
            if token.endswith(STRONG_END):
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
    for connector in ("同时", "通过", "随着", "其中", "目前", "如今", "此外", "和", "并", "但", "而"):
        start = 0
        while True:
            found = text.find(connector, start)
            if found < 1:
                break
            candidates.append((found, 1))
            start = found + len(connector)

    nearby = [item for item in candidates if max(1, preferred - 16) <= item[0] <= preferred + 16]
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
