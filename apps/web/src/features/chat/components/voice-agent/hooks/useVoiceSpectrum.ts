"use client";

import { useCallback, useEffect, useRef } from "react";

/** Number of control points across the X axis of the gradient. */
export const SPECTRUM_BINS = 24;

/**
 * Source of the spectrum on a given frame:
 * - "mic": live microphone input via Web Audio AnalyserNode
 * - "agent-track": Web Audio AnalyserNode over a remote MediaStreamTrack
 *   (e.g. the LiveKit agent's TTS audio track) passed in via `remoteTrack`
 * - "loading": procedural low-pass-filtered random walk — used during the
 *   voice-mode connecting phase so the gradient visibly vibrates while the
 *   room negotiates. Caller invokes `decayLoading()` when transitioning out
 *   to fade the amplitude to zero before switching sources.
 * - "idle": flat baseline — wave settles to zero
 */
export type SpectrumSource = "mic" | "agent-track" | "loading" | "idle";

interface UseVoiceSpectrumOptions {
  /** Which source to read from. */
  source: SpectrumSource;
  /**
   * Remote MediaStreamTrack to analyse when `source === "agent-track"`. The
   * hook re-attaches its analyser whenever this track identity changes.
   */
  remoteTrack?: MediaStreamTrack | null;
  /**
   * External mute flag — wire this to the REAL mic state (e.g. LiveKit's
   * `isMicrophoneEnabled`), not a hook-local toggle. While muted the hook's
   * own analysis stream is disabled, mic bins are zeroed so the wave glides
   * flat, and after a short settle window the sampling loop pauses entirely.
   * Agent speech (agent-track) and the loading shimmer are exempt so audible
   * or in-progress activity keeps animating.
   */
  muted?: boolean;
}

/**
 * How long after mute the sampling raf keeps running so the temporal lerp can
 * glide the wave down to flat before the loop pauses (freezing mid-wave looks
 * broken; pausing immediately would do exactly that).
 */
const MUTE_SETTLE_PAUSE_MS = 600;

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

/** Idle: pure zero — wave settles to a flat baseline with no motion. */
const buildIdleSpectrum = (_t: number, out: Float32Array) => {
  for (let i = 0; i < SPECTRUM_BINS; i++) out[i] = 0;
};

const getAudioContextCtor = (): typeof AudioContext =>
  globalThis.AudioContext ||
  (globalThis as unknown as { webkitAudioContext: typeof AudioContext })
    .webkitAudioContext;

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
  muted = false,
}: UseVoiceSpectrumOptions) {
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

  // Sync the external mute into the sampling loop and the hook's own analysis
  // stream — `track.enabled = false` stops the capture itself, so a muted mic
  // never feeds the analyser (privacy + no ambient-noise wave motion).
  useEffect(() => {
    mutedRef.current = muted;
    const tracks = streamRef.current?.getAudioTracks() ?? [];
    for (const t of tracks) {
      t.enabled = !muted;
    }
  }, [muted]);

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

    const AC = getAudioContextCtor();
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
  }, []);

  const start = useCallback(async () => {
    try {
      // Tear down any previous stream first.
      sourceNodeRef.current?.disconnect();
      analyserRef.current?.disconnect();
      streamRef.current?.getTracks().forEach((t) => t.stop());
      if (audioCtxRef.current && audioCtxRef.current.state !== "closed") {
        await audioCtxRef.current.close().catch(() => {});
      }

      const stream = await navigator.mediaDevices.getUserMedia({
        audio: true,
        video: false,
      });
      streamRef.current = stream;
      const track = stream.getAudioTracks()[0];
      if (track) track.enabled = !mutedRef.current;

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
    } catch (e) {
      // No mic → the wave just stays flat; LiveKit surfaces its own
      // permission errors to the user when the session itself starts.
      console.warn("[useVoiceSpectrum] mic analysis unavailable", e);
    }
  }, []);

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

  // Pause flag — toggled by the mute/visibility effect below. When true the
  // raf loop stops scheduling itself, which eliminates GPU work and prevents
  // the gradient from appearing to "react" to ambient audio during mute.
  const pausedRef = useRef(false);

  // Single requestAnimationFrame loop that updates the spectrum buffer in
  // place every frame regardless of source.
  useEffect(() => {
    const target = targetSpectrumRef.current;
    const smoothed = spectrumRef.current;

    // Bins an analyser's FFT into SPECTRUM_BINS perceptually-curved bands,
    // writing into `out`. Returns false when the analyser isn't ready yet
    // (caller falls back to idle).
    const sampleAnalyser = (
      analyser: AnalyserNode | null,
      raw: Uint8Array<ArrayBuffer> | null,
      out: Float32Array,
    ): boolean => {
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
        // Noise gate: anything quieter than NOISE_GATE → exactly 0 so true
        // silence reads as a flat wave (no idle shimmer).
        out[i] = gateBin(lifted);
      }
      return true;
    };

    const sampleMic = (out: Float32Array): boolean => {
      if (mutedRef.current) {
        // Muted: zero the spectrum so the wave glides down to flat during the
        // settle window; the pause effect below then cancels the raf loop.
        for (let i = 0; i < SPECTRUM_BINS; i++) out[i] = 0;
        return false;
      }
      return sampleAnalyser(analyserRef.current, rawFftRef.current, out);
    };

    // Reads from the remote-agent analyser built in the remoteTrack effect.
    const sampleAgentTrack = (out: Float32Array): boolean =>
      sampleAnalyser(remoteAnalyserRef.current, remoteFftRef.current, out);

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
        case "loading":
          buildLoadingSpectrum(
            now,
            target,
            loadingStateRef.current,
            loadingAmplitudeRef.current,
          );
          break;
        default:
          buildIdleSpectrum(now, target);
      }

      // Spatial smoothing (3-tap Gaussian) on the target, then temporal lerp
      // toward the smoothed buffer that consumers actually read.
      applySpatialSmoothing(target, target, scratchRef.current);
      for (let i = 0; i < SPECTRUM_BINS; i++) {
        smoothed[i] = lerp(smoothed[i], target[i], TEMPORAL_SMOOTHING);
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

  // Pause the raf on mute (after a settle window so the wave glides flat
  // first) or while the tab is hidden; resume on unmute / visibility return.
  // Agent-track frames are exempt from the mute pause — the agent's audible
  // speech should keep animating even while the user's mic is off.
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

    let settleTimer: ReturnType<typeof setTimeout> | null = null;
    const apply = () => {
      if (settleTimer !== null) {
        clearTimeout(settleTimer);
        settleTimer = null;
      }
      if (typeof document !== "undefined" && document.hidden) {
        pause();
        return;
      }
      if (muted && (source === "mic" || source === "idle")) {
        // Keep ticking briefly: mutedRef zeroes the bins and the temporal
        // lerp glides the wave down to flat, THEN the loop stops. Agent
        // speech and the loading shimmer keep animating while muted.
        settleTimer = setTimeout(pause, MUTE_SETTLE_PAUSE_MS);
        resume();
        return;
      }
      resume();
    };
    apply();

    if (typeof document !== "undefined") {
      document.addEventListener("visibilitychange", apply);
    }
    return () => {
      if (settleTimer !== null) clearTimeout(settleTimer);
      if (typeof document !== "undefined") {
        document.removeEventListener("visibilitychange", apply);
      }
    };
  }, [source, muted]);

  useEffect(() => () => stop(), [stop]);

  return {
    /** Length SPECTRUM_BINS, values in [0, 1]. Mutated in place across frames. */
    spectrum: spectrumRef.current,
    start,
    decayLoading,
  };
}
