---
title: Kpop Agent
sdk: docker
app_port: 7860
pinned: false
---

# K-pop Agent

K-pop Agent 是一個已部署至 Hugging Face Space 的 LINE Bot 專案，將 K-pop 榜單資料、Naver 新聞、YouTube 留言情感分析、Gemini 文字生成、SQLite 快取與 LINE Flex Message 整合成可互動的 K-pop 分析與遊玩型機器人。

- Hugging Face Space: <https://huggingface.co/spaces/EscA95103040126/kpop-agent>
- GitHub Repo: <https://github.com/EscA95103040126/K-pop-Agent>
- Runtime: Docker on Hugging Face Spaces
- App Port: `7860`
- Local Framework: Flask
- Bot Platform: LINE Messaging API

## 專案定位

這個專案分成兩條主要路線：

| 路線 | 說明 |
| --- | --- |
| 資料分析線 | 藝人分析報告、Bugs 榜單、Naver 新聞、YouTube 留言情感分析、Gemini 市場洞察 |
| 互動體驗線 | Rich Menu、AI 入坑、每日一首 K-pop、我的 K-pop 口袋、Play Zone 測驗與抽卡 |

核心目標不是只回覆固定文字，而是把資料與互動流程包裝成 LINE 使用者可以直接點選、抽取、測驗與追問的 Bot 體驗。

## 已部署狀態

本專案目前已部署在 Hugging Face Space：

```text
https://huggingface.co/spaces/EscA95103040126/kpop-agent
```

Hugging Face 使用 repo 根目錄的 `Dockerfile` 建置服務，並透過 README frontmatter 指定：

```yaml
sdk: docker
app_port: 7860
```

`Dockerfile` 會安裝 `requirements.txt`，初始化 SQLite 資料庫，並以 `gunicorn` 啟動 Flask app。

## 主要功能

### 1. LINE Rich Menu

Rich Menu 提供六個主要入口：

| 入口 | 功能 |
| --- | --- |
| 分析藝人 | 選擇藝人並產生完整市場分析報告 |
| 本週榜單 | 查詢 Bugs K-pop 週榜資料 |
| 互動專區 | 進入 K-pop Play Zone |
| 每日一首 | 抽 MV、直拍或舞台推薦 |
| AI 入坑 | 根據自然語言偏好推薦入坑路線 |
| 使用說明 | 顯示支援指令與使用方式 |

Rich Menu 建立腳本位於：

```text
scripts/setup_rich_menu.py
```

### 2. 藝人分析報告

使用者可以在 LINE 輸入：

```text
分析 aespa
分析 IVE
分析 NCT
```

Bot 會優先讀取離線產生的 ABSA cache，回傳包含以下內容的分析報告：

- 藝人基本分析
- Bugs 榜單表現
- YouTube 韓文留言 ABSA / 情感比例
- Naver 近期新聞摘要
- Gemini 市場洞察
- LINE Flex Message 視覺化卡片

目前支援分析的藝人：

```text
aespa, IVE, BABYMONSTER, NMIXX, ILLIT, NCT,
ZEROBASEONE, TXT, ENHYPEN, BOYNEXTDOOR
```

### 3. AI 入坑

AI 入坑支援自然語言偏好，例如：

```text
我喜歡小鹿臉的
我想入坑清冷感、舞台強的女團
幫我推薦 vocal 強、現場穩的 K-pop
我喜歡霸氣舞台、rap 和 dance
```

系統會解析使用者偏好，讀取 `data/play_zone/bias_radar_members.csv`，依照外貌、定位、氣質、關係感等欄位推薦成員與團體，再搭配 `data/play_zone/daily_mv.csv` 提供 MV 入坑路線。

若 Gemini API 可用，會產生較自然的推薦文字；若 API 不可用，會使用本地 fallback 產生穩定回覆。

### 4. 每日一首 K-pop

每日一首提供三種抽取：

| 類型 | 資料來源 |
| --- | --- |
| 每日 MV | `data/play_zone/daily_mv.csv` / Supabase `kpop_items` |
| 每日直拍 | `data/play_zone/daily_fancam.csv` |
| 每日舞台 | `data/play_zone/daily_stage.csv` |

抽取結果會回傳純文字連結，讓 LINE 自動產生 YouTube 預覽，並附上可再次抽取的 Flex Message。

