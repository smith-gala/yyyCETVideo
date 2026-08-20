"""
视频生成页面。
"""
import os
from pathlib import Path
from typing import Any

import streamlit as st

from app.config import (
    ASSET_CLOSING_AUDIO, ASSET_COVER_BG, ASSET_ENDING_EXAM_AUDIO,
    ASSET_KEYWORDS_BG, BACKGROUNDS_DIR, OUTPUT_DIR, TEMP_DIR,
)
from app.models import ExamMetadata, ExamPaper, KeyExpression, PexelsAsset, VideoConfig
from app.services.subtitle_service import english_word_count, normalize_source_text, realign_bilingual_segments


def render_video_generator():
    """渲染视频生成页面。"""
    st.title("视频生成")
    st.caption("选择真题，确认翻译与素材，然后生成完整短视频")
    st.markdown("---")

    # 页面首次打开时只加载真题缓存；MoviePy、Anthropic、Pexels 等重依赖在按钮触发时再加载。
    pdf_service = _get_pdf_service()

    # Streamlit 热重载后，session_state 可能仍持有由旧版 Pydantic 类创建的对象。
    # 通过 JSON 字典边界重建为当前模块的 ExamPaper，避免同名模型类型身份冲突。
    cached_papers = [
        ExamPaper.model_validate(paper.model_dump(mode="json"))
        for paper in pdf_service.list_cached_papers()
    ]
    if not cached_papers:
        st.warning("暂无可用真题，请先到【真题素材管理】页面上传 PDF 或手动添加真题。")
        return

    selected_paper = _select_paper(cached_papers)

    st.subheader("1. 原文确认")
    chinese_text = st.text_area("中文原文", selected_paper.chinese_text, height=170, key=f"chinese_{selected_paper.paper_id}")
    if st.button("保存中文修改", use_container_width=True):
        selected_paper.chinese_text = normalize_source_text(chinese_text)
        pdf_service.save_paper(selected_paper)
        st.success("中文原文已保存，后续生成会使用修改后的内容。")

    st.markdown("---")
    st.subheader("2. 翻译、关键词和重点表达")
    col_ai, col_manual = st.columns([1, 1])
    with col_ai:
        if st.button("AI生成翻译分析", use_container_width=True):
            ai_service = _get_ai_service()
            with st.spinner("正在调用模型生成翻译、主题关键词和重点表达..."):
                result = ai_service.analyze_translation(chinese_text)
            if result:
                st.session_state[f"analysis_{selected_paper.paper_id}"] = result
                selected_paper.english_text = result.get("english_text", "")
                generated_topic = str(result.get("topic_keyword") or "").strip()
                selected_paper.topic_cn = generated_topic
                selected_paper.topic_keyword = generated_topic
                selected_paper.publish_topic = (
                    str(result.get("publish_topic") or "").strip() or generated_topic
                )
                generated_expressions = [
                    KeyExpression(**item) for item in result.get("key_expressions", [])[:5]
                    if item.get("word") and item.get("meaning")
                ]
                if not generated_expressions and selected_paper.english_text:
                    generated_expressions = ai_service.extract_key_expressions(
                        chinese_text,
                        selected_paper.english_text,
                        count=5
                    )
                selected_paper.key_expressions = generated_expressions
                pdf_service.save_paper(selected_paper)
                _bump_key_expression_version(selected_paper.paper_id)
                st.success("分析完成。")
            else:
                st.error("AI分析失败，请检查 LLM_API_KEY / LLM_BASE_URL / LLM_MODEL。")

    analysis = st.session_state.get(f"analysis_{selected_paper.paper_id}", {})
    english_text = st.text_area(
        "英文翻译（可编辑）",
        value=analysis.get("english_text") or selected_paper.english_text or "",
        height=190,
    )
    topic_cn = st.text_input(
        "真题主题（封面展示，需忠于题源）",
        value=selected_paper.topic_cn or analysis.get("topic_keyword") or selected_paper.topic_keyword or _guess_topic(chinese_text),
    )
    topic_keyword = st.text_input(
        "背景素材搜索关键词",
        value=selected_paper.topic_keyword or topic_cn,
    )
    publish_topic = st.text_input(
        "发布文案主题（可编辑）",
        value=(
            analysis.get("publish_topic")
            or selected_paper.publish_topic
            or topic_cn
            or topic_keyword
        ),
        help="有人物时建议使用“人物--主题”，例如“袁隆平--杂交水稻”。",
    )
    if st.button("保存翻译和关键词", use_container_width=True):
        selected_paper.chinese_text = normalize_source_text(chinese_text)
        selected_paper.english_text = english_text.strip()
        selected_paper.topic_cn = topic_cn.strip()
        selected_paper.topic_keyword = topic_keyword.strip()
        selected_paper.publish_topic = publish_topic.strip()
        pdf_service.save_paper(selected_paper)
        st.success("翻译和关键词已保存。")

    if st.button("AI单独生成重点表达", use_container_width=True, disabled=not english_text.strip()):
        ai_service = _get_ai_service()
        with st.spinner("正在单独提取重点表达..."):
            generated_expressions = ai_service.extract_key_expressions(
                chinese_text.strip(),
                english_text.strip(),
                count=5
            )
        if generated_expressions:
            selected_paper.key_expressions = generated_expressions
            pdf_service.save_paper(selected_paper)
            _bump_key_expression_version(selected_paper.paper_id)
            st.success("重点表达已生成。")
            st.rerun()
        else:
            st.error("重点表达生成失败，请检查 LLM 配置，或先确认英文翻译内容。")

    expressions = _edit_key_expressions(selected_paper)
    if st.button("保存重点表达修改", use_container_width=True):
        selected_paper.key_expressions = expressions
        pdf_service.save_paper(selected_paper)
        st.success("重点表达已保存。")

    st.markdown("---")
    st.subheader("3. 英文朗读音频")
    current_ref = _env_value(
        "FISH_REFERENCE_ID",
        "FISH_CET_ZH_REFERENCE_ID",
        "FISH_DAILY_EN_REFERENCE_ID",
    )
    if current_ref:
        st.caption(f"当前 Fish Reference ID：{current_ref[:8]}...{current_ref[-6:]}")
    else:
        st.warning("当前没有读取到 Fish Reference ID，请检查 .env 中的 FISH_REFERENCE_ID。")

    raw_segments = realign_bilingual_segments(
        chinese_text,
        _subtitle_source_segments(analysis, selected_paper, chinese_text, english_text),
    )
    if st.button("生成/重新生成英文朗读", use_container_width=True, disabled=not english_text.strip()):
        audio_service = _get_audio_service(refresh=True)
        st.session_state.pop(f"audio_{selected_paper.paper_id}", None)
        with st.spinner("正在按字幕 cue 合成 Fish Audio，并按真实时长拼接音频..."):
            output = str(TEMP_DIR / f"english_audio_{selected_paper.paper_id}.wav")
            audio_path, durations, actual_segments = audio_service.generate_segmented_audio(raw_segments, output_path=output)
        if audio_path:
            subtitles = _build_subtitle_timeline(actual_segments, durations)
            selected_paper.subtitle_segments = subtitles
            selected_paper.english_text = english_text.strip()
            selected_paper.topic_cn = topic_cn.strip()
            selected_paper.topic_keyword = topic_keyword.strip()
            selected_paper.publish_topic = publish_topic.strip()
            pdf_service.save_paper(selected_paper)
            st.session_state[f"audio_{selected_paper.paper_id}"] = audio_path
            st.success("英文朗读音频已生成。")
        else:
            st.error("音频生成失败，请检查 FISH_API_KEY，以及 FISH_REFERENCE_ID / FISH_CET_ZH_REFERENCE_ID / FISH_DAILY_EN_REFERENCE_ID。")

    audio_path = st.session_state.get(f"audio_{selected_paper.paper_id}")
    if audio_path and any(english_word_count(segment.english) > 20 for segment in (selected_paper.subtitle_segments or [])):
        st.warning("检测到旧版长字幕时间轴。为避免字幕丢失，请点击上方按钮重新生成分段朗读。")
        audio_path = None
    if audio_path and os.path.exists(audio_path):
        st.audio(audio_path)
    elif selected_paper.subtitle_segments:
        st.info("已有字幕时间轴，但当前会话未记录音频路径。如需生成视频，请重新生成英文朗读。")

    st.markdown("---")
    st.subheader("4. 封面")
    cover_enabled = st.checkbox("生成视频时添加封面", value=True)
    selected_paper.topic_cn = topic_cn.strip()
    metadata = ExamMetadata.from_paper(selected_paper) if topic_cn.strip() else None
    if metadata:
        st.caption(f"{metadata.cover_kicker} / {metadata.cover_title} / {metadata.cover_subtitle}")
    cover_path = _single_image_background_selector(
        selected_paper,
        slot="cover",
        title="封面背景",
        default_keyword=topic_keyword or topic_cn,
        fallback_path=ASSET_COVER_BG,
    )
    if st.button("预览封面", use_container_width=True, disabled=metadata is None):
        from app.renderers.cover_renderer import CoverRenderer

        preview_path = str(TEMP_DIR / f"cover_preview_{selected_paper.paper_id}.jpg")
        CoverRenderer().render(preview_path, metadata, cover_path)
        st.image(preview_path, use_container_width=True)

    st.markdown("---")
    st.subheader("5. 背景素材")
    background_paths, background_type, orientation, background_timing = _background_selector(
        topic_keyword,
        selected_paper,
    )
    background_path = background_paths[0] if background_paths else None

    st.markdown("---")
    st.subheader("6. 重点表达页")
    keywords_bg_path = _single_image_background_selector(
        selected_paper,
        slot="keywords",
        title="重点表达页背景",
        default_keyword=topic_keyword or topic_cn,
        fallback_path=ASSET_KEYWORDS_BG,
    )
    if st.button("预览重点表达页", use_container_width=True, disabled=metadata is None):
        from app.renderers.keywords_renderer import KeywordsRenderer

        preview_path = str(TEMP_DIR / f"keywords_preview_{selected_paper.paper_id}.png")
        KeywordsRenderer().render(expressions, metadata, preview_path, keywords_bg_path)
        st.image(preview_path, use_container_width=True)

    st.markdown("---")
    st.subheader("7. 固定语音字幕")
    st.caption(
        "替换 exam_end.mp3 或 closing.mp3 后，生成视频时会按文件内容自动识别新字幕；"
        "也可以先点下面的按钮强制重新识别并检查结果。"
    )
    if st.button("重新识别固定语音字幕", use_container_width=True):
        from app.services.fixed_audio_subtitle_service import FixedAudioSubtitleService

        try:
            try:
                from moviepy.editor import AudioFileClip
            except ImportError:
                from moviepy import AudioFileClip

            service = FixedAudioSubtitleService()
            recognized_lines = []
            with st.spinner("正在用 Whisper 重新识别固定语音并生成新时间轴..."):
                for label, fixed_audio_path in [
                    ("考试结束", ASSET_ENDING_EXAM_AUDIO),
                    ("片尾", ASSET_CLOSING_AUDIO),
                ]:
                    if not fixed_audio_path.is_file():
                        continue
                    clip = AudioFileClip(str(fixed_audio_path))
                    try:
                        segments = service.segments_for(
                            fixed_audio_path,
                            float(clip.duration),
                            force=True,
                        )
                    finally:
                        clip.close()
                    recognized_lines.append(
                        f"{label}：" + " ".join(segment.chinese for segment in segments)
                    )
            if recognized_lines:
                st.success("固定语音字幕已重新识别；下次生成视频会直接使用这份结果。")
                for line in recognized_lines:
                    st.write(line)
            else:
                st.warning("没有找到可识别的固定语音文件。")
        except Exception as exc:
            st.error(f"固定语音字幕识别失败：{exc}")

    st.info(
        "动态开场使用 TTS 文案直接生成字幕和时间轴；更换 FISH_OPENING_REFERENCE_ID 或模型后，"
        "缓存键会变化并自动重建，不需要再做语音识别。第一套的套数只保留在题板图片中。"
    )

    st.markdown("---")
    st.subheader("8. 生成视频")
    opening_reference_id = _env_value("FISH_OPENING_REFERENCE_ID")
    if not opening_reference_id:
        st.warning("动态开场还缺少 .env 配置：FISH_OPENING_REFERENCE_ID")
    can_generate = bool(
        topic_cn.strip()
        and english_text.strip()
        and audio_path
        and background_paths
        and expressions
        and opening_reference_id
    )
    if not can_generate:
        missing = []
        if not topic_cn.strip():
            missing.append("已确认的真题主题")
        if not english_text.strip():
            missing.append("英文翻译")
        if not audio_path:
            missing.append("英文朗读音频")
        if not background_paths:
            missing.append("当前试卷背景素材")
        if not expressions:
            missing.append("重点表达")
        if not opening_reference_id:
            missing.append("动态开场音色 FISH_OPENING_REFERENCE_ID")
        st.warning("还缺少：" + "、".join(missing))

    if st.button("开始生成视频", use_container_width=True, disabled=not can_generate, type="primary"):
        from app.pipeline.video_pipeline import VideoPipeline

        selected_paper.chinese_text = normalize_source_text(chinese_text)
        selected_paper.english_text = english_text.strip()
        selected_paper.topic_cn = topic_cn.strip()
        selected_paper.topic_keyword = topic_keyword.strip()
        selected_paper.publish_topic = publish_topic.strip()
        selected_paper.key_expressions = expressions
        pdf_service.save_paper(selected_paper)

        config = VideoConfig(
            paper=selected_paper,
            background_type=background_type,
            background_orientation=orientation,
            background_path=background_path,
            background_paths=background_paths,
            background_min_clip_duration=background_timing["min"],
            background_target_clip_duration=background_timing["target"],
            background_max_clip_duration=background_timing["max"],
            background_cut_sensitivity=background_timing["sensitivity"],
            audio_path=audio_path,
            cover_enabled=cover_enabled,
            cover_path=cover_path,
            keywords_bg_path=keywords_bg_path,
            subtitle_segments=selected_paper.subtitle_segments or [],
            output_path=str(OUTPUT_DIR / f"{selected_paper.paper_id}.mp4"),
        )

        with st.spinner("正在生成视频，这可能需要几分钟..."):
            output_path = VideoPipeline().generate(config)

        if output_path:
            st.success("视频生成成功。")
            st.markdown("**可直接复制的发布文案**")
            st.code(selected_paper.publish_copy, language=None)
            st.markdown(f"输出路径：`{output_path}`")
            st.video(output_path)
            with open(output_path, "rb") as f:
                st.download_button("下载视频", data=f, file_name=os.path.basename(output_path), mime="video/mp4", use_container_width=True)
        else:
            st.error("视频生成失败，请查看终端日志。")


