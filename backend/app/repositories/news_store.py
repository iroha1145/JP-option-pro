"""jp-news.db — 日本株ニュースの保存層（worker 専用ライタ）。

原文は不変で保持し、日本語訳・中文分析は独立フィールドに追記する。
翻訳/分析はモデル・プロンプト版・指紋つきで保存し、静黙な上書きをしない。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from .base import SQLiteRepository, utc_now_iso

NEWS_SCHEMA_VERSION = "jp-news-v1"

NEWS_DDL: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS news_items (
        news_id TEXT PRIMARY KEY,
        source TEXT NOT NULL,
        source_url TEXT,
        original_title TEXT NOT NULL,
        original_summary TEXT,
        source_language TEXT NOT NULL DEFAULT 'unknown',
        published_at TEXT,
        fetched_at TEXT NOT NULL,
        content_fingerprint TEXT NOT NULL,
        duplicate_of TEXT,
        categories_json TEXT NOT NULL DEFAULT '[]',
        securities_json TEXT NOT NULL DEFAULT '[]',
        sectors_json TEXT NOT NULL DEFAULT '[]',
        market_relevance TEXT,
        importance REAL,
        importance_components_json TEXT NOT NULL DEFAULT '{}',
        translated_title_ja TEXT,
        translated_summary_ja TEXT,
        translation_model TEXT,
        translation_version TEXT,
        translation_fingerprint TEXT,
        translated_at TEXT,
        analysis_zh_json TEXT,
        analysis_model TEXT,
        analysis_version TEXT,
        analysis_fingerprint TEXT,
        analyzed_at TEXT
    ) WITHOUT ROWID
    """,
    "CREATE INDEX IF NOT EXISTS idx_news_published ON news_items(published_at)",
    "CREATE INDEX IF NOT EXISTS idx_news_fingerprint ON news_items(content_fingerprint)",
    """
    CREATE TABLE IF NOT EXISTS news_feed_state (
        feed_url TEXT PRIMARY KEY,
        etag TEXT,
        last_modified TEXT,
        last_fetched_at TEXT,
        last_error_code TEXT,
        items_seen INTEGER NOT NULL DEFAULT 0
    ) WITHOUT ROWID
    """,
    """
    CREATE TABLE IF NOT EXISTS entity_aliases (
        alias TEXT NOT NULL,
        canonical_code TEXT NOT NULL,
        alias_type TEXT NOT NULL,
        PRIMARY KEY (alias, canonical_code)
    ) WITHOUT ROWID
    """,
    "CREATE INDEX IF NOT EXISTS idx_alias_code ON entity_aliases(canonical_code)",
)


