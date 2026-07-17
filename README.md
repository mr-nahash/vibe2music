# vibe2music

vibe2music turns a creative brief into a reviewable, exact-length YouTube
production:

**vibe or cover image → coherent track plan → ACE-Step generation on a local
NVIDIA GPU → QC → loudness-normalized crossfades → exact 45-minute master →
artwork → MP4 → editable metadata → private YouTube upload.**

The Cloudflare page is the control panel. The Python API and worker run on the
machine that owns the GPU, so the expensive work never runs in a Cloudflare
Worker.

## What changed in the production workflow

- Local CUDA is detected and reported in the web panel; the selected GPU is
  passed to ACE-Step, with bfloat16, CPU-offload, and checkpoint options.
- ACE-Step is loaded once per job and reused across all tracks.
- The default set is automatically sized for 45 minutes (normally about 12
  distinct 3–4 minute tracks), then mixed to exactly the requested duration.
- A failed seed does not erase the whole album. QC writes a report and the
  mixer uses the passing tracks.
- A persistent, single-worker queue prevents concurrent jobs from
  oversubscribing the GPU and re-queues interrupted jobs after a restart.
- The API accepts cover-image uploads, creates deterministic fallback artwork,
  exposes audio/video/log/download endpoints, supports cancellation/retry, and
  keeps metadata editable.
- Prompt and metadata generation fall back to local templates when no
  \`ANTHROPIC_API_KEY\` is available. \`--dry-run\` is offline and makes no LLM or
  GPU request.
- YouTube upload stays private by default. Public upload requires an explicit
  server-side opt-in and a human review step.

## Local NVIDIA setup

Install \`ffmpeg\` first. On Ubuntu:

\`\`\`bash
sudo apt-get update
sudo apt-get install -y ffmpeg git python3-venv
\`\`\`

Then:

\`\`\`bash
./setup_local.sh
API_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')" \\
  ./run_local.sh
\`\`\`

The first ACE-Step run downloads its checkpoint. To use a persistent location:

\`\`\`bash
export ACE_CHECKPOINT_PATH=/data/models/ace-step
export V2M_DEVICE=cuda
export V2M_DEVICE_ID=0
\`\`\`

Open the deployed panel or a local copy of \`ui/index.html\`, enter:

\`\`\`text
GPU worker URL: http://127.0.0.1:8000
API token:      the token printed by run_local.sh
\`\`\`

An HTTPS Cloudflare page cannot call an ordinary HTTP localhost endpoint in
every browser. For the deployed panel, expose port 8000 through an HTTPS
tunnel/provider proxy. For a fully local session, serve the UI locally or use
the provider's HTTPS URL.

The same installer works on a RunPod/Vast.ai box:

\`\`\`bash
./runpod/setup.sh
API_TOKEN=<long-secret> ./run_local.sh
\`\`\`

## CLI

Preview the plan without API or GPU cost:

\`\`\`bash
python src/run_all.py \\
  "rainy Tokyo cafe at midnight, warm and spacious" \\
  --instruments "felt piano,tape hiss,soft pads" \\
  --target-minutes 45 \\
  --dry-run
\`\`\`

Run the complete pipeline:

\`\`\`bash
python src/run_all.py \\
  "rainy Tokyo cafe at midnight, warm and spacious" \\
  --instruments "felt piano,tape hiss,soft pads" \\
  --image cover.jpg \\
  --target-minutes 45 \\
  --device auto
\`\`\`

The result is in \`output/<set-slug>/\`:

\`\`\`text
mix.wav             exact-length master
preview.mp3         browser-friendly review copy
video.mp4           YouTube-ready render
metadata.json       editable title, description, and tags
chapters.txt        chapter timestamps
qc.json             per-track quality report
manifest.json       prompts, seeds, device, and generated files
\`\`\`

The optional upload command uploads the reviewed render as private:

\`\`\`bash
python src/upload.py output/<set-slug> --privacy private
\`\`\`

Set up YouTube OAuth by placing \`client_secret.json\` next to
\`src/upload.py\`. The OAuth token is ignored by Git. A public upload is
deliberately not part of the unattended default.

## Web API

All endpoints require \`Authorization: Bearer <API_TOKEN>\`, except that CORS
preflight remains unauthenticated.

\`\`\`text
GET  /health
POST /jobs
GET  /jobs
POST /jobs/{id}/cancel
POST /jobs/{id}/retry
GET  /jobs/{id}/audio
GET  /jobs/{id}/video
GET  /jobs/{id}/download/audio
GET  /jobs/{id}/download/video
GET  /jobs/{id}/metadata
PUT  /jobs/{id}/metadata
GET  /jobs/{id}/log
POST /jobs/{id}/upload
\`\`\`

\`POST /jobs\` accepts JSON or multipart form data. Multipart fields are
\`vibe\`, \`instruments\`, \`target_minutes\`, optional \`tracks\`, \`device\`,
\`device_id\`, and optional \`image\`.

## Deploy the control panel

The panel is static and can be deployed with the Cloudflare Pages command used
by the original project:

\`\`\`bash
npx wrangler pages deploy ui/ --project-name vibe2music
\`\`\`

It does not contain GPU credentials or YouTube OAuth credentials; the browser
stores only the API URL and bearer token locally.

## Monetization reality

This tool automates production and review mechanics; it cannot guarantee
YouTube Partner Program acceptance or revenue. Keep each release genuinely
distinct, review the complete render, vary the creative direction and artwork,
retain provenance (vibe, prompts, seeds, model/checkpoint), disclose AI
assistance where required, and verify the current ACE-Step and asset licenses
before monetizing. The upload code sets YouTube's
\`containsSyntheticMedia\` field and defaults to private.
