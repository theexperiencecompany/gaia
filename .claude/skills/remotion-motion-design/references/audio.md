# Audio Playbook — SFX, Music, Voiceover, Mix

Everything marked VERIFIED was downloaded and byte-checked from a GAIA dev container (through the agent proxy) on 2026-07-22. A silent or badly-mixed video is an automatic fail — every video ships with music, SFX, and (usually) VO.

## SFX sources (programmatic, no auth)

| Need | Use | Commercial | Status |
|---|---|---|---|
| Fully scripted pipeline | Openverse API → Freesound CDN (`license=cc0`) | yes (CC0) | VERIFIED |
| Curated quality | Mixkit asset URLs (scrape category pages) | yes | VERIFIED |
| Huge pro archive | BBC Rewind API | **no** (research/personal only — prototyping then swap) | VERIFIED |

```bash
# Openverse — keyless CC search (mostly Freesound), license filtering
curl -s "https://api.openverse.org/v1/audio/?q=riser&license=cc0&page_size=10" \
  | python3 -c "import json,sys; [print(r['license'], r['url']) for r in json.load(sys.stdin)['results']]"
# returned CDN URLs (cdn.freesound.org/previews/...) download directly, 128kbps mp3

# Mixkit — direct, commercial OK, no attribution
curl -sL "https://mixkit.co/free-sound-effects/whoosh/" | grep -oE 'https://assets\.mixkit\.co/[^"]+\.(mp3|wav)' | sort -u
curl -L -o sfx.wav "https://assets.mixkit.co/active_storage/sfx/{ID}/{ID}.wav"
# category slugs: whoosh click pop notification transition impact magic interface technology

# BBC (prototype only)
curl -s "https://sound-effects-api.bbcrewind.co.uk/api/sfx/search" -H 'content-type: application/json' \
  --data '{"criteria":{"from":0,"size":10,"query":"whoosh"}}'
curl -L -o out.wav "https://sound-effects-media.bbcrewind.co.uk/wav/{ID}.wav"
```

Pixabay CDN URLs (`cdn.pixabay.com/download/audio/...`) download keylessly but search is Cloudflare-blocked server-side — harvest URLs in a real browser once, then curl forever. ZapSplat and YouTube Audio Library: not programmatic, skip.

## The SFX vocabulary (what pros actually use)

| Category | Used for | Search keywords | Level vs music |
|---|---|---|---|
| Whoosh/swish | Transitions, camera moves, text fly-ins | `whoosh swish air transition` | −6 to −10 dB; pan with motion direction |
| Soft UI ticks/pops | Element entrances, list items | `pop click tick ui tap blip` | −12 to −18 dB (felt, not heard); <150ms |
| Risers | Build-ups into a reveal | `riser uplifter reverse cymbal build` | start −20 dB → −6 dB at the hit |
| Booms/impacts | Hero moments, logo stings | `impact boom cinematic hit sub drop` | −3 to −6 dB (loudest SFX); duck music 2–3 dB under |
| Shimmer | Logo resolves, sparkle accents | `shimmer chime bell soft` | −10 to −14 dB |
| Ambience beds | Room tone so silence never feels dead | `room tone air ambience soft` | −25 to −35 dB constant |
| Data/tech ticks | Counters, typing, charts drawing | `digital blip counter tick typing` | −14 to −18 dB, quantized to grid |

Craft rules: **one SFX per visual event max** · align the SFX transient to the ease-out peak of the animation (1–2f before visual rest) · high-pass all SFX at 80–100 Hz except intentional booms · risers end exactly on the downbeat of the reveal · **no cartoon/comedy SFX ever**.

## Music (free, commercial-safe)

```bash
# Mixkit music — 256kbps, commercial OK, no attribution (best free option)
curl -sL "https://mixkit.co/free-stock-music/ambient/" | grep -oE 'https://assets\.mixkit\.co/music/[0-9]+/[0-9]+\.mp3' | sort -u
curl -L -o track.mp3 "https://assets.mixkit.co/music/127/127.mp3"
# genre slugs: ambient corporate piano electronica chill cinematic future-bass

# Incompetech — machine-readable catalog with bpm/feel fields; CC-BY (attribution required)
curl -s "https://incompetech.com/music/royalty-free/pieces.json" > catalog.json
# filter on feel: Calm/Ambient/Contemplative; download via URL-encoded "filename" field (never guess filenames)

# Openverse → Jamendo (check license per track — only cc0/by/by-sa for commercial)
curl -s "https://api.openverse.org/v1/audio/?q=ambient+piano&category=music&license=cc0,by"
```

