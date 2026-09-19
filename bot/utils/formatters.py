def format_duration(seconds: int) -> str:
    minutes = seconds // 60
    sec = seconds % 60
    return f"{minutes:02d}:{sec:02d}"


def sanitize_query(text: str, bot_username: str = "") -> str:
    cleaned = text.strip()

    if bot_username:
        cleaned = cleaned.replace(f"@{bot_username}", "").replace(f"@{bot_username.lower()}", "")

    prefixes = ["найди песню", "найди трек", "найди музыку", "найди", "search", "music"]
    lower_text = cleaned.lower()

    for prefix in prefixes:
        if lower_text.startswith(prefix):
            cleaned = cleaned[len(prefix):].strip()
            break

    return cleaned.strip()