def _get_pdf_service() -> Any:
    if "pdf_service" not in st.session_state:
        from app.services.pdf_service import PDFService

        st.session_state.pdf_service = PDFService()
    return st.session_state.pdf_service


def _get_ai_service() -> Any:
    if "ai_service" not in st.session_state:
        from app.services.ai_service import AIService

        st.session_state.ai_service = AIService()
    return st.session_state.ai_service


def _get_audio_service(refresh: bool = False) -> Any:
    if refresh or "audio_service" not in st.session_state:
        from app.services.audio_service import FishAudioService

        st.session_state.audio_service = FishAudioService()
    return st.session_state.audio_service


def _get_pexels_service() -> Any:
    if "pexels_service" not in st.session_state:
        from app.services.pexels_service import PexelsService

        st.session_state.pexels_service = PexelsService()
    return st.session_state.pexels_service


def _env_value(*names: str) -> str:
    """重新读取 .env，让用户修改配置后无需重启整个 Streamlit 进程。"""
    from dotenv import load_dotenv

    load_dotenv(override=True)
    return next((os.getenv(name, "").strip() for name in names if os.getenv(name, "").strip()), "")


def _build_subtitle_timeline(segments: list[dict], durations: list[float]) -> list[dict]:
    """严格使用最终拼接 cue 的真实时长，保证字幕切换点与语音边界相同。"""
    if len(segments) != len(durations):
        raise ValueError("字幕 cue 数量与音频片段数量不一致")
    cursor = 0.0
    timeline = []
    for segment, duration in zip(segments, durations):
        end = cursor + max(0.001, float(duration))
        # 使用普通字典交给 ExamPaper 当前的验证器构造模型，兼容 Streamlit 热重载。
        timeline.append({
            "start": round(cursor, 3),
            "end": round(end, 3),
            "english": str(segment.get("english", "")).strip(),
            "chinese": str(segment.get("chinese", "")).strip(),
        })
        cursor = end
    return timeline


