# 四六级汉译英短视频生成工具

一个用于自动生成四六级英语翻译题短视频的工具，支持真题管理、AI翻译、语音合成和视频生成。

## 静态布局预览

无需调用 AI、TTS 或编码完整视频：

```bash
python preview_layout.py --page cover
python preview_layout.py --page question
python preview_layout.py --page keywords
python preview_layout.py --page subtitle
python preview_layout.py --page all --case B --output-dir data/output/previews/case_b
```

默认输出目录为 `data/output/previews`。`--case A/B/C` 分别用于四级 2026 年 6 月、四级 2024 年 12 月和六级动态 metadata 验证；这些值仅存在于预览 fixture，renderer 不包含具体真题硬编码。

## ✨ 功能特性

### 📚 真题素材管理
- 上传 PDF 并自动解析四六级翻译真题
- 支持手动添加和编辑真题
- 本地缓存管理

### 🎬 视频生成
- **中文题板展示**：动态渲染考试题目
- **倒计时动画**：3-2-1倒计时效果
- **英文朗读**：使用Fish Audio生成地道英文朗读
- **同步字幕**：英文字幕与朗读同步显示
- **重点表达板**：自动提取并展示关键词汇
- **发布文案**：生成视频后提供“年份 + 等级 + 套数 + 主题”的一键复制文案
- **完整音频流程**：开场、考试提示、结束语音

### 🤖 AI增强
- AI自动翻译中文原文
- AI自动提取重点表达
- 支持手动编辑和调整

## 📋 项目结构

```
yyyCETVideo/
├── app.py                      # Streamlit主应用
├── .env.example                # 环境变量模板
├── requirements.txt            # Python依赖
├── README.md                   # 项目说明
├── data/                       # 数据目录
│   ├── assets/                 # 程序使用的图片、音频和音效
│   ├── backgrounds/            # 正文背景素材
│   ├── cache/                  # 真题缓存
│   ├── pdfs/                   # 上传的真题 PDF
│   ├── output/                 # 视频输出目录
│   └── temp/                   # 临时文件
├── app/
│   ├── config.py               # 配置管理
│   ├── models.py               # 数据模型
│   ├── ui/                     # Streamlit页面
│   │   ├── exam_manager.py    # 真题管理页面
│   │   └── video_generator.py # 视频生成页面
│   ├── services/               # 服务层
│   │   ├── pdf_service.py     # PDF解析和真题缓存
│   │   ├── audio_service.py   # Fish Audio语音合成
│   │   └── ai_service.py      # AI翻译和关键词提取
│   ├── renderers/              # 渲染器
│   │   ├── question_renderer.py  # 题板渲染
│   │   └── keywords_renderer.py  # 重点表达渲染
│   ├── pipeline/               # 视频生成管道
│   │   └── video_pipeline.py  # 视频合成流程
│   └── utils/                  # 工具函数
└── logs/                       # 日志目录
```

## 🚀 快速开始

### 1. 环境准备

确保你已经激活了虚拟环境：

```powershell
# 激活虚拟环境
conda activate my_video
```

### 2. 安装依赖

```powershell
pip install -r requirements.txt
```

### 3. 配置环境变量

复制环境变量模板，并按需填写 API 配置：

```powershell
Copy-Item .env.example .env
```

```env
# Fish Audio配置
FISH_API_KEY=your_api_key_here
# 正文英文翻译朗读音色
FISH_REFERENCE_ID=your_english_translation_reference_id
# 动态开场中文播报音色（独立于正文音色）
FISH_OPENING_REFERENCE_ID=your_opening_reference_id

# Anthropic AI配置（可选，用于AI翻译和关键词提取）
ANTHROPIC_API_KEY=your_api_key_here
```

### 4. 准备素材文件

默认素材已放在 `data/assets/`，各试卷的背景素材保存在 `data/backgrounds/papers/`。封面和重点表达页可在界面中搜索 Pexels 图片，选中后会覆盖当前试卷对应目录中的 `background.jpg`。

