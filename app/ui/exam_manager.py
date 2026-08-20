"""真题素材管理页面。"""
from datetime import datetime

import streamlit as st

from app.models import ExamPaper
from app.services.pdf_service import PDFService


EXAM_TYPES = ["CET-4", "CET-6"]
EXAM_MONTHS = [6, 12]
MIN_EXAM_YEAR = 2010


def render_exam_manager():
    """渲染真题素材管理页面。"""
    st.title("📚 真题素材管理")
    st.caption("上传 PDF 自动解析翻译题，或手动录入真题内容")
    st.markdown("---")

    pdf_service = _get_pdf_service()
    _render_pdf_upload(pdf_service)

    st.markdown("---")
    _render_manual_add(pdf_service)

    st.markdown("---")
    _render_saved_papers(pdf_service)


def _get_pdf_service() -> PDFService:
    if "pdf_service" not in st.session_state:
        st.session_state.pdf_service = PDFService()
    return st.session_state.pdf_service


def _render_pdf_upload(pdf_service: PDFService) -> None:
    st.subheader("📤 上传 PDF 并自动解析")
    st.caption("系统会从 PDF 中自动提取 Part IV Translation 的中文原文。")

    uploaded_file = st.file_uploader(
        "选择一份真题 PDF",
        type=["pdf"],
        help="支持四六级真题 PDF；推荐保留包含年份、月份、级别和套数的原文件名。",
        key="exam_pdf_uploader",
    )

    filename_metadata = None
    if uploaded_file is not None:
        filename_metadata = pdf_service.parse_filename(uploaded_file.name)
        if filename_metadata:
            st.success(
                "已从文件名识别："
                f"{filename_metadata['exam_type']} · "
                f"{filename_metadata['year']}年{filename_metadata['month']}月 · "
                f"第{filename_metadata['set_number']}套"
            )
        else:
            st.info("未能从文件名识别试卷信息，请在下方确认后开始解析。")

    defaults = filename_metadata or {
        "exam_type": "CET-4",
        "year": datetime.now().year,
        "month": 6,
        "set_number": 1,
    }
    upload_key = _upload_widget_key(uploaded_file)

    with st.form("upload_pdf_form"):
        col_exam, col_year, col_month, col_set = st.columns(4)
        with col_exam:
            exam_type = st.selectbox(
                "考试类型",
                EXAM_TYPES,
                index=EXAM_TYPES.index(defaults["exam_type"]),
                key=f"upload_exam_{upload_key}",
            )
        with col_year:
            year = st.number_input(
                "年份",
                min_value=MIN_EXAM_YEAR,
                max_value=datetime.now().year + 1,
                value=int(defaults["year"]),
                step=1,
                key=f"upload_year_{upload_key}",
            )
        with col_month:
            month = st.selectbox(
                "月份",
                EXAM_MONTHS,
                index=EXAM_MONTHS.index(defaults["month"]),
                key=f"upload_month_{upload_key}",
            )
        with col_set:
            set_number = st.number_input(
                "套数",
                min_value=1,
                max_value=3,
                value=int(defaults["set_number"]),
                step=1,
                key=f"upload_set_{upload_key}",
            )

        submitted = st.form_submit_button(
            "上传并自动解析",
            type="primary",
            use_container_width=True,
        )

    if not submitted:
        return
    if uploaded_file is None:
        st.error("请先选择 PDF 文件。")
        return

    with st.spinner("正在解析 PDF 中的翻译题……"):
        paper = pdf_service.parse_uploaded_pdf(
            uploaded_file,
            exam_type=exam_type,
            year=int(year),
            month=int(month),
            set_number=int(set_number),
        )

    if paper:
        st.success(f"解析成功，已保存：{paper.display_name}")
    else:
        st.error("解析失败。请确认 PDF 包含可复制的 Part IV Translation 内容，或使用手动添加。")


def _upload_widget_key(uploaded_file) -> str:
    if uploaded_file is None:
        return "empty"
    return f"{uploaded_file.name}_{uploaded_file.size}"


def _render_manual_add(pdf_service: PDFService) -> None:
    st.subheader("➕ 手动添加真题")

    with st.expander("手动输入真题内容", expanded=False):
        with st.form("manual_add_form"):
            col_exam, col_year, col_month, col_set = st.columns(4)
            with col_exam:
                exam_type = st.selectbox("考试类型", EXAM_TYPES, key="manual_exam")
            with col_year:
                year = st.number_input(
                    "年份",
                    min_value=MIN_EXAM_YEAR,
                    max_value=datetime.now().year + 1,
                    value=datetime.now().year,
                    step=1,
                    key="manual_year",
                )
            with col_month:
                month = st.selectbox("月份", EXAM_MONTHS, key="manual_month")
            with col_set:
                set_number = st.number_input(
                    "套数", min_value=1, max_value=3, value=1, step=1, key="manual_set"
                )

            chinese_text = st.text_area(
                "中文原文",
                height=180,
                placeholder="请输入翻译题的中文原文……",
            )
            submitted = st.form_submit_button("保存真题", use_container_width=True)

        if submitted:
            if not chinese_text.strip():
                st.error("请输入中文原文。")
            else:
                paper = ExamPaper(
                    exam_type=exam_type,
                    year=int(year),
                    month=int(month),
                    set_number=int(set_number),
                    chinese_text=chinese_text,
                )
                pdf_service.save_paper(paper)
                st.success(f"已保存：{paper.display_name}")


def _render_saved_papers(pdf_service: PDFService) -> None:
    st.subheader("📂 已保存真题")
    papers = pdf_service.list_cached_papers()

    if not papers:
        st.info("暂无真题，请上传 PDF 或手动添加。")
        return

    st.caption(f"共 {len(papers)} 套，可直接修改原文或删除。")
    for paper in papers:
        with st.expander(f"📄 {paper.display_name}", expanded=False):
            with st.form(f"edit_form_{paper.paper_id}"):
                chinese_text = st.text_area(
                    "中文原文",
                    value=paper.chinese_text,
                    height=180,
                )
                if st.form_submit_button("保存修改", use_container_width=True):
                    if not chinese_text.strip():
                        st.error("中文原文不能为空。")
                    else:
                        paper.chinese_text = chinese_text
                        pdf_service.save_paper(paper)
                        st.success("修改已保存。")

            if st.button(
                "删除这套真题",
                key=f"delete_{paper.paper_id}",
                use_container_width=True,
            ):
                pdf_service.delete_paper(paper.paper_id)
                st.rerun()
