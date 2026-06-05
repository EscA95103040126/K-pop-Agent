# K-pop Agent LINE Bot 架構說明

## 1. 系統目標

這是一個 K-pop 市場分析 LINE Bot。

使用者透過 LINE 傳送固定指令，例如：

- `分析 aespa`
- `分析 IVE`
- `本週榜單`

Bot 會回覆：

- 藝人市場分析報告
- Bugs 本週榜單
- 粉絲留言情緒分析
- 預先生成的市場洞察 insight

目前不開放自由問答，避免回覆不穩定。

---

## 2. 主要技術棧

- Python
- Flask
- LINE Messaging API
- Gemini API
- Naver News API
- YouTube Data API
- KcELECTRA offline ABSA
- SQLite
- CSV
- JSON cache
- Bugs Chart crawler/parser

---

## 3. 核心資料來源

### 3.1 Bugs Chart

用途：

- 取得本週 Bugs K-pop 榜單
- 寫入 SQLite `data/chart_history.db`
- 用於榜單表現分析

主要檔案：

- `src/tools/bugs_chart.py`
- `src/tools/chart_db.py`
- `scripts/fetch_bugs_chart.py`
- `scripts/preload_chart.py`

資料表：

```text
chart_history
```

主要欄位：

```text
fetch_date
chart_date
source
chart_type
rank
title
artist
album
change_rank
```

---

### 3.2 Naver News API

用途：

- 查詢藝人近期新聞
- 取得新聞事件脈絡
- 若 API 失敗，會 fallback 到 mock data

主要檔案：

```text
src/tools/naver_news.py
data/mock/naver_*.json
```

---

### 3.3 YouTube Data API

用途：

- 抓取 10 位支援藝人的韓文留言
- 每位藝人 20 則留言
- 覆蓋 `data/sample_comments.csv`

主要檔案：

```text
scripts/fetch_youtube_comments.py
data/sample_comments.csv
```

支援藝人：

```text
aespa
IVE
BABYMONSTER
NMIXX
ILLIT
NCT
ZEROBASEONE
TXT
ENHYPEN
BOYNEXTDOOR
```

CSV 欄位：

```text
artist
song
comment
sentiment
```

---

### 3.4 Offline ABSA / KcELECTRA

用途：

- 在離線批次階段抓取 Naver News 與 YouTube 韓文留言
- 使用 KcELECTRA sentiment/ABSA model 對韓文新聞與留言做面向式情感分析
- 預先輸出本地 JSON / CSV，供 LINE Bot 低延遲讀取
- webhook 不即時跑 KcELECTRA，也不即時大量呼叫 YouTube API

主要檔案：

```text
src/tools/absa.py
scripts/build_absa_cache.py
data/cache/absa/{artist}.json
data/cache/absa/summary.csv
```

支援 ABSA 面向：

```text
song / music
performance
visual / styling
vocal / rap
fandom / public_opinion
```

JSON schema 至少包含：

```json
{
  "artist": "aespa",
  "generated_at": "...",
  "sources": {},
  "aspect_sentiment": {},
  "overall_sentiment": {},
  "top_comments_or_evidence": [],
  "naver_news_summary": [],
  "report_text": "..."
}
```

批次命令：

```bash
python3 scripts/build_absa_cache.py
```

若本機沒有大型模型依賴，可先用 sample comments 產生測試用 cache：

```bash
python3 scripts/build_absa_cache.py --no-model --use-sample-comments
```

---

### 3.5 Gemini API

用途：

1. 生成每位藝人的市場洞察 insight
2. 支援 AI 入坑與推薦理由文字
3. 在 cache 預生成階段使用，不在每次 LINE 訊息即時大量呼叫

主要檔案：

```text
src/tools/sentiment.py
scripts/label_sentiments.py
src/agent.py
```

情感分類標籤：

```text
positive
neutral
negative
```

Insight JSON 格式：

```json
{
  "headline": "一句話市場觀察",
  "risk": "高/中/低",
  "opportunity": "一句話機會點"
}
```

---

## 4. 快取系統

