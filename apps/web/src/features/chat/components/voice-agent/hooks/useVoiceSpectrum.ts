"use client";

import { useCallback, useEffect, useRef, useState } from "react";

/** Number of control points across the X axis of the gradient. */
export const SPECTRUM_BINS = 24;

/**
 * Source of the spectrum on a given frame:
 * - "mic": live microphone input via Web Audio AnalyserNode
 * - "agent-track": Web Audio AnalyserNode over a remote MediaStreamTrack
 *   (e.g. the LiveKit agent's TTS audio track) passed in via `remoteTrack`
 * - "synthetic": generated speech-like spectrum (demo only)
 * - "hybrid": synthetic spectrum additively blended with the live mic (demo only)
 * - "loading": procedural low-pass-filtered random walk — used during the
 *   voice-mode connecting phase so the gradient visibly vibrates while the
 *   room negotiates. Caller invokes `decayLoading()` when transitioning out
 *   to fade the amplitude to zero before switching sources.
 * - "idle": flat baseline — wave settles to zero
 */
export type SpectrumSource =
  | "mic"
  | "agent-track"
  | "synthetic"
  | "hybrid"
  | "loading"
  | "idle";

export interface VoiceSpectrumState {
  /** Float32Array of length SPECTRUM_BINS, values in [0, 1]. Mutated in place across frames. */
  spectrum: Float32Array;
  /** Smoothed RMS amplitude in [0, 1]. */
  scalar: number;
  /** True once microphone permission is granted and audio is flowing. */
  isActive: boolean;
  isMuted: boolean;
  devices: MediaDeviceInfo[];
  deviceId: string | null;
  error: string | null;
}

interface UseVoiceSpectrumOptions {
  /**
   * Which source to read from. When set to "synthetic" the spectrum is
   * generated locally so callers don't need a microphone.
   */
  source: SpectrumSource;
  /**
   * Remote MediaStreamTrack to analyse when `source === "agent-track"`. The
   * hook re-attaches its analyser whenever this track identity changes.
   */
  remoteTrack?: MediaStreamTrack | null;
}

const TEMPORAL_SMOOTHING = 0.18;
const SPATIAL_KERNEL = [0.25, 0.5, 0.25] as const;
const FFT_SIZE = 1024;

const lerp = (a: number, b: number, t: number) => a + (b - a) * t;

const applySpatialSmoothing = (
  src: Float32Array,
  dst: Float32Array,
  scratch: Float32Array,
) => {
  // First copy into scratch so we don't read in-place.
  for (let i = 0; i < SPECTRUM_BINS; i++) scratch[i] = src[i];
  for (let i = 0; i < SPECTRUM_BINS; i++) {
    const left = scratch[Math.max(0, i - 1)];
    const right = scratch[Math.min(SPECTRUM_BINS - 1, i + 1)];
    dst[i] =
      left * SPATIAL_KERNEL[0] +
      scratch[i] * SPATIAL_KERNEL[1] +
      right * SPATIAL_KERNEL[2];
  }
};

/**
 * Build a synthetic spectrum that visually reads as natural speech — three
 * drifting formant clusters spanning low/mid/high bands, a syllable
 * envelope on the foreground formant, and a persistent broadband floor so
 * inter-syllable moments still show shape (not flat).
 *
 * Writes into `out` in place; values in [0, 1].
 */
interface SynthState {
  /** Time the current phase started. */
  phaseStart: number;
  /** Duration of the current phase. */
  phaseDuration: number;
  /** Are we currently in a "speaking" phase or a silent pause? */
  isSpeaking: boolean;
  /** Random pitch for the current syllable's formant 1 center. */
  syllablePitch: number;
}

