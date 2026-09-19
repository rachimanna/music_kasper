# music_kasper

Telegram-бот для поиска музыки: метаданные берутся из Deezer, полные треки — из **вашего** источника
(сервер, которым вы владеете или на который у вас есть лицензия).

Deezer отдаёт только 30-секундное превью, поэтому бот **не** отправляет его вместо полной версии.

## Возможности

- Поиск в личке: просто напишите название.
- В группах: `@бот запрос`, `найди запрос` или ответ на сообщение бота. На остальные сообщения бот не реагирует.
- Inline-режим: `@бот запрос` в любом чате → карточка трека с кнопкой «⬇️ Скачать полную версию»
  (открывает личку с ботом и сразу присылает файл).
- Кэш поиска с автоматическим устареванием, пагинация, которая переживает перезапуск.
- Автоматический выбор битрейта, чтобы mp3 уложился в лимит Telegram (50 МБ).

## Настройка

1. Скопируйте `.env.example` в `.env` и заполните `BOT_TOKEN` и `AUDIO_SOURCE_URL_TEMPLATE`.
2. В @BotFather включите inline-режим: `/setinline`.
3. Чтобы бот видел «найди …» в группах без упоминания, выключите privacy mode: `/setprivacy` → Disable.

Пример шаблона: `https://your-domain.example/audio/{id}.m4a`
Поля `{artist}` и `{title}` кодируются автоматически (`AC/DC` → `AC%2FDC`).

## Запуск

### Termux (Android)

```bash
pkg install python ffmpeg
pip install -r requirements.txt
cp .env.example .env   # и отредактируйте
python -m bot.main
```

В Termux можно добавить в `.env` строку `WEB_SERVER_ENABLED=false`, веб-сервер там не нужен.

### Docker / Render

```bash
docker build -t music_kasper .
docker run --env-file .env music_kasper
```

На Render переменные окружения задаются в настройках сервиса; порт `PORT` Render выставляет сам.

## Структура

```
bot/
  main.py                      запуск, health-сервер, корректное завершение
  config.py                    все настройки
  database/db.py               SQLite: треки, кэш поиска, сессии пагинации
  filters/search_request.py    «адресовано ли сообщение боту»
  handlers/                    /start, /help, поиск, inline
  keyboards/pagination.py      клавиатуры
  middlewares/throttling.py    антиспам
  services/
    deezer_service.py          API Deezer
    catalog.py                 поиск с кэшем
    authorized_audio_service.py скачивание и конвертация полного трека
    delivery.py                отправка трека в чат
  utils/formatters.py          очистка запроса, форматирование
```