### 5. 运行应用

```powershell
streamlit run app.py
```

访问 `http://localhost:8501` 即可使用。

## 📖 使用流程

### 步骤1：真题素材管理
1. 选择本地真题 PDF
2. 确认系统从文件名识别的考试类型、年份、月份和套数
3. 点击“上传并自动解析”，系统会提取翻译部分的中文原文
4. 也可以手动添加、编辑或删除真题内容

### 步骤2：视频生成
1. **选择题目**：从已缓存的真题中选择一套
2. **英文翻译**：手动输入或使用AI自动翻译
3. **生成朗读**：使用Fish Audio生成英文朗读音频
4. **选择封面**：在 Pexels 搜索竖版图片，单选一张下载并覆盖当前封面
5. **选择正文背景**：搜索下载或上传图片/视频，默认使用视频素材
6. **重点表达**：手动添加或 AI 自动提取，并在 Pexels 搜索单张页面背景
7. **生成视频**：点击按钮生成完整短视频，并直接复制自动组合的发布文案

## 🎥 视频结构

生成的视频按以下时间线组织：

1. **0.2 秒封面**（可在 `app/config.py` 修改 `COVER_DURATION_SECONDS`）
2. **中文题板** + 按真实年月/四或六级动态生成的开场语音（两句间隔 0.4 秒）
3. **倒计时** (3-2-1，带音效)
4. **考试结束提示**
5. **正文内容** (背景 + 英文朗读 + 同步字幕，完整句末停顿约 0.3 秒)
6. **重点表达页** + 柔和完成提示音 + 结束语音

## 固定语音字幕重新识别

- `data/assets/audio/exam_end.mp3` 和 `closing.mp3` 的字幕清单保存在同目录的 `subtitles.json`。
- 程序按音频内容的 SHA-256 判断文件是否被替换。文件未变时直接使用人工审校的中英字幕；文件变化时使用 faster-whisper 重新识别并缓存新的字幕时间轴，不会继续套用旧字幕。
- 也可以在【视频生成 → 固定语音字幕】点击“重新识别固定语音字幕”，强制刷新并先检查识别结果。
- 动态开场的语音、字幕来自同一份 TTS 文案，更换 `FISH_OPENING_REFERENCE_ID` 或 `FISH_TTS_MODEL` 后会自动生成新的音频与时长缓存，无需 Whisper。第一套的套数仅显示在题板图片中，不再朗读。

## 🛠️ 技术栈

- **前端界面**: Streamlit
- **视频处理**: MoviePy
- **图像处理**: Pillow (PIL)
- **PDF解析**: PyMuPDF (fitz)
- **语音合成**: Fish Audio API
- **AI翻译**: Anthropic Claude API
- **HTTP请求**: requests

## 📝 注意事项

1. **虚拟环境**：必须使用 `my_video` 虚拟环境
2. **字体支持**：确保系统安装了中文字体（如微软雅黑、思源黑体）
3. **素材文件**：必须提前准备好音频和背景图素材
4. **API配置**：需要有效的Fish Audio和Anthropic API密钥
5. **视频输出**：默认输出到 `data/output/` 目录

## 🔄 开发优先级

### ✅ 第一阶段（已完成）
- [x] 项目结构搭建
- [x] 基本配置管理
- [x] 数据模型定义
- [x] 真题管理页面
- [x] 视频生成页面
- [x] PDF解析服务
- [x] Fish Audio集成
- [x] AI翻译和关键词提取
- [x] 题板和重点表达渲染
- [x] 视频生成管道

### 🚧 第二阶段（待开发）
- [x] Pexels图片/视频搜索集成
- [ ] 更精准的字幕时间轴（基于音频分析）
- [ ] 自定义音效（倒计时、转场）
- [ ] 视频转场效果优化
- [ ] 批量生成功能
- [ ] 视频预览功能
- [ ] 更多渲染样式选项

## 🤝 贡献

欢迎提出建议和改进意见！

## 📄 许可

MIT License
