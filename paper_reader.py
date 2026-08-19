"""Paper Reader — 用 Gemini 幫你讀論文。

執行方式:
    export GEMINI_API_KEY="your-key"
    streamlit run paper_reader.py
"""

import io
import os
import time
from datetime import datetime

import streamlit as st
from google import genai
from google.genai import types
from google.genai.errors import APIError
from pydantic import BaseModel, Field

MODEL = "gemini-3.5-flash"
MAX_UPLOAD_MB = 50
FILE_ACTIVE_TIMEOUT_S = 120


# --------------------------------------------------------------------------- #
# 結構化輸出 schema
# --------------------------------------------------------------------------- #
class Finding(BaseModel):
    statement: str = Field(description="一句話描述這項發現")
    evidence: str = Field(description="支撐這項發現的數據、實驗或論證，盡量引用具體數字")


class PaperAnalysis(BaseModel):
    title: str = Field(description="論文標題（保留原文語言）")
    authors: list[str] = Field(description="作者名單，最多列出前 8 位")
    venue_year: str = Field(description="發表場合與年份，例如 'NeurIPS 2024'；不確定就填 '未標示'")
    tldr: str = Field(description="用一句話總結這篇論文的核心貢獻")
    keywords: list[str] = Field(description="3-8 個關鍵詞")
    summary: str = Field(description="論文摘要，200-400 字的繁體中文，涵蓋研究動機、問題定義與貢獻")
    methodology: str = Field(description="研究方法：資料集、模型/實驗設計、評估指標與流程，用繁體中文條列式說明")
    findings: list[Finding] = Field(description="3-6 項主要發現")
    limitations: list[str] = Field(description="論文的限制、假設或潛在弱點，3-5 點")
    future_work: list[str] = Field(description="未來研究方向，3-5 點，可包含論文明示與你的延伸建議")


SYSTEM_PROMPT = """你是一位嚴謹的學術研究助理，專長是快速拆解論文並向研究者說明重點。

規則：
- 只根據 PDF 內容作答，不要杜撰數字、引用或作者。
- 遇到 PDF 中找不到的資訊，明確寫「論文未說明」，不要猜測。
- 涉及實驗結果時，盡量引用論文中的具體數值與比較基準。
- 除了論文標題、專有名詞與縮寫維持原文外，一律使用繁體中文（台灣用語）。
"""

USER_PROMPT = """請完整閱讀這份 PDF 論文，並依照指定的 JSON schema 產生分析結果。

特別注意：
1. summary：說清楚「為什麼要做」「做了什麼」「結論是什麼」。
2. methodology：具體到資料集名稱、模型架構、超參數設定與評估指標。
3. findings：以實驗數據為依據，避免空泛敘述。
4. limitations 與 future_work：先寫論文自己承認的，再補上你從方法論角度觀察到的。
"""


# --------------------------------------------------------------------------- #
# Gemini 呼叫
# --------------------------------------------------------------------------- #
@st.cache_resource(show_spinner=False)
def get_client() -> genai.Client:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("找不到環境變數 GEMINI_API_KEY，請先設定再啟動 app。")
    return genai.Client(api_key=api_key)


def upload_pdf(client: genai.Client, data: bytes, display_name: str) -> types.File:
    """把 PDF 丟到 Gemini File API，並等到檔案處理完成（ACTIVE）。"""
    uploaded = client.files.upload(
        file=io.BytesIO(data),
        config=types.UploadFileConfig(
            mime_type="application/pdf",
            display_name=display_name,
        ),
    )

    deadline = time.time() + FILE_ACTIVE_TIMEOUT_S
    while uploaded.state and uploaded.state.name == "PROCESSING":
        if time.time() > deadline:
            raise TimeoutError("Gemini 處理這份 PDF 超過時間上限，請稍後再試或換一份較小的檔案。")
        time.sleep(2)
        uploaded = client.files.get(name=uploaded.name)

    if uploaded.state and uploaded.state.name == "FAILED":
        raise RuntimeError("Gemini File API 無法處理這份 PDF（可能是加密或損毀的檔案）。")
    return uploaded


