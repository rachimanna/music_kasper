music_kasper

Telegram music search bot based on Deezer metadata and an authorized full-audio source.

Important

Deezer’s preview URL is only a short preview. This project deliberately does not fall back to that preview when a full file cannot be downloaded.

Set AUDIO_SOURCE_URL_TEMPLATE in Render to a full-audio endpoint that you own or are licensed to use. The template supports {id}, {artist} and {title}.

Example:

https://your-domain.example/audio/{id}.m4a

The downloader uses unique temporary filenames, streaming writes, a configurable file-size limit, longer read timeouts, and FFmpeg conversion. Temporary files are always removed after sending.
