# LocWarp「只需 iOS App」可行性評估

**對象**：Ravi Wu ｜ **日期**：2026-09-19 ｜ **repo HEAD**：`052d6ba`
**評估問題**：把 LocWarp 的 **書籤**（`frontend/src/i18n/strings.ts:212`）、**瞬間移動**（`:152`）、**多點導航**（`:155`）三個功能，改成只需要一支裝在 iPhone 上的 native App 就能完成，可以怎麼做？

**本報告的證據規則**：每個決策級論述都附 `path:line` 或可點連結。研究過程中被獨立 verifier 判定為 refuted 的說法一律不當事實使用，只列在 §9 附錄。矛盾的地方不取平均，直接攤開並說明哪一邊證據較強。授權段落是分析，不是法律意見。

---

## 0. 結論先行

### 總結論：**可行，但是 T1（需要一次性且會週期性重來的電腦 bootstrap），不是 T0**

機制本身**已經被證明可以完全跑在 iPhone 上**——不是理論，已被現行 OSS app（StikDebug、Locus）實作並有真實使用者，但使用規模未經量測（StikDebug 已被 Apple 下架）。擋路的是三件維運事實——**pairing file 會在不可預期的時間過期**、**簽章會過期**、**iOS 27 目前有未證實的 DDI 失敗回報**——再加上一個 iOS 平台限制：**背景執行**，這是多點導航唯一有實測失敗紀錄的項目。

### 逐功能結論

| 功能 | T-tier | 一句話結論 |
|------|--------|-----------|
| **書籤** | **T1**（一次性＋簽章週期） | 零裝置協定相依，唯一「未解缺口」（timezone polygon）已被 `tzf-swift` 關閉。可獨立先做、先出貨，但 App 本身仍需 Mac 建置與簽章——本案沒有任何功能嚴格達到 T0。 |
| **瞬間移動** | **T1（週期性）** | 機制完整可行且已被 OSS 實作，但**不是 set-and-forget**：模擬位置綁在 live DVT 連線上，App 死掉就還原真實 GPS。StikDebug 每 4 秒重送一次同一個座標。 |
| **多點導航** | **T1（週期性）＋可靠性未證實** | 移動數學可 1:1 移植且有 bit-exact golden vectors；on-device 多點播放**已被 StikDebug 實作**（不是空白）。真正的風險是「鎖屏＋別的 App 在前景、連續數十分鐘 1Hz」能不能活著——現有唯一的實測回報是**失敗**。 |

### 建議路徑

先做 **Phase 0 拋棄式實機 spike**（§7），用現成的 StikDebug + LocalDevVPN 在 Ravi 自己的手機上把三件事量出來：DDI 能不能掛、鎖屏連續推送能撐多久、pairing file 活多久。**不寫任何要保留的 App 程式碼**。spike 過了才進 Plan-First；spike 沒過就只做書籤（T0，本來就獨立），移動功能留在 Mac。

### Top 3 風險

