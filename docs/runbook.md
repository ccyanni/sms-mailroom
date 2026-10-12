# Mailroom 操作手冊

正體中文 | [English](./runbook.en.md)

說明如何在 Mac mini 上執行、檢查和調整 Mailroom。

用詞對照（定義見 `CONTEXT.md`）：模組＝Modem、簡訊＝Message、轉發＝Forwarding、異常通知＝Alert。

## 安裝了哪些東西

| 項目 | 位置 |
|---|---|
| Mailroom 服務 | launchd 系統服務 `us.b612.mailroom`（`/Library/LaunchDaemons/us.b612.mailroom.plist`），以擁有者的帳號執行，使用這個專案的 `.venv` |
| 網頁 | `https://mailroom.example.com`，經由 Cloudflare Tunnel 連到 `127.0.0.1:8000`，由 Cloudflare Access 保護 |
| Tunnel | `cloudflared`，另一個 launchd 系統服務（`com.cloudflare.cloudflared`） |
| 設定檔 | `~/Library/Application Support/Mailroom/config.toml`（僅限本人讀取，內含 Telegram 機器人的 token） |
| 資料庫 | `~/Library/Application Support/Mailroom/mailroom.db` |
| 備份 | `~/Library/Application Support/Mailroom/backups/`，每天一份，保留 14 份，僅限本人讀取 |
| 紀錄檔 | `~/Library/Logs/Mailroom/mailroom.log`（滿 5 MB 自動輪替，保留三份舊檔） |

兩個服務都在開機時啟動，不需要先登入；停止時會自動重新啟動。

## 日常操作

- **確認是否正常運作：** 打開網頁，切到「狀態」分頁。每張 SIM 一張卡片，顯示業者、訊號和註冊狀態；下方列出接著的模組，以及系統本身的狀態（服務、Telegram、macOS 網路服務、USB 連線、存取保護）。有異常時最上方會出現黃色方框，「狀態」分頁的圖示上也會有紅點，同一則內容會發到 Telegram。
- **整理簡訊：** 在「簡訊」分頁點一則簡訊可以展開全文。有用的按「封存」，移到「已封存」；沒用的按「刪除」。要一次刪除多則，按「選取」後勾選，或先搜尋再按「全選」。
- **語言與外觀：** 右上角的齒輪圖示可以切換中文／English，以及跟隨系統、淺色、深色。
- **啟動通知：** 服務每次啟動後約 15 秒，會在 Telegram 發一則「🟢 Mailroom 已啟動」，說明是電腦剛重新開機還是只有服務重啟，以及接上幾片模組、幾張 SIM 正常收訊。沒有預期卻收到這則通知，表示服務當掉後自動重啟了，請查看紀錄。
- **查看紀錄：** `tail -f ~/Library/Logs/Mailroom/mailroom.log`
- **重新啟動**（修改 `config.toml` 或更新程式之後）：`sudo launchctl kickstart -k system/us.b612.mailroom`
- **停止並移除服務：** `sudo scripts/install-service.sh uninstall`
- **安裝或重新安裝服務：** `sudo scripts/install-service.sh`。`config.toml` 裡沒有 `[access]` 設定時，腳本會拒絕安裝，因為那樣 Tunnel 會把網頁直接暴露在外。
- **更新程式：** 取得新版程式碼，執行 `uv sync`，執行 `uv run pytest`，然後重新啟動服務。

在 Mac mini 上直接開 `http://127.0.0.1:8000` 會得到 403：所有請求都必須經過 Cloudflare Access。

## 備份與還原

服務啟動時，以及之後每天（台北時間換日後）會備份一次資料庫，檔名是 `mailroom-YYYY-MM-DD.db`，超過保留份數的舊檔會自動刪除。「狀態」分頁的系統卡片會顯示最近一次備份的日期；備份失敗時會標示出來。

備份放在同一台電腦上，可以救回損毀或誤刪的資料庫，但救不了硬碟故障。需要異地備份的話，請把備份資料夾納入 Time Machine，或在設定檔把 `directory` 指到別的磁碟。備份檔含有簡訊的明文內容。

還原的步驟：

