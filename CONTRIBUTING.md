# 貢獻指南

感謝協助改善 NYCU/e3 課業提醒。請以 **匿名／虛構** 郵件與課程資料撰寫測試，不得上傳真實 Google OAuth 憑證、學號、姓名、私人附件、信件內文或行事曆匯出。

## 工作流程

1. Fork 儲存庫，建立 feature branch。
2. 安裝 `python -m pip install -e '.[dev]'`，執行 `pytest -q`。
3. 新增 parser 規則時，附上**虛構資料**的通過案例與不應誤判的反例。
4. Calendar 同步變更須確保事件去重、僅改動本程式建立的事件，以及支援 dry-run。
5. PR 描述需說明支援的郵件格式、預期行為與限制。

## 安全回報

如發現可能洩漏 token、過度 Gmail 權限、非預期修改 Calendar 等安全問題，先使用 GitHub 私下安全通報（Security advisory），避免在公開 Issue 貼出可重現的真實憑證。