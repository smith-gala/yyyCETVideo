"""快速生成 1080×1920 静态版式预览，不调用 AI/TTS 或视频编码。"""
import argparse
from pathlib import Path

from PIL import Image

from app.config import ASSET_COVER_BG, ASSET_KEYWORDS_BG, ASSET_QUESTION_BG, OUTPUT_DIR
from app.models import ExamMetadata, KeyExpression
from app.renderers.cover_renderer import CoverRenderer
from app.renderers.keywords_renderer import KeywordsRenderer
from app.renderers.question_renderer import QuestionRenderer
from app.renderers.subtitle_renderer import SubtitleRenderer


FIXTURES = {
    "A": {
        "metadata": ExamMetadata(
            exam_level="CET-4", exam_level_cn="四级", exam_year=2026, exam_month=6, exam_set_number=1,
            exam_session="2026年6月", exam_full_title="2026年6月全国大学英语四级考试",
            section_cn="翻译部分", section_en="TRANSLATION", topic_cn="餐桌礼仪", topic_en="Dining Etiquette",
        ),
        "chinese": "餐桌礼仪是中华传统文化的重要组成部分，蕴含着热情有礼的待客之道。为了招待客人，主人会根据客人的口味和喜好准备丰富精致的菜肴。就餐座位的安排非常讲究，主人坐在正对大门的位置，在主人身边得座的是最重要的客人。进餐时，主人会不时地为客人添加菜肴。这种独特的餐桌礼仪已延续了数千年，对促进和谐的人际交往起到了重要作用。",
    },
    "B": {
        "metadata": ExamMetadata(
            exam_level="CET-4", exam_level_cn="四级", exam_year=2024, exam_month=12, exam_set_number=2,
            exam_session="2024年12月", exam_full_title="2024年12月全国大学英语四级考试",
            section_cn="翻译部分", section_en="TRANSLATION", topic_cn="杂交水稻技术", topic_en="Hybrid Rice Technology",
        ),
        "chinese": "袁隆平和他的科研团队克服重重困难，研发出超级杂交水稻。这项技术提高了水稻抗旱抗病能力，使其能够适应不同的气候和土壤条件，并显著提高产量。如今，这项技术已经在许多国家得到广泛应用，为全球粮食安全作出了重大贡献。",
    },
    "C": {
        "metadata": ExamMetadata(
            exam_level="CET-6", exam_level_cn="六级", exam_year=2023, exam_month=6, exam_set_number=3,
            exam_session="2023年6月", exam_full_title="2023年6月全国大学英语六级考试",
            section_cn="翻译部分", section_en="TRANSLATION", topic_cn="城市公共交通", topic_en="Urban Public Transport",
        ),
        "chinese": "近年来，中国许多城市不断完善公共交通网络，地铁、公交车和共享出行服务相互衔接。便利高效的公共交通不仅缩短了通勤时间，也减少了能源消耗和空气污染，为建设宜居城市提供了有力支持。",
    },
}

EXPRESSIONS_BY_CASE = {
    "A": [
        KeyExpression(word="dining etiquette", meaning="餐桌礼仪", example="traditional Chinese dining etiquette"),
        KeyExpression(word="hospitality", meaning="热情好客；款待", example="show hospitality to guests"),
        KeyExpression(word="seating arrangement", meaning="座位安排", example="traditional seating arrangements"),
        KeyExpression(word="table manners", meaning="用餐礼仪", example="follow local table manners"),
        KeyExpression(word="treat guests with honor", meaning="以礼待客", example="a long-standing tradition of honoring guests"),
    ],
    "B": [
        KeyExpression(word="hybrid rice", meaning="杂交水稻", example="develop a new variety of hybrid rice"),
        KeyExpression(word="overcome challenges", meaning="克服困难", example="overcome numerous research challenges"),
        KeyExpression(word="disease resistance", meaning="抗病能力", example="improve drought and disease resistance"),
        KeyExpression(word="increase crop yields", meaning="提高产量", example="increase crop yields significantly"),
        KeyExpression(word="global food security", meaning="全球粮食安全", example="contribute to global food security"),
    ],
    "C": [
        KeyExpression(word="public transport network", meaning="公共交通网络", example="improve the public transport network"),
        KeyExpression(word="commuting time", meaning="通勤时间", example="shorten daily commuting time"),
        KeyExpression(word="energy consumption", meaning="能源消耗", example="reduce urban energy consumption"),
        KeyExpression(word="air pollution", meaning="空气污染", example="help reduce air pollution"),
        KeyExpression(word="livable city", meaning="宜居城市", example="build a more livable city"),
    ],
}


def generate(page: str, case: str, output_dir: Path) -> list[Path]:
    fixture = FIXTURES[case]
    metadata = fixture["metadata"]
    output_dir.mkdir(parents=True, exist_ok=True)
    pages = ["cover", "question", "keywords", "subtitle"] if page == "all" else [page]
    generated: list[Path] = []

    for current in pages:
        output = output_dir / f"preview_{current}.png"
        if current == "cover":
            CoverRenderer().render(str(output), metadata, str(ASSET_COVER_BG))
        elif current == "question":
            QuestionRenderer().render(fixture["chinese"], metadata, str(output), str(ASSET_QUESTION_BG))
        elif current == "keywords":
            KeywordsRenderer().render(EXPRESSIONS_BY_CASE[case], metadata, str(output), str(ASSET_KEYWORDS_BG))
        elif current == "subtitle":
            SubtitleRenderer().render_preview(
                str(output),
                "This technological breakthrough has been widely recognized around the world.",
                "这一技术突破获得了全世界的广泛认可。",
                str(ASSET_KEYWORDS_BG),
            )
        with Image.open(output) as image:
            if image.size != (1080, 1920):
                raise RuntimeError(f"{output.name} 尺寸错误: {image.size}")
        generated.append(output)
    return generated


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--page", choices=["cover", "question", "keywords", "subtitle", "all"], default="all")
    parser.add_argument("--case", choices=sorted(FIXTURES), default="A")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR / "previews")
    args = parser.parse_args()
    for output in generate(args.page, args.case, args.output_dir):
        print(output.resolve())


if __name__ == "__main__":
    main()
