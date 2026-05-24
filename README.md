---
title: Kpop Agent
sdk: docker
app_port: 7860
pinned: false
---

# K-pop Multi-Tool Agent

一個以 Flask 為基礎的 K-pop 市場分析 Agent，整合榜單趨勢、Naver 新聞、韓文情感分析，透過 Gemini 產出結構化繁體中文報告，並透過 LINE Messaging API 回覆使用者。所有 API 金鑰缺失時自動進入 mock 模式，本機無需任何外部帳號即可展演。

---

## 系統架構

```
使用者訊息（LINE / POST /analyze）
        │
        ▼
   Intent Router
   （src/router.py）
        │
   ┌────┴────────────────────────┐
   │                             │
   ▼                             ▼
Tool B                        Tool C
Naver News API                SQLite 榜單趨勢
（mock fallback）              （mock fallback）
   │                             │
   └──────────┬──────────────────┘
              │
              ▼
           Tool D
     情感分析 CSV classifier
     （fallback: 無資料訊息）
              │
              ▼
     Gemini Report Generator
     （mock fallback）
              │
              ▼
        結構化分析報告
```

> Tool A（Bugs 週榜爬蟲）為獨立腳本，定期執行後寫入 SQLite，不在即時分析路徑上。

---

## 四個 Tool 說明

| Tool | 功能 | 技術 | 狀態 |
|------|------|------|------|
| Tool A | Bugs 週榜爬蟲，抓取前 100 名並寫入 SQLite | requests + BeautifulSoup | ✅ 完成 |
| Tool B | Naver News API 搜尋近期新聞事件 | Naver Search API / mock JSON | ✅ 完成 |
| Tool C | SQLite 歷史榜單查詢與趨勢統計 | SQLite3 / mock JSON | ✅ 完成 |
| Tool D | 韓文評論規則式情感分類與摘要 | 關鍵字分類 / sample_comments.csv | ✅ 完成 |

---

## 快速啟動

### 安裝依賴

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 設定 .env

```bash
cp .env.example .env
# 編輯 .env，填入 API 金鑰（可留空，系統自動進入 mock 模式）
```

### 初始化資料庫

```bash
python3 scripts/init_db.py
python3 scripts/seed_data.py
```

### 啟動伺服器

```bash
python3 app.py
```

### 展演模式（全 mock，無需任何 API 金鑰）

```bash
python3 scripts/demo.py
```

---

## API 範例

健康檢查：

```bash
curl http://127.0.0.1:5000/health
```

分析報告：

```bash
curl -X POST http://127.0.0.1:5000/analyze \
  -H "Content-Type: application/json" \
  -d '{"message":"分析 aespa 最近表現"}'

curl -X POST http://127.0.0.1:5000/analyze \
  -H "Content-Type: application/json" \
  -d '{"message":"IVE 的輿論風向是什麼？"}'

curl -X POST http://127.0.0.1:5000/analyze \
  -H "Content-Type: application/json" \
  -d '{"message":"NewJeans 近期市場表現如何？"}'
```

LINE Webhook（mock 模式）：

```bash
curl -X POST http://127.0.0.1:5000/webhook \
  -H "Content-Type: application/json" \
  -d '{"message":"IVE 新專輯的粉絲反應如何？"}'
```

---

## 測試

```bash
pytest
```

---

## 抓取 Bugs 週榜

```bash
python3 scripts/fetch_bugs_chart.py
```

---

## 開發進度

| Phase | 說明 | 狀態 |
|-------|------|------|
| Phase 1 | Flask webhook、Intent Router、Tool B Naver News、Tool C SQLite、Gemini report | ✅ 完成 |
| Phase 2 | Tool A Bugs 週榜爬蟲、自動寫入 SQLite | ✅ 完成 |
| Phase 2.5 | 整合穩定化、real Naver API 支援、gitignore 修正 | ✅ 完成 |
| Phase 3-1 | Tool D CSV 評論資料集（60 則，aespa / IVE / NewJeans） | ✅ 完成 |
| Phase 3-2 | Tool D 規則式情感分類器（classify_comment / analyze_sentiment_from_csv）+ pytest 12 tests | ✅ 完成 |
| Phase 3-3 | Tool D 整合進 /analyze，Section 3 顯示真實情感數據 | ✅ 完成 |
| Phase 4 | 展演穩定化：mock fallback 補齊、demo script、README 更新 | ✅ 完成 |