def _select_paper(cached_papers):
    options = [paper.display_name for paper in cached_papers]
    index = st.selectbox("选择真题", range(len(options)), format_func=lambda i: options[i])
    return cached_papers[index]


def _edit_key_expressions(paper):
    st.markdown("重点表达")
    expressions = list(paper.key_expressions or [])
    updated = []
    version = st.session_state.get(f"kw_version_{paper.paper_id}", 0)
    for i in range(5):
        expr = expressions[i] if i < len(expressions) else KeyExpression(word="", meaning="", example="")
        cols = st.columns([1.2, 1.2, 1.8])
        word = cols[0].text_input(f"{i + 1}. 英文", value=expr.word, key=f"kw_word_{paper.paper_id}_{version}_{i}")
        meaning = cols[1].text_input("中文释义", value=expr.meaning, key=f"kw_meaning_{paper.paper_id}_{version}_{i}")
        example = cols[2].text_input("例句/搭配", value=expr.example, key=f"kw_example_{paper.paper_id}_{version}_{i}")
        if word.strip() and meaning.strip():
            updated.append(KeyExpression(word=word.strip(), meaning=meaning.strip(), example=example.strip()))
    return updated


def _bump_key_expression_version(paper_id: str):
    key = f"kw_version_{paper_id}"
    st.session_state[key] = st.session_state.get(key, 0) + 1