def analyze(client: genai.Client, file: types.File, extra_instruction: str = "") -> tuple[PaperAnalysis, object]:
    prompt = USER_PROMPT
    if extra_instruction.strip():
        prompt += f"\n\n使用者額外要求（請一併納入分析）：\n{extra_instruction.strip()}"

    response = client.models.generate_content(
        model=MODEL,
        contents=[file, prompt],
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_schema=PaperAnalysis,
            temperature=0.2,
        ),
    )
    parsed = response.parsed
    if parsed is None:
        raise RuntimeError(f"模型沒有回傳合法的 JSON：\n{response.text}")
    return parsed, response.usage_metadata


# --------------------------------------------------------------------------- #
# 報告輸出
# --------------------------------------------------------------------------- #
def to_markdown(a: PaperAnalysis, source_name: str) -> str:
    lines = [
        f"# {a.title}",
        "",
        f"- **來源檔案**：{source_name}",
        f"- **作者**：{', '.join(a.authors) if a.authors else '未標示'}",
        f"- **發表**：{a.venue_year}",
        f"- **關鍵詞**：{', '.join(a.keywords)}",
        f"- **一句話總結**：{a.tldr}",
        f"- **分析時間**：{datetime.now():%Y-%m-%d %H:%M}（{MODEL}）",
        "",
        "## 論文摘要",
        a.summary,
        "",
        "## 研究方法",
        a.methodology,
        "",
        "## 主要發現",
    ]
    for i, f in enumerate(a.findings, 1):
        lines += [f"{i}. **{f.statement}**", f"   - 依據：{f.evidence}"]
    lines += ["", "## 限制"]
    lines += [f"- {x}" for x in a.limitations]
    lines += ["", "## 未來方向"]
    lines += [f"- {x}" for x in a.future_work]
    lines += ["", "---", "*由 Gemini 自動產生，請對照原文查核。*"]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# UI
# --------------------------------------------------------------------------- #
st.set_page_config(page_title="Paper Reader", page_icon="📄", layout="wide")