```bash
sudo launchctl bootout system/us.b612.mailroom            # 停止服務
cd ~/Library/Application\ Support/Mailroom
mv mailroom.db mailroom.db.broken                         # 保留現有的資料庫，以防萬一
cp backups/mailroom-2026-10-12.db mailroom.db             # 換成要還原的那一天
cd <專案資料夾> && sudo scripts/install-service.sh         # 重新啟動服務
```

備份之後才收到的簡訊不在備份裡；它們在 Telegram 聊天室中仍然看得到。

## 硬體

- **天線：** 接在標示 `MANT` 的天線座。`GPS` 和 `BT` 兩個座用不到；天線接到這兩個座會完全沒有訊號。
- **重新插上模組：** 拔掉後等 5 到 8 秒再插回去。太快插回，板子可能有電但模組沒有啟動。
- **更換 SIM 卡：** 先拔掉模組，換卡，等幾秒，再插回去。新的 SIM 會自動登記；不論插在哪一片模組上，SIM 的名稱、轉發設定和簡訊紀錄都跟著它走。
- **增加模組：** 直接插上即可，Mailroom 會在幾秒內接手。
- **USB 集線器：** 請接上獨立的 5 V 電源。模組如果一直從 USB 上掉線，會收到「keeps disconnecting」的異常通知；請檢查集線器、它的電源和線材，或把模組直接插在 Mac 上。

## 設定檔

`config.toml` 裡 Mailroom 會讀取的所有區段：

```toml
language = "zh"     # 選填；"zh" 或 "en"。Telegram 訊息用這個語言，網頁在你另外選擇之前也用它

[telegram]
token = "<向 @BotFather 申請的機器人 token>"
chat_id = "<擁有者的聊天室 ID>"

[access]
team_domain = "<團隊名稱>.cloudflareaccess.com"
audience = "<Access 應用程式的 AUD 標籤>"

[alerts]
after_minutes = 3   # 選填；問題持續多久之後才發異常通知

[backup]
directory = "~/Library/Application Support/Mailroom/backups"   # 選填；備份放在哪裡
keep = 14           # 選填；保留幾份
```

沒有 `[telegram]` 時，簡訊只存檔、不轉發。沒有 `[access]` 時，網頁會鎖住。

## 從零開始設定

1. **Telegram 機器人。** 在 Telegram 對 `@BotFather` 傳送 `/newbot`，記下 token。打開新的機器人，按 Start，再隨便傳一則訊息。聊天室 ID 是 `https://api.telegram.org/bot<token>/getUpdates` 回應裡的 `chat.id`。
2. **Tunnel。** 安裝 `cloudflared`（`brew install cloudflared`）。在 Cloudflare Zero Trust 後台建立一個 Tunnel，執行它顯示的 `cloudflared service install` 指令，再新增一個公開主機名稱，指向 `http://localhost:8000`。
3. **Access。** 在 Zero Trust 新增一個自架（self-hosted）的 Access 應用程式，網域填同一個主機名稱，政策設為只允許擁有者的電子郵件。記下團隊網域和應用程式的 AUD 標籤。用無痕視窗打開該網址，確認會被導向登入頁；如果沒有，表示網頁沒有受到保護。
4. **設定檔。** 依上一節的格式寫好 `config.toml`，並執行 `chmod 600`。
5. **macOS 網路服務。** 在「系統設定 → 網路」停用「A76XX Series LTE Module」，確保 Mac 不會透過 SIM 卡上網。這個服務一旦被啟用，Mailroom 會發異常通知。
6. **服務。** 執行 `uv sync`，再執行 `sudo scripts/install-service.sh`。
7. **檢查。** 從公開網址登入，傳一則簡訊到其中一張 SIM，確認它出現在網頁和 Telegram。

## 已知的行為

- 模組偶爾會回報讀取錯誤，Mailroom 會重試並繼續運作。如果一連串讀取錯誤之後模組就消失，問題多半出在 USB 集線器。
- 漫遊中的 SIM 有時會晚幾分鐘才收到簡訊，或同一則收到兩次。寄件者、電信網路標記的時間和內容都相同的重複簡訊，只會存一筆。
- 在網頁上刪除的簡訊無法復原。
