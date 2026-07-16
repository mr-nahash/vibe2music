# Vibe-to-Music Channel — Blueprint & Task Plan
*July 2026 · goal: monetized background-music YouTube channel, open-source generation stack*

## 1. The polished concept

**Input:** a vibe (text) or an image, plus chosen instruments →
**Pipeline:** LLM turns it into structured music prompts → open-source model generates a set of instrumental tracks → auto-mastering → looping visual → **auto-upload to YouTube** as a 1–3 hour mix.

**One-liner:** *"Type 'rainy Tokyo café, piano + vinyl crackle' and wake up to a published hour-long album."*

### The critical constraint that shapes everything
YouTube renamed its repetitious-content rule to the **"inauthentic content" policy (July 2025)** and enforced it hard in **January 2026** (16 channels permanently demonetized, 4.7B views removed). Mass-produced, template AI music is exactly what it targets. So the design goal is **not** maximum volume — it's *automated production with visible human curation*:

- You approve/reject each generated set before upload (a 5-minute review step).
- Every video gets unique visuals, varied structure, and human-written titles/descriptions (LLM-drafted, you edit).
- Use the "altered/synthetic content" disclosure checkbox (mandatory since Jan 2026; it does **not** hurt monetization — failing to disclose does).
- Realistic revenue: RPM $1–4 typical, $3–8 for lofi/sleep/cinematic niches. Plan to diversify later (DSPs, licensing, Patreon).

## 2. Architecture

```
[Vibe text / image + instruments]
        │
        ▼
(1) PROMPT COMPILER ······· cheap LLM (Haiku-class)
    image → caption → mood tags → per-track music prompts
    (tempo, key, instruments, structure, 8–12 track variations)
        │
        ▼
(2) MUSIC GENERATION ······ open-source model on rented GPU
    ACE-Step 1.5 (primary candidate) — full tracks in seconds
    on consumer GPUs; fallback: Stable Audio Open / DiffRhythm
    RTX 4090 @ ~$0.30–0.35/hr (RunPod/Vast.ai) — both models
    fit in 24GB (MusicGen-large: 12GB fp16, SAO: 8GB min)
        │
        ▼
(3) QC + CURATION ········· cheap LLM + audio heuristics + YOU
    auto-reject silence/clipping/artifacts (ffmpeg/librosa, no LLM);
    human listens to shortlist, picks the set
        │
        ▼
(4) POST-PRODUCTION ······· no LLM needed (scripts)
    loudness normalize (-14 LUFS), crossfade into long mix,
    render video (image/loop + waveform) via ffmpeg
        │
        ▼
(5) METADATA + PACKAGING ·· cheap LLM drafts, human edits
    title, description, tags, chapters, thumbnail text
        │
        ▼
(6) UPLOAD ················ YouTube Data API v3
    100 quota units/upload (June 2026 rate), 10k units/day —
    quota is a non-issue. BUT: unverified API apps get videos
    locked private → complete Google's API audit early (Phase 1).
        │
        ▼
(7) ANALYTICS LOOP ········ cheap LLM weekly digest
    watch time per vibe/genre → feeds back into prompt compiler
```

## 3. Model-tiering strategy (delegate cheap, escalate rarely)

| Task | Tier | Why |
|---|---|---|
| Image captioning, mood tagging | Haiku-class | Simple extraction |
| Music prompt variations (8–12 per set) | Haiku-class | Templated creativity, high volume |
| Titles/descriptions/tags | Haiku-class | Short, formulaic |
| Analytics weekly digest | Haiku-class | Summarization |
| Audio QC | **No LLM** — librosa/ffmpeg | Deterministic signal checks |
| Mixing/rendering/upload | **No LLM** — scripts | Pure automation |
| Prompt-compiler design & channel strategy | Frontier model | One-time, high-leverage |
| Debugging pipeline failures | Frontier model | Only on escalation |

Estimated run-time LLM cost per published video: **cents.** Dominant costs are GPU time (~$0.35/hr, and generation is faster than realtime — DiffRhythm hits ~28× realtime on a 4090) and your review minutes.

## 4. Music model decision

