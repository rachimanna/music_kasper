"""Поиск с кэшем: сначала база, потом Deezer."""
import logging
from typing import List, Optional

from bot.config import config
from bot.database.db import db
from bot.services.base import Track
from bot.services.deezer_service import deezer

logger = logging.getLogger(__name__)


async def search_tracks(query: str) -> List[Track]:
    """Бросает ProviderError, если Deezer недоступен."""
    cached = await db.get_cached_search(query)
    if cached:
        return cached

    tracks = await deezer.search(query, limit=config.SEARCH_LIMIT)
    if tracks:
        await db.save_search_cache(query, tracks)
    return tracks


async def find_track(track_id: str) -> Optional[Track]:
    track = await db.get_track(track_id)
    if track:
        return track

    track = await deezer.get_track(track_id)
    if track:
        await db.save_tracks([track])
    return track
