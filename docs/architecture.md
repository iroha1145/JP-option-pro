# アーキテクチャ

## プロセス

| プロセス | 役割 | 起動 |
|---|---|---|
| backend | FastAPI + SPA 配信。読み取り専用でデータを提供 | `uvicorn app.main:app` |
| worker | 全同期・レーダー・スクリーナー・ニュース・AI・バックアップ | `python -m app.worker` |

同一イメージ・同一 `/data` ボリューム。worker は flock + SQLite リース
（fencing token 付き）で単一実行を保証し、クラッシュ後の `running` 行は
起動時に `interrupted` / 再 `queued` に回復される。

## データベース（すべて SQLite / WAL）

| ファイル | ライタ | 内容 |
|---|---|---|
| jp-core.db | worker | 銘柄マスタ・取引カレンダー・日足・指数・財務・決算予定・信用・空売り・レーダー・スクリーナー断面・同期チェックポイント |
| jp-news.db | worker | ニュース原文・日本語訳・中文分析・実体別名・フィード状態 |
| jp-ai-jobs.db | worker + API | モデルジョブキュー（UNIQUE(request_hash) 去重・トークン予算） |
| jp-worker.db | worker + API | タスク状態・リース・手動アクションキュー |
| jp-app.db | API | ウォッチリスト |

スキーマは DDL の SHA-256 をバージョン表に保存し、開くたびに照合する
（ドリフトは起動失敗として顕在化）。

## 同期レーン

- **incremental**: 「最終取込日 +1 〜 最新の完了取引日」を日単位で埋める。
  チェックポイントが無いデータセットは `backfill_required` を返して増分を拒否
  （数千リクエストの誤爆防止; `MAX_INCREMENTAL_DAYS=45` ガード付き）。
- **backfill**: `/v2/bulk/list` → `/v2/bulk/get` → gzip CSV を 1 ファイル/ステップで
  取込。残キーはチェックポイントに永続化され、再起動後は続きから。完了時に
  incremental へ引き継ぐ。
- レート制御はクライアント内蔵（全体 100/min + fins 50/min のスライディング
  ウィンドウ、429 で全バケット封鎖）。ページリロードが提供元アクセスを誘発する
  経路は存在しない（読みはすべてローカル DB）。

## レーダー（日足）

1. 対象ユニバース: アクティブ + 対象市場 + 業種コードあり（ETF/REIT 除外）
   + 上場 120 日以上 + 20 日平均売買代金 1 億円以上（personal.toml で調整可）
2. 特徴量（先読み禁止: 当日バーは自分の抵抗線に不参加）
3. シグナル: 52週/120日/60日/20日高値ブレイク・出来高急増ブレイク、
   接近中（+2%以内 & 20日騰落 ≥3%）は watching
4. ライフサイクル: discovered → watching → triggered → confirmed → holding →
   retesting → retest_held → reaccelerating / extended → failed / expired
   （遷移表に無い移動は拒否・同日再実行は冪等）
5. スコア: 欠損認識加重（欠損は重みごと除外し confidence に反映）。
   trend/base/confirmation/RS/participation/liquidity → breakout_quality →
   alert_priority（chase・crowding はペナルティ側）
6. スクリーナー断面は同じ特徴量パスから毎晩全量再構築

## ニュース

fetch(RSS) → 実体照合（別名目録: 正式名/略称/英名/コード文脈のみ）→
ルール分類（19 カテゴリ）→ 関連判定（銘柄 or 市場レベル、無関係は破棄）→
去重（指紋 + タイトル bigram Jaccard、実体共有で閾値 0.5）→ 重要度
（カテゴリ×実体×鮮度、欠損は中立値で埋めない）→ 保存。

AI は言語理解だけを担当:
- `news_translation_ja`: 外国語 → 日本語（原文は不変で保持）
- `news_analysis_zh`: 簡体中文の影響分析（allowed_codes 束縛・insufficient_context 正直）
決定論で出来ること（分類・指紋・コード対応・時刻）はモデルに渡さない。

## アクセス制御

- `private_network`: 承認済み CIDR のみ。Cookie なし。
- `password`: PBKDF2-600k・単一セッション・HTTPS 必須・失敗スロットリング。
  GET/HEAD は訪問者にも公開、書込は owner + 同源証明
  （Origin=Host・Sec-Fetch-Site・X-Optix-Action の四重チェック）。
- 起動時に配備境界を fail-closed 検証（プロキシ設定と CIDR の整合など）。
