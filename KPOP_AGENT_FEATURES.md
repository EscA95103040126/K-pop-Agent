# K-pop Agent 功能總整理

更新日期：2026-05-27

## 專案定位

K-pop Agent 是一個部署在 Hugging Face Space 的 LINE Bot，核心不是單純回傳固定文字，而是把 K-pop 榜單、新聞、留言情感分析、SQLite 資料庫、Gemini 與 LINE Flex Message 組合成一個可互動的分析型機器人。

專案主要分成兩條路線：

- 資料分析線：藝人報告、榜單資料、新聞摘要、ABSA 情感分析、快取報告。
- 互動體驗線：AI 入坑、每日一首、K-pop Play Zone 測驗與抽卡。

## 主要入口

Rich Menu 目前提供六個入口：

| 入口 | 功能 |
| --- | --- |
| 分析藝人 | 選擇藝人並產生完整分析報告 |
| 本週榜單 | 查詢本週 K-pop 榜單資料 |
| 互動專區 | 進入 K-pop Play Zone |
| 每日一首 | 抽 MV、直拍或舞台推薦 |
| AI 入坑 | 用自然語言描述偏好，讓 Gemini 推薦入坑路線 |
| 使用說明 | 顯示可用指令與支援範圍 |

## 視覺設計

為了讓 LINE Bot 的不同區塊更容易辨識，Flex Message 已區分色系：

| 區塊 | 色系 | 說明 |
| --- | --- | --- |
| 分析藝人 | 棕色 | 主分析報告入口 |
| AI 入坑 | 紫色 | AI 推薦與自然語言偏好 |
| 互動專區 / Play Zone | 綠色 | 測驗、抽卡、互動玩法 |
| 每日一首 | 藍色 | MV、直拍、舞台推薦 |

Play Zone 內部的本命雷達、粉絲屬性測驗、神圖抽卡再抽一次，也已統一成綠色系。

## 資料分析功能

### 1. 藝人完整報告

使用者可以輸入：

```text
分析 aespa
分析 IVE
分析 NCT
```

Bot 會回傳該藝人的 Flex Message 報告，包含：

- 藝人基本分析
- 榜單表現
- 粉絲留言情感比例
- 近期新聞摘要
- 市場洞察 insight

目前支援分析的藝人：

```text
aespa, IVE, BABYMONSTER, NMIXX, ILLIT, NCT,
ZEROBASEONE, TXT, ENHYPEN, BOYNEXTDOOR
```

### 2. SQLite 榜單資料

榜單資料使用 SQLite 儲存，主要由 `data/chart_history.db` 提供。

已修正的重點：

- 不再把同一週多首歌誤判為多週趨勢。
- 若資料庫只有單週資料，報告顯示「本週最高排名」、「本週上榜歌曲數」、「平均排名」。
- 若有兩週以上資料，才顯示多週趨勢。
- `本週榜單` 仍回覆最新週次的 Bugs 前 10；若資料庫有更早週次，會附上「歷史週次」按鈕，點選後只回覆該週前 10。

### 3. ABSA / 情感分析

情感分析已從 rule-based 關鍵字比對升級為 Gemini 零樣本分類，再進一步改成 CSV 預標註模式。

目前流程：

1. `scripts/fetch_youtube_comments.py` 抓取 YouTube 韓文留言。
2. `scripts/label_sentiments.py` 呼叫 Gemini 產生 `positive / neutral / negative` 標籤。
3. 結果寫入 `data/sample_comments.csv` 的 `sentiment` 欄位。
4. LINE Bot 執行分析時直接讀取 CSV，不即時大量呼叫 Gemini，降低延遲與 API 負擔。

如果 CSV 沒有 `sentiment` 欄位，系統仍可 fallback 到即時 Gemini 分析。

### 4. Naver News

專案串接 Naver API 取得 K-pop 相關新聞，並整理成藝人報告中的近期新聞摘要。

### 5. Gemini 市場洞察

快取報告中加入 `insight` 欄位：

```json
{
  "headline": "一句話市場觀察",
  "risk": "高/中/低",
  "opportunity": "一句話機會點"
}
```

