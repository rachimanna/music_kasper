"""music_kasper — Telegram-бот, который ищет песни и присылает полные mp3."""

import asyncio
import hashlib
import logging
import os
import re
import secrets
import shutil
import subprocess
import tempfile
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import yt_dlp
from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ChatType, ParseMode
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from aiogram.utils.markdown import html_decoration as hd
from aiohttp import web
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("music_kasper")

BOT_TOKEN = os.environ["BOT_TOKEN"]
# Источники поиска по порядку. YouTube с серверов Render почти всегда блокируется,
# поэтому по умолчанию только SoundCloud. Можно задать "soundcloud,youtube".
SOURCES = [s.strip() for s in os.getenv("SOURCES", "soundcloud").split(",") if s.strip()]
RESULTS_LIMIT = int(os.getenv("RESULTS_LIMIT", "6"))
MAX_DURATION = 15 * 60  # длиннее — это миксы и подкасты, пропускаем
MAX_FILESIZE = 48 * 1024 * 1024  # лимит Telegram для ботов — 50 МБ
YT_COOKIES = os.getenv("YT_COOKIES")  # содержимое cookies.txt, если нужен YouTube

SEARCH_PREFIX = {"soundcloud": "scsearch", "youtube": "ytsearch"}

# ---------------------------------------------------------------- тексты

TEXTS = {
    "ru": {
        "start": (
            "👻 Привет! Я <b>Каспер</b> — найду любую песню и пришлю её целиком.\n\n"
            "Просто напиши название, например:\n"
            "• <code>anna asti феникс</code>\n"
            "• <code>каспер найди песню кино группа крови</code>\n\n"
            "В группе обращайся ко мне по имени: <code>каспер …</code> "
            "или <code>найди песню …</code>"
        ),
        "searching": "🔎 Ищу «{q}»…",
        "results": "🎵 Нашёл по запросу «{q}». Выбирай:",
        "nothing": "😔 Ничего не нашёл по запросу «{q}». Попробуй написать по-другому.",
        "empty": "Что найти? Напиши, например: <code>каспер найди песню anna asti</code>",
        "error": "⚠️ Не получилось поискать, попробуй ещё раз чуть позже.",
        "expired": "Этот поиск устарел, поищи заново 🙏",
        "downloading": "⏬ Качаю: {t}",
        "dl_error": "⚠️ Не получилось скачать «{t}». Выбери другой вариант.",
        "preview_only": "😕 «{t}» доступна только 30-секундным отрывком. Выбери другой вариант.",
        "too_big": "😕 «{t}» слишком большая для Telegram. Выбери другой вариант.",
        "busy": "Подожди, уже качаю 🙂",
    },
    "en": {
        "start": (
            "👻 Hi! I'm <b>Kasper</b> — I find any song and send you the full track.\n\n"
            "Just type a title, for example:\n"
            "• <code>the weeknd blinding lights</code>\n"
            "• <code>kasper find song imagine dragons believer</code>\n\n"
            "In groups call me by name: <code>kasper …</code> or <code>find song …</code>"
        ),
        "searching": "🔎 Searching for “{q}”…",
        "results": "🎵 Results for “{q}”. Pick one:",
        "nothing": "😔 Nothing found for “{q}”. Try another wording.",
        "empty": "What should I find? E.g. <code>kasper find song believer</code>",
        "error": "⚠️ Search failed, please try again a bit later.",
        "expired": "This search has expired, please search again 🙏",
        "downloading": "⏬ Downloading: {t}",
        "dl_error": "⚠️ Couldn't download “{t}”. Pick another one.",
        "preview_only": "😕 “{t}” is only available as a 30-second preview. Pick another one.",
        "too_big": "😕 “{t}” is too big for Telegram. Pick another one.",
        "busy": "Hold on, already downloading 🙂",
    },
}

# ---------------------------------------------------------------- разбор фраз

NAMES_RU = ("каспер", "касперчик")
NAMES_EN = ("kasper", "casper")
VERBS_RU = ("найди", "найти", "поищи", "ищи", "скинь", "включи")
VERBS_EN = ("find", "search")  # не "play"/"get" — с них начинаются названия песен
OBJECTS = ("песню", "песня", "песенку", "трек", "музыку", "song", "track", "music")

_alt = lambda words: "|".join(words)  # noqa: E731
TRIGGER_RE = re.compile(
    rf"^\s*(?:(?P<name>{_alt(NAMES_RU + NAMES_EN)})\b[\s,!:.-]*)?"
    rf"(?:(?P<verb>{_alt(VERBS_RU + VERBS_EN)})\b\s*(?:(?:{_alt(OBJECTS)})\b)?)?"
    rf"[\s,:.—-]*(?P<query>.*?)\s*$",
    re.IGNORECASE | re.DOTALL,
)
CYRILLIC_RE = re.compile(r"[а-яё]", re.IGNORECASE)


