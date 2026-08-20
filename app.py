"""
Streamlit主应用
"""
import streamlit as st
from pathlib import Path

# 配置页面
st.set_page_config(
    page_title="四六级汉译英短视频生成工具",
    page_icon="📹",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown(
    """
    <style>
    section[data-testid="stSidebar"] { min-width: 330px; }
    section[data-testid="stSidebar"] [data-testid="stSidebarContent"] { padding: 1.35rem 1.15rem; }
    section[data-testid="stSidebar"] h1 { font-size: 1.72rem; line-height: 1.35; margin-bottom: 1.15rem; }
    section[data-testid="stSidebar"] .stRadio > div { gap: 0.72rem; }
    section[data-testid="stSidebar"] .stRadio label {
        font-size: 1.08rem;
        line-height: 1.5;
        padding: 0.38rem 0.35rem;
    }
    section[data-testid="stSidebar"] hr { margin: 1.25rem 0 1.15rem; }
    </style>
    """,
    unsafe_allow_html=True,
)

# 侧边栏导航
st.sidebar.title("📹 CET视频生成器")
st.sidebar.markdown("---")

page = st.sidebar.radio(
    "导航",
    ["真题素材管理", "视频生成"],
    label_visibility="collapsed"
)

# 加载对应页面
if page == "真题素材管理":
    from app.ui.exam_manager import render_exam_manager
    render_exam_manager()
elif page == "视频生成":
    from app.ui.video_generator import render_video_generator
    render_video_generator()