Genre fit for GAIA: minimal/felt piano, soft electronic (future garage, downtempo), ambient pulse. **60–90 BPM for calm product stories, 100–120 for energetic runs.** Prefer tracks with clear 4/8-bar structure so cuts land on bars. Audition before committing — determine actual BPM (tap it against the waveform or use `npx remotion ffprobe`-inspected onsets) and build the beat grid from the real number.

## Voiceover — free (edge-tts, VERIFIED on this machine)

```bash
uv venv tts-venv && uv pip install --python ./tts-venv/bin/python edge-tts
# In GAIA cloud containers ONLY: edge-tts pins certifi, so append the proxy CA once:
cat /root/.ccr/ca-bundle.crt >> "$(./tts-venv/bin/python -c 'import certifi; print(certifi.where())')"

./tts-venv/bin/edge-tts --voice en-US-AndrewMultilingualNeural --rate=-8% \
  --text "Meet GAIA. The assistant that works while you rest." \
  --write-media vo.mp3 --write-subtitles vo.srt   # word-timed SRT → caption/animation sync
```

Voice picks for calm premium product VO: **en-US-AndrewMultilingualNeural** (warm, confident — the default), en-US-BrianMultilingualNeural (younger; pair with −5..−10% rate), en-US-AvaMultilingualNeural (best female), en-US-EmmaMultilingualNeural. Avoid Guy/Aria (newsy cadence). Write short sentences — the model breathes at periods. Output is 24kHz mono 48kbps — normalize in the mix.

## Voiceover — paid (ElevenLabs)

```bash
curl -s -X POST "https://api.elevenlabs.io/v1/text-to-speech/${VOICE_ID}?output_format=mp3_44100_128" \
  -H "xi-api-key: $ELEVENLABS_API_KEY" -H "Content-Type: application/json" \
  -d '{"text": "...", "model_id": "eleven_multilingual_v2",
       "voice_settings": {"stability": 0.55, "similarity_boost": 0.75, "style": 0.15, "use_speaker_boost": true}}' -o vo.mp3
```

- Models: `eleven_multilingual_v2` (highest quality — use for product films), `eleven_v3` (most expressive, audio tags), `eleven_flash_v2_5` (realtime/cheap).
- Voices: list via `GET /v1/voices`; calm narration picks: Adam, Brian, Daniel (male), Rachel, Matilda (female).
- `/v1/text-to-speech/{voice_id}/with-timestamps` returns char-level timing for caption/animation sync. `output_format=pcm_44100` for lossless mastering.
- Pricing (2026): Free 10min/mo non-commercial; Starter $5+ for commercial rights; API ≈ $0.10/1k chars (v2/v3), $0.05/1k (Flash).

## Mix targets

- **Integrated loudness −14 LUFS**, true peak ≤ **−1.0 dBTP**, LRA 6–11 LU.
- VO is the anchor: ~−16 to −18 LUFS short-term alone, peaking ~−6 dBFS. Dialogue sits 10–15 LU above the music bed.
- **Music ducking under VO: −7 to −12 dB** — sidechain ~4:1, attack 5–20ms, release 300–600ms (swells back musically, no pumping): `sidechaincompress=threshold=0.02:ratio=4:attack=20:release=400`.
- Fades: music in 1–2s equal-power/exponential (`afade=t=in:curve=exp`), out 2–3s logarithmic. Never linear on music. SFX tails ring out — don't hard-cut.
- Final two-pass normalize (Remotion bundles ffmpeg — `npx remotion ffmpeg`):
```bash
npx remotion ffmpeg -i mix.wav -af loudnorm=I=-14:TP=-1.0:LRA=11:print_format=json -f null -   # measure
npx remotion ffmpeg -i mix.wav -af loudnorm=I=-14:TP=-1.0:LRA=11:measured_I=..:measured_TP=..:measured_LRA=..:measured_thresh=..:linear=true out.wav
```
- In Remotion: layer `<Audio>` tags (music + each SFX in its `<Sequence from={hitFrame}>` + VO); volume callbacks per frame; summed peaks < 1.0; exponential fade shaping (`Math.pow(linear, 2)`).
