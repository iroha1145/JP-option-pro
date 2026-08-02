# 運用メモ

## 日次リズム（JST）

| 時刻 | タスク | 内容 |
|---|---|---|
| 07:10 | calendar_master_sync | 取引カレンダー + 銘柄マスタ更新 |
| 17:00 | post_close_batch | 日足/指数/信用/空売り/決算予定 → レーダー → スクリーナー断面 |
| 18:40 | fins_evening_sync | 財務サマリー速報（開示 18:00 の後） |
| 01:10 | fins_late_sync | 前営業日の確報を再取込（〜24:30 確定分） |
| 常駐 | history_backfill | bulk CSV 履歴を 1 ファイルずつ消化 |
| 6h毎 | maintenance | 全 DB のオンラインバックアップ（検証つき、保持 7 世代） |
| 15分毎 | news_sync / ai_jobs | news_mode ≠ off のとき |

## 手動更新

データ状態ページ（オーナー時）に「触发收盘批处理 / 主数据同步 / 财务同步 /
推进历史回填 / 重算雷达」。API 直叩きは
`POST /api/worker/actions/{type}`（同源ヘッダ必須）。手動もスケジュールも
同じワーカータスクを通る——別系統のロジックは無い。

## 障害時の挙動

- 同期失敗: sync_state に error code を記録し、既存データは触らない。
  ページは古いデータを「数据截至 <日付>」表示のまま提供し続ける。
- ワーカー停止: `/api/worker/status` と `python -m app.worker --healthcheck`
  が degraded を返す。データ状態ページに劣化タスクが並ぶ。
- 空マスタ応答: 全銘柄 deactivate を防ぐため同期エラーとして拒否する。

## バックアップ / 復元

- `/data/backups/` に `<label>-<ts>.sqlite3` + `.sha256` + `.json`（オンライン
  バックアップ API、quick_check/integrity_check/foreign_key_check 済み）。
- 復元: コンテナ停止 → 対象 DB を差し替え → 起動。スキーマ照合が走るので
  版違いは起動時に検出される。

## シークレット

- `secrets.env`（chmod 600）: JQUANTS_API_KEY / OPENAI_API_KEY / APP_PASSWORD_HASH。
  machine.env に書いても**無視される**（キー所属ルール）。
- パスワードハッシュ生成:
  `python -c "from app.access import hash_owner_password; print(hash_owner_password('12文字以上'))"`
- 旧プロジェクトの env（FINNHUB_API_KEY / MASSIVE_API_KEY / MACROLENS_URL）が
  残っていると**起動を拒否**する（静かな誤設定より早期失敗）。

## 分足（1分/5分/60分チャート）

- J-Quants の**分足はオプション（アドオン）契約**。未契約だと API が 403 を返し、
  その事実は jp-intraday.db に `plan_not_included` として記録され、チャートは
  「アドオン未契約」を表示する（2026-08-02 の実測: 現在のキーは未契約）。
- 契約済みの場合: 銘柄ページの分足タブからオーナーが「直近5営業日を取得」→
  worker の `intraday_fetch` アクションが 1分足をキャッシュし、5分/60分は
  読み出し時にリサンプリング（欠けた分は埋めない）。完了日のキャッシュは不変。

## 既知の制約（正直リスト）

- 決算発表予定 API は 3月期・9月期決算のみ・直近分のみ・REIT なし（J-Quants 仕様）。
  ページにもその旨を常時表示している。
- 信用規制（margin-alert の規制区分）はレーダーの crowding にまだ結線していない
  （margin_interest 由来の信用倍率のみ使用）。
- investor-types / EDINET 3 表は Standard で取得可能だが v1 未接続（capability
  宣言では planned）。
- ニュースフィードは同梱していない。personal.toml の feed_urls にオーナーが
  RSS を登録して初めて動く（news_mode=read/scheduled）。
- 視覚回帰（Playwright）は未整備。ブラウザ実測はリリース前に手動で実施した。