若 Supabase 已設定，`每日 MV` 會優先使用 `kpop_items` 做個人化推薦。使用者在「我的 K-pop 口袋」設定的 `preferred_gender` 會對應到 `kpop_items.gender_category`，因此可以只抽女團、男團或都可以。若選擇 `all` / 都可以，系統不會只推薦 `mixed` 內容，而是不加性別篩選，從男團、女團與 mixed 全部 MV 中抽取。若 Supabase 未設定或查詢失敗，系統會回到 `daily_mv.csv` 的本地隨機抽取。

`daily_mv.csv` 本身只存 `artist`、`title`、`url`，不直接存性別分類。分類是在匯入 Supabase 前由 `scripts/import_kpop_items.py` 補上：

- 先從 `data/play_zone/bias_radar_members.csv` 的 `group_type` 建立藝人性別 lookup。
- 再用 `MANUAL_ARTIST_GENDERS` 補齊 CSV 內沒有出現在本命雷達資料集的團體名稱。
- 匯入後寫入 `kpop_items.gender_category`，每日 MV 推薦再用使用者的 `preferred_gender` 篩選。
- `mixed` 是內容分類，不是使用者偏好選項；使用者偏好選項只有女團、男團、都可以。

目前 MV 藝人分類已校正為：

| 分類 | 藝人 |
| --- | --- |
| `boy_group` | ATEEZ, BOYNEXTDOOR, BSS, CRAVITY, DAY6, ENHYPEN, EXO, MONSTA X, NCT 127, NCT DREAM, NCT U, NCT WISH, SEVENTEEN, Stray Kids, TXT, ZEROBASEONE |
| `girl_group` | aespa, BABYMONSTER, BLACKPINK, H1-KEY, Hearts2Hearts, i-dle, ILLIT, IVE, KISS OF LIFE, LE SSERAFIM, MEOVV, QWER, Red Velvet, Red Velvet X aespa, tripleS, TWICE |
| `mixed` | ALLDAY PROJECT |

### 5. 我的 K-pop 口袋

我的 K-pop 口袋使用 Supabase 儲存使用者收藏與推薦偏好，包含：

- `user_preferences.preferred_gender`：每日 MV 推薦偏好，可為 `girl_group`、`boy_group` 或 `all`。
- `kpop_items.gender_category`：每筆 MV、直拍或照片的團體分類。
- `user_saved_items`：使用者收藏的 MV、直拍與照片。
- `user_draw_history`：每日 MV 已抽過的項目，用來降低重複推薦。

使用者可以在 LINE 中查看收藏數、查看已收藏內容、修改每日 MV 推薦偏好，並從每日推薦、直拍或神圖抽卡結果加入收藏。

推薦邏輯重點：

1. 設定推薦偏好
使用者可以選擇女團、男團或都可以，讓每日 MV 推薦更符合自己的追星方向。

2. 減少每日 MV 重複推薦
系統會記錄使用者已抽過與已收藏的 MV，推薦時優先避開重複項目，提升探索新內容的效率。

3. 建立個人化資料層
收藏、偏好與抽取記錄會寫入 Supabase，讓 LINE Bot 從一次性回覆工具，升級成能累積使用者喜好的 K-pop 助理。

### 6. K-pop Play Zone

Play Zone 是互動遊玩區，目前包含：

| 功能 | 說明 | 主要資料 |
| --- | --- | --- |
| 粉絲屬性測驗 | 透過 5 題選擇題判斷使用者是團飯、唯飯或跟風粉 | app 內建題庫 |
| 本命雷達測驗 | 依照性別團、外貌偏好、定位、氣質、關係感推薦 K-pop 成員 | `bias_radar_questions.json`, `bias_radar_members.csv`, `radar_image/` |
| 認人測驗 | 顯示成員圖片並讓使用者選答案 | `member_quiz.csv`, `member_quiz_images/` |
| 神圖抽卡 | 隨機抽取成員神圖或推薦內容 | `photo_cards.csv` |

### 7. 榜單、新聞與情感分析

專案整合多個資料來源：

| 資料 | 用途 | 主要檔案 |
| --- | --- | --- |
| Bugs Chart | K-pop 週榜爬取與 SQLite 儲存 | `src/tools/bugs_chart.py`, `src/tools/chart_db.py` |
| Naver News | 查詢藝人近期新聞 | `src/tools/naver_news.py` |
| YouTube Comments | 抓取韓文留言 | `scripts/fetch_youtube_comments.py` |
| Offline ABSA | 對新聞與留言做面向式情感分析，輸出本地 cache | `src/tools/absa.py`, `scripts/build_absa_cache.py`, `data/cache/absa/*.json` |
| Sentiment CSV | 預標註留言情感分析 fallback | `src/tools/sentiment.py`, `data/sample_comments.csv` |
| Gemini | 市場洞察、AI 入坑、推薦原因生成 | `src/agent.py`, `app.py` |

