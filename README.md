# NYCU e3 課業提醒 × Google Calendar 同步

讓 NYCU 同學用**自己的 Gmail 與 Google Calendar**管理 e3 課業：從 e3 通知信整理作業／報告／考試資訊、比對作業提交確認、建立或更新行事曆事件，並保存課程錄影的「未觀看／已觀看」狀態。

> **專案狀態：v0.1.0（可執行的社群 MVP）**。這是可獨立安裝的 Python 工具，**不是** ChatGPT 排程本身的原始碼，也不是陽明交大官方服務。它目前依賴 **Gmail 收到的 e3／課程通知**；尚未登入 e3 網站讀取所有作業。課程郵件格式不一，部分內容需要人工核對或補入 `manual_events`。**不能保證零漏報**，重要截止日期仍以 e3 課程頁面為準。

## 主要功能

| 類型 | 行為 |
|---|---|
| 待交作業／報告 | 從 Gmail e3 通知辨識截止時間，依到期先後排序 |
| 已提交作業 | 比對主旨 `You have submitted your assignment submission for ...`；從待交清單排除；自動化建立的日曆事件可標示已完成並停止提醒 |
| 遲交／補交／免交 | 排除標示「遲交區」「補交」「免交預報」等項目 |
| 截止時間 | 有明確時間使用原時間；**只有日期**以當日 **23:59** 建立；沒有日期則**不推測、不建事件** |
| 考試 | 若起訖時間完整，使用精確時段；僅知道日期或只知道開始時間，使用標註「待確認」的全天事件 |
| 課程異動 | 嘗試解析停課通知（依賴郵件格式；不保證涵蓋所有異動） |
| Google Calendar | 建立／更新前查重、保存事件 ID，避免重複；有更動時更新程式建立的事件 |
| 教學影片 | 偵測「影片／錄影／lecture video」等已上傳通知，按來源連結去重，保存「未觀看／已觀看」狀態 |
| 隱私 | **每個使用者自己授權**；OAuth Token、私人信件及 SQLite 狀態保存在自己的電腦，預設不傳到第三方伺服器 |

## 1. 系統需求

- Python **3.10 以上**，Windows／macOS／Linux。
- 個人可存取 e3 課務通知的 Gmail 帳號、Google Calendar 帳號（最好相同）。
- Google Cloud 專案及 OAuth Desktop 用戶端憑證（**每位同學自行建立最安全**）。
- 第一次授權需要瀏覽器；之後通常可以使用 refresh token。

## 2. 安裝

```bash
git clone https://github.com/KelsierW/nycu-e3-calendar.git
cd nycu-e3-calendar
python -m venv .venv
```

Windows PowerShell：

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
Copy-Item config.example.yaml config.yaml
New-Item -ItemType Directory -Force .secrets
```

macOS／Linux：

```bash
source .venv/bin/activate
python -m pip install -e .
cp config.example.yaml config.yaml
mkdir -p .secrets
```

> 本專案已公開於 https://github.com/KelsierW/nycu-e3-calendar 。也可以下載原始碼 ZIP 安裝。

## 3. 建立個人 Google OAuth 憑證

1. 開啟 [Google Cloud Console](https://console.cloud.google.com/)，建立自己的專案（建議一位使用者一個專案）。
2. 到 **APIs & Services → Library**，啟用 **Gmail API** 與 **Google Calendar API**。
3. 到 Google Auth Platform／OAuth consent screen，設定應用程式名稱及測試使用者。若仍在測試模式，將**自己的 Gmail 地址**加入測試使用者名單。
4. 建立 **OAuth client ID → Desktop app**，下載 JSON，放到專案的 **`.secrets/credentials.json`**。這份檔案含 OAuth 用戶端資訊，**不可提交到 GitHub**。
5. 本工具會請求兩項 Google OAuth 權限：
   - `https://www.googleapis.com/auth/gmail.readonly`：讀取 e3／課程 Gmail 通知（**不會刪信或寄信**）。
   - `https://www.googleapis.com/auth/calendar.events`：讀取及管理使用者有編輯權限的日曆事件（工具預設**只動主要日曆**）。
6. 透過瀏覽器完成授權：

```bash
nycu-e3 auth
```

第一次成功後產生 `.secrets/token.json`。不要與任何人共用，尤其是 refresh token；如遺失或懷疑外流，前往 Google 帳號權限頁撤銷授權，並刪除本機 token 重新授權。

**關於 Google Cloud 測試模式：** 使用者需列在 OAuth 測試名單中；測試模式授權可能有 refresh token 效期限制。若希望同學大量使用，建議各自建立 Google Cloud 專案與 OAuth 用戶端，而不是在公開儲存庫發布同一組憑證，或依照 Google 官方規定完成應用程式驗證。

