# Optix Japan — 日本株リサーチワークベンチ

個人投資家向け・プライベート配備・日本株専用のリサーチ環境。データソースは
**J-Quants API V2（Standard プラン）** のみ。日足粒度で正直に動く——リアルタイム
を装う UI は存在しない。

参照元の米国株プロジェクト（option-pro）から成熟した基盤（アクセス制御・
キャッシュ・ワーカー・AI ジョブ規律・デザインシステム）を移植し、ドメインは
全面的に日本株用に再設計した。詳細は [docs/migration-decisions.md](docs/migration-decisions.md)。

## 主な機能

| ページ | 内容 | 粒度 |
|---|---|---|
| 首页 | 指数タープ・騰落・業種強弱・レーダー・直近決算・自選異動 | 日足 |
| 日本市場 | TOPIX/市場別指数チャート・33業種テーブル・空売り比率 | 日足 |
| 突破雷達 | 引け後全市場スキャン: 高値ブレイク検出 → ライフサイクル → 多次元スコア | 日足 |
| 筛选器 | SQL 断面フィルタ（市場区分/33業種/売買代金/RS/MA/52週高値乖離） | 日足 |
| 自选股 | ウォッチリスト（オーナーのみ書込） | 日足 |
| 决算日历 | 発表予定（J-Quants 制限を明記）+ 直近開示 + 会社予想の修正方向 | 開示 |
| 新闻 | RSS 取込 → 実体照合 → 去重 → **日本語訳** + **簡体中文影響分析** | 随時 |
| 数据状态 | データセット鮮度・能力宣言・ワーカー状態・手動更新 | — |

## セットアップ

```bash
# 1) 設定ファイル
cp machine.env.example machine.env
cp secrets.env.example secrets.env && chmod 600 secrets.env
#    secrets.env に JQUANTS_API_KEY を記入（J-Quants ダッシュボードで発行）

# 2) Docker 起動（backend + worker の 2 コンテナ）
./scripts/deploy.sh

# 3) 初回データ投入
#    ワーカーが自動で bulk CSV バックフィル（10年分）を開始する。
#    進捗は http://127.0.0.1:2100/data-status で確認。
```

### ローカル開発（Docker なし）

```bash
python3.12 -m venv .venv && .venv/bin/pip install -r backend/requirements.txt pytest
# 合成フィクスチャで全ページを動かす:
cd backend && DATA_DIR=/tmp/jp-dev PYTHONPATH=. ../.venv/bin/python -m app.tools.dev_fixture
DATA_DIR=/tmp/jp-dev PYTHONPATH=. ../.venv/bin/python -m uvicorn app.main:app --port 2100
# フロント開発サーバー:
cd frontend-src && npm install && npm run dev   # :3100 → /api は :2100 へプロキシ
```

### テスト

```bash
.venv/bin/python -m pytest tests/ -q          # 48 tests — 実 API に一切接続しない
npm run build --prefix frontend-src           # tsc + vite build
```

## アーキテクチャ

```
J-Quants API V2 ──(rate-limited client)── worker ──> jp-core.db (SQLite/WAL)
   bulk CSV ────(backfill lane)──────────┘   │            │ read-only
   RSS feeds ──> jp-news.db <── AI jobs ─────┤            ▼
   OpenAI (background, 並行度1) <────────────┘        FastAPI ──> React SPA
```

- **書込境界**: worker だけが jp-core.db / jp-news.db を書く。API は read-only 接続
  （`file:...?mode=ro`）。API が書けるのは jp-app.db（自選）と action queue のみ。
- **冪等**: 全同期は UPSERT + チェックポイント。同じ日付の再実行は無害。
- **スケジュール**: Asia/Tokyo 固定。17:00 引け後バッチ / 18:40 財務速報 / 01:10 確報
  補完 / バックフィルは常駐レーン。取引日判定は J-Quants カレンダー（半日立会=営業日）。
- **AI 言語契約**: 翻訳=日本語（仮名検証つき）、影響分析=簡体中文（仮名混入で棄却）、
  出力の銘柄コードは allowed_codes 束縛。プロンプト版更新は request_hash を動かし、
  古い結果を静かに再利用しない。
- **能力宣言**: Standard プランに無いデータ（fins/details・配当・分足など）は
  `unavailable` と表示する。空配列で「データなし」を偽装しない。

詳細: [docs/architecture.md](docs/architecture.md) / [docs/jquants-v2-notes.md](docs/jquants-v2-notes.md) / [docs/operations.md](docs/operations.md)

## 将来のリアルタイム拡張

`backend/app/providers/intraday.py` の `IntradayQuoteProvider / IntradayBarProvider /
RealtimeRankingProvider` プロトコルが唯一の接続点。J-Quants 分足オプションや証券会社
API を足すときはこの実装を追加するだけで、マスタ・ニュース・日足レーダーは無改修。
現在は `DisabledIntradayProvider` が「未接続」を正直に返す。
