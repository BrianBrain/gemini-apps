# 📄 Paper Reader

上傳一份論文 PDF，讓 Gemini 幫你整理出**摘要、研究方法、主要發現、限制與未來方向**，並可下載成 Markdown 報告。

用 [Streamlit](https://streamlit.io/) + [google-genai SDK](https://googleapis.github.io/python-genai/) 寫成，模型為 `gemini-3.5-flash`。

---

## 功能

- **PDF 直接上傳** — 透過 Gemini File API 處理，整份論文（含圖表、公式排版）交給模型閱讀，不需自己做 PDF 文字擷取。
- **結構化分析** — 用 pydantic schema 強制模型回傳固定欄位，四大區塊保證存在，不靠解析自由文字。
- **有依據的發現** — 每項「主要發現」都拆成「結論 + 支撐數據」，要求引用論文中的具體數值與比較基準。
- **可自訂視角** — 側邊欄的「額外指示」可以追加要求，例如「請用工程實作角度評論」或「特別比較與 Transformer baseline 的差異」。
- **一鍵匯出** — 下載完整的 Markdown 報告，並顯示本次 token 使用量。

## 安裝

```bash
git clone git@github.com:BrianBrain/gemini-apps.git
cd gemini-apps
pip install -r requirements.txt
```

## 設定 API Key

到 [Google AI Studio](https://aistudio.google.com/apikey) 取得金鑰，然後設定環境變數：

```bash
export GEMINI_API_KEY="your-api-key"
```

想寫進 `.env` 也可以，該檔案已列在 `.gitignore`，不會被 commit。

## 執行

```bash
streamlit run paper_reader.py
```

瀏覽器開啟 <http://localhost:8501>，上傳 PDF 後按「開始分析」即可。

## 運作流程

```
PDF 上傳 (Streamlit)
   └─> client.files.upload()        把 bytes 直接送進 Gemini File API（不落地暫存檔）
        └─> 輪詢 files.get()         等待狀態從 PROCESSING 變成 ACTIVE
             └─> generate_content()  帶 response_schema=PaperAnalysis 取得結構化 JSON
                  └─> Streamlit UI   四個分頁 + Markdown 報告下載
```

分析結果由 `PaperAnalysis` 這個 pydantic model 定義：

| 欄位 | 說明 |
| --- | --- |
| `title` / `authors` / `venue_year` | 書目資訊 |
| `tldr` / `keywords` | 一句話總結與關鍵詞 |
| `summary` | 論文摘要（研究動機、問題定義、貢獻） |
| `methodology` | 資料集、模型架構、超參數、評估指標 |
| `findings` | 主要發現，每項含 `statement` 與 `evidence` |
| `limitations` / `future_work` | 限制與未來方向 |

## 專案結構

```
paper_reader.py     主程式（schema、Gemini 呼叫、Streamlit UI）
requirements.txt    相依套件
```

## 可調整的參數

`paper_reader.py` 開頭：

| 常數 | 預設 | 說明 |
| --- | --- | --- |
| `MODEL` | `gemini-3.5-flash` | 換成其他 Gemini 模型 |
| `MAX_UPLOAD_MB` | `50` | 單檔上限；太大的 PDF 分析會明顯變慢 |
| `FILE_ACTIVE_TIMEOUT_S` | `120` | 等待 File API 處理完成的秒數上限 |

生成溫度設為 `0.2`，system prompt 要求模型只依 PDF 內容作答、找不到的資訊要明寫「論文未說明」，以壓低幻覺。

## 注意事項

- 上傳的檔案存放在 Gemini File API，**48 小時後自動刪除**。
- 分析結果由 LLM 生成，**引用前請務必對照原文查核**。
- 每次分析都會消耗 token，長論文的 prompt token 數量可觀，費用請參考 [Gemini API pricing](https://ai.google.dev/pricing)。
- 加密或損毀的 PDF 會被 File API 拒絕，程式會顯示對應錯誤訊息。
