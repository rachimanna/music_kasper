import json
import logging
from typing import List, Optional
import aiosqlite
from bot.config import config
from bot.services.base import Track

logger = logging.getLogger(__name__)


class Database:
    def __init__(self, db_path: str = config.DB_PATH):
        self.db_path = db_path

    async def init(self):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
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
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS search_cache (
                    query TEXT PRIMARY KEY,
                    track_ids TEXT NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            await db.commit()
            logger.info("Database initialized successfully.")

    async def save_track(self, track: Track):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT OR REPLACE INTO tracks (id, title, artist, duration, preview_url, cover_url, external_url)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                track.id,
                track.title,
                track.artist,
                track.duration,
                track.preview_url,
                track.cover_url,
                track.external_url
            ))
            await db.commit()

    async def get_track(self, track_id: str) -> Optional[Track]:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT id, title, artist, duration, preview_url, cover_url, external_url FROM tracks WHERE id = ?",
                (track_id,)
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    return Track(
                        id=row[0],
                        title=row[1],
                        artist=row[2],
                        duration=row[3],
                        preview_url=row[4],
                        cover_url=row[5],
                        external_url=row[6]
                    )
        return None

    async def get_cached_search(self, query: str) -> Optional[List[Track]]:
        normalized = query.strip().lower()
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT track_ids FROM search_cache WHERE query = ?",
                (normalized,)
            ) as cursor:
                row = await cursor.fetchone()
                if not row:
                    return None

                track_ids: List[str] = json.loads(row[0])
                tracks: List[Track] = []
                for tid in track_ids:
                    t = await self.get_track(tid)
                    if t:
                        tracks.append(t)
                return tracks if len(tracks) == len(track_ids) else None

    async def save_search_cache(self, query: str, tracks: List[Track]):
        normalized = query.strip().lower()
        track_ids = [t.id for t in tracks]
        for t in tracks:
            await self.save_track(t)

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT OR REPLACE INTO search_cache (query, track_ids, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
            """, (normalized, json.dumps(track_ids)))
            await db.commit()


db = Database()