st.markdown(
    """
    <style>
      .block-container {padding-top: 2.5rem; max-width: 1100px;}
      .pr-hero h1 {margin-bottom: .2rem;}
      .pr-hero p {color: #6b7280; margin-top: 0;}
      .pr-card {
        border: 1px solid rgba(128,128,128,.25);
        border-radius: 12px; padding: 1rem 1.2rem; margin-bottom: .8rem;
        background: rgba(128,128,128,.06);
      }
      .pr-card .lead {font-weight: 600; margin-bottom: .35rem;}
      .pr-card .sub {color: #6b7280; font-size: .9rem;}
      .pr-tag {
        display: inline-block; padding: .15rem .6rem; margin: 0 .3rem .3rem 0;
        border-radius: 999px; font-size: .8rem;
        background: rgba(99,102,241,.15); color: inherit;
      }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    """
    <div class="pr-hero">
      <h1>📄 Paper Reader</h1>
      <p>上傳論文 PDF，讓 Gemini 幫你整理摘要、方法、發現與限制。</p>
    </div>
    """,
    unsafe_allow_html=True,
)

with st.sidebar:
    st.subheader("設定")
    st.caption(f"模型：`{MODEL}`")
    if os.environ.get("GEMINI_API_KEY"):
        st.success("已讀取 GEMINI_API_KEY", icon="🔑")
    else:
        st.error("未設定 GEMINI_API_KEY", icon="🔑")
        st.code("export GEMINI_API_KEY='your-key'", language="bash")

    extra = st.text_area(
        "額外指示（選填）",
        placeholder="例如：請特別比較與 Transformer baseline 的差異，並用工程實作角度評論。",
        height=110,
    )
    st.divider()
    st.caption(f"單檔上限 {MAX_UPLOAD_MB} MB。上傳的檔案存放在 Gemini File API，48 小時後自動刪除。")

uploaded_file = st.file_uploader("選擇一份 PDF 論文", type=["pdf"], label_visibility="collapsed")

col_run, col_info = st.columns([1, 3])
with col_run:
    run = st.button("開始分析", type="primary", use_container_width=True, disabled=uploaded_file is None)
with col_info:
    if uploaded_file is not None:
        size_mb = len(uploaded_file.getvalue()) / 1024 / 1024
        st.caption(f"已選擇：**{uploaded_file.name}**（{size_mb:.1f} MB）")

if run and uploaded_file is not None:
    data = uploaded_file.getvalue()
    if len(data) > MAX_UPLOAD_MB * 1024 * 1024:
        st.error(f"檔案超過 {MAX_UPLOAD_MB} MB 上限。")
    else:
        try:
            client = get_client()
            with st.status("分析中…", expanded=True) as status:
                st.write("上傳 PDF 到 Gemini File API…")
                gfile = upload_pdf(client, data, uploaded_file.name)
                st.write(f"檔案就緒：`{gfile.name}`，開始閱讀全文…")
                analysis, usage = analyze(client, gfile, extra)
                status.update(label="分析完成", state="complete", expanded=False)

            st.session_state["analysis"] = analysis
            st.session_state["source_name"] = uploaded_file.name
            st.session_state["usage"] = usage
        except (RuntimeError, TimeoutError) as e:
            st.error(str(e))
        except APIError as e:
            st.error(f"Gemini API 錯誤（{e.code}）：{e.message}")

analysis = st.session_state.get("analysis")

if analysis is not None:
    source_name = st.session_state.get("source_name", "paper.pdf")
    st.divider()

    st.markdown(f"### {analysis.title}")
    st.markdown(
        "".join(f'<span class="pr-tag">{k}</span>' for k in analysis.keywords),
        unsafe_allow_html=True,
    )
    st.info(f"**TL;DR** — {analysis.tldr}")

    m1, m2, m3 = st.columns(3)
    m1.metric("作者", f"{len(analysis.authors)} 位", help=", ".join(analysis.authors) or "未標示")
    m2.metric("發表", analysis.venue_year)
    m3.metric("主要發現", f"{len(analysis.findings)} 項")

    tab_sum, tab_method, tab_find, tab_limit = st.tabs(
        ["📝 論文摘要", "🔬 研究方法", "💡 主要發現", "⚠️ 限制與未來方向"]
    )

    with tab_sum:
        st.markdown(analysis.summary)
        if analysis.authors:
            with st.expander("作者名單"):
                st.markdown("\n".join(f"- {a}" for a in analysis.authors))

    with tab_method:
        st.markdown(analysis.methodology)

    with tab_find:
        for i, f in enumerate(analysis.findings, 1):
            st.markdown(
                f'<div class="pr-card"><div class="lead">{i}. {f.statement}</div>'
                f'<div class="sub">依據：{f.evidence}</div></div>',
                unsafe_allow_html=True,
            )

    with tab_limit:
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("#### ⚠️ 限制")
            for x in analysis.limitations:
                st.markdown(f"- {x}")
        with c2:
            st.markdown("#### 🚀 未來方向")
            for x in analysis.future_work:
                st.markdown(f"- {x}")

    st.divider()
    report = to_markdown(analysis, source_name)
    dl, meta = st.columns([1, 3])
    with dl:
        st.download_button(
            "下載 Markdown 報告",
            data=report,
            file_name=f"{os.path.splitext(source_name)[0]}_analysis.md",
            mime="text/markdown",
            use_container_width=True,
        )
    with meta:
        usage = st.session_state.get("usage")
        if usage is not None:
            st.caption(
                f"Token 使用量：prompt {usage.prompt_token_count}，"
                f"output {usage.candidates_token_count}，"
                f"總計 {usage.total_token_count}"
            )
    st.caption("結果由 LLM 生成，引用前請對照原文查核。")
