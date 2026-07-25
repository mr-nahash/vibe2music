# vibe2music

A simple local web app that turns a creative brief into an exact-length
instrumental mix and matching cover image.

Atlas Cloud generates the music with `suno/chirp-fenix`. Your computer handles
the queue, quality checks, mixing, cover creation, and downloads. No GPU is
required.

## First run

1. Install the Python packages:

   ```bash
   python -m pip install -r requirements.txt
   ```

2. Copy `.env.example` to `.env`.

3. Open `.env` and paste the Atlas Cloud key:

   ```dotenv
   ATLASCLOUD_API_KEY=your-key-here
   ```

4. Start the app:

   ```bash
   python app.py
   ```

The browser opens automatically at <http://127.0.0.1:8000>.

In VS Code, you can instead press **F5** and choose
**vibe2music: local web app**.

Enter the vibe, instruments, and target duration, then select **Start
production**. If no cover is uploaded, the app generates one automatically.

## Outputs

Every production is stored under `jobs/<job-id>/` and can be downloaded from
the web interface:

- `mix.wav` — exact-length audio master
- `cover.png` — generated or uploaded cover
- `metadata.json` — title, description, and tags
- `chapters.txt` — track timestamps
- `qc.json` — audio quality report
- `manifest.json` — prompts, selected outputs, and Atlas provenance

FFmpeg is optional. When available, the app also creates `preview.mp3` and
`video.mp4`. Without FFmpeg, song and cover generation still complete normally.

## Configuration

The only required setting is:

```dotenv
ATLASCLOUD_API_KEY=
```

Optional settings are documented in `.env.example`. Secrets belong in `.env`,
which is excluded from Git.

## Notes

- Atlas returns two audio alternatives per paid request. The app downloads the
  first and records both URLs in `manifest.json`.
- Long productions are coherent multi-track mixes because the Atlas
  Chirp-fenix endpoint does not expose a continuation operation.
- Review generated material and current commercial-use terms before publishing.