def _subtitle_source_segments(analysis: dict, paper, chinese_text: str, english_text: str) -> list[dict]:
    """优先复用与当前译文一致的语义分段，避免刷新后重新按长度错切。"""
    current_english = " ".join(english_text.split())
    candidates = []
    if analysis.get("segments"):
        candidates.append(analysis["segments"])
    if paper.subtitle_segments:
        candidates.append([
            {"chinese": segment.chinese, "english": segment.english}
            for segment in paper.subtitle_segments
        ])

    for segments in candidates:
        joined = " ".join(
            " ".join(str(segment.get("english", "")).split())
            for segment in segments
        ).strip()
        if joined == current_english:
            return segments
    return [{"chinese": normalize_source_text(chinese_text), "english": current_english}]


def _background_selector(default_keyword: str, paper):
    mode = st.radio("背景来源", ["Pexels搜索", "本地上传"], horizontal=True)
    kind_label = st.radio("素材形式", ["图片", "视频"], index=1, horizontal=True)
    orientation_label = st.radio("筛选方向", ["竖屏", "横屏"], horizontal=True)
    kind = "photo" if kind_label == "图片" else "video"
    background_type = "image" if kind == "photo" else "video"
    orientation = "portrait" if orientation_label == "竖屏" else "landscape"
    material_dir = _paper_background_dir(paper, background_type, orientation)
    material_dir.mkdir(parents=True, exist_ok=True)

    timing_options = {
        "舒适（语义切换，约8-12秒）": {
            "min": 7.0,
            "target": 10.0,
            "max": 12.0,
            "sensitivity": "relaxed",
        },
        "均衡（语义切换，约4-10秒）": {
            "min": 4.0,
            "target": 7.0,
            "max": 10.0,
            "sensitivity": "standard",
        },
        "快速（语义切换，约2.5-7秒）": {
            "min": 2.5,
            "target": 4.0,
            "max": 7.0,
            "sensitivity": "fast",
        },
    }
    timing_label = st.radio(
        "素材切换节奏",
        list(timing_options),
        index=1,
        horizontal=True,
        key=f"bg_duration_{paper.paper_id}_{background_type}_{orientation}",
    )
    background_timing = timing_options[timing_label]

    st.caption(f"当前试卷素材文件夹：{material_dir}")

    if mode == "本地上传":
        types = ["jpg", "jpeg", "png"] if background_type == "image" else ["mp4", "mov", "avi"]
        uploads = st.file_uploader(
            "上传背景素材（可多选）",
            type=types,
            accept_multiple_files=True,
            key=f"background_upload_{paper.paper_id}_{background_type}_{orientation}",
        )
        if uploads:
            saved = _save_background_uploads(uploads, material_dir)
            if saved:
                st.success(f"已保存 {len(saved)} 个素材到当前试卷文件夹。")
    else:
        query = st.text_input("Pexels搜索关键词", value=default_keyword or "中国文化")
        per_page = st.slider("预览数量", min_value=20, max_value=60, value=30, step=10)

        if not _env_value("PEXELS_API_KEY"):
            st.warning("PEXELS_API_KEY 未配置，无法在线搜索。可以切换到本地上传。")
        else:
            search_key = f"pexels_{paper.paper_id}_{query}_{kind}_{orientation}_{per_page}"
            if st.button("搜索Pexels", use_container_width=True):
                pexels_service = _get_pexels_service()
                with st.spinner("正在搜索Pexels素材..."):
                    try:
                        assets = pexels_service.search(query, kind, orientation, per_page=per_page)
                        st.session_state[search_key] = [asset.model_dump(mode="json") for asset in assets]
                    except Exception as e:
                        st.error(f"Pexels搜索失败：{e}")

            assets = [PexelsAsset(**item) for item in st.session_state.get(search_key, [])]
            if assets:
                st.success(f"找到 {len(assets)} 个候选素材。")
                selected_assets = []
                columns_per_row = 3 if kind == "video" else 4
                for start in range(0, len(assets), columns_per_row):
                    row_assets = assets[start:start + columns_per_row]
                    for offset, (column, candidate) in enumerate(zip(st.columns(columns_per_row), row_assets), start=1):
                        with column:
                            st.caption(f"{start + offset}. {candidate.author or candidate.title or candidate.asset_id}")
                            if candidate.kind == "video":
                                if candidate.preview_url:
                                    st.video(candidate.preview_url, format="video/mp4")
                                st.caption(f"{candidate.duration:g}s · {candidate.width}×{candidate.height} · {candidate.fps:g}fps")
                            else:
                                if candidate.preview_url:
                                    st.image(candidate.preview_url, use_container_width=True)
                                st.caption(f"{candidate.width}×{candidate.height}")
                            if st.checkbox(
                                f"选择 Pexels {candidate.asset_id}",
                                key=f"choose_pexels_{search_key}_{candidate.asset_id}",
                            ):
                                selected_assets.append(candidate)

                if st.button(f"下载已选素材到当前试卷文件夹（{len(selected_assets)}）", use_container_width=True, disabled=not selected_assets):
                    pexels_service = _get_pexels_service()
                    with st.spinner("正在下载背景素材..."):
                        downloaded_paths = []
                        try:
                            progress = st.progress(0, text="准备下载...")
                            for index, asset in enumerate(selected_assets, start=1):
                                downloaded = pexels_service.download(asset, material_dir)
                                if downloaded and downloaded.local_path:
                                    downloaded_paths.append(downloaded.local_path)
                                progress.progress(index / len(selected_assets), text=f"{index}/{len(selected_assets)}")
                            if downloaded_paths:
                                st.success(f"已下载 {len(downloaded_paths)} 个素材到当前试卷文件夹。")
                        except Exception as e:
                            st.error(f"下载失败：{e}")

    available_paths = _list_background_assets(material_dir, background_type)
    if not available_paths:
        st.info("当前试卷的背景素材文件夹还是空的。请先搜索下载，或上传本地素材。")
        return [], background_type, orientation, background_timing

    selected_paths = [str(path) for path in available_paths]
    st.success(f"当前试卷素材库已有 {len(selected_paths)} 个可用素材。")
    st.info("生成时会从素材库自动挑选：优先使用未出现过的素材和未使用片段；素材不足时才重复利用。")

    with st.expander("预览当前素材库", expanded=False):
        for path_text in selected_paths[:6]:
            path = Path(path_text)
            st.caption(path.name)
            if background_type == "video":
                st.video(str(path))
            else:
                st.image(str(path), use_container_width=True)
        if len(selected_paths) > 6:
            st.caption(f"还有 {len(selected_paths) - 6} 个素材未展开预览。")

    return selected_paths, background_type, orientation, background_timing


