# K-pop Multi-Tool Agent MVP

Phase 1 MVP：Line Bot webhook → Flask backend → intent routing → Naver News API → SQLite chart history → Gemini report → reply.

目前刻意不包含 Tool D 韓文情感模型、YouTube API、Melon 評論爬蟲與複雜前端。

## 專案結構

```text
kpop-agent/
├── app.py
├── requirements.txt
├── .env.example
├── data/
│   ├── chart_history.db
│   ├── seed_chart_data.csv
│   └── mock/
├── scripts/
├── src/
└── tests/
```

## 安裝

```bash
cd kpop-agent
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

## 設定環境變數

編輯 `.env`：

```bash
LINE_CHANNEL_ACCESS_TOKEN=你的 Line access token
LINE_CHANNEL_SECRET=你的 Line channel secret
NAVER_CLIENT_ID=你的 Naver client id
NAVER_CLIENT_SECRET=你的 Naver client secret
GEMINI_API_KEY=你的 Gemini API key
```

沒有填 API key 也可以跑：系統會自動進入 mock mode，讀取 `data/mock/` 的 demo JSON 和報告。

## 初始化資料庫與匯入 seed data

```bash
python scripts/init_db.py
python scripts/seed_data.py
```

`seed_data.py` 會匯入 `data/seed_chart_data.csv`，目前包含 aespa、IVE、NewJeans 的 12 週 demo chart data。

## 本機執行

```bash
flask --app app run --debug --port 5000
```

健康檢查：

```bash
curl http://127.0.0.1:5000/health
```

`/health` 會回報目前主線整合狀態：

```json
{
  "status": "ok",
  "sqlite_ok": true,
  "bugs_tool_available": true,
  "naver_mode": "real 或 mock",
  "gemini_mode": "real 或 mock",
  "line_mode": "real 或 mock"
}
```

本機測試分析 API：

```bash
curl -X POST http://127.0.0.1:5000/analyze \
  -H "Content-Type: application/json" \
  -d '{"message":"分析 aespa 最近三個月表現"}'
```

## LINE Webhook

部署後，把 LINE Developers 後台 webhook URL 設成：

```text
https://你的網域/webhook
```

開發時若尚未設定 LINE key，`/webhook` 會接受 mock JSON：

```bash
curl -X POST http://127.0.0.1:5000/webhook \
  -H "Content-Type: application/json" \
  -d '{"message":"IVE 新專輯的粉絲反應如何？"}'
```

## 測試

```bash
pytest
```

## 抓取 Bugs 週榜並寫入 SQLite

Phase 2 新增 Tool A，可從 Bugs 週榜抓取目前週榜前 100 名並寫入既有 `chart_history` table：

```bash
python scripts/fetch_bugs_chart.py
```

寫入使用 `INSERT OR IGNORE`，同一週同一首歌重複執行不會重複新增。

## Phase 1 範圍

- Flask webhook 與本機 `/analyze` 測試端點
- 簡單 intent router
- Tool B：Naver News API，無 key 時讀 mock JSON
- Tool C：SQLite 歷史榜單查詢與趨勢統計
- Gemini report generator，無 key 時產生 mock report
- SQLite schema、seed CSV、seed script

## Phase 2 範圍

- Tool A：Bugs 週榜爬蟲
- Bugs 週榜資料自動寫入 SQLite `chart_history`
- 保留既有 Line Bot、mock mode、`/health`、`/analyze` 主線

## Phase 2.5 穩定化檢查

```bash
python scripts/fetch_bugs_chart.py
curl http://127.0.0.1:5000/health
curl -X POST http://127.0.0.1:5000/analyze \
  -H "Content-Type: application/json" \
  -d '{"message":"分析 aespa 最近三個月表現"}'
pytest
```
