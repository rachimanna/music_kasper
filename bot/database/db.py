import json
import logging
import time
import uuid
from typing import Iterable, List, Optional, Tuple

import aiosqlite

from bot.config import config
from bot.services.base import Track
from bot.utils.formatters import normalize_query

logger = logging.getLogger(__name__)

_TRACK_COLUMNS = "id, title, artist, duration, preview_url, cover_url, external_url"


def _row_to_track(row) -> Track:
    return Track(
        id=row[0],
        title=row[1],
        artist=row[2],
        duration=int(row[3] or 0),
        preview_url=row[4],
        cover_url=row[5],
        external_url=row[6],
    )


class Database:
    """Одно постоянное соединение с SQLite вместо нового на каждый запрос."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._conn: Optional[aiosqlite.Connection] = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Database is not initialized, call db.init() first")
        return self._conn

    async def init(self) -> None:
        self._conn = await aiosqlite.connect(self.db_path)
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS tracks (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                artist TEXT NOT NULL,
                duration INTEGER NOT NULL,
                preview_url TEXT,
                cover_url TEXT,
                external_url TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            -- Старая таблица кэша без срока жизни больше не нужна.
            DROP TABLE IF EXISTS search_cache;

            CREATE TABLE IF NOT EXISTS search_cache_v2 (
                query TEXT PRIMARY KEY,
                track_ids TEXT NOT NULL,
                updated_at INTEGER NOT NULL
            );

            -- Результаты конкретного поиска: кнопки страниц ссылаются на session id,
            -- поэтому пагинация работает после перезапуска и не путает разные поиски.
            CREATE TABLE IF NOT EXISTS search_sessions (
                id TEXT PRIMARY KEY,
                query TEXT NOT NULL,
                track_ids TEXT NOT NULL,
                created_at INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_search_sessions_created ON search_sessions(created_at);
            """
        )
        await self._conn.commit()
        logger.info("Database initialized: %s", self.db_path)

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    # ---------- tracks ----------

    async def save_tracks(self, tracks: Iterable[Track]) -> None:
        rows = [
            (t.id, t.title, t.artist, t.duration, t.preview_url, t.cover_url, t.external_url)
            for t in tracks
        ]
        if not rows:
            return
        await self.conn.executemany(
            f"INSERT OR REPLACE INTO tracks ({_TRACK_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        await self.conn.commit()

    async def get_track(self, track_id: str) -> Optional[Track]:
        async with self.conn.execute(
            f"SELECT {_TRACK_COLUMNS} FROM tracks WHERE id = ?", (track_id,)
        ) as cursor:
            row = await cursor.fetchone()
        return _row_to_track(row) if row else None

    async def get_tracks(self, track_ids: List[str]) -> List[Track]:
        """Треки в том же порядке, что и track_ids (отсутствующие пропускаются)."""
        if not track_ids:
            return []
        placeholders = ",".join("?" * len(track_ids))
        async with self.conn.execute(
            f"SELECT {_TRACK_COLUMNS} FROM tracks WHERE id IN ({placeholders})", track_ids
        ) as cursor:
            rows = await cursor.fetchall()
        by_id = {row[0]: _row_to_track(row) for row in rows}
        return [by_id[tid] for tid in track_ids if tid in by_id]

    async def _load_track_list(self, raw_ids: str) -> Optional[List[Track]]:
        try:
            track_ids = [str(x) for x in json.loads(raw_ids)]
        except (ValueError, TypeError):
            return None
        tracks = await self.get_tracks(track_ids)
        return tracks if len(tracks) == len(track_ids) else None

    # ---------- search cache ----------

    async def get_cached_search(self, query: str) -> Optional[List[Track]]:
        if config.SEARCH_CACHE_TTL <= 0:
            return None
        min_time = int(time.time()) - config.SEARCH_CACHE_TTL
        async with self.conn.execute(
            "SELECT track_ids FROM search_cache_v2 WHERE query = ? AND updated_at >= ?",
            (normalize_query(query), min_time),
        ) as cursor:
            row = await cursor.fetchone()
        if not row:
            return None
        return await self._load_track_list(row[0])

    async def save_search_cache(self, query: str, tracks: List[Track]) -> None:
        await self.save_tracks(tracks)
        now = int(time.time())
        await self.conn.execute(
            "INSERT OR REPLACE INTO search_cache_v2 (query, track_ids, updated_at) VALUES (?, ?, ?)",
            (normalize_query(query), json.dumps([t.id for t in tracks]), now),
        )
        # Заодно чистим протухший кэш, чтобы база не росла бесконечно.
        await self.conn.execute(
            "DELETE FROM search_cache_v2 WHERE updated_at < ?", (now - config.SEARCH_CACHE_TTL,)
        )
        await self.conn.commit()

    # ---------- search sessions (пагинация) ----------

    async def create_session(self, query: str, tracks: List[Track]) -> str:
        await self.save_tracks(tracks)
        session_id = uuid.uuid4().hex[:12]
        now = int(time.time())
        await self.conn.execute(
            "INSERT INTO search_sessions (id, query, track_ids, created_at) VALUES (?, ?, ?, ?)",
            (session_id, query, json.dumps([t.id for t in tracks]), now),
        )
        await self.conn.execute(
            "DELETE FROM search_sessions WHERE created_at < ?", (now - config.SESSION_TTL,)
        )
        await self.conn.commit()
        return session_id

    async def get_session(self, session_id: str) -> Optional[Tuple[str, List[Track]]]:
        min_time = int(time.time()) - config.SESSION_TTL
        async with self.conn.execute(
            "SELECT query, track_ids FROM search_sessions WHERE id = ? AND created_at >= ?",
            (session_id, min_time),
        ) as cursor:
            row = await cursor.fetchone()
        if not row:
            return None
        tracks = await self._load_track_list(row[1])
        if not tracks:
            return None
        return row[0], tracks


db = Database(config.DB_PATH)