def _single_image_background_selector(
    paper,
    slot: str,
    title: str,
    default_keyword: str,
    fallback_path: Path,
) -> str:
    """从 Pexels 搜索单张竖图，并覆盖当前试卷的固定背景文件。"""
    material_dir = _paper_single_image_dir(paper, slot)
    material_dir.mkdir(parents=True, exist_ok=True)
    target_path = material_dir / "background.jpg"
    active_path = target_path if target_path.exists() else Path(fallback_path)

    st.caption(f"当前试卷{title}文件夹：{material_dir}")
    if target_path.exists():
        st.success("当前试卷已有自定义背景；下载新图后会直接覆盖。")
        with st.expander(f"预览当前{title}", expanded=False):
            st.image(str(target_path), use_container_width=True)
    else:
        st.info("当前试卷还没有自定义背景，暂时使用默认图片。")

    query = st.text_input(
        f"{title} Pexels 搜索关键词",
        value=default_keyword or "中国文化",
        key=f"single_image_query_{paper.paper_id}_{slot}",
    )
    per_page = st.number_input(
        "预览数量",
        min_value=1,
        max_value=80,
        value=10,
        step=1,
        key=f"single_image_count_{paper.paper_id}_{slot}",
    )

    if not _env_value("PEXELS_API_KEY"):
        st.warning("PEXELS_API_KEY 未配置，无法在线搜索。")
        return str(active_path)

    results_key = f"single_image_results_{paper.paper_id}_{slot}"
    selection_key = f"single_image_selection_{paper.paper_id}_{slot}"
    if st.button(
        f"搜索{title}图片",
        use_container_width=True,
        key=f"single_image_search_{paper.paper_id}_{slot}",
    ):
        pexels_service = _get_pexels_service()
        with st.spinner(f"正在搜索{title}图片..."):
            try:
                assets = pexels_service.search(query.strip(), "photo", "portrait", per_page=int(per_page))
                st.session_state[results_key] = [asset.model_dump(mode="json") for asset in assets]
                st.session_state.pop(selection_key, None)
            except Exception as exc:
                st.error(f"Pexels 搜索失败：{exc}")

    assets = [PexelsAsset(**item) for item in st.session_state.get(results_key, [])]
    if not assets:
        return str(active_path)

    st.success(f"找到 {len(assets)} 张候选图片。")
    columns_per_row = 4
    for start in range(0, len(assets), columns_per_row):
        row_assets = assets[start:start + columns_per_row]
        for offset, (column, candidate) in enumerate(zip(st.columns(columns_per_row), row_assets), start=1):
            with column:
                if candidate.preview_url:
                    st.image(candidate.preview_url, use_container_width=True)
                st.caption(
                    f"{start + offset}. {candidate.author or candidate.title or candidate.asset_id}"
                    f" · {candidate.width}×{candidate.height}"
                )

    selected_index = st.radio(
        "选择一张要下载的图片",
        options=list(range(len(assets))),
        index=None,
        format_func=lambda index: (
            f"{index + 1}. "
            f"{assets[index].author or assets[index].title or assets[index].asset_id} "
            f"(Pexels {assets[index].asset_id})"
        ),
        key=selection_key,
    )
    if st.button(
        f"下载选中图片并替换{title}",
        use_container_width=True,
        disabled=selected_index is None,
        key=f"single_image_download_{paper.paper_id}_{slot}",
    ):
        pexels_service = _get_pexels_service()
        with st.spinner(f"正在下载并替换{title}..."):
            try:
                downloaded = pexels_service.download_single_image(
                    assets[selected_index],
                    material_dir,
                    filename=target_path.name,
                )
                if downloaded and downloaded.local_path:
                    active_path = Path(downloaded.local_path)
                    st.success(f"{title}已替换，文件夹内只保留 {target_path.name}。")
            except Exception as exc:
                st.error(f"图片下载失败：{exc}")

    return str(active_path)