`本週榜單` 仍回覆資料庫中最新一週的 Bugs 前 10；若資料庫有更早週次，Bot 會額外顯示「歷史週次」按鈕，點選後回覆該週前 10。

### 8. 離線 ABSA pipeline

`分析 藝人` 的輿論面向分析不在 LINE webhook 內即時跑模型，也不在 webhook 內大量抓 YouTube 留言。正式流程是先執行離線批次：

```bash
python3 scripts/build_absa_cache.py
```

批次腳本會：

- 透過 Naver News API 抓取每位藝人近期新聞；API 不可用時沿用既有 mock fallback。
- 透過 YouTube Data API 抓取韓文留言；若未提供 `YOUTUBE_API_KEY` 可用 `--use-sample-comments` 讀取 `data/sample_comments.csv`。
- 使用 KcELECTRA sentiment/ABSA model 做韓文新聞與留言情感分類；若批次環境未安裝 `transformers` / `torch`，腳本會降級為 keyword fallback，仍維持相同 JSON schema。
- 依五個面向輸出 `data/cache/absa/{artist}.json`，另輸出 `data/cache/absa/summary.csv`。

支援面向：

```text
song / music
performance
visual / styling
vocal / rap
fandom / public_opinion
```

LINE Bot 收到 `分析 aespa`、`分析 IVE` 等完整藝人分析指令時，會先讀 `data/cache/absa/{artist}.json`。若 ABSA cache 不存在或 schema 無效，才回到既有 `data/cache/artists/{artist}.json` / 本地 fallback 流程。

## 系統架構

```text
LINE 使用者
    |
    v
LINE Messaging API
    |
    v
Flask app.py
    |
    +-- Intent Router / 指令判斷
    |
    +-- 藝人分析
    |     +-- Bugs Chart SQLite
    |     +-- Offline ABSA JSON cache
    |     +-- Artist cache fallback
    |     +-- Gemini Insight
    |
    +-- AI 入坑
    |     +-- bias_radar_members.csv
    |     +-- daily_mv.csv
    |     +-- Gemini / fallback
    |
    +-- 我的 K-pop 口袋 / 每日 MV 個人化
    |     +-- Supabase user_preferences
    |     +-- Supabase kpop_items.gender_category
    |     +-- Supabase user_saved_items / user_draw_history
    |
    +-- Play Zone
    |     +-- 粉絲屬性測驗
    |     +-- 本命雷達
    |     +-- 認人測驗
    |     +-- 神圖抽卡
    |
    +-- LINE Flex Message Formatter
```

## 專案結構

```text
.
├── app.py                         # Flask app、LINE webhook、Flex Message 與互動流程
├── Dockerfile                     # Hugging Face Space Docker runtime
├── requirements.txt               # Python dependencies
├── src/
│   ├── agent.py                   # 藝人分析、Gemini 報告與 fallback
│   ├── config.py                  # 環境變數與路徑設定
│   ├── router.py                  # 使用者訊息 intent routing
│   ├── tools/
│   │   ├── bugs_chart.py          # Bugs 榜單爬蟲/parser
│   │   ├── chart_db.py            # SQLite 榜單查詢
│   │   ├── naver_news.py          # Naver News API
│   │   ├── sentiment.py           # 留言情感分析 fallback
│   │   ├── kpop_radar.py          # Supabase K-pop 口袋、收藏與每日 MV 個人化
│   │   └── absa.py                # 離線 ABSA cache schema / loader / analyzer
│   └── utils/
│       ├── response_formatter.py  # LINE 文字長度處理
│       └── text_cleaner.py        # 文字清理
├── scripts/
│   ├── setup_rich_menu.py         # 建立 LINE Rich Menu
│   ├── fetch_bugs_chart.py        # 抓取 Bugs 週榜
│   ├── fetch_youtube_comments.py  # 抓取 YouTube 留言
│   ├── build_absa_cache.py        # 離線 Naver + YouTube + KcELECTRA ABSA cache
│   ├── import_kpop_items.py       # 將每日 MV、直拍與神圖資料匯入 Supabase kpop_items
│   ├── label_sentiments.py        # Gemini 標註留言情感
│   ├── preload_cache.py           # 預先產生藝人分析快取
│   └── start.sh                   # 本機 ngrok + Flask 啟動輔助
├── data/
│   ├── chart_history.db           # SQLite 榜單資料庫
│   ├── sample_comments.csv        # 留言情感資料
│   └── play_zone/                 # Play Zone CSV、JSON 與圖片素材
├── supabase/
│   └── kpop_radar_schema.sql      # K-pop 口袋 Supabase schema
└── tests/                         # pytest 測試
```