### 4.1 ABSA Cache

每位支援藝人會先生成一份離線 ABSA cache。

位置：

```text
data/cache/absa/{artist}.json
```

例如：

```text
data/cache/absa/aespa.json
data/cache/absa/ive.json
data/cache/absa/nct.json
```

用途：

- LINE Bot 收到 `分析 藝人名` 時優先讀取
- 降低 webhook 延遲
- 避免即時跑 KcELECTRA / Transformers
- 避免即時大量呼叫 YouTube Data API
- 若檔案不存在或 schema 無效，回到 Artist Cache fallback

---

### 4.2 Artist Cache

每位藝人會生成一份本地 JSON cache。

位置：

```text
data/cache/artists/{artist}.json
```

例如：

```text
data/cache/artists/aespa.json
data/cache/artists/ive.json
data/cache/artists/nct.json
```

生成腳本：

```bash
python3 scripts/preload_cache.py
```

每份 artist cache 包含：

```json
{
  "cached_at": "...",
  "artist": "aespa",
  "period_months": 3,
  "report": "...",
  "insight": {
    "headline": "...",
    "risk": "低",
    "opportunity": "..."
  },
  "flex": {
    "...": "LINE Flex Message JSON"
  },
  "sources": {
    "chart": {},
    "news": [],
    "sentiment": {}
  }
}
```

用途：

- ABSA cache 缺失時的既有 fallback
- 避免每次訊息都即時呼叫 Gemini / Naver / YouTube
- 提升回覆速度與穩定性

---

### 4.3 Weekly Chart Cache

位置：

```text
data/cache/chart/weekly.json
```

用途：

- 快取本週 Bugs 榜單報告
- LINE Bot 收到 `本週榜單` 時直接回覆

主要檔案：

```text
src/agent.py
scripts/preload_chart.py
```

---

## 5. LINE Bot 請求流程

### 5.1 使用者輸入 `分析 aespa`

流程：

```text
LINE 使用者
  ↓
LINE Messaging API
  ↓
Flask /webhook
  ↓
app.py handle_text_message()
  ↓
route_message()
  ↓
判斷為 artist analysis
  ↓
KpopAnalysisAgent.get_artist_analysis_cache("aespa")
  ↓
優先讀取 data/cache/absa/aespa.json
  ↓
若 ABSA cache 不存在，fallback 到 data/cache/artists/aespa.json
  ↓
取得 flex JSON
  ↓
LINE Flex Message 回覆
```

回覆內容包含：

- 榜單表現
- 粉絲與輿論反應
- 綜合判斷
- 市場洞察 insight
- 一句話總結

---

### 5.2 使用者輸入 `本週榜單`

流程：

```text
LINE 使用者
  ↓
LINE Messaging API
  ↓
Flask /webhook
  ↓
route_message()
  ↓
判斷為 weekly_chart
  ↓
KpopAnalysisAgent.get_weekly_chart_cache()
  ↓
讀取 data/cache/chart/weekly.json
  ↓
Text Message 回覆榜單
```

---

### 5.3 使用者輸入非固定指令

例如：

```text
目前輿論風險最低的是誰？
NCT 輿論風險高嗎？
今天天氣如何？
```

目前不走自由問答。

Bot 會回覆固定指令提示：

```text
目前支援固定指令：
1. 分析 aespa
2. 分析 IVE
3. 本週榜單

請用「分析 藝人名」取得完整報告。
```

---

## 6. Flask API Routes

主要入口：

```text
GET  /health
POST /analyze
POST /webhook
```

### 6.1 `/health`

用途：

- 檢查 SQLite
- 檢查 Bugs tool
- 顯示 Naver / Gemini / LINE 是 real 或 mock mode

---

### 6.2 `/analyze`

用途：

- 本地測試分析功能
- 接收 JSON：

```json
{
  "message": "分析 aespa"
}
```

或：

```json
{
  "artist": "aespa"
}
```

回傳：

```json
{
  "report": "...",
  "cache": {},
  "flex": {}
}
```

---

### 6.3 `/webhook`

用途：

