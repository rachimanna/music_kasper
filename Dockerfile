FROM python:3.12-slim

# ffmpeg — конвертация в mp3, deno — нужен yt-dlp для YouTube
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*
COPY --from=denoland/deno:bin /deno /usr/local/bin/deno

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY bot.py .

ENV PYTHONUNBUFFERED=1
CMD ["python", "bot.py"]