## 環境變數

可以從 `.env.example` 複製：

```bash
cp .env.example .env
```

主要設定：

| 變數 | 用途 | 必填 |
| --- | --- | --- |
| `LINE_CHANNEL_ACCESS_TOKEN` | LINE Bot access token | 部署 LINE Bot 時必填 |
| `LINE_CHANNEL_SECRET` | LINE webhook 驗證 | 部署 LINE Bot 時必填 |
| `NAVER_CLIENT_ID` | Naver Search API client id | 有真實新聞資料時填 |
| `NAVER_CLIENT_SECRET` | Naver Search API secret | 有真實新聞資料時填 |
| `GEMINI_API_KEY` | Gemini API key | 使用 AI 生成時填 |
| `GEMINI_MODEL` | Gemini model name | 選填 |
| `YOUTUBE_API_KEY` | YouTube Data API key | 抓留言時填 |
| `SUPABASE_URL` | Supabase project URL | 啟用 K-pop 口袋與每日 MV 個人化時填 |
| `SUPABASE_SERVICE_ROLE_KEY` | Supabase service role key | 啟用 K-pop 口袋與每日 MV 個人化時填 |
| `DATABASE_PATH` | SQLite 資料庫位置 | 預設可用 |
| `MOCK_DATA_DIR` | mock data 位置 | 預設可用 |
| `PORT` | Flask port | HF 使用 `7860` |

若部分 API key 未設定，系統會使用 mock data 或本地 fallback，避免整個 Bot 中斷。

## 本機啟動

### 1. 安裝依賴

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. 初始化資料庫

```bash
python3 scripts/init_db.py
python3 scripts/seed_data.py
```

### 3. 啟動 Flask

```bash
python3 app.py
```

本機預設 port 由 `.env` 的 `PORT` 決定，若未設定則使用 `5000`。

### 4. 健康檢查

```bash
curl http://127.0.0.1:5000/health
```

### 5. 測試分析 API

```bash
curl -X POST http://127.0.0.1:5000/analyze \
  -H "Content-Type: application/json" \
  -d '{"message":"分析 aespa"}'
```

## LINE Webhook

部署後，在 LINE Developers 後台將 webhook 指向：

```text
https://你的網域/webhook
```

若使用 Hugging Face Space，webhook URL 會是：

```text
https://EscA95103040126-kpop-agent.hf.space/webhook
```

本機測試可使用 `scripts/start.sh` 搭配 ngrok，啟動後將輸出的 public URL 設定到 LINE Developers。

## 常用資料更新指令

```bash
# 抓取 Bugs 週榜
python3 scripts/fetch_bugs_chart.py

# 抓取指定週次 Bugs 週榜
python3 scripts/fetch_bugs_chart.py --chart-date 2026-05-18

# 預先產生藝人 cache
python3 scripts/preload_cache.py

# 抓取 YouTube 留言
python3 scripts/fetch_youtube_comments.py

# 使用 Gemini 標註留言情感
python3 scripts/label_sentiments.py

# 建立或更新 LINE Rich Menu
python3 scripts/setup_rich_menu.py

# 匯入每日 MV、直拍與神圖資料到 Supabase kpop_items
python3 scripts/import_kpop_items.py

# 僅檢查匯入資料數量，不寫入 Supabase
python3 scripts/import_kpop_items.py --dry-run
```

## 測試

```bash
pytest
```

目前測試涵蓋：

- Flask health check
- LINE webhook 去重與 debounce
- Router intent 判斷
- Bugs chart parser
- SQLite chart query
- Naver News fallback
- Sentiment classifier
- Play Zone、每日一首、本命雷達、認人測驗與抽卡流程
- K-pop 口袋、Supabase 每日 MV 推薦與收藏流程

## 技術棧

- Python 3.13
- Flask
- LINE Messaging API
- Gemini API
- Naver Search API
- YouTube Data API
- SQLite
- CSV / JSON cache
- Docker
- Hugging Face Spaces
- pytest

## 目前狀態

- 已部署至 Hugging Face Space
- 已整合 LINE webhook 與 Rich Menu
- 已完成藝人分析、榜單、新聞、情感分析與 Gemini insight
- 已完成 AI 入坑、每日一首、我的 K-pop 口袋、Play Zone 測驗與抽卡
- 已提供本地 fallback 與 mock data，方便無 API key 的展示與測試