- LINE Developers webhook endpoint
- 接收 LINE Messaging API event
- 驗證 LINE signature
- 回覆 TextMessage 或 FlexMessage

---

## 7. 主要程式模組

### 7.1 `app.py`

職責：

- Flask app
- LINE webhook
- LINE Flex Message 回覆
- 指令分流
- `/health`
- `/analyze`

---

### 7.2 `src/router.py`

職責：

- 解析使用者訊息
- 判斷 intent
- 解析藝人名稱
- 判斷是否為本週榜單

Intent 類型：

```text
weekly_chart
artist_analysis
artist_sentiment_context
artist_market_analysis
```

---

### 7.3 `src/agent.py`

核心 Agent。

職責：

- 統整 chart / news / sentiment
- 生成本地分析報告
- 生成 LINE Flex Message
- 生成 artist cache
- 生成 weekly chart cache
- 生成 insight
- fallback mock / local summary

核心 class：

```python
KpopAnalysisAgent
```

重要方法：

```python
analyze_message()
analyze_message_local()
get_artist_cache()
preload_artist_cache()
get_weekly_chart_cache()
preload_weekly_chart_cache()
build_flex_message()
```

---

### 7.4 `src/tools/chart_db.py`

職責：

- SQLite chart history repository
- 寫入 Bugs chart rows
- 查詢藝人榜單表現
- 查詢本週榜單

重要邏輯：

- 如果只有單週資料，不顯示「最近 12 週趨勢」
- 單週多首歌時，視為「本週上榜歌曲數」
- 多週資料時，每週取最高排名來算趨勢

---

### 7.5 `src/tools/sentiment.py`

職責：

- 載入 `data/sample_comments.csv`
- 分析藝人留言情緒
- 優先讀取 CSV 裡的 `sentiment` 欄位
- 如果沒有 sentiment 欄位，才 fallback 即時 Gemini 分類

輸出：

```json
{
  "artist": "aespa",
  "total_comments": 20,
  "sentiment": {
    "positive": 0.55,
    "neutral": 0.45,
    "negative": 0.0
  },
  "top_keywords": [],
  "summary": "整體評論偏正面。"
}
```

---

## 8. 預處理 / 更新流程

### 8.1 抓 Bugs 榜單

```bash
python3 scripts/fetch_bugs_chart.py
```

寫入：

```text
data/chart_history.db
```

---

### 8.2 抓 YouTube 留言

```bash
python3 scripts/fetch_youtube_comments.py
```

輸出：

```text
data/sample_comments.csv
```

---

### 8.3 標註留言情感

```bash
python3 scripts/label_sentiments.py
```

會呼叫 Gemini，將結果寫入：

```text
data/sample_comments.csv
```

新增欄位：

```text
sentiment
```

---

### 8.4 生成 artist cache

```bash
python3 scripts/preload_cache.py
```

輸出：

```text
data/cache/artists/*.json
```

---

### 8.5 生成 weekly chart cache

```bash
python3 scripts/preload_chart.py
```

輸出：

```text
data/cache/chart/weekly.json
```

---

## 9. 整體資料流

```text
Bugs Chart
  ↓
SQLite chart_history.db
  ↓
ChartHistoryRepository
  ↓
KpopAnalysisAgent

Naver News API
  ↓
NaverNewsClient
  ↓
KpopAnalysisAgent

YouTube API
  ↓
sample_comments.csv
  ↓
Gemini sentiment labeling
  ↓
sample_comments.csv with sentiment
  ↓
analyze_sentiment_from_csv()
  ↓
KpopAnalysisAgent

KpopAnalysisAgent
  ↓
Artist JSON Cache
  ↓
LINE Flex Message
  ↓
User
```

---

## 10. 設計原則

目前系統採用「預先生成 + 快取回覆」策略。

原因：

- LINE Bot 回覆速度較快
- 降低 Gemini / Naver / YouTube API 即時壓力
- 減少 rate limit 風險
- 回覆內容較穩定
- Demo 體驗比較可控

目前不開放自由問答，避免使用者期待過高或回答不穩定。