## 4. 設定個人課務查詢

編輯 `config.yaml`：

```yaml
timezone: Asia/Taipei
since_days: 120
gmail_query: '{from:e3@nycu.edu.tw "1151."}'
max_messages: 1200
calendar_id: primary
calendar_write: true
course_whitelist: []
manual_events: []
```

- **`gmail_query`：** Gmail 搜尋語法；不同老師、助教的寄件者可能不同，請按自己的收信情況調整。可以在 Gmail 搜尋框測試。預設不會讀取所有私人郵件，只查詢符合條件的信件。
- **`since_days`：** 回溯天數；初次同步可以暫時加大，但會增加 API 用量。
- **`course_whitelist`：** 可指定課號，例如 `["1151.515505", "1151.515514"]`；留空則不限定課號。
- **`calendar_id`：** 預設 `primary`，即自己的主要行事曆。共享或唯讀日曆不能任意寫入。
- **`manual_events`：** 某些郵件格式無法辨識時，手動加入**已核實**的作業／考試日期。請參考 `config.example.yaml` 的註解。

**重要：** 此工具為保守的規則解析器，不會使用 AI 猜測缺失日期；遇到無法解析的郵件，請自行核對 e3，並用 `manual_events` 補充。所有存取只發生在個人授權的 Gmail／Google Calendar。

## 5. 第一次檢查與正式同步

先預覽、不寫入 Google Calendar：

```bash
nycu-e3 check --dry-run
```

檢查輸出中的作業標題、截止日期與考試是否正確，再正式同步：

```bash
nycu-e3 check
```

範例輸出（**虛構課務資料**）：

```text
NYCU/e3 課業檢查：2026-11-01 08:00（Asia/Taipei）
信件 70 封｜待交 1｜未觀看 2｜新影片 1
  [待交] 2026-11-02 23:59  1151.123456 HW1 截止 ...
  [未觀看] 2026-10-28 1151.123456 Lecture 3 recording (a1b2...)
  [已新增] 1151.123456 HW1 截止 https://www.google.com/calendar/event?...
```

新增的作業截止事件預設提前 **24 小時、3 小時**提醒；有完整時段的考試預設提前 **24 小時、90 分鐘**提醒。時間不明的考試使用全天佔位，**不表示整天都在考試**。

### 如何避免重複與誤改？

- 程式在本機 `data/state.db` 記錄 Google Calendar event ID，並對自己新增的事件寫入私人 `nycuE3Key` 屬性。
- 每次先搜尋候選日期範圍內的日曆事件；同一主題／來源已存在時不重複新增。
- **不會覆寫非本程式建立的既有私人事件。**
- 只有來源資料改變時，才更新本程式建立的事件；若你手動刪除了它，工具不會默默重新建立。
- 已提交作業：透過 e3 提交確認比對，從待交清單排除；程式建立且仍存在的提醒事件會標示完成並取消提醒。
- 多個公告提供衝突日期時，程式以**最新解析出的通知**為準；重要考試、緊急變更和延長期限仍應人工核對 e3。

## 6. 教學影片：未觀看／已觀看

掃描通知會將已提供觀看連結的錄影加入 `data/state.db`，並以影片連結 hash 去重。已手動切換的狀態不會因再次掃描被重設。

```bash
# 查看所有影片（含完整 VIDEO_KEY）
nycu-e3 videos

# 標為已觀看（用前面列出的 key）
nycu-e3 videos --watched VIDEO_KEY

# 再標為未觀看
nycu-e3 videos --unwatched VIDEO_KEY
```

「**預計上傳／將會補上錄影**」不等於已可觀看，不加入未觀看佇列。影片資料夾若沒有通知信，本工具無法主動知道影片已更新。

## 7. 排程自動檢查

建議以**每位同學自己的電腦**執行排程，不需要將 OAuth Token 放到 GitHub Actions Secrets。請確保先完成首次 OAuth 授權。

### Linux/macOS：crontab

```cron
# 台灣時間 08:00 / 12:00 / 16:00 / 20:00
CRON_TZ=Asia/Taipei
0 8,12,16,20 * * * cd /你的絕對路徑/nycu-e3-calendar && /你的絕對路徑/nycu-e3-calendar/.venv/bin/nycu-e3 check >> /你的絕對路徑/nycu-e3-calendar/out/check.log 2>&1
```

