import re

# «найди», «найди песню/трек/музыку», «search», «music» — только как отдельное слово в начале.
_PREFIX_RE = re.compile(
    r"^(?:найди(?:\s+(?:песню|трек|музыку))?|search|music)(?=\s|$)[\s,.:;-]*",
    re.IGNORECASE,
)
_BAD_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def format_duration(seconds) -> str:
    try:
        seconds = max(0, int(seconds or 0))
    except (TypeError, ValueError):
        seconds = 0
    hours, rest = divmod(seconds, 3600)
    minutes, sec = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{sec:02d}"
    return f"{minutes}:{sec:02d}"


def mention_pattern(bot_username: str) -> re.Pattern:
    return re.compile(rf"@{re.escape(bot_username)}\b", re.IGNORECASE)


def normalize_query(query: str) -> str:
    """Ключ для кэша: нижний регистр и одиночные пробелы."""
    return " ".join(query.lower().split())


def sanitize_query(text: str, bot_username: str = "", max_length: int = 100) -> str:
    cleaned = text or ""
    if bot_username:
        cleaned = mention_pattern(bot_username).sub(" ", cleaned)
    cleaned = " ".join(cleaned.split())
    cleaned = _PREFIX_RE.sub("", cleaned, count=1)
    return cleaned.strip()[:max_length].strip()


def truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def safe_filename(name: str, limit: int = 120) -> str:
    cleaned = _BAD_FILENAME_CHARS.sub("", name)
    cleaned = " ".join(cleaned.split()).strip(" .")
    return cleaned[:limit] or "track"