const buildSyntheticSpectrum = (
  t: number,
  out: Float32Array,
  state: SynthState,
) => {
  const now = t / 1000;
  // Alternate "speaking" and silent "pause" phases. During pause, output is
  // exactly zero — the gradient settles flat with no idle motion.
  if (now - state.phaseStart > state.phaseDuration) {
    state.phaseStart = now;
    state.isSpeaking = !state.isSpeaking;
    if (state.isSpeaking) {
      state.phaseDuration = 1.4 + Math.random() * 1.4;
      state.syllablePitch = Math.random();
    } else {
      state.phaseDuration = 1.2 + Math.random() * 1.6;
    }
  }

  if (!state.isSpeaking) {
    // Silent: bins go to exactly 0. Smoothed in the consumer loop so the
    // wave glides down to flat instead of snapping.
    for (let i = 0; i < SPECTRUM_BINS; i++) out[i] = 0;
    return;
  }

  const syllableProgress = Math.min(
    1,
    (now - state.phaseStart) / state.phaseDuration,
  );
  // Long soft attack, brief plateau, long release — like a sighing breath
  const envelopeRaw =
    syllableProgress < 0.4
      ? (syllableProgress / 0.4) ** 1.5
      : syllableProgress < 0.55
        ? 1.0
        : (1 - (syllableProgress - 0.55) / 0.45) ** 1.5;
  // No baseline lift — between syllables we want to be able to go to zero.
  const envelope = envelopeRaw;

  // Three formants drifting at calmer rates
  const f1 = 3.2 + state.syllablePitch * 2.5 + Math.sin(now * 0.6) * 1.8;
  const f2 = 9.5 + Math.sin(now * 0.42 + 1.3) * 2.4;
  const f3 = 16.5 + Math.cos(now * 0.28 + 0.4) * 2.8;
  const a1 = 0.85 + Math.sin(now * 0.2) * 0.15;
  const a2 = 0.7 + Math.sin(now * 0.29 + 1.1) * 0.2;
  const a3 = 0.5 + Math.sin(now * 0.38 + 2.3) * 0.18;

  for (let i = 0; i < SPECTRUM_BINS; i++) {
    // Tighter formants → sharper peaks (smaller divisors)
    const d1 = (i - f1) / 1.8;
    const d2 = (i - f2) / 2.2;
    const d3 = (i - f3) / 2.8;
    const bump =
      Math.exp(-d1 * d1) * a1 +
      Math.exp(-d2 * d2) * a2 +
      Math.exp(-d3 * d3) * a3;
    const sibilance = i > 14 ? (Math.random() - 0.5) * 0.1 * envelopeRaw : 0;
    out[i] = Math.max(0, Math.min(1, bump * envelope + sibilance));
  }
};

/** Idle: pure zero — wave settles to a flat baseline with no motion. */
const buildIdleSpectrum = (_t: number, out: Float32Array) => {
  for (let i = 0; i < SPECTRUM_BINS; i++) out[i] = 0;
};

interface LoadingState {
  /** Per-bin current values (smoothed). */
  current: Float32Array;
  /** Per-bin random targets, refreshed at LOADING_TARGET_REFRESH_MS cadence. */
  target: Float32Array;
  /** Timestamp of the last target refresh. */
  lastRefresh: number;
}

const LOADING_AMPLITUDE = 0.3;
const LOADING_TARGET_REFRESH_MS = 80;
const LOADING_SMOOTHING = 0.12;

/**
 * Loading: low-pass-filtered random walk per bin. Reads visually as gentle,
 * organic vibration — not the buzzy white noise you'd get from raw
 * Math.random() per frame. Multiplied by `amplitude` so the caller can fade
 * the source out via `decayLoading()` before switching to mic/agent.
 */
const buildLoadingSpectrum = (
  t: number,
  out: Float32Array,
  state: LoadingState,
  amplitude: number,
) => {
  if (t - state.lastRefresh > LOADING_TARGET_REFRESH_MS) {
    for (let i = 0; i < SPECTRUM_BINS; i++) {
      state.target[i] = Math.random() * LOADING_AMPLITUDE;
    }
    state.lastRefresh = t;
  }
  for (let i = 0; i < SPECTRUM_BINS; i++) {
    state.current[i] = lerp(
      state.current[i],
      state.target[i],
      LOADING_SMOOTHING,
    );
    out[i] = state.current[i] * amplitude;
  }
};