若 Gemini 呼叫失敗，會 fallback 到本地規則產生保守洞察，避免報告中斷。

### 6. 快取系統

報告可透過 `scripts/preload_cache.py` 預先產生並存成 JSON。

優點：

- LINE Bot 回覆速度更快。
- 減少即時呼叫 Gemini / Naver / YouTube 的壓力。
- 適合部署到 Hugging Face Space。

## AI 入坑

AI 入坑是自然語言偏好推薦功能。

使用者可以直接輸入：

```text
我喜歡小鹿臉的
我想入坑清冷感、舞台強的女團
幫我推薦 vocal 強、現場穩的 K-pop
我喜歡霸氣舞台、rap 和 dance
```

系統會：

1. 從自然語言中解析偏好。
2. 讀取 `data/play_zone/bias_radar_members.csv`。
3. 根據外貌、定位、氣質、關係感等欄位推薦成員與團體。
4. 從 `data/play_zone/daily_mv.csv` 挑選推薦藝人所屬團體的 MV。
5. 回傳文字入坑路線。
6. 額外回傳 Flex Message，提供後續操作：
   - 本命雷達
   - 抽 MV
   - 抽直拍

AI 入坑使用 Gemini 產生自然語言回覆；若 Gemini 失敗，會使用本地 fallback 產生推薦文字。

## 每日一首 K-pop

每日一首提供三種推薦：

- 每日 MV
- 每日直拍
- 每日舞台

資料來源：

| 檔案 | 筆數 | 用途 |
| --- | ---: | --- |
| `data/play_zone/daily_mv.csv` | 477 | MV 推薦 |
| `data/play_zone/daily_fancam.csv` | 619 | 直拍推薦 |
| `data/play_zone/daily_stage.csv` | 40 | 舞台推薦 |

以上筆數以 CSV 中有完整 `artist / title / url` 的有效資料列計算。

輸出格式是純文字，讓 LINE 可以自動產生連結預覽與縮圖。

範例：

```text
🎵 今天推薦的是 aespa 的 Supernova
https://...
```

輸出後會再額外發一則 Flex Message，讓使用者選擇：

- MV
- 直拍
- 舞台

隨機抽取已加入短期不重複機制，降低連續幾次抽到同一首的機率。

## K-pop Play Zone

Play Zone 是專案的互動功能區，將既有資料包裝成 LINE 可玩的形式。

目前包含：

- 粉絲屬性測驗
- 本命雷達測驗
- 認人測驗
- 神圖抽卡

### 1. 粉絲屬性測驗

功能：

- 透過 5 題選擇題判斷使用者粉絲屬性。
- 結果包含屬性名稱、說明、建議玩法。
- 結果 Flex Message 有「再測一次」按鈕。

目前分類：

- 團飯
- 唯飯
- 跟風粉

### 2. 本命雷達測驗

功能：

- 使用 5 題選擇題推薦適合的 K-pop 成員。
- 問題包含：
  - 想看男團 / 女團 / 都可以
  - 外貌偏好：貓、狗、兔、狐、鹿
  - 喜歡定位：Vocal、Dance、Rap、Visual、All-rounder
  - 喜歡氣質：冷感、甜系、霸氣、反差、清冷
  - 本命關係感：戀愛感、神性、朋友感、初戀感、舞台支配感

資料來源：

| 檔案 | 筆數 |
| --- | ---: |
| `data/play_zone/bias_radar_members.csv` | 164 |
| `data/play_zone/radar_image/` | 164 張圖片 |

結果 Flex Message 會顯示：

- 推薦藝人與成員
- 命中標籤
- 推薦原因
- 再測一次
- 回 Play Zone

### 3. 認人測驗

功能：

- Bot 輸出一張圖片。
- Flex Message 顯示自訂題目。
- 使用者從兩個選項中選答案。
- 回覆正確或錯誤。
- 再詢問是否要再一題。

資料來源：