`CRON_TZ` 的支援因 cron 實作而異；也請確認主機時間和時區。先手動執行 `nycu-e3 check`，確認排程環境能讀到 `.secrets/` 和 `config.yaml`。建立 `out/` 資料夾後才能寫入上述日誌。

### Windows：工作排程器

1. 開啟「工作排程器」，建立新工作。
2. 觸發程序：每天 **08:00、12:00、16:00、20:00**（可建立四個觸發程序）。
3. 動作：啟動程式 `C:\你的路徑\nycu-e3-calendar\.venv\Scripts\nycu-e3.exe`。
4. 引數：`check`；「開始位置」填專案完整路徑 `C:\你的路徑\nycu-e3-calendar`。
5. 確保執行使用者有存取 `.secrets/token.json` 和 `data/state.db` 的權限。

> 此版本是**本機命令列／排程工具**：它會更新 Google Calendar 並列印結果，**不會自動送出 ChatGPT 推播或 LINE 訊息**。行事曆提醒會由 Google Calendar 依個人通知設定發出。若需要 Telegram／Email 摘要，歡迎貢獻獨立通知模組。

## 8. 安全與隱私

**請絕對不要公開下列項目：**

- `.secrets/credentials.json`、`.secrets/token.json`、`.env`、`config.yaml`（可能包含個人資訊）。
- `data/state.db`、任何 SQLite／log 檔、個人郵件內容、含學號／姓名的課程名單或測試資料。
- 個人的 e3 session cookie、Google refresh token、Gmail 附件及行事曆匯出資料。

`.gitignore` 預設排除上述檔案；**仍須自行檢查 `git status`**，尤其是已經被 git 追蹤過的檔案。Token 萬一已經進入 Git 歷史，刪除最新 commit 的檔案**不足以撤銷憑證**；請立即撤銷該授權並更新憑證。

本專案不要求 e3 密碼，也不讀取未授權帳號；不會把信箱內容上傳至專案作者的伺服器。不要把個人的 OAuth token 放進公開 repository 或共享的雲端執行器。

## 9. 已知限制與規劃

1. **Gmail 不等於 e3 全站：** e3 有可能只在課程頁面發布公告，不寄出郵件；目前沒有 e3 網頁登入／爬蟲功能。
2. **解析器是規則式 MVP：** 不保證正確解析所有中英文日期、考試時段、訊息引用或多項目合併通知；例如 `1:30 PM`、複雜附件及多教室名單目前未完整支援。未辨識到的內容請用 `manual_events` 補充。
3. **提交確認匹配：** 以課程代碼、標題做近似比對；若老師修改作業名稱、同一信件含多個作業，可能無法精準匹配。以 e3「已繳交」狀態為最終依據。
4. **來源衝突：** 新舊公告可能互相矛盾。工具會保留最新辨識結果，尚未提供完整衝突審核介面。
5. **資料留在本機：** 影片觀看狀態儲存在 `data/state.db`，更換電腦時需要自己備份／搬移；不是跨使用者共享資料庫。
6. **定期檢查依賴執行環境：** 電腦關機或排程器停用就不會檢查；請勿視為保證送達的緊急通知系統。
7. **Google API 配額與 OAuth 驗證：** 依自己的 Google Cloud 專案設定和權限限制運作；公開服務若要讓所有同學共用 OAuth 應用程式，可能需要 Google 驗證與進一步安全審查。

歡迎提交 Issue／PR 支援其他老師郵件格式、影片頁面、自動回報無法解析郵件、測試及更安全的 Google OAuth 配置。

## 10. 開發與測試

```bash
python -m pip install -e '.[dev]'
pytest -q
```

GitHub Actions 的 `Python tests` 工作流程**只跑無個資的單元測試**；不會連接你的私人 Gmail 或 Google Calendar。

貢獻程式碼或測試資料前，請閱讀 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 11. Fork 與發布到自己的 GitHub

在確認沒有個人資料後，透過 [GitHub CLI](https://cli.github.com/) 或一般 git：

```bash
# 首次使用 GitHub CLI 先登入自己的 GitHub
# gh auth login

git init
git add .
git status   # 再次確認不包含 token、私人信件和 state.db
git commit -m "Initial public NYCU e3 coursework reminder MVP"
gh repo create nycu-e3-calendar --public --source . --remote origin --push
```

如果是從本專案 Fork，請依自己的 Fork URL 設定 `origin`；如果儲存庫已存在，改用自己的 repo URL 設定 `origin` 後 `git push`。**請勿將個人 e3/Gmail 資料用於公開範例或截圖。**

## 授權

本專案採用 [MIT License](LICENSE)。這個非官方社群工具不隸屬於國立陽明交通大學或 Google。