**Primary: ACE-Step 1.5** — full songs in seconds on consumer GPUs, editing/cover/personalization workflows, efficient. **Fallbacks:** Stable Audio Open (light, 8GB), DiffRhythm (fastest), AudioCraft Plus/MusicGen (mature, best docs). HeartMuLa-7B tops quality charts but is vocal-oriented — less relevant for instrumentals.

⚠️ **Verify before building (top of Phase 1):** exact license terms for commercial YouTube monetization. From training knowledge: MusicGen *weights* are CC-BY-NC (non-commercial — likely disqualifying), ACE-Step has been Apache-2.0 (good), Stable Audio Open uses Stability's community license (commercial OK under $1M revenue). Confirm current versions' terms — this decides the final pick.

## 5. Phased task plan

**Phase 0 — Decisions (this week, ~half a day)**
0.1 Verify model licenses (above) — *delegate to Haiku, you confirm*
0.2 Pick niche(s): lofi/study, sleep, cinematic ambient — *you*
0.3 Create Google Cloud project + start YouTube API verification (lead time!) — *you, guided*

**Phase 1 — Generation core (week 1–2)**
1.1 RunPod/Vast template with chosen model, one-command track generation — *frontier model builds, cheap model writes docs/tests*
1.2 Prompt compiler: vibe/image+instruments → track-set prompts — *frontier designs the schema, Haiku runs it forever after*
1.3 Generate 3 test sets across niches; you judge quality — *you + pipeline*

**Phase 2 — Assembly (week 2–3)**
2.1 QC filters (silence/clipping/loudness) — *cheap model can write this*
2.2 Mix builder: normalize, crossfade, chapters — *cheap model*
2.3 Video renderer (image + subtle motion via ffmpeg) — *cheap model*
2.4 Metadata generator — *cheap model*

**Phase 3 — Publish loop (week 3–4)**
3.1 YouTube upload script + disclosure flag + scheduling — *cheap model, frontier reviews auth code*
3.2 Human review dashboard (simple local page: listen, approve, edit title, publish) — *frontier*
3.3 First 5 uploads, manually reviewed — *you*

**Phase 4 — Operate & learn (ongoing)**
4.1 2–3 uploads/week (quality over volume — inauthentic-content policy)
4.2 Weekly analytics digest → prompt tuning — *Haiku, scheduled task*
4.3 At 1k subs / 4k watch-hours: apply to YPP; then diversify (DSP distribution, licensing)

## 6. Budget sketch (monthly, operating)

| Item | Est. |
|---|---|
| GPU rental (~10 hr/mo at 4090 rates) | $3–5 |
| LLM API (all cheap-tier) | $1–3 |
| YouTube API | free (within quota) |
| **Total** | **≈ $10/mo** until it earns |

## 7. Sources

- [YouTube inauthentic content policy & 2026 enforcement](https://flocker.tv/posts/youtube-inauthentic-content-ai-enforcement/) · [policy overview](https://www.subsub.io/blog/youtube-inauthentic-content-policy-2025)
- [AI music monetization & RPM (2026)](https://outlierkit.com/resources/ai-generated-music-youtube-monetization-2026/) · [disclosure rules](https://shortsfast.com/blog/youtube-ai-content-disclosure-rules-2026/)
- [Best open-source music models 2026](https://www.siliconflow.com/articles/en/best-open-source-music-generation-models) · [open-source music gen guide](https://apatero.com/blog/ai-music-generation-open-source-complete-guide-2026) · [HeartMuLa repo](https://github.com/HeartMuLa/heartlib)
- [RunPod pricing](https://www.runpod.io/pricing) · [Vast.ai pricing](https://vast.ai/pricing) · [GPU deploy guide](https://www.spheron.network/blog/deploy-open-source-ai-music-generation-gpu-cloud-2026/)
- [YouTube API quota costs](https://developers.google.com/youtube/v3/determine_quota_cost) · [upload guide + verification](https://postproxy.dev/blog/youtube-upload-api-guide/) · [MusicGen docs](https://github.com/facebookresearch/audiocraft/blob/main/docs/MUSICGEN.md)