class NewsStore(SQLiteRepository):
    SCHEMA_NAME = "jp_news"
    SCHEMA_VERSION = NEWS_SCHEMA_VERSION
    DDL = NEWS_DDL

    def __init__(self, db_path: Path, *, read_only: bool = False) -> None:
        super().__init__(db_path, read_only=read_only)

    # -- feed state -------------------------------------------------------

    def feed_state(self, feed_url: str) -> dict[str, Any] | None:
        with self.read() as connection:
            row = connection.execute(
                "SELECT * FROM news_feed_state WHERE feed_url = ?", (feed_url,)
            ).fetchone()
        return dict(row) if row else None

    def feed_states(self) -> list[dict[str, Any]]:
        with self.read() as connection:
            rows = connection.execute(
                "SELECT * FROM news_feed_state ORDER BY feed_url"
            ).fetchall()
        return [dict(row) for row in rows]

    def alias_count(self) -> int:
        with self.read() as connection:
            return int(connection.execute("SELECT COUNT(*) FROM entity_aliases").fetchone()[0])

    def record_feed_fetch(
        self, feed_url: str, *, etag: str | None, last_modified: str | None,
        items_seen: int, error_code: str | None = None,
    ) -> None:
        with self.write() as connection:
            connection.execute(
                "INSERT INTO news_feed_state (feed_url, etag, last_modified, last_fetched_at, "
                "last_error_code, items_seen) VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT (feed_url) DO UPDATE SET etag = excluded.etag, "
                "last_modified = excluded.last_modified, last_fetched_at = excluded.last_fetched_at, "
                "last_error_code = excluded.last_error_code, "
                "items_seen = news_feed_state.items_seen + excluded.items_seen",
                (feed_url, etag, last_modified, utc_now_iso(), error_code, items_seen),
            )

    # -- entity aliases -----------------------------------------------------

    def replace_entity_aliases(self, rows: Iterable[tuple[str, str, str]]) -> int:
        prepared = [(alias, code, alias_type) for alias, code, alias_type in rows if alias and code]
        if not prepared:
            # Don't wipe the alias catalog on an empty rebuild (e.g. a transient
            # empty master); keep the last good set.
            return 0
        with self.write() as connection:
            connection.execute("DELETE FROM entity_aliases")
            connection.executemany(
                "INSERT OR IGNORE INTO entity_aliases (alias, canonical_code, alias_type) "
                "VALUES (?, ?, ?)",
                prepared,
            )
        return len(prepared)

    def all_entity_aliases(self) -> list[dict[str, Any]]:
        with self.read() as connection:
            rows = connection.execute("SELECT * FROM entity_aliases").fetchall()
        return [dict(row) for row in rows]

    # -- news items -----------------------------------------------------------

    def known_news_ids(self, news_ids: Iterable[str]) -> set[str]:
        ids = [news_id for news_id in news_ids if news_id]
        if not ids:
            return set()
        placeholders = ", ".join("?" for _ in ids)
        with self.read() as connection:
            rows = connection.execute(
                f"SELECT news_id FROM news_items WHERE news_id IN ({placeholders})", ids
            ).fetchall()
        return {row[0] for row in rows}

    def recent_titles_since(self, since_iso: str) -> list[tuple[str, str, str]]:
        """近接重複判定用: (news_id, original_title, securities_json)。"""

        with self.read() as connection:
            rows = connection.execute(
                "SELECT news_id, original_title, securities_json FROM news_items "
                "WHERE fetched_at >= ? AND duplicate_of IS NULL",
                (since_iso,),
            ).fetchall()
        return [(row[0], row[1], row[2] or "[]") for row in rows]

    def fingerprint_exists_since(self, fingerprint: str, *, since_iso: str) -> str | None:
        with self.read() as connection:
            row = connection.execute(
                "SELECT news_id FROM news_items WHERE content_fingerprint = ? "
                "AND fetched_at >= ? AND duplicate_of IS NULL LIMIT 1",
                (fingerprint, since_iso),
            ).fetchone()
        return row[0] if row else None

    def insert_news_items(self, items: Iterable[Mapping[str, Any]]) -> int:
        now = utc_now_iso()
        prepared = []
        for item in items:
            if not item.get("news_id") or not item.get("original_title"):
                continue
            prepared.append(
                (
                    item["news_id"], item.get("source") or "unknown", item.get("source_url"),
                    item["original_title"], item.get("original_summary"),
                    item.get("source_language") or "unknown",
                    item.get("published_at"), item.get("fetched_at") or now,
                    item.get("content_fingerprint") or item["news_id"],
                    item.get("duplicate_of"),
                    json.dumps(item.get("categories") or [], ensure_ascii=False),
                    json.dumps(item.get("securities") or [], ensure_ascii=False),
                    json.dumps(item.get("sectors") or [], ensure_ascii=False),
                    item.get("market_relevance"),
                    item.get("importance"),
                    json.dumps(item.get("importance_components") or {}, ensure_ascii=False),
                )
            )
        if not prepared:
            return 0
        with self.write() as connection:
            connection.executemany(
                "INSERT OR IGNORE INTO news_items (news_id, source, source_url, original_title, "
                "original_summary, source_language, published_at, fetched_at, content_fingerprint, "
                "duplicate_of, categories_json, securities_json, sectors_json, market_relevance, "
                "importance, importance_components_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                prepared,
            )
        return len(prepared)

    def attach_translation(
        self, news_id: str, *, title_ja: str, summary_ja: str | None,
        model: str, version: str, fingerprint: str,
    ) -> bool:
        with self.write() as connection:
            cursor = connection.execute(
                "UPDATE news_items SET translated_title_ja = ?, translated_summary_ja = ?, "
                "translation_model = ?, translation_version = ?, translation_fingerprint = ?, "
                "translated_at = ? WHERE news_id = ?",
                (title_ja, summary_ja, model, version, fingerprint, utc_now_iso(), news_id),
            )
            return bool(cursor.rowcount)

    def attach_analysis(
        self, news_id: str, *, analysis: Mapping[str, Any],
        model: str, version: str, fingerprint: str,
    ) -> bool:
        with self.write() as connection:
            cursor = connection.execute(
                "UPDATE news_items SET analysis_zh_json = ?, analysis_model = ?, "
                "analysis_version = ?, analysis_fingerprint = ?, analyzed_at = ? WHERE news_id = ?",
                (
                    json.dumps(analysis, ensure_ascii=False, sort_keys=True),
                    model, version, fingerprint, utc_now_iso(), news_id,
                ),
            )
            return bool(cursor.rowcount)

    def recent_items(self, *, since_iso: str, limit: int = 200) -> list[dict[str, Any]]:
        with self.read() as connection:
            rows = connection.execute(
                "SELECT * FROM news_items WHERE duplicate_of IS NULL "
                "AND COALESCE(published_at, fetched_at) >= ? "
                "ORDER BY COALESCE(published_at, fetched_at) DESC LIMIT ?",
                (since_iso, int(limit)),
            ).fetchall()
        return [self._decode(row) for row in rows]

    def items_for_security(self, canonical_code: str, *, limit: int = 50) -> list[dict[str, Any]]:
        pattern = f'%"{canonical_code}"%'
        with self.read() as connection:
            rows = connection.execute(
                "SELECT * FROM news_items WHERE duplicate_of IS NULL AND securities_json LIKE ? "
                "ORDER BY COALESCE(published_at, fetched_at) DESC LIMIT ?",
                (pattern, int(limit)),
            ).fetchall()
        return [self._decode(row) for row in rows]

    def pending_ai_candidates(
        self,
        *,
        since_iso: str,
        limit: int,
        translation_version: str | None = None,
        analysis_version: str | None = None,
    ) -> list[dict[str, Any]]:
        """重要度順で翻訳/分析が欠けている（または版が古い）アイテムを返す。

        translation_version / analysis_version を渡すと、既訳・既分析でも保存された
        版が現行 prompt 版と異なる行を再選択する（版更新時に旧結果を再処理するため）。

        SQLite の ``col IS NOT ?`` は bind が非 NULL でも ``col IS NULL`` を真にする。
        日本語原文は翻訳しないので ``translation_version`` がずっと NULL のままになり、
        素の ``IS NOT ?`` だと「既に分析済みの日本語」が候補を埋め尽くす。
        欠落、または「成果物があるのに版が違う」だけを拾う。
        """

        if translation_version is None and analysis_version is None:
            predicate = "(translated_title_ja IS NULL OR analysis_zh_json IS NULL)"
            params: tuple[Any, ...] = (since_iso, int(limit))
        else:
            # 翻訳: 日本語以外で未訳、または既訳だが版が違う / 版が空。
            # 分析: 未分析、または既分析だが版が違う / 版が空。
            predicate = """(
                (translated_title_ja IS NULL AND source_language != 'ja')
                OR (translated_title_ja IS NOT NULL AND (
                    translation_version IS NULL OR translation_version IS NOT ?
                ))
                OR analysis_zh_json IS NULL
                OR (analysis_zh_json IS NOT NULL AND (
                    analysis_version IS NULL OR analysis_version IS NOT ?
                ))
            )"""
            params = (since_iso, translation_version, analysis_version, int(limit))
        with self.read() as connection:
            rows = connection.execute(
                "SELECT * FROM news_items WHERE duplicate_of IS NULL "
                "AND COALESCE(published_at, fetched_at) >= ? "
                f"AND {predicate} "
                "AND securities_json != '[]' "
                "ORDER BY importance IS NULL, importance DESC LIMIT ?",
                params,
            ).fetchall()
        return [self._decode(row) for row in rows]

    def get_item(self, news_id: str) -> dict[str, Any] | None:
        with self.read() as connection:
            row = connection.execute(
                "SELECT * FROM news_items WHERE news_id = ?", (news_id,)
            ).fetchone()
        return self._decode(row) if row else None

    def prune_older_than(self, cutoff_iso: str) -> int:
        with self.write() as connection:
            cursor = connection.execute(
                "DELETE FROM news_items WHERE COALESCE(published_at, fetched_at) < ?",
                (cutoff_iso,),
            )
            return cursor.rowcount or 0

    @staticmethod
    def _decode(row: Any) -> dict[str, Any]:
        item = dict(row)
        for json_key, target in (
            ("categories_json", "categories"),
            ("securities_json", "securities"),
            ("sectors_json", "sectors"),
            ("importance_components_json", "importance_components"),
        ):
            raw = item.pop(json_key, None)
            try:
                item[target] = json.loads(raw) if raw else ([] if target != "importance_components" else {})
            except ValueError:
                item[target] = [] if target != "importance_components" else {}
        raw_analysis = item.pop("analysis_zh_json", None)
        try:
            item["analysis_zh"] = json.loads(raw_analysis) if raw_analysis else None
        except ValueError:
            item["analysis_zh"] = None
        return item


__all__ = ["NEWS_SCHEMA_VERSION", "NewsStore"]