def parse_request(text: str, user_lang: str | None) -> tuple[bool, str, str]:
    """Возвращает (обратились_к_боту, запрос, язык)."""
    m = TRIGGER_RE.match(text)
    name, verb, query = m.group("name"), m.group("verb"), m.group("query")
    if verb:
        lang = "en" if verb.lower() in VERBS_EN else "ru"
    elif name:
        lang = "en" if name.lower() in NAMES_EN else "ru"
    elif CYRILLIC_RE.search(text):
        lang = "ru"
    else:
        lang = "ru" if (user_lang or "").startswith(("ru", "uk", "be", "kk")) else "en"
    return bool(name or verb), query, lang


def t(lang: str, key: str, **kw) -> str:
    return TEXTS[lang][key].format(**{k: hd.quote(str(v)) for k, v in kw.items()})


# ---------------------------------------------------------------- yt-dlp


def _base_opts() -> dict:
    opts = {"quiet": True, "no_warnings": True, "noprogress": True, "noplaylist": True}
    if YT_COOKIES:
        path = Path(tempfile.gettempdir()) / "yt_cookies.txt"
        if not path.exists():
            path.write_text(YT_COOKIES)
        opts["cookiefile"] = str(path)
    return opts


def _search_source(source: str, query: str, limit: int) -> list[dict]:
    opts = _base_opts() | {"extract_flat": "in_playlist", "skip_download": True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(f"{SEARCH_PREFIX[source]}{limit}:{query}", download=False)
    results = []
    for e in info.get("entries") or []:
        duration = e.get("duration")
        if not duration or duration > MAX_DURATION:
            continue  # каналы, плейлисты, миксы
        url = e.get("url")
        if source == "youtube":
            url = f"https://www.youtube.com/watch?v={e['id']}"
        results.append(
            {
                "title": e.get("title") or "?",
                "artist": e.get("uploader") or e.get("channel") or "",
                "duration": int(duration),
                "url": url,
            }
        )
    return results


def _is_downloadable(track: dict) -> bool:
    """Отсеивает треки с DRM и прочие, которые не скачать."""
    try:
        with yt_dlp.YoutubeDL(_base_opts() | {"skip_download": True}) as ydl:
            info = ydl.extract_info(track["url"], download=False)
        return bool(info.get("formats") or info.get("url"))
    except Exception as e:
        log.info("skip %s: %s", track["url"], str(e)[-80:])
        return False


def search(query: str) -> list[dict]:
    last_error = None
    for source in SOURCES:
        try:
            candidates = _search_source(source, query, RESULTS_LIMIT * 2 + 4)
            with ThreadPoolExecutor(max_workers=8) as pool:
                ok = list(pool.map(_is_downloadable, candidates))
            if results := [t for t, good in zip(candidates, ok) if good][:RESULTS_LIMIT]:
                return results
        except Exception as e:  # пробуем следующий источник
            last_error = e
            log.warning("search via %s failed: %s", source, e)
    if last_error and len(SOURCES) == 1:
        raise last_error
    return []


def _probe_duration(path: Path) -> float | None:
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, timeout=30,
        )
        return float(out.stdout.strip())
    except Exception:
        return None


class PreviewOnly(Exception):
    pass


class TooBig(Exception):
    pass


