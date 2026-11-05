# Windows 本地執行

Windows 主執行方式為本專案的 `.venv\Scripts\pythonw.exe` 執行 `scripts\run_windows_check.py`，由 Windows 工作排程器啟動。啟動器再執行 `nycu_e3.scheduled`，並將 Python 啟動階段錯誤寫入私人日誌；日常執行不依賴 PowerShell 政策。日常檢查不需要 ChatGPT、Codex 或瀏覽器持續開啟。

## 安裝及授權

在專案資料夾使用 PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e '.[dev]'
# 僅第一次安裝，已有 config.yaml 時不要覆寫：
if (-not (Test-Path config.yaml)) { Copy-Item config.example.yaml config.yaml }
.\.venv\Scripts\python.exe -m nycu_e3 doctor
```

`doctor` 只回報 OAuth 用戶端與 Token 是否存在，不代表授權有效。`check --dry-run` 才會實際測試 Token 更新與 Google API 讀取。`doctor` 缺少 Token 回傳 2；檢查失敗回傳 1；成功回傳 0。

Windows 會沿用桌面舊腳本使用的認證服務 `nycu-e3-crawler`。Client secret 和 Token 保存於 Windows Credential Manager，不會產生專案內的 `token.json`。若已存在舊用戶端但 Token 失效：

```powershell
.\.venv\Scripts\python.exe -m nycu_e3 auth
```

若沒有用戶端，依 [Google 官方 Desktop OAuth 設定](https://developers.google.com/workspace/gmail/api/quickstart/python)建立 Desktop app，啟用 Gmail API 與 Google Calendar API，將自己的 Google 帳號列入測試使用者。把下載 JSON 存於 OneDrive 與 Git 專案以外的私人位置，再執行：

```powershell
.\.venv\Scripts\python.exe -m nycu_e3 auth --client-file 'C:\私人位置\credentials.json'
```

僅 `auth` 會開啟瀏覽器，等待最多十分鐘；每次重新執行請使用這次新開的頁面。看到本機程式顯示「個人 Gmail 和 Google Calendar 授權完成」才代表 Token 已保存，舊程序逾時後的頁面不能保存新授權。程式會請求重新同意並確認收到排程所需的 Refresh Token。Google 登入及授權需由本人完成。不要貼出 JSON、Token 或 Client secret。若 OAuth 應用程式仍為測試模式，Refresh Token 可能定期失效，需重新授權。

## 預覽與正式執行

```powershell
# 唯讀 Google Calendar；本機課務資料庫以記憶體副本預覽
.\.venv\Scripts\python.exe -m nycu_e3.scheduled --project-dir . --dry-run
# 內容核對後正式同步
.\.venv\Scripts\python.exe -m nycu_e3.scheduled --project-dir .
# 影片觀看狀態由本人更新
.\.venv\Scripts\python.exe -m nycu_e3 videos
.\.venv\Scripts\python.exe -m nycu_e3 videos --watched VIDEO_KEY
```

`--dry-run` 不改 Google Calendar 或正式 SQLite 課務資料庫；仍會更新本機預覽日誌／狀態檔，必要時更新認證管理員中的 OAuth 存取 Token。檢查與排程不會因 Token 失效開啟瀏覽器，也不會寄信或修改 Gmail。

Windows 預設私人執行資料夾為 `%LOCALAPPDATA%\NYCU-e3-calendar`，避開 OneDrive：

| 路徑 | 用途 |
| --- | --- |
| `data\state.db` | 影片觀看狀態、程式事件 ID／指紋 |
| `out\check.log` | UTF-8 日誌，超過 2 MB 輪替，保留五份舊檔 |
| `out\bootstrap.log` | 啟動器與套件載入結果，2 MB 輪替一份 |
| `out\last-run.json` | 最近正式執行的結果與錯誤摘要 |
| `out\last-preview.json` | 最近預覽的結果；與正式執行狀態分開 |

錯誤只保存錯誤類別、HTTP 狀態或固定設定提示，不記錄 Google 回應內文或 Token。日誌仍可能含課務標題與來源連結，僅供本人查看，不應上傳。

```powershell
Get-Content "$env:LOCALAPPDATA\NYCU-e3-calendar\out\check.log" -Tail 40
Get-Content "$env:LOCALAPPDATA\NYCU-e3-calendar\out\last-run.json"
```

目前錯誤回報透過這些狀態檔、日誌與工作排程器的 LastTaskResult，沒有另設 Email 或 ChatGPT 推播。若 LastTaskResult 為 `267009`／`0x41301`，表示工作仍在執行，並非已成功；`267011`／`0x41303` 表示尚未執行。

## 工作排程器

```powershell
& .\scripts\install-windows-task.ps1
Get-ScheduledTaskInfo -TaskName 'NYCU e3 Coursework Check'
```

同一工作包含每天 08:00、12:00、16:00、20:00 四個觸發程序，StartBoundary 明確指定 `+08:00`。使用目前帳號及最低權限，不儲存 Windows 密碼。重新執行安裝腳本會更新同名且屬於同一專案的工作；不同專案的同名工作會拒絕覆寫。

電腦需開機且目前 Windows 使用者保持登入（鎖定畫面可以，登出不行）。這是為了存取該使用者的 Windows Credential Manager。設定允許電池供電、嘗試喚醒、錯過後補執行；實際喚醒仍受電源／硬體設定影響。失敗每 15 分鐘重試、最多兩次；最長執行 30 分鐘。排程器 IgnoreNew 與檔案鎖共同防止重複執行。

移動專案後需重新安裝虛擬環境及排程；舊的 GitHub 空 checkout 與桌面 `test.py` 不會自動更新，也不應同時手動執行舊腳本。

## 每天 08:00 的 Android／Google 日曆摘要

在 `config.yaml` 設定 `daily_digest: true`，再執行安裝排程腳本。原有 08／12／16／20 時檢查保留，另建立 `NYCU e3 Coursework Check - Morning Digest Prep` 於台灣時間 07:45 準備當天 08:00 摘要。

每次成功檢查會在 Google 日曆建立或更新「下一個 08:00」的私人摘要事件，列出尚未繳交的作業、截止時間、近期考試及未觀看影片。摘要以當天日期的穩定事件 ID 去重，不占用忙碌時段；提醒為事件開始時 `popup`，可由 Google 日曆手機應用程式顯示。摘要中的作業連結不會被誤當成原作業事件來查重。

摘要只列出未找到相同課程／作業提交確認的項目，排除遲交區、補交和免交。已提交作業不出現在摘要，也會關閉本程式或已驗證舊 NYCU 自動化事件的後續提醒。找不到提交確認不等於確定未繳，仍以 e3 狀態為準。

Android 請使用相同 Google 帳號，並確認手機「設定 → 應用程式 → Google 日曆 → 通知」允許通知，以及 Google 日曆中的該帳號已啟用同步。通知功能以手機系統設定為準；詳見 [Google 官方通知說明](https://support.google.com/calendar/answer/37242?hl=zh-Hant&co=GENIE.Platform%3DAndroid)。

作業事件的 24 小時、3 小時提前提醒仍保留，不會因新增摘要而改變。電腦需開機且登入以更新內容；若 07:45 沒有成功執行，已建立的 08:00 事件仍可提醒，但內容會保留上次成功檢查時間。若電腦持續離線且下一天摘要尚未建立，該天不會有新的摘要通知。

## 課務規則與驗證

- 保留既有 Gmail 查詢、課程篩選、人工已核實事件及 Calendar ID；本次本機設定沿用桌面舊腳本的 `gmail_query: nycu`。
- 排除遲交、補交、免交；日期不完整時不猜測截止時間；只有日期的作業使用 23:59。
- 提交確認需能辨識相同課程及作業名稱；HW1 不會套用到 HW10，課程不明時保守地保留待交。僅根據通知信判定，不會向 e3 提交作業。
- 已繳事件只對有本程式識別標記的事件加上 ✅ 並取消提醒；私人事件維持原內容。已刪事件不重建。
- 舊 NYCU 自動化事件需同時驗證課程、來源及自動同步標記，才會承接已繳完成及取消提醒；不接管一般私人事件。
- 日曆以本機 event ID、Google 私有 key、來源及標題查重，新事件另使用穩定 ID，避免插入成功但本機紀錄失敗造成重複。
- 支援 `Nov 17 23:59`、`9 November 2026, 11:59 PM` 等常見日期；Moodle 合併到期提醒按每項作業的課程、名稱及 activity 連結拆分，避免把名稱中的實驗日期當截止日。
- 與舊日曆來源比對時，會處理 HTML 字元、字面換行、頁面錨點及 Moodle `action=view` 參數，避免舊事件因格式差異被重複新增。
- 影片以來源連結去重；已觀看狀態不被新一輪掃描重設；僅「預計上傳」不列為已可觀看。

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

這些測試使用虛構資料與假的 Google API，不會觸碰私人 Gmail／Calendar。完整實機成功驗證仍須 OAuth 有效。工具只讀取 Gmail 通知，沒有直接登入 e3 網站，不能涵蓋未寄信的公告。舊 ChatGPT 同功能排程需在本機同步驗證完成後停用；本機安裝不會自動更改 ChatGPT 雲端排程。
