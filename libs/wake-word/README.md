# @gaia/wake-word

Cross-platform, on-device **"Hey GAIA"** wake-word detection. Runs in the
browser (web app), Electron (desktop app), and React Native (mobile app)
with a single shared ONNX model artifact and a shared TypeScript core.

- **Tiny** — < 5 MB combined model footprint
- **Fast** — 1–3 ms per 80 ms frame on a modern laptop CPU; warmup ≈ 2 s
- **Local** — no audio ever leaves the device
- **Hardened against false positives** — Silero VAD pre-gate + consecutive-hit
  debounce + post-detection cooldown + optional per-user verifier head

## Architecture

```
                            ┌──────────────────────────────┐
mic ─► PCM @ 16 kHz mono ─► │  WakeWordDetector            │ ─► DetectionEvent
                            │  ├─ frame buffer (80 ms)     │
                            │  ├─ Silero VAD (pre-gate)    │
                            │  └─ WakeWordPipeline         │
                            │     ├─ melspectrogram.onnx   │
                            │     ├─ embedding_model.onnx  │
                            │     └─ hey_gaia.onnx (custom)│
                            └──────────────────────────────┘
```

The first two ONNX stages (melspec + embedding) come unchanged from
[openWakeWord v0.5.1](https://github.com/dscripka/openWakeWord) and are shared
across every wake word — the only custom-trained artifact is `hey_gaia.onnx`,
a tiny classifier head that consumes 16 × 96 embedding sequences and emits a
single probability.

## Package layout

```
libs/wake-word/
├── src/
│   ├── core/                 # platform-agnostic detector + pipeline + VAD
│   ├── types/                # public types and shape constants
│   ├── web/                  # ORT-Web runtime + AudioWorklet + React hook
│   ├── native/               # ORT-RN runtime + react-native-live-audio-stream + hook
│   └── node/                 # ORT-Node runtime — tests only
├── models/                   # bundled ONNX artifacts (~5 MB total)
├── training/                 # Python training pipeline (synth data → ONNX)
├── test/                     # vitest pipeline tests with real audio fixtures
├── test-fixtures/            # hey_mycroft_test.wav (positive) + hey_jane.wav (negative)
└── scripts/                  # fetch-models.sh + ONNX probe utilities
```

## Use in the web app

```ts
"use client";
import { useHeyGaia } from "@/features/wake-word";

export function ChatShell() {
  const { state, lastDetection } = useHeyGaia({ enabled: micConsent });
  useEffect(() => {
    if (lastDetection) openVoiceSession();
  }, [lastDetection]);
  return ...;
}
```

The web app ships the four ONNX models from `apps/web/public/wake-word/`.

## Use in Electron (desktop)

The Electron renderer loads the same Next.js bundle as the web app, so the
hook above works without modification. Two desktop-specifics:

1. **macOS microphone permission** — add to the Electron main process at
   startup (`apps/desktop/src/main/index.ts`):

   ```ts
   import { systemPreferences } from "electron";
   await systemPreferences.askForMediaAccess("microphone");
   ```

2. **Background listening** — if the main window is minimised to a tray, the
   renderer must stay alive (don't destroy the BrowserWindow). The hook keeps
   listening as long as the page is mounted.

## Use in React Native (mobile)

```tsx
import { useHeyGaia } from "@/features/wake-word";

export function MainScreen() {
  const { state, lastDetection } = useHeyGaia({ enabled: micConsent });
  useEffect(() => {
    if (lastDetection) openVoiceModal();
  }, [lastDetection]);
  return ...;
}
```

Platform setup:
- **iOS** — `NSMicrophoneUsageDescription` in `Info.plist`; for background
  detection also enable the "Audio, AirPlay, and Picture in Picture" background
  mode.
- **Android** — declare `RECORD_AUDIO` permission and (for Android 14+) a
  foreground service of type `microphone` if you want detection to continue
  with the app in background.

## Train a fresh "Hey GAIA" model

See [`training/README.md`](./training/README.md). Highlights:

- Synthetic positive samples generated from Piper TTS with voice / speed /
  pitch / pronunciation variation (~50k clips)
- Hard negatives include phonetic neighbours ("hey gaby", "hey gaza", "gaia"
  alone, "hey google") — weighted 3× over random negatives
- Eval gates: minimum recall, maximum false-positive rate per hour against
  LibriSpeech + MUSAN — training refuses to ship a regression

## Tests

```bash
cd libs/wake-word
pnpm test
```

The test harness loads the real ONNX models and asserts:

| Test | Assertion |
|---|---|
| Warmup math | Exactly 0 scores in frame 1–24, 1 score on frame 25 |
| Silence | Max score < 0.1 over 4.8 s of zeros |
| Positive (`hey_mycroft_test.wav`) | Max score > 0.7 |
| Negative (`hey_jane.wav`) | Max score < 0.2 |
| Per-frame latency | < 20 ms on Node CPU (measured: ~1.6 ms) |
| Detector e2e | Fires exactly once on positive, never on negative |
| Cooldown | Two back-to-back positives → one detection |

## License

Apache-2.0 for the openWakeWord components and the training pipeline.
GAIA owns the custom-trained `hey_gaia.onnx` artifact.
