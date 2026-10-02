# 👻 music_kasper

Telegram-бот, который ищет песни и присылает **полные треки mp3-файлом**, а не ссылки и не 30-секундные отрывки.

## Как пользоваться

| Где | Что писать |
|---|---|
| Личка | просто название: `anna asti феникс` |
| Группа | `каспер найди песню anna asti`, `каспер anna asti`, `найди песню …` |
| По-английски | `kasper find song believer`, `find track …` — ответит на английском |
| Команды | `/find <запрос>`, `/start` |

Бот показывает до 6 вариантов кнопками. Нажимаешь на кнопку, и приходит аудиофайл.

## Деплой на Render (бесплатно)

1. **@BotFather** → `/newbot` → получить токен.
   Затем `/setprivacy` → выбрать бота → **Disable**, чтобы бот видел сообщения в группах.
2. [render.com](https://render.com) → **New → Blueprint** → выбрать этот репозиторий
   (или **New → Web Service** → репозиторий → Runtime: **Docker** → Plan: **Free**).
3. В **Environment** добавить `BOT_TOKEN` = токен от BotFather.
4. Deploy. Бот сам настроит вебхук на адрес Render.

### Чтобы бот не засыпал
Бесплатный Render усыпляет сервис через 15 минут без запросов. Первое сообщение его разбудит,
но ответ придёт через ~30–60 секунд. Чтобы бот отвечал сразу, заведи бесплатный монитор на
[uptimerobot.com](https://uptimerobot.com): тип HTTP(s), адрес `https://<твой-сервис>.onrender.com/health`, интервал 5 минут.

## Переменные окружения

| Переменная | Зачем |
|---|---|
| `BOT_TOKEN` | токен бота (обязательно) |
| `SOURCES` | откуда искать: `soundcloud` (по умолчанию) или `soundcloud,youtube` |
| `YT_COOKIES` | содержимое cookies.txt от YouTube. Без него YouTube блокирует серверы Render |
| `RESULTS_LIMIT` | сколько вариантов показывать (по умолчанию 6) |

## Локальный запуск

```bash
pip install -r requirements.txt   # и установить ffmpeg
BOT_TOKEN=... python bot.py        # без RENDER_EXTERNAL_URL работает через polling
```
