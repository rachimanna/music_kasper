# music_kasper

Telegram-бот для поиска музыки. Поиск идёт по каталогу Deezer, а при выборе трека бот присылает:

1. **Полную версию со своего сервера** — если задан `AUDIO_SOURCE_URL_TEMPLATE` (музыка, на которую у вас есть права).
2. **Полную версию с [Jamendo](https://www.jamendo.com)** — если трек выложен там под Creative Commons и разрешён
   к скачиванию (в основном независимые исполнители). В подписи указывается ссылка на лицензию.
3. **30-секундное превью Deezer** с явной пометкой и кнопкой «Открыть в Deezer» — если полной версии нет.

Полные версии коммерческих релизов бот не скачивает: легального бесплатного источника для них нет.

## Возможности

- Поиск в личке: просто напишите название.
- В группах: `@бот запрос`, `найди запрос` или ответ на сообщение бота. На остальные сообщения бот не реагирует.
- Inline-режим: `@бот запрос` в любом чате → карточка трека с кнопкой «⬇️ Скачать полную версию»
  (открывает личку с ботом и сразу присылает файл).
- Кэш поиска с автоматическим устареванием, пагинация, которая переживает перезапуск.
- Автоматический выбор битрейта, чтобы mp3 уложился в лимит Telegram (50 МБ).

## Настройка

1. Скопируйте `.env.example` в `.env` и заполните `BOT_TOKEN`.
   Для полных треков с Jamendo получите бесплатный `JAMENDO_CLIENT_ID` на https://devportal.jamendo.com.
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
    jamendo_service.py         поиск полной версии на Jamendo
    catalog.py                 поиск с кэшем
    authorized_audio_service.py скачивание и конвертация полного трека
    delivery.py                выбор источника и отправка трека в чат
  utils/formatters.py          очистка запроса, форматирование
```