1. **iOS 27 上目前有一則未經證實的 DDI mount 失敗回報，且沒有任何成功案例**。StikDebug issue [#464](https://github.com/StikDebug/StikDebug/issues/464)「On the ios27 system, ddi mount failed」**今天（2026-09-19）開的，open，零留言，單一回報者**；同期兩則直球提問 #461/#463 都被關掉且零回覆——狀態是**未證實**，不是已確認損壞，但公開資料裡也找不到反例。iOS 27 已於 2026-09-14 公開上市（不是 beta）。整個 DDI 供應鏈依賴一個志工 GitHub mirror，最後更新 2026-08-07，內容是 iOS 27 **beta** build `27A5228h`，是這個回報最可能的成因（分析，非已證實）。
2. **Apple 帳號風險不是理論**。StikDebug 開發者的 Apple Developer Program 帳號被終止，App 於 2025-12-18 從 173/175 個 storefront 下架；2025-08-26 的撤銷潮打到了**自稱只用帳號讀文件與測試自己 App、從未公開散佈**的開發者。這不是「上架被拒」的風險，是「$99 帳號沒了」的風險。
3. **背景執行沒有乾淨解**。StikDebug 已經把所有招式用完（always-location + 無聲音訊 + beginBackgroundTask + `UIBackgroundModes = audio, location, fetch`），issue [#458](https://github.com/StikDebug/StikDebug/issues/458)（2026-09-06、iOS 26.5）仍回報被系統砍掉。而其中最有效的一招（無聲音訊）是 App Store Guideline 2.5.4 的教科書級拒絕理由。

### Ravi 必須先決定的四件事

1. **手機現在跑什麼 iOS？** 26.x 還是 27.0？這一題直接決定 spike 是「今天可做」還是「等上游修」。
2. **接受週期性的 Mac 動作嗎？**（pairing file 隨機過期 + 簽章過期）真正的 T0 沒有證據支持。
3. **Mac 版要留著嗎？** 這一題決定書籤要不要保留整套 CRDT（見 §5.1）——留著就必須完整移植，不留就可以直接砍掉 496 行合併邏輯。
4. **分發通道**：個人自用走自簽 sideload；家人用 **TestFlight-Internal**（家人加為 Limited-Access team member）——Apple 官方定義「TestFlight App Review」只適用於 external tester，internal 不會觸發具名審查（見 §4.3）。絕對避免 External tester；App Store 完全不可能。Ad Hoc 是零審查的保守備案。

---

## 1. 問題定義

### 1.1 T0 / T1 / T2 的判準

| Tier | 定義 | 本案對應 |
|------|------|---------|
| **T0** | 電腦**從未**介入，一次都沒有 | 本案沒有任何功能嚴格達到 T0 |
| **T1** | 一次性電腦 bootstrap，之後純手機 | 瞬間移動 / 多點導航的**實際**位置 |
| **T2** | 每個 session 都要電腦 | Ravi 明示不接受；LocWarp 現況即是 |

**App 本身的建置與簽章永遠需要 Mac + Xcode**，因此嚴格說本案沒有任何功能是 T0。書籤真正的優勢不是「T0」，而是**不繼承 pairing file / DDI / 背景執行這三條裝置協定風險**——它只受一般 App 簽章週期的影響，跟瞬間移動/多點導航額外背負的 pairing-file 隨機過期完全無關。

**本報告新增一個必要的細分：T1-recurring（週期性 T1）。** 把「一次性」當成「一次就好」會誤導決策，因為有兩個獨立的到期時鐘：

- **pairing file**：StikDebug 官方指南原文——裝置更新或重置會失效，而且「**This also occurs at random times.** This is simply because of how Apple's software works, and there is nothing we can do at this point to fix it.」（[StikDebug-Guide/pairing_file.md](https://github.com/StikDebug/StikDebug-Guide/blob/main/pairing_file.md)）
- **簽章 / provisioning profile**：Apple DTS Engineer 在 [forums/thread/796061](https://developer.apple.com/forums/thread/796061)（Aug '25）明說「In-house provisioning profiles expire after a year, **ad hoc after 90 days**, and personal provisioning profiles expire after 7 days」。付費帳號的 **development** profile 期限 Apple 沒有任何頁面明文說明（社群傳說 1 年，未經證實）。

所以誠實的標示是：**T1-recurring**，Mac 必須長期保持可用，不是 bootstrap 完就能丟掉。

### 1.2 三個功能今天在 LocWarp 裡的樣子

| 功能 | 主要模組 | 規模 | 裝置協定相依 |
|------|---------|------|------------|
| **書籤** | `backend/services/bookmarks.py`、`domain/store_merge.py`(391)、`domain/catalog_merge.py`(105)、`infra/persistence/json_store.py`、`services/bookmark_import.py`、`services/bookmark_export.py`(140)、`services/geo_offline.py`(162)、`services/cloud_sync.py`、`services/file_watcher.py`、`api/bookmarks.py` | 前端書籤相關 TSX/TS **約 4,500 LOC / 約 22 個元件與 hook**；資料模型 **14 欄位**（`backend/models/schemas.py:279-309`）；catalog seed **8 分類 / 140 書籤**；離線地理資料 **2.88 MB**（cities5000.json 2,780,911 B / 68,704 筆） | **零** |
| **瞬間移動** | `useSimActions.ts:192` → `useSimulation.ts:696,972` → `api.ts:212` → `api/location.py:116` → `simulation_engine.py:176` → `core/teleport.py:18` → `infra/device/location_service_port.py:14` → `services/location_service.py:223-241` | cooldown `services/cooldown.py` 129 LOC（純 server 端 UI gate，HTTP 429，**從不傳給 iPhone**） | **全部**（DVT LocationSimulation） |
| **多點導航** | `useSimulation.ts:1009` → `api.ts:258` → `api/location.py:231-244` → `simulation_engine.py:305-346` → `core/multi_stop.py:21`；共用 tick loop `simulation_engine.py:668`（`_move_along_route`，docstring 明寫「Core movement loop shared by navigate, loop, multi-stop, and random walk modes」） | `domain/movement.py` **523 LOC 純函式**，golden vectors 在 `tests/test_interpolator_golden.py`(90)；characterization suite `tests/test_multi_stop_cov.py`(512) + `tests/_engine_harness.py`(65) | **全部** |

**Tick 速率**（`backend/config.py:175-187`）：`update_interval = 0.5 if speed_mps > 5 else 1.0`，即 **1–2 Hz**。
**裝置寫入面**：`LocationSimulation.set(latitude, longitude)` 與 legacy `DtSimulateLocation.set()` **都只吃 lat/lng 兩個 float64**——沒有 altitude、accuracy、speed、heading。Swift 版繼承同樣限制。

### 1.3 現況起點

- **Repo 裡沒有任何 iOS 資產**：`find . -iname '*.swift' -o -iname '*.xcodeproj' -o -iname '*.xcworkspace'` 零結果，沒有 `ios/` 目錄。這是**從零寫一個 native App**，不是接續半成品。
- 測試基線：backend pytest 約 1,332 collected（2026-09-18 量測）；frontend Vitest 約 651 tests / 84 files。

### 1.4 明確不在範圍內

joystick（`core/joystick.py`，自有 200ms dead-reckoning loop，**不走** `_move_along_route`）、random walk、route loop、GPX 錄製回放、雙機 hand-off（`capture_resumable_snapshot`）、WiFi tunnel 探索 UI、cooldown 的 Pokémon-GO 語意、Electron 桌面殼。

---

## 2. 核心難題：iPhone 對自己下 location simulation

### 2.1 一句話版本

LocWarp 今天透過 pymobiledevice3 走 **DVT LocationSimulation**——Apple 私有的開發者工具通道。過去所有人的直覺是「這需要一台主機」。**這個直覺在 2025–2026 已經被推翻**：RemotePairing 協定從未規定 host 與 device 必須是兩台實體機器，而 iOS 的 **NetworkExtension packet-tunnel** 讓一個普通（非越獄、非私有 entitlement）App 可以造出 loopback，讓手機連上自己的 lockdownd。

### 2.2 機制鏈（ASCII）

```
┌──────────────────────── 同一支 iPhone，無任何外部主機 ────────────────────────┐
│                                                                              │
│   ┌──────────────────────┐                                                   │
│   │   LocWarp-iOS App    │  ① 讀 pairing file（RPPairing plist）              │
│   │  Swift + idevice FFI │     rp_pairing_file_read()                        │
│   └───────────┬──────────┘                                                   │
│               │ ② TCP connect → 10.7.0.1 : 49152                             │
│               ▼                                                              │
│   ┌──────────────────────────────────────────────┐                           │
│   │  NEPacketTunnelProvider（loopback VPN）       │  LocalDevVPN 或自建        │
│   │  utun 介面 10.7.0.0/24                        │                           │
│   │  NAT：src 10.7.0.0 ⇄ dst 10.7.0.1（IP 標頭交換）│ ③ 封包原地折返             │
│   └───────────┬──────────────────────────────────┘                           │
│               │ ④ 交回本機 listener（沒有第二台機器）                           │
│               ▼                                                              │
│   ┌──────────────────────────────────────────────┐                           │
│   │  remoted / RemotePairing service :49152       │  ⑤ pairing handshake      │
│   └───────────┬──────────────────────────────────┘     （用 pairing 金鑰）     │
│               │ ⑥ 第二條 TCP，包在 TLS-PSK tunnel（PSK = pairing 推導金鑰）      │
│               ▼                                                              │
│   ┌──────────────────────────────────────────────┐                           │
│   │  RSD（Remote Service Discovery）handshake      │  ⑦ 列舉可用服務            │
│   └───────────┬──────────────────────────────────┘                           │
│               │ ⑧ 前提：Personalized DDI 已掛載 ←── iOS 27 有未證實的失敗回報   │
│               ▼                                                              │
│   ┌──────────────────────────────────────────────┐                           │
│   │  DTServiceHub → DVT / DTX channel             │                           │
│   │  "com.apple.instruments.server.services.      │                           │
│   │                      LocationSimulation"      │                           │
│   └───────────┬──────────────────────────────────┘                           │
│               │ ⑨ simulateLocationWithLatitude:longitude:（期待回覆）           │
│               │    stopLocationSimulation（fire-and-forget，無確認）            │
│               ▼                                                              │
│   ┌──────────────────────────────────────────────┐                           │
│   │  CoreLocation → 全系統定位（所有 App 都看到）    │  ⑩ 必須維持連線才持續      │
│   └──────────────────────────────────────────────┘                           │
└──────────────────────────────────────────────────────────────────────────────┘

外部依賴（決定 T-tier 的全部原因）：
  ┌ Mac/PC + iloader 或 idevice_pair ──USB/Wi-Fi──▶ 產生 pairing file   ← T1，且隨機過期
  ├ Mac + Xcode ────────────────────────────────▶ 簽章並安裝 App        ← T1，且會過期
  ├ github.com/doronz88/DeveloperDiskImage ─HTTPS─▶ 基礎 DDI 映像        ← 志工 mirror，落後 Apple
  └ gs.apple.com/TSS/controller?action=2 ──HTTP──▶ DDI 個人化簽章        ← 手機自己直接發，不需電腦
```

### 2.3 今天的 OSS 現況：不是缺口，是已經做好了

這是本次評估**推翻最多前提**的一段。

| 元件 | 專案 | 授權 | 事實 |
|------|------|------|------|
| Rust 協定核心 | [jkcoxson/idevice](https://github.com/jkcoxson/idevice) | **MIT** | `idevice/src/services/dvt/location_simulation.rs:63-110` 開 DVT channel 並送 `simulateLocationWithLatitude:longitude:` / `stopLocationSimulation`。C-ABI FFI `location_simulation_new/_set/_clear/_free` 已 `#[unsafe(no_mangle)] extern "C"` 匯出，Swift 可直接呼叫。HEAD `d32c818`（2026-09-14），v0.1.68 於 2026-09-15 發佈。 |
| iOS 打包 | idevice release asset | MIT | `idevice-xcframework-v0.1.68.zip` 是 release 資產。`swift/Package.swift` 宣告 `.binaryTarget`，平台 `.iOS(.v12)`；**但實際裝置 slice 用 `IPHONEOS_DEPLOYMENT_TARGET=17.0` 編譯**（`justfile:67`），所以真正下限是 **iOS 17**。 |
| loopback tunnel | [LocalDevVPN](https://apps.apple.com/us/app/localdevvpn/id6755608044) | MIT 系 | **現在還活在 App Store 上**，Developer Tools 分類、免費、v1.3.0、iOS 14.0+、賣家 **Coxson Engineering LLC**（組織帳號）。整個 provider 只做一件事：交換 IPv4 標頭的 src/dst（`TunnelProv/PacketTunnelProvider.swift`）。 |
| 完整參考實作 | [StikDebug](https://github.com/StikDebug/StikDebug) | **AGPL-3.0** | 已內建 Location Simulator。**而且已經內建書籤與路線播放**（見下）。 |
| 另一個參考 | [RicePollution/Locus](https://github.com/RicePollution/Locus) | **MIT** | 「Fully on-device」，用 idevice FFI 打 DVT，需搭配 LocalDevVPN。MIT 授權這點很重要（見 §6）。 |

**關鍵發現：StikDebug 已經實作了 Ravi 要的三件事中的兩件半。**

- **書籤**：`StikDebug/Views/MapSelectionView.swift:683` `struct LocationBookmark: Identifiable, Codable`，JSON 落地（:1047-1052）、新增（:1060-1065）、列表刪除（:1819-1854）。
- **瞬間移動**：`IdeviceFFIBridge.swift:757-845` 完整 handshake + `location_simulation_set`。
- **路線播放**：`MapSelectionView.swift:1523-1560` `startRoutePlayback()`，逐 sample `Task.sleep(for: .seconds(sample.delayFromPrevious))`，tick 預設 **0.5 秒（2 Hz），與 LocWarp 在 >5 m/s 時的間隔相同**（LocWarp 步行速度則是 1.0 秒），含 OSM 速限查詢；可匯入 GPX / GeoJSON / JSON / CSV。
- **唯一真正缺的**：App 內多點挑選 UI——`RouteSearchField { case start; case end }`（:32-35）只有起點/終點兩欄，MKDirections 也是 start→end（:1448）。匯入 GPX polyline 可以涵蓋任意多點播放。

所以「需要自己從頭寫一個 App 才能取代三個功能」是**過度悲觀**的說法。誠實的差距是**一個 UI affordance**，不是三個功能。

### 2.4 iOS 版本矩陣

| iOS | 機制狀態 | 證據 |
|-----|---------|------|
| ≤ 17.3 | **不支援** | StikDebug README:50「Uses Different Connection Protocols」 |
| 17.4 – 18.x | **Fully supported / Stable** | StikDebug README:51 |
| 26.0+ | **Supported**，但「Limited App Availability」 | StikDebug README:52 |
| **27.0（現行公開版）** | **未證實，且有未解 bug** | 見下 |

**iOS 27 的真實狀態（截至 2026-09-19）**：

- iOS 27 **已於 2026-09-14 公開發佈**，不是 beta。2026-09-16 釋出的是 iOS 27.2 developer beta 1（9to5Mac 原文：「The update follows the release of iOS 27 to everyone on Monday.」）。
- pymobiledevice3 維護者唯一一次「still works」的確認是 **iOS 26**，日期 **2025-09-28**（[discussions/1463](https://github.com/doronz88/pymobiledevice3/discussions/1463)）——整整一年前，完全沒有涵蓋 iOS 27。
- StikDebug 兩個直球提問 issue [#461](https://github.com/StikDebug/StikDebug/issues/461)（iPadOS 27，2026-09-14 開）與 #463（2026-09-17）**都被關掉、零留言、零答案**。
- **issue [#464](https://github.com/StikDebug/StikDebug/issues/464)「On the ios27 system, ddi mount failed」，2026-09-19 今天開的，狀態 open，零留言**，回報者 iOS 27.0 / StikDebug 3.1.10，重匯入 pairing file 仍失敗。
- **最可能的原因（分析，非已證實）**：DDI 供應鏈落後。基礎 DDI 來自志工 mirror `doronz88/DeveloperDiskImage`，最後一次更新是 **2026-08-07「Update DDIs to 27A5228h」**——`27A5228h` 是 iOS 27 的 **beta** build train。GA 版 iOS 27 需要對應的 DDI 才能通過 TSS 個人化。

> **決策意義**：LocWarp-iOS 會繼承一個硬相依——每次 iOS 大版本更新後，都要等一個第三方志工重新上傳 Apple 的 DDI。這是 Ravi 無法控制、也無法用錢解決的外部相依。

### 2.5 持續性與 keep-alive 語意（最常被誤解的一段）

**模擬位置不是「寫入後就留著」，它綁在 live 連線上。**

- idevice 模組文件原文（`location_simulation.rs:4-5`）：「**Note that a connection must be maintained to keep location simulated.**」
- pymobiledevice3 的 CLI 自己就這樣寫：`cli/developer/dvt/simulate_location.py:36-38` 在 `set()` 之後**刻意 block**（POSIX 上是 `signal.sigwait([SIGINT, SIGTERM])`），全程持有 DvtProvider/LocationSimulation context 不放。
- StikDebug 的答案是 **每 4 秒 Timer 重送同一個座標**（`MapSelectionView.swift:1380-1389`），連單點靜態模擬也這樣做。
- LocWarp 桌面版本來就假設了這個限制：`DvtLocationService` 持有長連線並有 `_reconnect()`（`location_service.py:148`），`_move_along_route` 每 tick 推新座標而非設一次。

**版本相依的細節**（重要，避免寫錯設計）：持續性行為在 iOS 18 前後改過。Apple forum [thread/698147](https://developer.apple.com/forums/thread/698147) 有開發者回報 iOS 18 上「拔線就失去模擬」，而「幾個月前」拔線後模擬仍留著直到重開機。所以：**iOS 18+ 斷線即還原真實 GPS**（對 Ravi 來說其實是安全的失效模式），但這是 Apple 的行為、不是架構保證。沒有任何一則回報顯示模擬能撐過完整重開機。

**背景執行——這是多點導航的真正風險：**

StikDebug 把能用的招都用了，而且預設全開：

- `BackgroundLocationManager.swift:18-21`：`allowsBackgroundLocationUpdates = true`、`pausesLocationUpdatesAutomatically = false`、`requestAlwaysAuthorization`
- `BackgroundAudioManager.swift`：AVAudioEngine 無聲音訊 keepalive，`AppBootstrapper.swift:25-26` 兩者預設 `true`
- `Info.plist:24-29`：`UIBackgroundModes = audio, location, fetch`
- `MapSelectionView.swift:1369-1372`：`beginBackgroundTask`

**結果**：issue [#458](https://github.com/StikDebug/StikDebug/issues/458)（2026-09-06、iPhone 11 / iOS 26.5 / StikDebug 3.1.10）原文——「iOS still kills stikdebug in the background even if I have location set to always and silent noise enabled」，`all background anti-kills on`。2026-09-17 關閉，**無維護者回覆**。

同期社群 PR [#432](https://github.com/StikDebug/StikDebug/pull/432)（把無聲音訊從「數位靜音」改成約 -80 dBFS 讓 iOS 不回收 audio session、並讓 keepalive lease 強制持有）於 2026-09-04 被維護者 **closed unmerged**，理由是「I'd prefer to implement these changes differently」。兩天後 #458 就出現。

**替代架構（尚未有任何 OSS 驗證）**：把 1 Hz mover loop 搬進 **packet-tunnel extension 自己的行程**。Apple DTS 在 [forums/thread/729227](https://developer.apple.com/forums/thread/729227) 明說「An NE appex runs in a separate process from the container app. The lifecycle of that process is independent of the container app... it's the system that controls when it starts and stops.」這條路的限制不是排程，而是 **50 MiB 的 jetsam 記憶體上限**（Apple DTS Quinn，[thread/73148](https://developer.apple.com/forums/thread/73148)，iOS 15.0 起 packet tunnel = 50 MiB，並警告「You should not hard code knowledge about these limits into your code」）以及 `noNetworkAvailable` / `unrecoverableNetworkChange` 的系統拆除。**這是 Phase 0 之後才值得做的第二個 spike。**

**其他 API 已排除**：`BGProcessingTask` 只在閒置/充電時跑幾分鐘，使用者一拿起手機就數秒內被要求結束。iOS 26 新增的 `BGContinuedProcessingTask` 已查證——限定「finite, user-initiated, atomic operations」並強制顯示系統 UI 進度條，不是無限 sub-second loop 的逃生口。

### 2.6 Developer Mode 與 pairing：iOS 27 有沒有解放 T0？

**Apple 官方（Developer Mode）**：「Developer Mode only appears in Settings if you initiate pairing or if you **previously paired the device to a Mac**.」（[enabling-developer-mode-on-a-device](https://developer.apple.com/documentation/xcode/enabling-developer-mode-on-a-device)）開啟後只有另一次明確的關閉開關 + 重開機才會取消，**一般重開機會保留**——所以 Developer Mode 本身是乾淨的一次性 T1。

**iOS 27 的新 pairing——這是本次評估最需要被講清楚的一點。**

Locus 的 README 主張 iOS 27 = T0：
> 「Settings → **Pair on this iPhone** advertises `_remotepairing-pairable-host._tcp`. Confirm the 6-digit code under Settings › Privacy & Security › Developer Mode › Pair with Host — **no computer**.」（iOS 18–26 則需「import an RPPairing file once from idevice_pair」）

**我去查了 Apple 自己怎麼說。Apple 的 Device Hub 文件（Xcode 27）原文**：
> 「**Upgrade your iPhone or iPad to iOS or iPadOS 27 or later to wirelessly pair it; otherwise, use a cable.**」
> 「First, ensure that the device is on the same Wi-Fi network as **your Mac** so that it can discover it.」
> 「Then click the Add Device button (+) in the toolbar and choose **Pair Nearby Device…**」
> 「In the Device Hub sheet, select the device that it discovers and click Next. In the next sheet, **enter the PIN that appears on your device**.」

**判讀（需要小心的地方）**：這段引文來自 Apple 對 **Xcode Device Hub 這一條配對路徑**的說明，必然是 Mac 中心的——它沒有、也不需要說明是否存在其他 host 端實作。**這頁本身既不能證實、也不能否證 Locus 的主張**：Locus 講的是另一個裝置端 UI（設定 → 在此 iPhone 上配對），而引文裡「enter the PIN that appears on your device」反而**佐證** iOS 27 確實新增了一條裝置端主動廣播、手機顯示 PIN 的無線配對路徑——正是 Locus 描述的機制。換句話說，Apple 的文件不排斥 Locus 的主張成立，只是完全沒有證據去確認它。

Locus 的 T0 主張建立在一個架構上成立、但無人獨立驗證的推論：既然手機現在會以 `_remotepairing-pairable-host._tcp` 對外廣播、而 loopback VPN 讓手機連得到自己，那麼同一支手機上的 App 就可以扮演「Mac」那一側完成配對。idevice 確實有對應的 responder 實作（`remote_pairing/responder.rs` 記錄了 iOS 27 由裝置發起配對的角色反轉流程）。

**結論（必須照實寫）**：**iOS 27 的 T0 pairing 是「有可能、架構自洽、但未經驗證」**——證據只有單一 OSS README，沒有 Apple 來源，StikDebug 官方指南也完全沒提。而且**目前是空論**：iOS 27 的 DDI 掛載現在就是壞的（#464）。在 spike 實測之前，**規劃一律以 T1 為準**。

---

## 3. 方案比較

### 3.1 評分規則（1–5，分數越高越好）

| 維度 | 5 分 | 1 分 |
|------|------|------|
| **達成 T-tier** | 已證實 T0 | T2 或做不到 |
| **iOS 版本風險** | 用公開 API，Apple 不會動 | 依賴私有通道 + 第三方 DDI mirror |
| **分發適配** | App Store 可上 | 需越獄 / 帳號有被終止先例 |
| **可靠性 / keep-alive** | 系統保證持續 | 有實測失敗回報 |
| **維護負擔** | 裝完不用管 | 多個到期時鐘 + 追上游 |
| **授權風險** | MIT/BSD 全可用 | GPL/AGPL 汙染或無合規路徑 |
| **工作量** | < 5 人日 | > 60 人日 |

### 3.2 五個架構

**方案 A — 純裝置端 T0（idevice + loopback VPN，完全不碰電腦）**
自建 Swift App 內嵌 idevice XCFramework 與自己的 `NEPacketTunnelProvider`，pairing 走 iOS 27 的「Pair on this iPhone」。
→ **唯一真正達成 Ravi 字面要求的方案，但 T0 那一環未經驗證，且 iOS 27 DDI 現在壞的。**

**方案 B — 一次性/週期性 Mac bootstrap + 手機端執行（T1）← 建議**
與 A 同一個技術堆疊，但誠實承認兩個到期時鐘：pairing file 用 `idevice_pair` 在 Mac 產生、App 用 Xcode 簽章安裝。執行期完全在手機上，Mac 不在迴圈內。
→ **這就是 StikDebug / Locus 今天在跑的形態，有真實使用者基數背書。**

**方案 C — iPhone 當 UI、Mac 或常駐小主機執行（T2）**
保留現有 Python backend，只把 UI 換成 iOS App。
→ 技術風險最低、可靠性最好，但**每個 session 都要有第二台機器通電**，Ravi 明示不接受。Raspberry Pi / 旅行路由器也一樣算 T2。

**方案 D — 非 DVT 路徑**
- **MFi GNSS 接收器**（Bad Elf 等）：真 T0、永久有效、零軟體風險，但它**轉發真實衛星定位，無法瞬間移動**——三個功能一個都不給，是另一個產品類別，不是本題的選項。
- **TrollStore + Geranium**（`CLSimulationManager` 私有 API + `com.apple.locationd.simulation` entitlement）：**已出局**——TrollStore 支援上限是 iOS 14.0 b2–16.6.1、16.7 RC、17.0，且官方說明 16.7.x 與 17.0.1+「will NEVER be supported」。涵蓋不到 iOS 26/27。
- **WPS MITM**（`acheong08/ios-location-spoofer`）：on-device packet tunnel 攔改 Apple Wi-Fi 定位回應。**不是 T0**（README 明寫需付費開發者帳號 + Xcode sideload），而且只騙得過 Wi-Fi AP 三角定位，**壓不過真實 GNSS 衛星定位**，戶外基本無效；還要使用者裝 .mobileconfig 並到「憑證信任設定」啟用 CA。另已於 2026-01-19 被 TestFlight 拒絕。
- **App 內模擬**（只在自己 App 內顯示假座標）：對書籤有意義，對「讓其他 App 看到」零價值。

**方案 E — 混合分階段：書籤先 iOS 化，移動功能暫留 Mac**
書籤是 T0 且零協定相依，可以獨立出貨；瞬間移動 / 多點導航等 spike 結果與 iOS 27 上游修復。
→ **不是妥協，是風險切割**：把唯一確定能做的事先做掉，不讓它被不確定的部分綁架。

### 3.3 評分表

| 維度（權重） | A 純 T0 | **B T1 bootstrap** | C companion host | D 非 DVT | E 混合分階段 |
|---|---|---|---|---|---|
| 達成 T-tier (×3) | 5（未證實） | **4** | 1 | 2（GNSS 給 5 但不含功能） | 4（書籤 5 / 移動 4） |
| iOS 版本風險 (×3) | 1 | **1** | 2 | 3 | 3（書籤段 5） |
| 分發適配 (×2) | 2 | **2** | 4 | 1 | 3 |
| 可靠性 / keep-alive (×3) | 2 | **2** | 5 | 2 | 4 |
| 維護負擔 (×2) | 2 | **2** | 4 | 3 | 3 |
| 授權風險 (×1) | 4 | **4** | 2（現況 GPL 問題未解） | 2 | 4 |
| 工作量 (×2) | 1 | **2** | 3 | 4 | 3 |
| **加權總分 /80** | **38** | **37** | **48** | **39** | **55** |
| 是否交付三個功能 | 是 | 是 | 是 | **否**（GNSS/WPS 皆給不出瞬移+多點導航） | 是 |

> **算式更正**：上一版本表格的總分（39/41/47/43）算錯，且錯誤的方向剛好會反轉排名——用同一張表自己的權重與分數重算，B（37）其實是五個選項裡**最低分**，C（48）最高，其次是 E（55，見下方獨立列——E 是跨欄混合方案，這裡補列它自己的加權總分）。原始分數表沒有「是否交付三個功能」這一列，這正是 D 能算出 39 分（高於 B）卻仍要出局的原因：本評分表本身沒有硬性把不交付功能的方案篩掉，純看加權分數會誤導。

### 3.4 建議與理由

**純看加權分數，排序是 E(55) > C(48) > D(39) > A(38) > B(37)。** 但兩個方案要先被篩掉，篩掉的理由不是分數，是硬約束：

- **C（companion host）出局**：雖然總分最高，但違反 Ravi 明示的「不接受 T2」硬約束——每個 session 都要有第二台機器通電。
- **D（非 DVT 路徑）出局**：雖然總分（39）高於 B，但**一個功能都交不出來**——GNSS 接收器轉發真實衛星定位、WPS MITM 壓不過真實 GNSS，兩者都無法瞬間移動或多點導航。分數高只是因為「風險低」，不代表「有用」。

篩掉 C、D 之後，剩下 A(38)、B(37)、E(55)。**E 分數最高，且已經是本報告從頭到尾建議的路徑**（§0、§3.2）：

1. **先做 Phase 0 spike**（§7），把三個未知數量掉。
2. **書籤獨立先行**（T1、零裝置協定相依，不依賴 spike 結果）。
3. **spike 通過** → 沿用 A/B 共用的技術堆疊（idevice + loopback VPN），做瞬間移動 + 多點導航；至於 pairing 是走 A 的裝置端自我配對（iOS 27，未證實）還是 B 的 Mac bootstrap，由 spike 當場的 iOS 版本與 DDI 掛載結果決定。
4. **spike 不通過** → 停在書籤，移動功能留 Mac 版；重新評估時機是上游修好 iOS 27 DDI。

不建議直接把 A（純 T0）當成規劃前提：唯一支持它的是一份 OSS README，而 Apple 自己的文件說 iOS 27 拿掉的是線不是電腦。把 T0 當成規劃前提，會在 pairing file 第一次隨機過期時整個方案失信——這也是為什麼即使 A 在分數上略勝 B，執行時仍應**以 T1（B 的假設）為預設**，A 只是「若 spike 證實可行」的加碼。

---

## 4. Apple Developer 帳號與分發

### 4.1 付費帳號買到什麼（與本案相關的部分）

Apple 的 membership 比較表（[compare-memberships](https://developer.apple.com/support/compare-memberships/)）：「On-device testing using Xcode」**免費與付費都有**。付費（$99/年）多出來的、與本案有關的是：

| 能力 | 免費 | 付費 ADP |
|------|------|---------|
| **Network Extension / Personal VPN capability** | ✗ | ✓ |
| TestFlight | ✗ | ✓ |
| 裝置註冊 100 台/產品族/會員年 | ✗ | ✓ |
| Certificates, Identifiers & Profiles | ✗ | ✓ |
| provisioning profile 效期 | 7 天 | 較長（見下） |

**Network Extension 是自助的，不需要 Apple 審批。** Apple 的 entitlement 文件原文：「To add this entitlement to an App Store app, **enable the Network Extensions capability in Xcode**」（只有 macOS Developer-ID 的 `*-systemextension` 路徑才有申請流程）。Apple DTS Engineer 在 [thread/819032](https://developer.apple.com/forums/thread/819032)（Mar '26）更直白：「**There is no approval process for creating an NE packet tunnel provider. Any paid developer can do that.**」

**部署面也是通的**：TN3134 的表格顯示 iOS packet tunnel provider 是 app extension、最低 iOS 9.0，唯一限制是「per-app mode requires managed device」——**沒有依分發通道或帳號類型的限制**。（相對地，iOS 的 app-proxy / content-filter / DNS-proxy 才限定 managed/supervised 裝置。）

**所以技術門檻是零，全部的障礙都是政策。**

### 4.2 但同一份 DTS 回覆也給了警告

同一則回覆接著說「don't try to use a packet tunnel provider for something other than VPN. See TN3120.」而 TN3120 原文：
> 「**Do not use a packet tunnel provider to host a network listener or proxy server.** There is no reasonable alternative here other than using one of the [Network] APIs. **This path is simply not a recommended use case** for a packet tunnel provider or any other Network Extension.」
> 「Packets that are read from [the tunnel] are meant to be sent over a tunnel connection to a remote server... **They are not meant to be dropped or re-injected back into the system.**」

LocalDevVPN 式的 loopback 正是後者。所以「no approval」的意思是**沒有申請表**，不是**官方認可用法**。

另外 DPLA 3.3.3(G) 保留了一手：「Your Application must not access the Network Extension Framework unless Your Application is primarily designed for providing networking capabilities, and **You have received an entitlement from Apple**」，且「Apple reserves the right to not provide You with an entitlement... **and to revoke such entitlement at any time**」，**in its sole discretion**。（DPLA 最後更新 2026-08-18。）

### 4.3 分發通道比較

| 通道 | 可行性 | 關鍵事實 |
|------|--------|---------|
| **Xcode dev-signed（自簽 sideload）** | 個人自用最簡單的路徑 | 需 Mac + Xcode 每次重簽。Developer Mode 需先與 Mac 配對過。 |
| **Ad Hoc** | 可行、**零審查、最保守** | 100 台/產品族/會員年，停用裝置不回補額度，只有年度重置才回補。**Apple DTS 明說 ad hoc profile 90 天到期**。裝置需手動收集 UDID、換機要重新簽；完全不碰任何 Apple 審查或自動掃描系統。 |
| **TestFlight — Internal** | **建議：給家人用的路徑** | Apple 官方 glossary 原文：「**TestFlight App Review is the process of reviewing apps distributed to external testers using TestFlight.**」——字面上把審查範圍限定在 external，完全沒提 internal。build-status 參考頁把「distributed to internal testers」列為與「submitted to TestFlight App Review」**不同的分支**（[app-build-statuses](https://developer.apple.com/help/app-store-connect/reference/app-uploads/app-build-statuses/)）。Internal tester 必須是 App Store Connect 團隊成員，但可用 **Limited Access + Developer/App Manager 角色**把家人鎖死在只看得到這一個 App、看不到其他 App 或財務資料；team member 不額外收費，含在既有 $99/年裡。仍會過 Apple 上傳時的自動掃描（無效二進位／entitlement／私有 API 檢查），但那是機械式門檻，跟 Guideline 1.1.6「假造位置」這種人工判斷無關。 |
| **TestFlight — External** | **不建議，且有直接反例** | 只有 external 才會觸發**具名的「TestFlight App Review」**，且審查標準等同正式 App Review Guidelines（1.1.6/5.4/2.5.4 全部適用）。`ios-location-spoofer` 2026-01-19 被拒（README 原文：「Apple has rejected this app from testflight」）——重新查證後**推論**（非 Apple 證實）是走了 external 路徑，因為 internal 定義上不會觸發具名審查；找不到任何 DVT/Instruments 式（非 WPS-MITM）定位模擬 App 送過 TestFlight 審查的紀錄，成功或失敗都沒有。 |
| **App Store** | **不可能** | 見下。 |

> **給 Ravi 的結論**：個人自用走自簽 sideload；家人用 **TestFlight-Internal**（把家人加為 Limited-Access team member），這是唯一同時滿足「零審查風險」與「自動更新」的路徑。**絕對不要用 External tester**——那是唯一會把 1.1.6/5.4/2.5.4 這幾條槍實際招來人工審查的通道。若想連 Apple 伺服器都完全不碰（比 TestFlight-Internal 更保守一級，但要手動收集 UDID、換機重簽、沒有自動更新），退回 **Ad Hoc**。

### 4.4 App Review 可行性：不行，有四條獨立的槍

（全部引自 2026-06-08 版 App Review Guidelines 與 DPLA）

1. **1.1.6**：「False information and features, including inaccurate device data or trick/joke functionality, such as **fake location trackers**. Stating that the app is 'for entertainment purposes' won't overcome this guideline.」
2. **2.5.1**：「Apps may only use **public APIs** and must run on the currently shipping OS.」（DVT LocationSimulation 是否算私有 API 是推論——Apple 沒有頁面這樣說——但這是 Instruments 的內部服務通道。）
3. **5.4**：「Apps offering VPN services must utilize the NEVPNManager API and **may only be offered by developers enrolled as an organization**.」→ 若 Ravi 是**個人**付費帳號，自帶 NE tunnel 的 App 上架直接被擋，與行為描述無關。（LocalDevVPN 能上架正是因為賣家是 Coxson Engineering **LLC**。）
4. **2.5.4 / 2.4.4**：無聲音訊 keepalive 是 2.5.4「background services only for their intended purposes」的教科書拒絕理由；要使用者去改系統設定則踩 2.4.4。

另有 **5.5（MDM）** 對需要安裝 .mobileconfig 的設計（方案 D 的 WPS MITM）另外設了組織限定門檻。

### 4.5 帳號風險（這是本案最被低估的一項）

- **StikDebug**：2025-12-18 從 173/175 個測試 storefront 消失，2026-01-17 前全數下架（AppleCensorship：「Jan 8, 2026 Last seen available anywhere」）。開發者原文：「**Due to a recent Apple decision, my developer account is terminated**, so StikDebug is no longer on the App Store.」Apple 未公開理由。
- **2025-08-26 撤銷潮**：iDownloadBlog 報導，受影響開發者自述「only ever used their Apple Developer accounts for reading Apple documentation and writing and testing their own apps」且「never distributed their apps outside of Apple's approved methods」，申訴被駁回，規模被形容為「unprecedented」。
- **DPLA 11.2** 允許 Apple 在「misleading, fraudulent, improper, unlawful or dishonest act... including misrepresenting the nature of Your Application」時**立即終止**；其他違約給 30 天改正；任一方都可 30 天通知無理由終止。
- 另一則常被引用的「個人 sideload 被終止」案例（開發者 Alfie）**無法從主要來源證實**（onejailbreak.com 回 HTTP 403、archive.org 無快照）；而且從側面資料看，該開發者是 TrollInstallerX / TrollStore / TrollRestore 的作者，事件發生在 2026 年 1 月針對 sideloading 的執法潮中——**這不是乾淨的「無辜個人使用者」樣本**，不應拿來當作一般風險的證據。

> **誠實的風險陳述**：沒有任何公開資料證明「純自用、從不散佈的 dev-signed build」會招致終止。但也沒有資料證明它安全，而 2025-08 的撤銷潮顯示 Apple 的打擊範圍**不可靠地**侷限於公開散佈者。Ravi 應該把 $99 帳號視為**有非零損失機率的資產**來做決定。

### 4.6 續期雜務清單

| 項目 | 週期 | 需要什麼 |
|------|------|---------|
| ADP 會籍 | 每年 $99 | 到期前 30 天起可續，僅 Account Holder。**台灣不支援自動續期**（Ravi 的帳號地區未查證）。 |
| App 簽章 | ad hoc 90 天 / development 未明文（社群傳 1 年） | Mac + Xcode |
| **pairing file** | **隨機** | Mac/PC + `idevice_pair` 或 `iloader` |
| DDI | 每次 iOS 大版本 | 等志工 mirror 更新（不可控） |
| PPQ check-in | 首次啟動 | 2021-06-06 後建立的團隊需連 `ppq.apple.com`；離線 profile 僅 7 天；需離線超過 30 天要另外申請 |

---

## 5. 三個功能的 iOS 實作設計

### 5.1 書籤（T1 — 零裝置協定相依）

**架構**：SwiftUI + MapKit；資料層看 §「同步決策」。

**可 1:1 移植的純邏輯**（約 1,412 LOC Python → Swift）：

| 模組 | LOC | 備註 |
|------|-----|------|
| `domain/store_merge.py` | 391 | CRDT 核心，零 I/O |
| `domain/catalog_merge.py` | 105 | 三方合併，stdlib only |
| `domain/movement.py` | 523 | 給多點導航用 |
| `domain/recent.py` / `backup.py` / `coords.py` | 123 / 95 / 16 | |
| `services/bookmark_export.py` / `coord_format.py` | 140 / 19 | 去掉 I/O 的部分 |

**必須重寫的**：整個前端約 4,500 LOC 的書籤 UI（拖拉排序、多選、分類日期範圍、catalog diff 計數等邏輯**只存在於 frontend**，是唯一的 UX spec 來源）。

**必須換掉的（macOS 專屬，iOS 無對應）**：
- `services/file_watcher.py`（`watchdog.observers.Observer`；macOS fsevents 對同一路徑排第二個 Observer 會 `RuntimeError`）→ iOS 沒有常駐背景檔案監看 daemon。iOS 26 新增的 `BGContinuedProcessingTask` 已查證**不是**逃生口。改用 `NSMetadataQuery` / `NSFilePresenter` 或前景輪詢。
- `services/cloud_sync.py` 的 `materialize_if_placeholder()`——它 `subprocess.run(["brctl", "download", ...])`。**iOS 沒有 brctl。** 必須換成 `FileManager.startDownloadingUbiquitousItem(at:)` + `NSMetadataQuery` + `NSFileCoordinator`。
  > **這一條是隱藏地雷**：若沒換，iOS 端會把 `.icloud` placeholder 讀成空 store，餵進 CRDT merge，而空 store 對上真實 tombstone 正是 2026-09-18 事件裡丟掉 13 個 tombstone 的失效模式。`BackupService.tick` 的「bookmarks==0 AND routes==0 就整個跳過」保護必須原樣移植。

**離線地理資料（缺口已關閉）**：
- 城市/行政區：直接打包 `cities5000.json`（2,780,911 B / 68,704 筆）、`zone_to_country.json`、`admin1_names.json`，共 2.88 MB。
- **timezone polygon**：先前被標為「未解技術缺口」，**現已關閉**——[ringsaturn/tzf-swift](https://github.com/ringsaturn/tzf-swift) 是現成 Swift package，`Package.swift` 宣告 `.iOS(.v16)`、Swift 6.0，程式碼 MIT / 資料 ODbL-1.0，資料源自 `evansiroky/timezone-boundary-builder`（與 Python `timezonefinder==8.2.4` 同一血統），lite 資料集約 111 m 邊界誤差、**約 48 MB 常駐記憶體**。
  > 48 MB 常駐是設計約束：**如果 mover loop 最後要塞進 packet-tunnel extension（50 MiB jetsam 上限），tzf 絕對不能放在那個行程裡。**

**同步決策（必須 Ravi 拍板，見 §8）**：

- **若 Mac 版要留著**（兩台機器共用一個 iCloud Drive 資料夾）→ 整套 CRDT 必須完整移植，包含所有隱藏不變量：
  - per-unit LWW（`field_updated_at`）、三段 tiebreak（unit stamp → record `updated_at` → 對稱內容排序）
  - alive 判定：`ts is None or not (ts >= (obj.updated_at or ""))`
  - **空 `updated_at` 陷阱**：`updated_at = ""` 的項目永遠輸給有真實時間戳的 tombstone，`force_seed_items(items, now)` 就是為了打敗它而存在
  - tombstone 30 天 GC（`TOMBSTONE_RETENTION_DAYS = 30`）
  - `stamp_units()` 必須**把沒動到的 unit 回填成記錄的前一個 `updated_at`**，否則 per-unit 合併等於白做
  - catalog baseline **本機專屬、絕不進 sync folder**（`config.py`：「each Mac must bootstrap its own baseline independently」）
  - 合併的交換律/冪等性有隨機性質測試背書：`tests/test_store_merge_per_field.py:312-336`，`random.Random(20260827)`、300 輪、6 書籤隨機 store

  **iOS 端存取共享資料夾的正確做法（重要修正）**：`UIDocumentPickerViewController` 可以取得沙盒外的資料夾，但**不要用 security-scoped bookmark**——`NSURL.BookmarkCreationOptions.withSecurityScope` 在 iOS 上標示為 "Not available"（僅 macOS 10.7+/Mac Catalyst）。Apple DTS Quinn 原文：「Technically, **iOS doesn't support security-scoped bookmarks**... However, if you have access to a resource then you should be able to persist that access using a **regular bookmark**.」所以：`startAccessingSecurityScopedResource()` → `url.bookmarkData()`（**不帶 options**）→ 下次無 options 解析。
  > ~~**更簡單的替代方案**：`NSUbiquitousContainers`……~~ **（2026-09-19 撤回，見下方 D9）**：這條路是 App 自己的私有 ubiquity container，綁定單一 Apple ID，跨 Apple ID 的第二支裝置完全存取不到，只適用「同一 Apple ID 多裝置」這個現在已經不成立的假設。

  > **D9（2026-09-19 已拍板）：跨 Apple ID 書籤同步。** Ravi 確認之後登入的第二台裝置會是**不同 Apple ID**，兩個私有同步方案（本節的 `NSUbiquitousContainers` 與下方的 `CKSyncEngine`）都預設同一帳號多裝置，對跨帳號無效。**決定：iCloud Drive 共用資料夾**——Mac 端把現有 `sync_folder` 在 Finder 用「共享」邀請另一個 Apple ID，iOS 端就用上面那條「document picker + regular bookmark」路徑指向這個共用資料夾，`merge_stores` 與所有隱藏不變量**完全不用重寫**，只是容器換成共用資料夾而非私有 ubiquity container。**已驗證（2026-09-19, `locwarp-ios` Phase 1.0 spike，PASS）**：`NSFilePresenter` 在「共用（非自有）」iCloud 資料夾上的變更通知可靠——兩台實機、兩個不同 Apple ID 互寫，雙方都自動收到對方寫入的通知，不需輪詢。細節見 `~/personal/locwarp-ios/docs/plans/2026-09-19-phase1-bookmarks-plan.md`。

- **若不留 Mac 版**（只有一支 iPhone 寫這個 store）→ **整套 CRDT 是不需要的複雜度**，SwiftData 或單純本機檔案即可。這會省掉 ~496 LOC 最難移植、最容易寫錯的程式碼。
- **不要用 SwiftData + CloudKit 自動同步**：`NSPersistentCloudKitContainer` 是**整筆記錄 last-writer-wins，沒有欄位級或自訂合併的公開 API**（Apple WWDC19 session 202 原文：「Conflict resolution is implemented automatically by NSPersistentCloudKitContainer using a **last writer wins merge policy**」；2026-09 查證仍無自訂 API）。用了就是把 per-unit CRDT 降級回整筆 LWW。
- **若要走 CloudKit**，正確的層級是 **`CKSyncEngine`（iOS 17+）**，不是 SwiftData、也不是手刻 `CKModifyRecordsOperation`。Apple 文件原文：「CKSyncEngine does not handle errors that require application-specific logic. For example, if you try to save a record and get a `CKError.Code.serverRecordChanged`, **you need to handle that error yourself.**」——正好把三方合併的縫隙（`CKRecordChangedErrorClientRecordKey` / `ServerRecordKey` / `AncestorRecordKey`）留給 `merge_stores`，同時自己接手 change token、訂閱、批次（250 筆/請求）與重試。

**測試策略**：目前 `backend/tests/` **沒有** `fixtures/*.json` 或 `golden/` 目錄——跨語言 golden vectors 還不存在，要新建。做法：在 Python 端寫一個 exporter，把既有 merge 測試的輸入/輸出序列化成 JSON fixture，Swift Package test 讀同一份 fixture 斷言逐欄位相等。`test_store_merge_per_field.py` 的隨機性質測試用固定 seed `20260827`，可以在兩邊產生完全相同的序列。

### 5.2 瞬間移動（T1-recurring）

**架構**：`LocationSimulationClient` Swift wrapper → idevice FFI → 已快取的 DVT channel。

**設計要點（與桌面版不同的地方）**：

1. **不是一次性寫入。** 必須有 heartbeat。StikDebug 用 4 秒 Timer；沒有任何 Apple 文件說明安全的間隔上限，這個值要在 spike 量。
2. **channel 要快取重用**，不是每次呼叫都重建（`IdeviceFFIBridge.swift:757-765` 的模式：有快取就直接 `location_simulation_set`，失敗才走完整 handshake）。
3. **`stopLocationSimulation` 是 fire-and-forget**（`expects_reply=False`），單次 `clear()` 可能靜默失敗。LocWarp 桌面版已經知道這件事（`location_service.py:82-85`）並在所有 session 結束路徑（Restore、斷線、關閉）都明確 clear。iOS 端必須照抄這個防禦。
4. **cooldown 完全是 client 端 UI 邏輯**（`services/cooldown.py`，從不傳給 iPhone），可原樣移植成 Swift。
5. **API 面只有 lat/lng**，不要設計 altitude/accuracy 欄位。
6. **運作形態的意外後果**：因為要維持連線，「書籤 + 瞬間移動」**不能**是「按一下就退出 App」的動作——App、DVT channel、loopback VPN 三者都要活著。這跟多點導航是同一種運作形態，不是比較便宜的那種。
7. **諷刺但必要**：keepalive 需要真的跑一個 CoreLocation session，才能維持假造的位置。

### 5.3 多點導航（T1-recurring，可靠性待證）

**可 1:1 移植**：`domain/movement.py` 523 LOC 全部是 `@staticmethod` 純函式（haversine、bearing、interpolate、interpolate_with_timing、add_jitter、jitter_speed、move_point、random_point_in_radius），且有 **bit-exact golden vectors**（`tests/test_interpolator_golden.py`，90 行，斷言精確 float literal）。這是整份 codebase 裡移植信心最高的一塊。

**狀態機可 1:1 移植**：`core/multi_stop.py` 的停留規則——
`is_last = i == len(waypoints) - 2`；`stop_duration > 0` 優先，否則 `pause_enabled` 時取 `random.uniform(lo, hi)`，否則 0；`should_pause = this_pause > 0 and (not is_last or loop)`；停留用 `asyncio.wait_for(stop_event.wait(), timeout=...)` 所以**可被中斷**。
測試側 `tests/_engine_harness.py`(65 LOC) 的 FakeClock / SteppedSleep / RecordingLocation 三件組，**直接對應 Swift 的 ClockPort + mock Timer 設計**——這是照著移植就能用的測試骨架。

**路由服務——這裡有個常見的設計錯誤要避開**：

不要用 MKDirections 取代 OSRM。理由：
- `MKDirections.Request` **沒有 waypoints 屬性**（已查證 Apple 文件，成員只有 source / destination / transportType / highwayPreference / tollPreference / requestsAlternateRoutes / departureDate / arrivalDate）。多點只能逐段呼叫。
- **LocWarp 現在是整條路線一次請求**：`services/route_service.py:278-280` 把所有 waypoint 串成 `coords_str = ";".join(...)` 送一次 OSRM；Valhalla 送單一 `locations` 陣列；BRouter 用 `|` 串 `lonlats`。改用 MKDirections 等於 **1 次請求變成 N−1 次**、失去全域最佳化的路線幾何，還要面對 `MKError.Code.loadingThrottled`（Apple 唯一公開的節流訊號，無數字配額）。
- **正確做法**：iOS App 直接用 `URLSession` 呼叫原本的 OSRM FOSSGIS / Valhalla / BRouter。這些全是**免 API key 的純 HTTPS 端點**（`config.py:124-149`），iOS 呼叫它們毫無障礙。連 fallback 邏輯（`httpx.Timeout(8.0, connect=4.0)`、任何 HTTP 錯誤就走 `_straight_line_fallback`）都可以照搬。OSRM demo server 政策約 1 req/s、服務全域 5000 req/min、不保證可用性、禁止商業轉售。

**GPX**：`vincentneo/CoreGPX`（純 Foundation、XMLParser、GPX 1.1）可用，但 LocWarp 自己的 **track > route > waypoint 優先序**、以及「只有當每個 track point 都有 `<time>` 且 offset 單調遞增才回傳時間軸」的規則（`services/gpx_service.py:23-76`）是 CoreGPX **不提供**的，必須在上層重寫。

**GCJ-02 / WGS-84（若 Ravi 會在中國大陸用）**：MapKit 在中國大陸回傳 GCJ-02 座標，而注入路徑期待 WGS-84，誤差 **470–560 m**。兩個獨立的 iOS location-simulator 專案都撞到：StikDebug PR [#462](https://github.com/StikDebug/StikDebug/pull/462)（2026-09-15 以重複為由 **closed unmerged**，未修進去）與 Roam-Control issue #8（2026-09-15，**open**）。沒有任何 Apple API 可以偵測手上的座標是哪個基準面。

**背景執行**：見 §2.5。這是本功能唯一的紅燈，也是 Phase 0 spike 的主要目標。

---

## 6. 授權與法務風險

> **以下是分析，不是法律意見。** 若要公開散佈，請找真正的律師。

### 6.1 授權矩陣

| 專案 | 授權 | 對本案的意義 |
|------|------|------------|
| **LocWarp** | MIT（`LICENSE`：© 2026 keezxc1223，**上游作者、不是 Ravi**） | 重新授權不是 Ravi 單方面能決定的 |
| **idevice** | **MIT** | ✅ 可直接嵌入。`Cargo.toml:7 license = "MIT"` |
| **Locus** | **MIT** | ✅ Swift 層可參考/借用（fork 自 ChrisMack32/Locus，MIT） |
| **LocalDevVPN** | MIT 系（「StosVPN License」標頭） | ✅ 可參考；也可直接依賴 App Store 版 |
| **StikDebug** | **AGPL-3.0** | ⛔ **不能把它的 Swift 膠水層抄進 MIT/專有 App**——而膠水層（pairing、heartbeat、VPN 時序）正是最難的部分 |
| **pymobiledevice3** | **GPL-3.0-or-later** | ⛔ 翻譯成 Swift 極可能構成衍生著作 |
| **libimobiledevice** | LGPL-2.1 核心，但 **`tools/idevicesetlocation.c` 是 GPL-2.0** | ⛔ 而且**完全沒有 RSD/tunnel 支援**，碰不到 iOS 17+ 任何服務 |
| **LocationSimulator** | GPL-3.0 | ⛔ 且 macOS-only，README 明寫不支援 iOS 17+ |
| **go-ios** | MIT | 協定覆蓋完整，但**沒有 Swift binding / XCFramework**，無法嵌入 iOS |
| **tzf-swift** | 程式碼 MIT / 資料 ODbL-1.0 | ✅ ODbL 對打包進 App 有 attribution/share-alike 條件需確認 |

**結論**：**唯一同時「permissive + 有 iOS 路徑」的協定堆疊只有 idevice（與 MIT 的 Locus）**。這是集中風險——不是舒適的預設值。

### 6.2 兩個關鍵的法律判斷

**(a) 翻譯 = 衍生著作。** 17 U.S.C. §101 明文把 translation 列為衍生著作類型。所以**把 pymobiledevice3 的 Python 原始碼結構逐行翻成 Swift**，很可能繼承 GPL-3.0；而**從協定/wire format 知識獨立重寫**則不會——這正是 idevice(MIT) / go-ios(MIT) / libimobiledevice(LGPL) / pymobiledevice3(GPL) 能各自用不同授權實作同一套協定的法律基礎。

**(b) 不散佈 = 沒有 GPL 義務。** GPL-3.0 §2 原文：「**You may make, run and propagate covered works that you do not convey, without conditions** so long as your license otherwise remains in force.」→ **如果 LocWarp-iOS 只是 Ravi 自簽、裝在自己手機上的個人 App，整個授權章節在法律上是空的。** 這一點把「不能碰 GPL 程式碼」從硬約束降級成「只要你哪天想散佈就會變成硬約束」。

### 6.3 ⚠️ 一個與 iOS 無關、但現在就存在的合規缺口

**這件事值得 Ravi 單獨處理，跟 iOS 評估無關：**

- LocWarp 是**公開** fork（`README.en.md:324`：「The macOS build is maintained and released from this fork (raviwu/locwarp)」）
- `.github/workflows/release.yml` 用 `softprops/action-gh-release` 把 `frontend/release/*.dmg` **公開上傳到 GitHub Releases**
- `backend/locwarp-backend.spec:8` 的 `collect_all('pymobiledevice3')` 把整個 **GPL-3.0-or-later** 套件凍進那顆二進位檔
- `find . -maxdepth 2 -iname 'NOTICE*' -o -iname 'THIRD*' -o -iname '*LICENSES*'` → **零結果**

即使完全不碰「in-process linking 算不算衍生著作」這個爭論，**GPL-3.0 §4/§5（保留授權聲明）與 §6（提供對應源碼）的義務，在已經發佈的 artifact 上目前就是未滿足的**。建議動作：加一份 THIRD-PARTY-NOTICES，並在 Release 說明裡指向 pymobiledevice3 的原始碼。

### 6.4 第三方 App 的偵測

- **`isSimulatedBySoftware`**：Apple DTS Engineer Albert Pascual（Oct '25，[thread/803179](https://developer.apple.com/forums/thread/803179)）說這個 flag「is set by Core Location when you are using **Core Location's simulation**... Only when simulating with Core Location will the flag be set to true **using the Xcode debugger and loading in Xcode a GPX file**」，第三方工具「will not have access to set that API flag」。
  **重要修正**：研究過程中曾推論「StikDebug 走 Apple 原生路徑所以大概會觸發這個 flag」——**這個推論站不住腳**。StikDebug 走的是 Instruments 的 DVT channel，不是 DTS 所指的 Xcode-debugger GPX 路徑；而最接近的實證（Apple forum [thread/797864](https://developer.apple.com/forums/thread/797864)）顯示同類工具在真機上**從未**觸發此 flag，Apple Staff 的回覆也只是「It is not possible to know how every single spoofing tool works」。**正確陳述：未知，且傾向不觸發。**
- **實際被偵測的證據存在，但機制不同**：StikDebug issue [#402](https://github.com/StikDebug/StikDebug/issues/402)（2026-05-20 關閉，無說明）回報啟用模擬後 Pokémon GO 約 3 秒內出現「Failed to detect location. (12)」。Error 12 是 Niantic 自己的檢查（包含 SIM/電信商位置不符），**不能當作 `isSimulatedBySoftware` 的證據**。
- **DPLA 3.3.1(A)**「must not use or call any private APIs」與 **3.2**（不得干擾 iOS 的安全/簽章/驗證機制）是散佈情境下的合約層風險。

---

## 7. 工作量與階段

### 7.1 Phase 0 — 拋棄式實機 spike（**不保留任何 App 程式碼**）

**目的**：用現成工具把三個未知數量掉，再決定要不要投入開發。**估 1–2 人日。**

**步驟**：
1. 確認 Ravi 手機的 iOS 版本（26.x / 27.0）。
2. Mac 上用 `idevice_pair` 產生 pairing file（USB 或同網段 Wi-Fi）。
3. 手機安裝 App Store 的 **LocalDevVPN**，以及 sideload **StikDebug**（AGPL，僅作實驗）或 **Locus**（MIT）。
4. 執行並記錄下列六項量測。

**Phase 0a — 立即可跑（1–2 人日，K1–K4/K6 全數 PASS 才進 Phase 2/3）**：

| # | 量測 | **單一門檻（PASS，否則 KILL）** |
|---|------|--------------------------------|
| **K1** | Personalized DDI 是否掛載成功 | 重試 3 次、重開機 1 次後 mount 成功（若失敗，不管上游 issue 狀態如何，一律 KILL——issue 狀態只是診斷資訊，不是判準本身） |
| **K2** | 單點 teleport 是否對**其他 App** 生效 | 第三方地圖 App（非 Locus/StikDebug 本身）看到假座標 |
| **K3** | 前景保持 | 切到另一 App 前景後，模擬位置存活 **≥ 10 分鐘**（不足 10 分鐘一律 KILL，不留模糊帶） |
| **K4** | **鎖屏連續推送**（多點導航的核心，只記量測不當硬性 KILL） | 螢幕鎖定 + 另一 App 前景，1 Hz 連續推送 **30 分鐘零中斷** 才算 PASS；30 分鐘那次是唯一的 gate，之後再測的 2 小時**只是記錄用的量測，不影響 Phase 0a 的 PASS/KILL 判定** |
| **K6** | 電池 | K4 那次 30 分鐘測試耗電 **≤ 12%** 為 PASS，否則 KILL |

**Phase 0b — 被動觀察（30 天，不卡 Phase 2/3 起跑，但卡 M4「可長期使用」的驗收）**：

| # | 量測 | **PASS 條件** |
|---|------|--------------|
| **K5** | pairing file 壽命 | 30 天內、未更新 iOS、未重置的情況下沒有失效算 PASS；提前失效就記下第幾天失效，作為 M4 的續期頻率設計輸入，**不回頭否定 Phase 0a 已經 PASS 的結論** |

**額外記錄（不作為 KILL，但影響設計）**：heartbeat 間隔拉到 8s / 15s 是否仍穩；斷線後是否確實還原真實 GPS（驗證 §2.5 的 iOS 18+ 行為）；若會在中國大陸使用，量 GCJ-02 偏移。

> **K1 與 K4 是真正的門。** K1 失敗 = iOS 27 上游未修，時程不可控。K4 失敗 = 多點導航在 iOS 上就是個不可靠的功能，不管寫得多好。0a 五項全數 PASS 才進 Phase 2/3；0b 的 K5 只影響「多久要重新配對一次」的維運設計，不影響要不要做。

### 7.2 Phase 1 — 書籤（**不依賴 Phase 0 結果，可平行開始**）

| WBS | 內容 | 估時 |
|-----|------|------|
| 1.1 | Xcode 專案骨架、SwiftUI 導航、MapKit 地圖 | 2–3 人日 |
| 1.2 | 資料模型（14 欄位 Codable）+ 儲存層 | 2–3 人日 |
| 1.3 | **CRDT 移植**（`store_merge` 391 + `catalog_merge` 105）＋跨語言 golden fixtures | **5–8 人日**（若決定不留 Mac 版 → 降到 1–2 人日） |
| 1.4 | 離線地理（打包 2.88 MB GeoNames + 整合 tzf-swift） | 2–3 人日 |
| 1.5 | 書籤 UI 重寫（對照 4,500 LOC 的 TSX 當 UX spec） | 8–12 人日 |
| 1.6 | import/export 四格式 + catalog seed（8 分類 / 140 書籤） | 3–4 人日 |
| 1.7 | iCloud 同步（`NSUbiquitousContainers` 或 document picker + plain bookmark）＋ placeholder materialize | 3–5 人日 |
| | **小計** | **25–38 人日**（無 CRDT：21–32） |

### 7.3 Phase 2 — 瞬間移動（**Phase 0 通過才開始**）

| WBS | 內容 | 估時 |
|-----|------|------|
| 2.1 | 整合 idevice XCFramework（下載 release asset 並 vendor；注意 `swift/Package.swift` 不在 repo 根目錄，**不能直接當 SPM 依賴**） | 2–3 人日 |
| 2.2 | pairing file 匯入 UI + 過期偵測與明確的錯誤指引 | 2–3 人日 |
| 2.3 | loopback tunnel：先依賴 LocalDevVPN，評估後再決定要不要自建 NE extension | 1 人日（依賴）/ 5–8 人日（自建） |
| 2.4 | DDI 掛載流程（基礎映像下載 + on-device TSS 個人化）+ 失敗診斷 | 3–5 人日 |
| 2.5 | `LocationSimulationClient` wrapper + channel 快取 + heartbeat + 全路徑 clear | 3–4 人日 |
| 2.6 | cooldown 移植（129 LOC）+ UI | 1–2 人日 |
| | **小計** | **12–18 人日**（自建 tunnel：+4–7） |

### 7.4 Phase 3 — 多點導航（**Phase 0 的 K4 通過才開始**）

| WBS | 內容 | 估時 |
|-----|------|------|
| 3.1 | `movement.py` 523 LOC → Swift + golden vectors 驗證 | 4–6 人日 |
| 3.2 | 路由客戶端（`URLSession` 直打 OSRM/Valhalla/BRouter，含 straight-line fallback） | 3–4 人日 |
| 3.3 | multi-stop 狀態機 + ClockPort 測試骨架（對照 `_engine_harness.py`） | 4–6 人日 |
| 3.4 | 多點挑選 UI（StikDebug 唯一真正缺的那一塊） | 4–6 人日 |
| 3.5 | 背景 keepalive + 斷線恢復 + 進度/ETA UI | **5–10 人日（高變異，取決於 K4 結果）** |
| 3.6 | GPX 匯入（CoreGPX + LocWarp 的優先序規則） | 2–3 人日 |
| | **小計** | **22–35 人日** |

### 7.5 總計與假設

| | 樂觀 | 保守 |
|---|---|---|
| Phase 0 | 1 | 2 |
| Phase 1 書籤 | 25 | 38 |
| Phase 2 瞬間移動 | 12 | 25 |
| Phase 3 多點導航 | 22 | 35 |
| 整合 / 打磨 / 簽章流程 | 5 | 10 |
| **總計（人日）** | **65** | **110** |

**估算假設（必須一起讀）**：
- Ravi 一人 + agentic development（AI 負責規劃與實作，人力主要在 review / 驗證 / 實機測試）
- Ravi 是 **hobbyist iOS 開發者**——Swift Concurrency、NetworkExtension、CloudKit 的學習曲線已含在保守值
- **不含**追上游 iOS 版本破壞的長期維運
- **不含** iOS 27 DDI 若長期未修的等待時間（不可控）
- 純邏輯移植（movement、store_merge）有 golden vectors，變異最小；UI 與背景執行變異最大

### 7.6 里程碑

| M | 內容 | 驗收 |
|---|------|------|
| **M0** | Phase 0 spike 完成 | 六項量測都有數字，K1–K6 明確 PASS/KILL |
| **M1** | 書籤 App 可用 | 與 Mac 版同一份 iCloud store 雙向同步 24h 無資料遺失；CRDT golden fixtures 兩語言全綠 |
| **M2** | 單點 teleport 端到端 | 第三方地圖 App 看到假座標，連續維持 ≥ 10 分鐘 |
| **M3** | 多點導航端到端 | 3 個以上 waypoint，沿真實道路，停留規則與 Python 版行為一致 |
| **M4** | 可長期使用 | pairing 過期有清楚指引；簽章更新流程文件化；斷線一定還原真實 GPS |

---

## 8. 未解問題與需要 Ravi 決定的事

### 8.1 必須由 Ravi 決定（每題附建議）

| # | 問題 | 選項 | 建議 |
|---|------|------|------|
| **D1** | **手機現在的 iOS 版本？** | 26.x / 27.0 | **已解決（2026-09-19）：26.6.2**。走 iOS 18–26 的 `idevice_pair` 電腦一次性配對路徑，不是 iOS 27 免電腦流程。Phase 0a 的 K1–K4 已實測 PASS，K6 待補測（見 `~/locwarp-ios-spike/PHASE0-RUNBOOK.md`） |
| **D2** | **接受週期性 Mac bootstrap（T1-recurring）嗎？** | 接受 / 只接受真 T0 / 不接受 | **已解決：接受**（Ravi 已確認建置/簽章可以用 Mac,只要求執行期免電腦） |
| **D3** | **Mac 版要留著嗎？** | 留 / 不留 | **已解決（2026-09-19）：留著,兩邊都要能寫書籤**。CRDT 全套移植確定要做（~496 LOC,5–8 人日,§7.2 WBS 1.3）。連帶觸發 D9（見下）——原本假設的「同一 Apple ID 多裝置」不成立 |
| **D9** | **（新增,2026-09-19 已拍板）跨 Apple ID 書籤同步走哪條路？** | iCloud Drive 共用資料夾 / CloudKit CKShare | **已解決：iCloud Drive 共用資料夾**。理由：重用 §5.1 現有的 document-picker + regular-bookmark 設計與整套 `merge_stores`,幾乎零改動;CKShare 除了要做邀請/接受流程,底層 CKSyncEngine 衝突處理本來就只有整筆 LWW（已在 §5.1 標註過的缺口）,複雜度更高。未驗證項：共用（非自有）iCloud 資料夾上 `NSFilePresenter`/`NSMetadataQuery` 的可靠性,列入 Phase 1 早期 spike |
| **D4** | **分發通道** | 自簽 sideload / Ad Hoc / TestFlight | **自簽 sideload**。TestFlight 有直接被拒的先例，App Store 不可能 |
| **D5** | **自建 NE tunnel 還是依賴 LocalDevVPN？** | 自建 / 依賴 | 先**依賴**（省 5–8 人日）；但要知道這是單點故障——整條路徑掛在一個小開發者的單一 App Store 上架上，而其姊妹專案 StikDebug 已被下架過 |
| **D6** | **接受 $99 帳號的非零終止風險嗎？** | 接受 / 不接受 | Ravi 自己判斷。無法量化，但 2025-08 撤銷潮確實打到過純自用者 |
| **D7** | **會在中國大陸使用嗎？** | 會 / 不會 | 會 → 必須處理 GCJ-02↔WGS-84（470–560 m 偏移），兩個同類專案都還沒修好 |
| **D8** | **（與 iOS 無關）要不要補 GPL 合規？** | 補 / 不補 | **補**。加 THIRD-PARTY-NOTICES 並在 Release 指向 pymobiledevice3 源碼，成本極低 |

### 8.2 仍然未解的技術問題（spike 或後續調查）

1. **iOS 27 DDI 何時修好、由誰修**——依賴志工 mirror `doronz88/DeveloperDiskImage`，Ravi 無法加速。
2. **iOS 27「Pair on this iPhone」能否在 loopback 上自我配對**（真 T0 的唯一希望）——只有一份 OSS README 主張，Apple 文件說的是「拿掉線材、不是拿掉電腦」。
3. **安全的 heartbeat 間隔**——沒有任何 Apple 文件給數字；StikDebug 選 4 秒但沒說明理由。
4. **把 mover loop 放進 packet-tunnel extension 是否可行**——Apple DTS 證實 NE appex 行程生命週期獨立於容器 App，但**沒有任何 OSS 專案這樣做過**，且有 50 MiB jetsam 上限。這是第二個 spike。
5. **付費帳號 development profile 的實際效期**——Apple 沒有任何頁面明文說明（DTS 只說了 in-house 1 年 / ad hoc 90 天 / personal 7 天）。
6. **Ravi 的 Apple Developer 帳號地區**——台灣不支援自動續期。
7. **模擬位置是否能撐過完整重開機**——沒有任何回報說可以，但也沒有明確否證。

### 8.3 研究缺口（本次未涵蓋的主題）

- **沒有實機驗證**。全部結論來自原始碼、Apple 文件與第三方回報。Phase 0 就是為了補這個缺口而存在。
- **電池與熱節流**沒有任何量化來源（K6 要自己量）。
- **Low Power Mode、來電、記憶體壓力**對這套 keepalive 堆疊的影響，沒有任何資料。
- **Ravi 實際的使用強度**（每次模擬幾分鐘？多久一次？）未知，而這直接決定 K4 的門檻該訂在哪。

---

## 9. 附錄 — 證據表

### 9.1 決策級主張與 verifier 判定

| ID | 主張 | 證據 | 判定 | as_of |
|----|------|------|------|-------|
| M-1 | DVT LocationSimulation 需維持 live 連線才持續模擬 | `idevice/src/services/dvt/location_simulation.rs:4-5`；pymobiledevice3 `cli/developer/dvt/simulate_location.py:36-38` | **confirmed** | 2026-09-19 |
| M-2 | StikDebug 每 4 秒重送座標維持模擬 | `StikDebug/Views/MapSelectionView.swift:1380-1389` | **confirmed** | 2026-09-09 (commit 94bc9e8) |
| M-3 | LocalDevVPN 的 NEPacketTunnelProvider 做 IP 標頭 src/dst 交換的 on-device loopback | `TunnelProv/PacketTunnelProvider.swift`（jkcoxson af3fd69 / Stossy11 c4566ce 兩個 fork 皆同） | **confirmed** | 2026-09-02 |
| M-4 | StikDebug 完整 on-device chain：TCP 10.7.0.1:49152 → rppairing → RSD → DVT LocationSimulation | `StikDebug/Device/IdeviceFFIBridge.swift:757-845`；`DeviceConnectionContext.swift:11` | **confirmed** | 2026-09-09 |
| M-5 | DDI 的 Apple TSS 個人化由手機自己直接 HTTP POST 到 `gs.apple.com/TSS/controller?action=2` | `idevice/src/services/mobile_image_mounter.rs:621-768`；`idevice/src/tss.rs:17,71-84` | **confirmed** | 2026-09-14 |
| M-6 | 基礎 DDI 由 StikDebug 從志工 GitHub mirror 以 HTTPS 下載 | `StikDebug/Services/DeveloperDiskImageService.swift:80-96` | **confirmed** | 2026-09-09 |
| M-7 | DDI mirror 最後更新 2026-08-07，內容為 iOS 27 **beta** build `27A5228h` | [doronz88/DeveloperDiskImage commits](https://github.com/doronz88/DeveloperDiskImage/commits/main/PersonalizedImages/Xcode_iOS_DDI_Personalized) | **confirmed（本次親自查證）** | 2026-09-19 |
| M-8 | iOS 27 DDI mount 失敗，issue open 無解 | [StikDebug#464](https://github.com/StikDebug/StikDebug/issues/464) | **confirmed（本次親自查證：open、零留言）** | 2026-09-19 |
| M-9 | pairing file 需電腦產生，且會在**隨機時間**失效 | [StikDebug-Guide/pairing_file.md](https://github.com/StikDebug/StikDebug-Guide/blob/main/pairing_file.md) | **confirmed** | 2026-09-19 |
| M-10 | **iOS 27 拿掉的是線材，不是電腦**；Apple 官方流程仍是 Mac Device Hub 發現手機、手機顯示 PIN | [Apple: Managing your devices in Device Hub](https://developer.apple.com/documentation/xcode/managing-your-simulated-and-physical-devices-in-device-hub) | **confirmed（本次親自查證）** | 2026-09-19 |
| M-11 | Locus 主張 iOS 27 可純手機配對（T0），iOS 18–26 需 RPPairing 檔（T1） | [Locus README](https://github.com/RicePollution/Locus) | **README 所述，未獨立驗證**；與 M-10 並存，見 §2.6 | 2026-09-19 |
| M-12 | Developer Mode 需先與 Mac 配對過才會出現；開啟後一般重開機保留 | [Apple: Enabling Developer Mode](https://developer.apple.com/documentation/xcode/enabling-developer-mode-on-a-device) | **confirmed** | 2026-09-19 |
| M-13 | 背景 keepalive 全開仍被 iOS 砍掉（iOS 26.5） | [StikDebug#458](https://github.com/StikDebug/StikDebug/issues/458) | **confirmed** | 2026-09-06 |
| M-14 | iOS 26 的 `BGContinuedProcessingTask` 限定 finite / user-initiated / 強制系統 UI，不是無限迴圈的解 | Apple `BGContinuedProcessingTask` 文件 + WWDC25 | **confirmed** | 2026-09-19 |
| M-15 | NE appex 行程生命週期獨立於容器 App | Apple DTS，[forums/thread/729227](https://developer.apple.com/forums/thread/729227) | **confirmed** | 2026-09-19 |
| M-16 | packet tunnel provider 記憶體上限 iOS 15.0 起為 50 MiB | Apple DTS Quinn，[forums/thread/73148](https://developer.apple.com/forums/thread/73148) | **confirmed（修正原研究的「~15MB」說法）** | 2026-09-19 |
| A-1 | NE packet-tunnel entitlement 自助，無審批；「Any paid developer can do that」 | Apple entitlement 文件；DTS [thread/819032](https://developer.apple.com/forums/thread/819032) | **confirmed** | 2026-03 貼文 |
| A-2 | 但 TN3120 明說「Do not use a packet tunnel provider to host a network listener or proxy server」 | [TN3120](https://developer.apple.com/documentation/technotes/tn3120-expected-use-cases-for-network-extension-packet-tunnel-providers) | **confirmed** | rev 2025-07-22 |
| A-3 | DPLA 3.3.3(G)：Apple 得自行裁量拒絕或撤銷 NE entitlement | [DPLA](https://developer.apple.com/support/terms/apple-developer-program-license-agreement/) §3.3.3(G) | **confirmed**（DPLA 版本日 2026-08-18） | 2026-09-19 |
| A-4 | Guideline 5.4：VPN App 僅限組織帳號 | [App Review Guidelines](https://developer.apple.com/app-store/review/guidelines/) §5.4 | **confirmed** | 2026-06-08 版 |
| A-5 | Guideline 1.1.6：fake location trackers 被列為不實功能 | 同上 §1.1.6 | **confirmed** | 2026-06-08 版 |
| A-6 | TN3134：iOS packet tunnel provider **無**分發通道限制 | [TN3134](https://developer.apple.com/documentation/technotes/tn3134-network-extension-provider-deployment) | **confirmed** | rev 2025-08-19 |
| A-7 | StikDebug 2025-12-18 從 173/175 storefront 消失，2026-01-17 前全數；開發者稱帳號被終止 | [AppleCensorship](https://applecensorship.com/app-store-monitor/app/6744045754)；[Ubergizmo](https://www.ubergizmo.com/2025/12/stikdebug-pulled-appstore/) | **partially-true**（原說法把全面下架訂在 12-18；實為 173/175） | 2025-12-18 / 2026-01-17 |
| A-8 | ios-location-spoofer 於 2026-01-19 被 TestFlight 拒絕 | [repo README](https://github.com/acheong08/ios-location-spoofer) | **confirmed** | 2026-01-19 |
| A-9 | 2025-08-26 撤銷潮打到自述純自用的開發者 | [iDownloadBlog](https://www.idownloadblog.com/2025/08/26/in-latest-revocation-wave-a-trigger-happy-apple-reportedly-revokes-even-innocent-developer-accounts/) | **confirmed** | 2025-08-26 |
| A-10 | Apple DTS：ad hoc profile 90 天、in-house 1 年、personal 7 天 | [forums/thread/796061](https://developer.apple.com/forums/thread/796061) | **confirmed（修正原研究的「付費約 1 年」）** | Aug '25 |
| A-11 | TestFlight「internal 不需審查」**不是** Apple 說法；Apple 頁面說 build 加入 group 即自動送審 | [developer.apple.com/testflight](https://developer.apple.com/testflight/) | **partially-true → 已修正** | 2026-09-19 |
| A-12 | iOS 27 已於 2026-09-14 **公開發佈**（非 beta）；2026-09-16 釋出的是 27.2 developer beta | [9to5Mac](https://9to5mac.com/2026/09/16/apple-releases-first-ios-27-2-developer-beta-for-iphone/) | **confirmed（推翻原研究的「iOS 27 在 beta」）** | 2026-09-16 |
| B-1 | 書籤 CRDT：per-unit LWW + tombstone 抑制 + 30 天 GC + 三段 tiebreak | `backend/domain/store_merge.py:42,113-178,265-289,345-355,376-381` | **confirmed** | repo `052d6ba` |
| B-2 | `merge_stores` 交換律與冪等性由隨機性質測試背書（seed 20260827、300 輪） | `backend/tests/test_store_merge_per_field.py:312-336` | **confirmed** | repo `052d6ba` |
| B-3 | Bookmark 模型 **14** 欄位 | `backend/models/schemas.py:279-309` | **partially-true → 已修正**（原研究寫 12/13） | repo `052d6ba` |
| B-4 | 空 `updated_at` 陷阱與 `force_seed_items` | `backend/domain/store_merge.py:358-364`；`services/bookmarks.py:691,846-847` | **confirmed** | repo `052d6ba` |
| B-5 | catalog baseline 本機專屬，絕不進 sync folder | `backend/config.py`；`domain/catalog_merge.py` | **confirmed** | repo `052d6ba` |
| B-6 | 離線地理：timezonefinder 8.2.4 + GeoNames cities5000（2,780,911 B / 68,704 筆），無網路呼叫 | `backend/services/geo_offline.py:1-162`；`requirements.txt:11,15` | **confirmed** | repo `052d6ba` |
| B-7 | timezone polygon 缺口已由 tzf-swift 關閉（iOS 16+、MIT/ODbL、lite 約 48 MB 常駐） | [ringsaturn/tzf-swift](https://github.com/ringsaturn/tzf-swift)、其 `Package.swift` | **partially-true → 升級為 confirmed**（原研究稱「未解缺口」） | 2026-09-19 |
| B-8 | macOS 專屬同步機制無 iOS 對應：`brctl download` + watchdog Observer | `backend/services/cloud_sync.py`；`services/file_watcher.py:1-45` | **confirmed** | repo `052d6ba` |
| B-9 | iOS **不支援** security-scoped bookmark；應用 plain bookmark | Apple `withSecurityScope` 文件（iOS "Not available"）；DTS Quinn [thread/766646](https://developer.apple.com/forums/thread/766646) | **partially-true → 已修正** | 2026-09-19 |
| B-10 | `NSPersistentCloudKitContainer` 為整筆 LWW，無自訂合併 API | Apple [WWDC19 session 202](https://developer.apple.com/videos/play/wwdc2019/202/) | **confirmed** | 2026-09 複查 |
| B-11 | `CKError.serverRecordChanged` 提供 client/server/ancestor 三份記錄 | [Apple CloudKit 文件](https://developer.apple.com/documentation/cloudkit/ckerror/serverrecordchanged) | **confirmed** | 2026-09-19 |
| T-1 | 完整 teleport 呼叫鏈 UI→API→engine→DVT | `useSimActions.ts:192` … `services/location_service.py:223-241` | **confirmed** | repo `052d6ba` |
| T-2 | 裝置 API 只吃 lat/lng，無 altitude/accuracy/speed | pymobiledevice3 `location_simulation.py:21-25`、`simulate_location.py:20-27`；`backend/models/schemas.py:9-11,59-62` | **confirmed** | pymobiledevice3 9.27.0 |
| T-3 | `stopLocationSimulation` 為 fire-and-forget（`expects_reply=False`），clear 可能靜默失敗 | pymobiledevice3 `location_simulation.py:12-13`；`location_service.py:82-85`、[issue#572](https://github.com/doronz88/pymobiledevice3/issues/572) | **confirmed** | 2026-09-19 |
| T-4 | cooldown 純 server 端，從不傳給 iPhone | `backend/services/cooldown.py:1-129`；`api/location.py:116-136` | **confirmed** | repo `052d6ba` |
| T-5 | 模擬位置在 iOS 18+ 斷線即還原（iOS 18 前則留存至重開機） | Apple [forums/thread/698147](https://developer.apple.com/forums/thread/698147) | **partially-true → 已修正**（非架構保證，是版本相依行為） | 2026-09-19 |
| S-1 | `domain/movement.py` 523 LOC 純函式，有 bit-exact golden vectors | `backend/domain/movement.py`；`tests/test_interpolator_golden.py`（90 行） | **confirmed** | repo `052d6ba` |
| S-2 | tick 0.5s（>5 m/s）或 1.0s | `backend/config.py:175-187` | **confirmed** | repo `052d6ba` |
| S-3 | `_move_along_route` 為 navigate/loop/multi-stop/random-walk 共用；joystick 自有 200ms loop | `simulation_engine.py:668`；`core/joystick.py:16` | **confirmed** | repo `052d6ba` |
| S-4 | 停留規則優先序與可中斷性 | `backend/core/multi_stop.py:255-283` | **confirmed** | repo `052d6ba` |
| S-5 | `MKDirections.Request` **無** waypoints 屬性 | [Apple MKDirections.Request 文件](https://developer.apple.com/documentation/mapkit/mkdirections/request) | **confirmed** | 2026-09-19 |
| S-6 | **LocWarp 現在是整條路線一次請求**（非逐段） | `backend/services/route_service.py:278-280,319,387` | **confirmed（修正原研究「與逐段做法一致」的說法）** | repo `052d6ba` |
| S-7 | StikDebug 已內建書籤 + 路線播放（0.5s tick）；唯一缺口是多點挑選 UI | `MapSelectionView.swift:683,1047-1065,1523-1560,45,306-339`；`:32-35` | **confirmed** | 2026-09-09 |
| S-8 | 中國大陸 GCJ-02/WGS-84 偏移 470–560 m，兩個同類專案皆未修好 | [StikDebug PR#462](https://github.com/StikDebug/StikDebug/pull/462)（closed unmerged）；[Roam-Control#8](https://github.com/seanhowarthdev/Roam-Control/issues/8)（open） | **partially-true → 已修正**（PR 未合併；無 Apple 來源） | 2026-09-15 |
| L-1 | idevice = MIT；StikDebug = AGPL-3.0；Locus = MIT；pymobiledevice3 = GPL-3.0-or-later | 各 repo LICENSE / Cargo.toml / pyproject.toml | **confirmed** | 2026-09 |
| L-2 | libimobiledevice 核心 LGPL-2.1，但 `tools/idevicesetlocation.c` 是 GPL-2.0；且**完全無 RSD 支援** | 114 檔全掃：111 LGPL、1 GPL-2.0；grep RSD/CoreDeviceProxy/CDTunnel = 0 | **partially-true → 已修正** | 2026-09 |
| L-3 | 翻譯構成衍生著作（17 U.S.C. §101 明列 translation） | [17 U.S.C. §101](https://www.law.cornell.edu/uscode/text/17/101) | **confirmed** | n/a |
| L-4 | GPL-3.0 §2：不 convey 即無條件 | pymobiledevice3 LICENSE §2 | **confirmed（關鍵：個人自用讓授權章節失去拘束力）** | n/a |
| L-5 | LocWarp 現已公開散佈含 GPL-3.0 pymobiledevice3 的 DMG，且無 NOTICE/THIRD-PARTY 檔 | `backend/locwarp-backend.spec:8`；`.github/workflows/release.yml:60-63`；`find` 零結果 | **confirmed** | repo `052d6ba` |

### 9.2 被推翻（refuted）的主張 — **不得在正文當事實使用**

| 原主張 | 為何被推翻 |
|--------|-----------|
| **「iOS 沒有任何公開 API 讓 App 對自己開 host↔device 協定，所以 teleport 結構上是 T2」**（code-teleport C9） | NE packet-tunnel entitlement 自助、非私有；minimuxer / StikDebug / Locus 已實際做到同一支手機自我連線。正確陳述：**T1，已被 OSS 實作**。 |
| **「iOS 27 還在 beta」**（web-alt C11） | iOS 27 已於 **2026-09-14 公開發佈**。2026-09-16 的是 27.2 developer beta。 |
| **「安裝並啟動自簽 App 本身就足以讓 Developer Mode 選項出現」**（web-mechanism C24） | Apple 明文：「Developer Mode only appears in Settings if you initiate pairing or if you **previously paired the device to a Mac**.」 |
| **「idevice 的 location_simulation FFI 對應 `com.apple.dt.simulatelocation`，即 Xcode Simulate Location 用的同一服務」**（web-field C3） | 實際是 DVT Instruments channel `com.apple.instruments.server.services.LocationSimulation`。`com.apple.dt.simulatelocation` 是另一個 lockdownd 服務（iOS 16 以下），由不同 FFI 家族 `lockdown_location_simulation_*` 提供，StikDebug 一個都沒呼叫。 |
| **「StikDebug 走 Apple 原生路徑，所以 `isSimulatedBySoftware` 很可能會觸發」**（web-field C14） | 機制不同（Instruments DVT ≠ DTS 所述的 Xcode-debugger GPX 路徑）；最接近的實證顯示同類工具在真機上從未觸發。正確：**未知，傾向不觸發**。 |
| **「LocWarp 的 iOS 17+ tunnel 是唯一 live 的連線路徑，iOS 16 legacy path 不可達」**（code-device R1） | 版本閘門擋的是 <16.0，16.x 走 `_connect_legacy()`，且 `_create_legacy_location_service` 仍在用。檔案裡「iOS < 17 path removed in v0.1.49」的註解是過時殘留。 |
| **「LocWarp 的 WiFi tunnel 流程沒有自己的 cold-start pairing」**（code-device R8） | `POST /wifi/tunnel/start` → `open_wifi_tunnel` → `create_core_device_tunnel_service_using_remotepairing()`，是真正的 root 權限 RemotePairing handshake。 |
| **「Python + pymobiledevice3 跑不進 iOS 是因為拿不到 raw device-protocol / DVT entitlement」**（web-alt C13 的理由） | 結論對、理由錯。**完全不需要私有 entitlement**（StikDebug entitlements 只有 app-sandbox、app group、user-selected read-only）。真正的阻礙是：Pyto 無法載入非內建的原生擴充（pymobiledevice3 需要 `cryptography`），以及直譯器 App 無法自帶 NE loopback tunnel。 |
| **「MFi GNSS 接收器是本題的一個選項」**（web-alt C1 的框架） | 它轉發**真實**衛星定位，無法瞬間移動——三個功能一個都不給，屬於不同產品類別。 |
| **「ios-location-spoofer 是 T0」**（web-alt C7） | 其 README 明寫需付費開發者帳號 + Xcode sideload（T1），且只騙得過 Wi-Fi 定位、壓不過真實 GNSS。 |
| **「Xcode 的 Simulate Location 就是 DVT 那條路，且只在 debug session 期間有效」**（web-alt C12） | 被引用的頁面是 test plan 的模擬位置，**只對 test bundle 內的程式碼生效**（UI automation 測試裡 App 本身不會用到），與系統層 DVT 不同。系統層是另一條 scheme/Debug > Simulate Location 路徑。 |

### 9.3 本次未涵蓋、需標示為 gap 的主題

- **實機驗證**：完全沒有。所有結論出自原始碼、Apple 文件與第三方回報。→ Phase 0 存在的理由。
- **電池 / 熱節流 / Low Power Mode / 來電**對 keepalive 堆疊的影響：無任何來源。
- **Ravi 手機的實際 iOS 版本與機型**：未查（超出 repo-only 範圍）。
- **iOS 27 上 DVT location simulation 是否真的可用**：公開資料中**無人驗證**——#461、#463 皆被關閉且零回覆，#464 open。
- **把 mover loop 放進 NE extension**：無任何 OSS 前例。
- **付費帳號 development profile 實際效期**：Apple 無明文。

---

*本報告的所有 GitHub / Apple 連結皆於 2026-09-19 由研究者或驗證者實際開啟過。Locus README 的 iOS 27 T0 主張、Apple Device Hub 的網路配對說明、StikDebug #464 現況、以及 DDI mirror 的最後更新時間，為本次撰寫時親自複查。*
