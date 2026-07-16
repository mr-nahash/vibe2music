# vibe2music

Vibe (text or image) + instruments -> AI instrumental track set -> mixed,
rendered, and uploaded to YouTube. Human review before every publish.
Companion doc: `vibe-to-music-blueprint.md`.

## Layout

```
vibe2music/
  config.yaml                 pipeline settings
  requirements.txt
  runpod/setup.sh             one-shot GPU box setup
  src/
    prompt_compiler.py        vibe -> prompts.json      (cheap LLM: Haiku)
    generate.py               prompts -> WAVs           (ACE-Step, GPU)
    qc.py                     audio quality gate        (no LLM)
    mix.py                    normalize+crossfade mix   (no LLM)
    render.py                 image+mix -> video.mp4    (ffmpeg)
    metadata.py               title/desc/tags draft     (cheap LLM: Haiku)
    upload.py                 YouTube Data API upload   (private by default)
    run_all.py                one-command pipeline
    server.py                 FastAPI backend for the web control panel
  ui/index.html               control panel (deploy to Cloudflare Pages)
```

## Option A -- CLI (simplest)

On a RunPod RTX 4090 (~$0.35/hr):
```
bash runpod/setup.sh
export ANTHROPIC_API_KEY=sk-ant-...
python src/run_all.py "rainy tokyo cafe" --instruments piano,vinyl --image cover.jpg
# review mix.wav + metadata.json, then:
python src/upload.py output/<set-name> --privacy private
```
`--dry-run` on run_all.py previews the plan with zero GPU/API cost.

## Option B -- Web control panel (Cloudflare)

1. On the GPU box after setup.sh:
   `export ANTHROPIC_API_KEY=... API_TOKEN=<pick-a-secret>`
   `cd src && uvicorn server:app --host 0.0.0.0 --port 8000`
   Expose port 8000 via RunPod's HTTP proxy (gives you an https URL).
2. Deploy the UI (free):
   `npx wrangler pages deploy ui/ --project-name vibe2music`
3. Open the Pages URL, paste the GPU box URL + token, submit a vibe.
   Review (listen + edit metadata) -> Upload (always private) -> publish
   manually in YouTube Studio.

Note: Cloudflare only serves the static panel; generation/ffmpeg stay on the
GPU box -- Workers can't run them.

## YouTube setup (one time)

1. Google Cloud project -> enable YouTube Data API v3.
2. OAuth consent screen (External, add yourself as test user).
3. OAuth client ID (Desktop) -> save as `src/client_secret.json`.
4. First upload opens browser consent; token cached to `src/token.json`.
5. Until Google's API audit passes, API uploads are locked private (fine --
   the flow keeps uploads private for human review anyway).

## Policy guardrails (why the review step is not optional)

- YouTube's inauthentic-content policy targets mass-produced AI music.
  Keep human curation: listen, edit metadata, vary covers/structure.
- `upload.py` sets the synthetic-media disclosure flag; verify the field
  name against current API docs before first real upload.
- Verify ACE-Step's license permits monetized use (blueprint Phase 0.1).