def _paper_background_dir(paper, background_type: str, orientation: str) -> Path:
    return _paper_asset_dir(paper) / background_type / orientation


def _paper_single_image_dir(paper, slot: str) -> Path:
    folder_names = {"cover": "cover", "keywords": "keywords"}
    if slot not in folder_names:
        raise ValueError(f"不支持的单图背景类型：{slot}")
    return _paper_asset_dir(paper) / folder_names[slot]


def _paper_asset_dir(paper) -> Path:
    folder_name = _safe_folder_name(f"{paper.year}年{paper.month}月 {paper.exam_type} 第{paper.set_number}套")
    return BACKGROUNDS_DIR / "papers" / folder_name


def _safe_folder_name(value: str) -> str:
    forbidden = '<>:"/\\|?*'
    cleaned = "".join("_" if char in forbidden else char for char in value).strip()
    return cleaned or "未命名试卷"


def _list_background_assets(directory: Path, background_type: str) -> list[Path]:
    extensions = {".jpg", ".jpeg", ".png", ".webp"} if background_type == "image" else {".mp4", ".mov", ".avi"}
    if not directory.exists():
        return []
    return sorted(
        path for path in directory.iterdir()
        if path.is_file() and path.suffix.lower() in extensions
    )


def _save_background_uploads(uploaded_files, directory: Path) -> list[str]:
    directory.mkdir(parents=True, exist_ok=True)
    saved = []
    for uploaded_file in uploaded_files:
        safe_name = Path(uploaded_file.name).name
        target = _unique_path(directory / safe_name)
        with open(target, "wb") as handle:
            handle.write(uploaded_file.getbuffer())
        saved.append(str(target))
    return saved


def _unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    for index in range(2, 1000):
        candidate = path.with_name(f"{stem}_{index}{suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"无法生成不重复文件名：{path.name}")


def _guess_topic(text: str) -> str:
    for marker in ["餐桌礼仪", "传统文化", "春节", "教育", "旅游", "环保", "科技", "健康"]:
        if marker in text:
            return marker
    chinese = "".join(ch for ch in text if "\u4e00" <= ch <= "\u9fff")
    return chinese[:6] or "中国文化"