def download(url: str, workdir: str) -> tuple[Path, dict]:
    opts = _base_opts() | {
        "format": "bestaudio/best",
        "outtmpl": f"{workdir}/%(id)s.%(ext)s",
        "max_filesize": MAX_FILESIZE,
        "postprocessors": [
            {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"},
        ],
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
    files = list(Path(workdir).glob("*.mp3"))
    if not files:
        raise TooBig()
    path = files[0]
    if path.stat().st_size > MAX_FILESIZE:
        raise TooBig()
    # SoundCloud иногда отдаёт только 30-секундный отрывок платных треков
    real = _probe_duration(path)
    expected = info.get("duration") or 0
    if real and expected > 60 and real < 40:
        raise PreviewOnly()
    return path, info


# ---------------------------------------------------------------- бот

router = Router()
searches: OrderedDict[str, dict] = OrderedDict()  # token -> {"results", "lang", "query"}
file_cache: dict[str, str] = {}  # url -> telegram file_id, чтобы повторно не качать
in_progress: set[tuple[int, str]] = set()
download_slots = asyncio.Semaphore(2)  # бесплатный Render — 512 МБ RAM


def fmt_duration(sec: int) -> str:
    return f"{sec // 60}:{sec % 60:02d}"


def results_keyboard(token: str, results: list[dict]) -> InlineKeyboardMarkup:
    rows = []
    for i, r in enumerate(results):
        label = r["title"]
        has_artist = " - " in label or " — " in label or (r["artist"] or "").lower() in label.lower()
        if r["artist"] and not has_artist:
            label = f"{r['artist']} — {label}"
        label = f"🎵 {label}"[:58] + f" · {fmt_duration(r['duration'])}"
        rows.append([InlineKeyboardButton(text=label, callback_data=f"d:{token}:{i}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def do_search(message: Message, query: str, lang: str) -> None:
    if not query:
        await message.reply(t(lang, "empty"))
        return
    query = query[:100]
    status = await message.reply(t(lang, "searching", q=query))
    try:
        results = await asyncio.to_thread(search, query)
    except Exception:
        log.exception("search failed")
        await status.edit_text(t(lang, "error"))
        return
    if not results:
        await status.edit_text(t(lang, "nothing", q=query))
        return
    token = secrets.token_urlsafe(6)
    searches[token] = {"results": results, "lang": lang, "query": query}
    while len(searches) > 1000:
        searches.popitem(last=False)
    await status.edit_text(t(lang, "results", q=query), reply_markup=results_keyboard(token, results))


@router.message(CommandStart())
@router.message(Command("help"))
async def cmd_start(message: Message) -> None:
    _, _, lang = parse_request(message.text or "", message.from_user and message.from_user.language_code)
    await message.answer(t(lang, "start"))


@router.message(Command("find", "song", "search", "naydi"))
async def cmd_find(message: Message, command: CommandObject) -> None:
    query = (command.args or "").strip()
    _, _, lang = parse_request(query, message.from_user and message.from_user.language_code)
    await do_search(message, query, lang)


@router.message(F.text & ~F.text.startswith("/"))
async def on_text(message: Message) -> None:
    called, query, lang = parse_request(message.text, message.from_user and message.from_user.language_code)
    if message.chat.type != ChatType.PRIVATE and not called:
        return  # в группах отвечаем только когда зовут по имени или «найди песню …»
    await do_search(message, query, lang)


@router.callback_query(F.data.startswith("d:"))
async def on_pick(cb: CallbackQuery, bot: Bot) -> None:
    _, token, idx = cb.data.split(":")
    entry = searches.get(token)
    if not entry:
        await cb.answer(t("ru", "expired"), show_alert=True)
        return
    lang = entry["lang"]
    track = entry["results"][int(idx)]
    chat_id = cb.message.chat.id
    title = f"{track['artist']} — {track['title']}" if track["artist"] else track["title"]

    if cached := file_cache.get(track["url"]):
        await cb.answer()
        await bot.send_audio(chat_id, cached, reply_to_message_id=cb.message.message_id)
        return

    key = (chat_id, track["url"])
    if key in in_progress:
        await cb.answer(t(lang, "busy"))
        return
    in_progress.add(key)
    await cb.answer(t(lang, "downloading", t=title)[:200])
    status = await cb.message.reply(t(lang, "downloading", t=title))
    workdir = tempfile.mkdtemp(prefix="kasper_")
    try:
        async with download_slots:
            path, info = await asyncio.to_thread(download, track["url"], workdir)
        sent = await bot.send_audio(
            chat_id,
            FSInputFile(path, filename=f"{title[:60]}.mp3"),
            title=info.get("track") or track["title"],
            performer=info.get("artist") or track["artist"] or None,
            duration=int(info.get("duration") or track["duration"]),
            reply_to_message_id=cb.message.message_id,
        )
        file_cache[track["url"]] = sent.audio.file_id
        await status.delete()
    except PreviewOnly:
        await status.edit_text(t(lang, "preview_only", t=title))
    except TooBig:
        await status.edit_text(t(lang, "too_big", t=title))
    except Exception:
        log.exception("download failed: %s", track["url"])
        await status.edit_text(t(lang, "dl_error", t=title))
    finally:
        in_progress.discard(key)
        shutil.rmtree(workdir, ignore_errors=True)


# ---------------------------------------------------------------- запуск


def main() -> None:
    bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(router)

    public_url = os.getenv("RENDER_EXTERNAL_URL") or os.getenv("WEBHOOK_URL")
    if not public_url:
        log.info("Локальный запуск: long polling")
        asyncio.run(dp.start_polling(bot))
        return

    # На Render: вебхук. Входящее сообщение будит бесплатный сервис после сна.
    path = "/webhook"
    secret = hashlib.sha256(BOT_TOKEN.encode()).hexdigest()[:32]

    async def on_startup(bot: Bot) -> None:
        await bot.set_webhook(f"{public_url}{path}", secret_token=secret, drop_pending_updates=False)
        log.info("Webhook set: %s%s", public_url, path)

    dp.startup.register(on_startup)
    app = web.Application()
    app.router.add_get("/", lambda _: web.Response(text="music_kasper is alive 👻"))
    app.router.add_get("/health", lambda _: web.Response(text="ok"))
    SimpleRequestHandler(dispatcher=dp, bot=bot, secret_token=secret).register(app, path=path)
    setup_application(app, dp, bot=bot)
    web.run_app(app, host="0.0.0.0", port=int(os.getenv("PORT", "10000")))


if __name__ == "__main__":
    main()