| 檔案 / 資料夾 | 數量 |
| --- | ---: |
| `data/play_zone/member_quiz.csv` | 70 題 |
| `data/play_zone/member_quiz_images/` | 70 張圖片 |

這個功能支援自訂題目，因此可以處理合成圖、左右對照圖或特殊題型。

### 4. 神圖抽卡

功能：

- 從本地 CSV 隨機抽出一筆神圖資料。
- 回傳藝人、類型與連結。
- 額外回傳「再抽一次」Flex Message。

資料來源：

| 檔案 | 筆數 | 欄位 |
| --- | ---: | --- |
| `data/play_zone/photo_cards.csv` | 412 | `artist`, `type`, `url` |

輸出格式：

```text
✨ 神圖抽卡結果 ✨

🎉 恭喜你今天抽到
💖 {artist}
📸 類型：{type}

🔗 點開看神圖
{url}
```

## 技術架構摘要

主要檔案：

| 檔案 | 說明 |
| --- | --- |
| `app.py` | Flask / LINE webhook / Flex Message / Play Zone 互動 |
| `src/agent.py` | 藝人報告生成、快取、Gemini insight |
| `src/router.py` | 使用者訊息 intent routing |
| `src/tools/chart_db.py` | SQLite 榜單查詢與趨勢計算 |
| `src/tools/sentiment.py` | CSV-based ABSA 與 Gemini fallback |
| `src/tools/naver_news.py` | Naver News API |
| `scripts/preload_cache.py` | 預先生成藝人快取 |
| `scripts/fetch_youtube_comments.py` | 抓取 YouTube 留言 |
| `scripts/label_sentiments.py` | Gemini 標註留言情感 |
| `scripts/setup_rich_menu.py` | 建立 / 更新 LINE Rich Menu |

主要資料：

| 資料 | 說明 |
| --- | --- |
| `data/chart_history.db` | SQLite 榜單資料 |
| `data/sample_comments.csv` | YouTube 留言與 sentiment 標籤 |
| `data/cache/artists/` | 藝人快取 JSON |
| `data/play_zone/*.csv` | Play Zone 與每日推薦資料 |

## API 與 AI 使用

專案使用：

- Gemini：情感分類、AI 入坑自然語言回覆、市場洞察 insight。
- Naver News API：近期新聞搜尋。
- YouTube API：抓取粉絲留言資料。
- LINE Messaging API：Webhook、Flex Message、Postback、Rich Menu。

重要設計：

- 大量分析不在 LINE 回覆時即時執行，而是透過 CSV 標註與快取降低延遲。
- Gemini 呼叫皆設計 fallback，避免 API 失敗時整個 Bot 沒反應。
- 測驗類功能盡量使用本地資料，不依賴即時 AI，確保速度與穩定性。

## 部署狀態

專案已部署至 Hugging Face Space。

LINE Bot webhook 指向 Hugging Face Space 的 `/webhook` endpoint。

部署特點：

- 使用 `Dockerfile`。
- 支援 Hugging Face Space 環境變數。
- SQLite 與 CSV 資料可隨 repo 一起部署。
- 使用快取降低雲端運行負擔。

## 測試狀態

目前測試涵蓋：

- 榜單資料與趨勢邏輯
- 情感分析 CSV 與 fallback
- Router intent
- Play Zone 測驗流程
- LINE webhook dedupe
- Naver News fallback
- Health endpoint

最近一次完整測試結果：

```text
88 passed
```

## 展示重點

如果要向老師或評審說明，可以強調：

1. 不是單純回傳固定資料，而是結合資料工程與 LINE 互動設計。
2. 使用 SQLite 管理榜單歷史資料。
3. 使用 Gemini 做零樣本情感分析與自然語言推薦。
4. 使用 CSV 預標註與快取，解決 LINE Bot 即時回覆壓力。
5. Play Zone 把既有 K-pop 資料包裝成測驗、抽卡、每日推薦等互動體驗。
6. 系統有 fallback 機制，不會因 Gemini / API 失敗就停止回覆。
7. Flex Message 已做不同色系分區，讓使用者感覺像完整的 LINE Bot 服務，而不是單一報告產生器。