/** Threshold below which a bin is considered "noise" and squelched to zero
 *  so silence reads as a flat wave instead of background fuzz. */
const NOISE_GATE = 0.05;

const gateBin = (v: number): number => {
  if (v < NOISE_GATE) return 0;
  // Smooth gate above threshold so the transition isn't a hard step.
  return ((v - NOISE_GATE) / (1 - NOISE_GATE)) ** 0.9;
};

export function useVoiceSpectrum({
  source,
  remoteTrack = null,
}: UseVoiceSpectrumOptions) {
  const [isActive, setIsActive] = useState(false);
  const [isMuted, setIsMuted] = useState(false);
  const [devices, setDevices] = useState<MediaDeviceInfo[]>([]);
  const [deviceId, setDeviceId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [scalar, setScalar] = useState(0);

  // Persistent buffer — mutated in place each frame. Consumers read it via
  // a ref so they don't trigger re-renders on every audio frame.
  const spectrumRef = useRef<Float32Array>(new Float32Array(SPECTRUM_BINS));
  const targetSpectrumRef = useRef<Float32Array>(
    new Float32Array(SPECTRUM_BINS),
  );
  const scratchRef = useRef<Float32Array>(new Float32Array(SPECTRUM_BINS));
  const rawFftRef = useRef<Uint8Array<ArrayBuffer> | null>(null);

  const audioCtxRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const sourceNodeRef = useRef<MediaStreamAudioSourceNode | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  // Parallel pipeline for the remote agent audio track (only built when a
  // remoteTrack is passed in). Kept separate from the mic pipeline so the two
  // sources can be swapped per-frame by `source` without tearing each other down.
  const remoteCtxRef = useRef<AudioContext | null>(null);
  const remoteAnalyserRef = useRef<AnalyserNode | null>(null);
  const remoteSourceNodeRef = useRef<MediaStreamAudioSourceNode | null>(null);
  const remoteFftRef = useRef<Uint8Array<ArrayBuffer> | null>(null);
  const rafRef = useRef<number | null>(null);
  const tickRef = useRef<((now: number) => void) | null>(null);
  const sourceRef = useRef<SpectrumSource>(source);
  const mutedRef = useRef(false);
  const syntheticStateRef = useRef<SynthState>({
    phaseStart: 0,
    phaseDuration: 1.0,
    isSpeaking: true,
    syllablePitch: 0.4,
  });
  const loadingStateRef = useRef<LoadingState>({
    current: new Float32Array(SPECTRUM_BINS),
    target: new Float32Array(SPECTRUM_BINS),
    lastRefresh: 0,
  });
  // 1 → full loading jitter visible. Caller flips `decayLoading()` and the
  // tick loop decays this toward 0 over ~LOADING_DECAY_MS so the gradient
  // smoothly settles before the next source (mic/agent-track) takes over.
  const loadingAmplitudeRef = useRef(1);
  const loadingDecayingRef = useRef(false);
  const lastTickTsRef = useRef(0);

  useEffect(() => {
    sourceRef.current = source;
  }, [source]);

  useEffect(() => {
    mutedRef.current = isMuted;
  }, [isMuted]);

  // Build / rebuild the analyser pipeline over the remote agent track whenever
  // its identity changes. Tear down cleanly on unmount or when the track goes
  // away. Idle source paths read remoteFftRef which stays null until attached.
  useEffect(() => {
    const teardown = () => {
      remoteSourceNodeRef.current?.disconnect();
      remoteSourceNodeRef.current = null;
      remoteAnalyserRef.current?.disconnect();
      remoteAnalyserRef.current = null;
      remoteFftRef.current = null;
      if (remoteCtxRef.current && remoteCtxRef.current.state !== "closed") {
        remoteCtxRef.current.close().catch(() => {});
      }
      remoteCtxRef.current = null;
    };

    if (!remoteTrack) {
      teardown();
      return;
    }

    const AC =
      window.AudioContext ||
      (window as unknown as { webkitAudioContext: typeof AudioContext })
        .webkitAudioContext;
    const ctx = new AC();
    const stream = new MediaStream([remoteTrack]);
    const node = ctx.createMediaStreamSource(stream);
    const analyser = ctx.createAnalyser();
    analyser.fftSize = FFT_SIZE;
    analyser.smoothingTimeConstant = 0.5;
    node.connect(analyser);

    remoteCtxRef.current = ctx;
    remoteSourceNodeRef.current = node;
    remoteAnalyserRef.current = analyser;
    remoteFftRef.current = new Uint8Array(
      new ArrayBuffer(analyser.frequencyBinCount),
    );

    return teardown;
  }, [remoteTrack]);

  const stop = useCallback(() => {
    sourceNodeRef.current?.disconnect();
    sourceNodeRef.current = null;
    analyserRef.current?.disconnect();
    analyserRef.current = null;
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    if (audioCtxRef.current && audioCtxRef.current.state !== "closed") {
      audioCtxRef.current.close().catch(() => {});
    }
    audioCtxRef.current = null;
    setIsActive(false);
  }, []);

  const start = useCallback(async (preferredDeviceId?: string) => {
    try {
      setError(null);
      // Tear down any previous stream first.
      sourceNodeRef.current?.disconnect();
      analyserRef.current?.disconnect();
      streamRef.current?.getTracks().forEach((t) => t.stop());
      if (audioCtxRef.current && audioCtxRef.current.state !== "closed") {
        await audioCtxRef.current.close().catch(() => {});
      }

      const stream = await navigator.mediaDevices.getUserMedia({
        audio: preferredDeviceId
          ? { deviceId: { exact: preferredDeviceId } }
          : true,
        video: false,
      });
      streamRef.current = stream;
      const track = stream.getAudioTracks()[0];
      if (track) track.enabled = !mutedRef.current;
      const settings = track?.getSettings();
      if (settings?.deviceId) setDeviceId(settings.deviceId);

      const AC =
        window.AudioContext ||
        (window as unknown as { webkitAudioContext: typeof AudioContext })
          .webkitAudioContext;
      const ctx = new AC();
      audioCtxRef.current = ctx;
      const node = ctx.createMediaStreamSource(stream);
      sourceNodeRef.current = node;
      const analyser = ctx.createAnalyser();
      analyser.fftSize = FFT_SIZE;
      analyser.smoothingTimeConstant = 0.5;
      node.connect(analyser);
      analyserRef.current = analyser;
      rawFftRef.current = new Uint8Array(
        new ArrayBuffer(analyser.frequencyBinCount),
      );
      setIsActive(true);

      const list = await navigator.mediaDevices.enumerateDevices();
      setDevices(list.filter((d) => d.kind === "audioinput"));
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Mic error";
      setError(msg);
      setIsActive(false);
    }
  }, []);

  const selectDevice = useCallback(
    async (id: string) => {
      setDeviceId(id);
      await start(id);
    },
    [start],
  );

  const decayLoading = useCallback(() => {
    loadingDecayingRef.current = true;
  }, []);

  // When source switches BACK to "loading" (e.g. a re-entered connecting
  // phase), reset the amplitude + decay flag so the jitter is visible again.
  useEffect(() => {
    if (source === "loading") {
      loadingAmplitudeRef.current = 1;
      loadingDecayingRef.current = false;
    }
  }, [source]);

  const toggleMute = useCallback(() => {
    setIsMuted((m) => {
      const next = !m;
      const tracks = streamRef.current?.getAudioTracks() ?? [];
      for (const t of tracks) {
        t.enabled = !next;
      }
      return next;
    });
  }, []);

  // Pause flag — toggled by the mute/visibility effect below. When true the
  // raf loop stops scheduling itself, which eliminates GPU work and prevents
  // the gradient from appearing to "react" to ambient audio during mute.
  const pausedRef = useRef(false);

  // Single requestAnimationFrame loop that updates the spectrum buffer in
  // place every frame regardless of source. Scalar amplitude is published
  // to React state at a throttled rate so consumers can re-render lightly.
  useEffect(() => {
    let lastScalarPush = 0;
    const target = targetSpectrumRef.current;
    const smoothed = spectrumRef.current;

    const micBuf = new Float32Array(SPECTRUM_BINS);

    // Writes the current mic spectrum into `out`. Returns true if real data
    // was written; false if the analyser isn't ready yet (caller decides
    // what to do — fall back to idle, or just skip the mic contribution in
    // hybrid mode).
    const sampleMic = (out: Float32Array): boolean => {
      const analyser = analyserRef.current;
      const raw = rawFftRef.current;
      if (!analyser || !raw) {
        for (let i = 0; i < SPECTRUM_BINS; i++) out[i] = 0;
        return false;
      }
      if (mutedRef.current) {
        // Muted: zero the spectrum so the wave settles flat. The raf loop
        // itself is cancelled by the pause effect below when mute + mic
        // source coincide, so this branch is only hit briefly between
        // mutedRef flipping and the pause effect cancelling the raf.
        for (let i = 0; i < SPECTRUM_BINS; i++) out[i] = 0;
        return false;
      }
      analyser.getByteFrequencyData(raw);
      const usableBins = Math.min(raw.length, 256);
      for (let i = 0; i < SPECTRUM_BINS; i++) {
        const norm = i / (SPECTRUM_BINS - 1);
        const curved = norm ** 1.6;
        const fromIdx = Math.floor(curved * (usableBins - 4)) + 2;
        const toIdx = Math.min(
          usableBins - 1,
          Math.floor(((i + 1) / SPECTRUM_BINS) ** 1.6 * (usableBins - 4)) + 2,
        );
        let sum = 0;
        let count = 0;
        for (let j = fromIdx; j <= toIdx; j++) {
          sum += raw[j];
          count++;
        }
        const avg = count > 0 ? sum / count / 255 : 0;
        const lifted = Math.min(1, (avg * 2.4) ** 1.1);
        // Noise gate: anything quieter than NOISE_GATE → exactly 0 so true
        // silence reads as a flat wave (no idle shimmer).
        out[i] = gateBin(lifted);
      }
      return true;
    };

    // Reads from the remote-agent analyser built in the remoteTrack effect.
    // Returns false when no analyser is attached yet.
    const sampleAgentTrack = (out: Float32Array): boolean => {
      const analyser = remoteAnalyserRef.current;
      const raw = remoteFftRef.current;
      if (!analyser || !raw) {
        for (let i = 0; i < SPECTRUM_BINS; i++) out[i] = 0;
        return false;
      }
      analyser.getByteFrequencyData(raw);
      const usableBins = Math.min(raw.length, 256);
      for (let i = 0; i < SPECTRUM_BINS; i++) {
        const norm = i / (SPECTRUM_BINS - 1);
        const curved = norm ** 1.6;
        const fromIdx = Math.floor(curved * (usableBins - 4)) + 2;
        const toIdx = Math.min(
          usableBins - 1,
          Math.floor(((i + 1) / SPECTRUM_BINS) ** 1.6 * (usableBins - 4)) + 2,
        );
        let sum = 0;
        let count = 0;
        for (let j = fromIdx; j <= toIdx; j++) {
          sum += raw[j];
          count++;
        }
        const avg = count > 0 ? sum / count / 255 : 0;
        const lifted = Math.min(1, (avg * 2.4) ** 1.1);
        out[i] = gateBin(lifted);
      }
      return true;
    };

    const LOADING_DECAY_MS = 300;

    const tick = (now: number) => {
      const dt = lastTickTsRef.current === 0 ? 16 : now - lastTickTsRef.current;
      lastTickTsRef.current = now;

      if (loadingDecayingRef.current) {
        loadingAmplitudeRef.current = Math.max(
          0,
          loadingAmplitudeRef.current - dt / LOADING_DECAY_MS,
        );
      }

      switch (sourceRef.current) {
        case "mic":
          if (!sampleMic(target)) buildIdleSpectrum(now, target);
          break;
        case "agent-track":
          if (!sampleAgentTrack(target)) buildIdleSpectrum(now, target);
          break;
        case "synthetic":
          buildSyntheticSpectrum(now, target, syntheticStateRef.current);
          break;
        case "loading":
          buildLoadingSpectrum(
            now,
            target,
            loadingStateRef.current,
            loadingAmplitudeRef.current,
          );
          break;
        case "hybrid": {
          // Synthetic baseline + live mic added on top.
          // Mic contribution scales itself down when no audio is coming in.
          buildSyntheticSpectrum(now, target, syntheticStateRef.current);
          const micHas = sampleMic(micBuf);
          if (micHas) {
            for (let i = 0; i < SPECTRUM_BINS; i++) {
              // Additive blend with soft compression so loud voice doesn't
              // saturate the wave into a flat plateau.
              const combined = target[i] * 0.65 + micBuf[i] * 0.85;
              target[i] = 1 - Math.exp(-combined * 1.4);
            }
          }
          break;
        }
        default:
          buildIdleSpectrum(now, target);
      }

      // Spatial smoothing (3-tap Gaussian) on the target, then temporal lerp
      // toward the smoothed buffer that consumers actually read.
      applySpatialSmoothing(target, target, scratchRef.current);
      for (let i = 0; i < SPECTRUM_BINS; i++) {
        smoothed[i] = lerp(smoothed[i], target[i], TEMPORAL_SMOOTHING);
      }

      // Throttled scalar push every ~120ms so the UI's "talking" caption
      // can react without re-rendering the whole tree every frame.
      if (now - lastScalarPush > 120) {
        let sum = 0;
        for (let i = 0; i < SPECTRUM_BINS; i++) sum += smoothed[i];
        setScalar(sum / SPECTRUM_BINS);
        lastScalarPush = now;
      }

      if (pausedRef.current) {
        rafRef.current = null;
        return;
      }
      rafRef.current = requestAnimationFrame(tick);
    };

    tickRef.current = tick;
    rafRef.current = requestAnimationFrame(tick);
    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
      tickRef.current = null;
    };
  }, []);

  // Pause raf when (mic-source && muted) or document.hidden.
  // Resume on unmute / visibility return.
  useEffect(() => {
    const resume = () => {
      if (rafRef.current !== null || !tickRef.current) return;
      pausedRef.current = false;
      rafRef.current = requestAnimationFrame(tickRef.current);
    };
    const pause = () => {
      pausedRef.current = true;
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
      }
    };

    const shouldPause =
      (source === "mic" && isMuted) ||
      (typeof document !== "undefined" && document.hidden);
    if (shouldPause) pause();
    else resume();

    const onVisibility = () => {
      const nowShouldPause = (source === "mic" && isMuted) || document.hidden;
      if (nowShouldPause) pause();
      else resume();
    };

    if (typeof document !== "undefined") {
      document.addEventListener("visibilitychange", onVisibility);
    }
    return () => {
      if (typeof document !== "undefined") {
        document.removeEventListener("visibilitychange", onVisibility);
      }
    };
  }, [source, isMuted]);

  useEffect(() => () => stop(), [stop]);

  const state: VoiceSpectrumState = {
    spectrum: spectrumRef.current,
    scalar,
    isActive,
    isMuted,
    devices,
    deviceId,
    error,
  };
  return { ...state, start, stop, toggleMute, selectDevice, decayLoading };
}
