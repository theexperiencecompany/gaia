"use client";

import { useCallback, useEffect, useRef, useState } from "react";

/** Number of control points across the X axis of the gradient. */
export const SPECTRUM_BINS = 24;

/**
 * Source of the spectrum on a given frame:
 * - "mic": live microphone input via Web Audio AnalyserNode
 * - "synthetic": generated speech-like spectrum
 * - "hybrid": synthetic spectrum additively blended with the live mic so the
 *   demo's "GAIA speaking" mode still reacts to your voice
 * - "idle": low-amplitude ambient noise so the wave never goes dead
 */
export type SpectrumSource = "mic" | "synthetic" | "hybrid" | "idle";

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

/** Threshold below which a bin is considered "noise" and squelched to zero
 *  so silence reads as a flat wave instead of background fuzz. */
const NOISE_GATE = 0.05;

const gateBin = (v: number): number => {
  if (v < NOISE_GATE) return 0;
  // Smooth gate above threshold so the transition isn't a hard step.
  return ((v - NOISE_GATE) / (1 - NOISE_GATE)) ** 0.9;
};

export function useVoiceSpectrum({ source }: UseVoiceSpectrumOptions) {
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
  const rafRef = useRef<number | null>(null);
  const sourceRef = useRef<SpectrumSource>(source);
  const mutedRef = useRef(false);
  const syntheticStateRef = useRef<SynthState>({
    phaseStart: 0,
    phaseDuration: 1.0,
    isSpeaking: true,
    syllablePitch: 0.4,
  });

  useEffect(() => {
    sourceRef.current = source;
  }, [source]);

  useEffect(() => {
    mutedRef.current = isMuted;
  }, [isMuted]);

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
        for (let i = 0; i < SPECTRUM_BINS; i++) out[i] = out[i] * 0.85;
        return true;
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

    const tick = (now: number) => {
      switch (sourceRef.current) {
        case "mic":
          if (!sampleMic(target)) buildIdleSpectrum(now, target);
          break;
        case "synthetic":
          buildSyntheticSpectrum(now, target, syntheticStateRef.current);
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

      rafRef.current = requestAnimationFrame(tick);
    };

    rafRef.current = requestAnimationFrame(tick);
    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
    };
  }, []);

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
  return { ...state, start, stop, toggleMute, selectDevice };
}
