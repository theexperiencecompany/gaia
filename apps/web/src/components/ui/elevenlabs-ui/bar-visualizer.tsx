"use client";

import * as React from "react";
import { useEffect, useMemo, useRef, useState } from "react";

import { cn } from "@/lib/utils";

export interface AudioAnalyserOptions {
  fftSize?: number;
  smoothingTimeConstant?: number;
  minDecibels?: number;
  maxDecibels?: number;
}

function createAudioAnalyser(
  mediaStream: MediaStream,
  options: AudioAnalyserOptions = {},
) {
  const audioContext = new (
    window.AudioContext ||
    (window as unknown as { webkitAudioContext: typeof AudioContext })
      .webkitAudioContext
  )();
  const source = audioContext.createMediaStreamSource(mediaStream);
  const analyser = audioContext.createAnalyser();

  if (options.fftSize) analyser.fftSize = options.fftSize;
  if (options.smoothingTimeConstant !== undefined) {
    analyser.smoothingTimeConstant = options.smoothingTimeConstant;
  }
  if (options.minDecibels !== undefined)
    analyser.minDecibels = options.minDecibels;
  if (options.maxDecibels !== undefined)
    analyser.maxDecibels = options.maxDecibels;

  source.connect(analyser);

  const cleanup = () => {
    source.disconnect();
    audioContext.close();
  };

  return { analyser, audioContext, cleanup };
}

/**
 * Hook for tracking the volume of an audio stream using the Web Audio API.
 * @param mediaStream - The MediaStream to analyze
 * @param options - Audio analyser options
 * @returns The current volume level (0-1)
 */
export function useAudioVolume(
  mediaStream?: MediaStream | null,
  options: AudioAnalyserOptions = { fftSize: 32, smoothingTimeConstant: 0 },
) {
  const [volume, setVolume] = useState(0);
  const volumeRef = useRef(0);
  const frameId = useRef<number | undefined>(undefined);

  // Memoize options to prevent unnecessary re-renders
  const memoizedOptions = useMemo(
    () => options,
    [
      options.fftSize,
      options.smoothingTimeConstant,
      options.minDecibels,
      options.maxDecibels,
    ],
  );

  useEffect(() => {
    if (!mediaStream) {
      setVolume(0);
      volumeRef.current = 0;
      return;
    }

    const { analyser, cleanup } = createAudioAnalyser(
      mediaStream,
      memoizedOptions,
    );

    const bufferLength = analyser.frequencyBinCount;
    const dataArray = new Uint8Array(bufferLength);
    let lastUpdate = 0;
    const updateInterval = 1000 / 30; // 30 FPS

    const updateVolume = (timestamp: number) => {
      if (timestamp - lastUpdate >= updateInterval) {
        analyser.getByteFrequencyData(dataArray);
        let sum = 0;
        for (let i = 0; i < dataArray.length; i++) {
          const a = dataArray[i];
          sum += a * a;
        }
        const newVolume = Math.sqrt(sum / dataArray.length) / 255;

        // Only update state if volume changed significantly
        if (Math.abs(newVolume - volumeRef.current) > 0.01) {
          volumeRef.current = newVolume;
          setVolume(newVolume);
        }
        lastUpdate = timestamp;
      }
      frameId.current = requestAnimationFrame(updateVolume);
    };

    frameId.current = requestAnimationFrame(updateVolume);

    return () => {
      cleanup();
      if (frameId.current) {
        cancelAnimationFrame(frameId.current);
      }
    };
  }, [mediaStream, memoizedOptions]);

  return volume;
}

export interface MultiBandVolumeOptions {
  bands?: number;
  loPass?: number; // Low frequency cutoff
  hiPass?: number; // High frequency cutoff
  updateInterval?: number; // Update interval in ms
  analyserOptions?: AudioAnalyserOptions;
}

const multibandDefaults: MultiBandVolumeOptions = {
  bands: 24, // Match the typical bar count
  loPass: 20, // Much lower to capture bass frequencies
  hiPass: 4000, // Higher to capture full audio range
  updateInterval: 50, // Slower updates for more stability
  analyserOptions: {
    fftSize: 2048, // Reduced for better performance and stability
    smoothingTimeConstant: 0.3, // Increased for more smoothing
    minDecibels: -80, // Less sensitive to avoid noise
    maxDecibels: -20, // Better dynamic range
  },
};

// Memoized normalization function to avoid recreating on each render
const normalizeDb = (value: number) => {
  if (value === -Infinity) return 0;
  const minDb = -80; // Less sensitive floor to reduce noise
  const maxDb = -20; // Adjusted ceiling for better range
  const db = 1 - (Math.max(minDb, Math.min(maxDb, value)) * -1) / 60; // Adjusted denominator
  return db ** 0.7; // Apply stronger power curve for better control
};

/**
 * Hook for tracking volume across multiple frequency bands
 * @param mediaStream - The MediaStream to analyze
 * @param options - Multiband options
 * @returns Array of volume levels for each frequency band
 */
export function useMultibandVolume(
  mediaStream?: MediaStream | null,
  options: MultiBandVolumeOptions = {},
) {
  const opts = useMemo(
    () => ({ ...multibandDefaults, ...options }),
    [
      options.bands,
      options.loPass,
      options.hiPass,
      options.updateInterval,
      options.analyserOptions?.fftSize,
      options.analyserOptions?.smoothingTimeConstant,
      options.analyserOptions?.minDecibels,
      options.analyserOptions?.maxDecibels,
    ],
  );

  const [frequencyBands, setFrequencyBands] = useState<number[]>(() =>
    new Array(opts.bands).fill(0),
  );
  const bandsRef = useRef<number[]>(new Array(opts.bands).fill(0));
  const frameId = useRef<number | undefined>(undefined);
  const lastActivityTime = useRef<number>(Date.now());

  useEffect(() => {
    if (!mediaStream) {
      const emptyBands = new Array(opts.bands).fill(0);
      setFrequencyBands(emptyBands);
      bandsRef.current = emptyBands;
      return;
    }

    const { analyser, audioContext, cleanup } = createAudioAnalyser(
      mediaStream,
      opts.analyserOptions,
    );

    const bufferLength = analyser.frequencyBinCount;
    const dataArray = new Float32Array(bufferLength);

    // Calculate frequency range for better distribution across all bars
    const nyquist = audioContext.sampleRate / 2;
    const sliceStart = Math.floor((opts.loPass! / nyquist) * bufferLength);
    const sliceEnd = Math.floor((opts.hiPass! / nyquist) * bufferLength);
    const sliceLength = sliceEnd - sliceStart;
    const chunkSize = Math.ceil(sliceLength / opts.bands!);

    let lastUpdate = 0;
    const updateInterval = opts.updateInterval!;

    const updateVolume = (timestamp: number) => {
      if (timestamp - lastUpdate >= updateInterval) {
        analyser.getFloatFrequencyData(dataArray);

        // Process directly without creating intermediate arrays
        const chunks = new Array(opts.bands!);
        let hasAnyActivity = false;

        for (let i = 0; i < opts.bands!; i++) {
          let sum = 0;
          let count = 0;
          const startIdx = sliceStart + i * chunkSize;
          const endIdx = Math.min(sliceStart + (i + 1) * chunkSize, sliceEnd);

          for (let j = startIdx; j < endIdx; j++) {
            sum += normalizeDb(dataArray[j]);
            count++;
          }

          chunks[i] = count > 0 ? sum / count : 0;

          // Check for any significant activity
          if (chunks[i] > 0.02) {
            hasAnyActivity = true;
          }
        }

        // Update last activity time if there's activity
        if (hasAnyActivity) {
          lastActivityTime.current = timestamp;
        }

        // Apply decay if no activity for a while
        const timeSinceActivity = timestamp - lastActivityTime.current;
        if (timeSinceActivity > 200) {
          // 200ms of silence before decay starts
          const decayFactor = Math.max(0, 1 - (timeSinceActivity - 200) / 1000); // Decay over 1 second
          for (let i = 0; i < chunks.length; i++) {
            chunks[i] = Math.max(0, chunks[i] * decayFactor);
          }
        }

        // Only update state if bands changed significantly
        let hasChanged = false;
        for (let i = 0; i < chunks.length; i++) {
          if (Math.abs(chunks[i] - bandsRef.current[i]) > 0.01) {
            // Increased threshold for more stability
            hasChanged = true;
            break;
          }
        }

        if (hasChanged) {
          bandsRef.current = chunks;
          setFrequencyBands(chunks);
        }

        lastUpdate = timestamp;
      }

      frameId.current = requestAnimationFrame(updateVolume);
    };

    frameId.current = requestAnimationFrame(updateVolume);

    return () => {
      cleanup();
      if (frameId.current) {
        cancelAnimationFrame(frameId.current);
      }
    };
  }, [mediaStream, opts]);

  return frequencyBands;
}

type AnimationState =
  | "connecting"
  | "initializing"
  | "listening"
  | "speaking"
  | "thinking"
  | undefined;

export const useBarAnimator = (
  state: AnimationState,
  columns: number,
  interval: number,
): number[] => {
  const indexRef = useRef(0);
  const [currentFrame, setCurrentFrame] = useState<number[]>([]);
  const animationFrameId = useRef<number | null>(null);

  // Memoize sequence generation
  const sequence = useMemo(() => {
    if (state === "thinking" || state === "listening") {
      return generateListeningSequenceBar(columns);
    } else if (state === "connecting" || state === "initializing") {
      return generateConnectingSequenceBar(columns);
    } else if (state === undefined) {
      return [new Array(columns).fill(0).map((_, idx) => idx)];
    } else if (state === "speaking") {
      // For speaking state, return empty array to disable highlight animation
      // and let the audio data drive the visualization
      return [[]];
    } else {
      return [[]];
    }
  }, [state, columns]);

  useEffect(() => {
    indexRef.current = 0;
    setCurrentFrame(sequence[0] || []);
  }, [sequence]);

  useEffect(() => {
    let startTime = performance.now();

    const animate = (time: DOMHighResTimeStamp) => {
      const timeElapsed = time - startTime;

      if (timeElapsed >= interval) {
        indexRef.current = (indexRef.current + 1) % sequence.length;
        setCurrentFrame(sequence[indexRef.current] || []);
        startTime = time;
      }

      animationFrameId.current = requestAnimationFrame(animate);
    };

    animationFrameId.current = requestAnimationFrame(animate);

    return () => {
      if (animationFrameId.current !== null) {
        cancelAnimationFrame(animationFrameId.current);
      }
    };
  }, [interval, sequence]);

  return currentFrame;
};

// Memoize sequence generators
const generateConnectingSequenceBar = (columns: number): number[][] => {
  const seq = [];
  for (let x = 0; x < columns; x++) {
    seq.push([x, columns - 1 - x]);
  }
  return seq;
};

const generateListeningSequenceBar = (columns: number): number[][] => {
  // Create a sequence where all bars blink together for thinking state
  const allBars = Array.from({ length: columns }, (_, i) => i);
  const noBars: number[] = [];
  return [allBars, noBars];
};

export type AgentState =
  | "connecting"
  | "initializing"
  | "listening"
  | "speaking"
  | "thinking";

export interface BarVisualizerProps
  extends React.HTMLAttributes<HTMLDivElement> {
  /** Voice assistant state */
  state?: AgentState;
  /** Number of bars to display */
  barCount?: number;
  /** Audio source */
  mediaStream?: MediaStream | null;
  /** Min/max height as percentage */
  minHeight?: number;
  maxHeight?: number;
  /** Enable demo mode with fake audio data */
  demo?: boolean;
  /** Align bars from center instead of bottom */
  centerAlign?: boolean;
}

const BarVisualizerComponent = React.forwardRef<
  HTMLDivElement,
  BarVisualizerProps
>(
  (
    {
      state,
      barCount = 15,
      mediaStream,
      minHeight = 40,
      maxHeight = 150,
      demo = false,
      centerAlign = false,
      className,
      ...props
    },
    ref,
  ) => {
    // Audio processing
    const realVolumeBands = useMultibandVolume(mediaStream, {
      bands: barCount, // Use the actual bar count, not the default 5
      loPass: 20, // Much lower frequency to capture more bass
      hiPass: 1000, // Higher frequency to capture full speech range
      updateInterval: 50, // Slower updates for more stability
      analyserOptions: {
        fftSize: 2048, // Reduced for better performance and stability
        smoothingTimeConstant: 0.3, // Increased for more smoothing
        minDecibels: -80, // Less sensitive to avoid noise
        maxDecibels: -20, // Better dynamic range
      },
    });

    // Generate fake volume data for demo mode using refs to avoid state updates
    const fakeVolumeBandsRef = useRef<number[]>(new Array(barCount).fill(0.1));
    const [fakeVolumeBands, setFakeVolumeBands] = useState<number[]>(() =>
      new Array(barCount).fill(0.1),
    );
    const fakeAnimationRef = useRef<number | undefined>(undefined);

    // Animate fake volume bands for speaking and listening states
    useEffect(() => {
      if (!demo) return;

      if (state !== "speaking" && state !== "listening") {
        const bands = new Array(barCount).fill(0.02); // Much smaller idle values
        fakeVolumeBandsRef.current = bands;
        setFakeVolumeBands(bands);
        return;
      }

      let lastUpdate = 0;
      const updateInterval = state === "speaking" ? 30 : 50; // Faster updates for speaking
      const startTime = Date.now() / 1000;

      const updateFakeVolume = (timestamp: number) => {
        if (timestamp - lastUpdate >= updateInterval) {
          const time = Date.now() / 1000 - startTime;
          const newBands = new Array(barCount);

          for (let i = 0; i < barCount; i++) {
            if (state === "speaking") {
              // More dynamic animation for speaking - reduced amplitude
              const waveOffset = i * 0.3;
              const frequency = 3 + Math.sin(time * 0.5) * 1.5; // Variable frequency
              const baseVolume =
                Math.sin(time * frequency + waveOffset) * 0.2 + 0.3; // Reduced amplitude
              const randomNoise = Math.random() * 0.1; // Reduced noise
              newBands[i] = Math.max(
                0.05,
                Math.min(0.6, baseVolume + randomNoise), // Reduced max
              );
            } else {
              // Original listening animation - reduced amplitude
              const waveOffset = i * 0.5;
              const baseVolume = Math.sin(time * 2 + waveOffset) * 0.15 + 0.25; // Reduced amplitude
              const randomNoise = Math.random() * 0.1; // Reduced noise
              newBands[i] = Math.max(
                0.05,
                Math.min(0.5, baseVolume + randomNoise), // Reduced max
              );
            }
          }

          // Only update if values changed significantly
          let hasChanged = false;
          for (let i = 0; i < barCount; i++) {
            if (Math.abs(newBands[i] - fakeVolumeBandsRef.current[i]) > 0.02) {
              // Reduced threshold for demo mode too
              hasChanged = true;
              break;
            }
          }

          if (hasChanged) {
            fakeVolumeBandsRef.current = newBands;
            setFakeVolumeBands(newBands);
          }

          lastUpdate = timestamp;
        }

        fakeAnimationRef.current = requestAnimationFrame(updateFakeVolume);
      };

      fakeAnimationRef.current = requestAnimationFrame(updateFakeVolume);

      return () => {
        if (fakeAnimationRef.current) {
          cancelAnimationFrame(fakeAnimationRef.current);
        }
      };
    }, [demo, state, barCount]);

    // Use fake or real volume data based on demo mode
    const volumeBands = useMemo(
      () => (demo ? fakeVolumeBands : realVolumeBands),
      [demo, fakeVolumeBands, realVolumeBands],
    );

    // Animation sequencing
    const highlightedIndices = useBarAnimator(
      state,
      barCount,
      state === "connecting"
        ? 2000 / barCount
        : state === "thinking"
          ? 150
          : state === "listening"
            ? 500
            : 1000,
    );

    return (
      <div
        ref={ref}
        data-state={state}
        className={cn(
          "relative flex justify-center gap-1.5",
          centerAlign ? "items-center" : "items-center",
          "bg-muted/30 w-full overflow-hidden rounded-b-full",
          className,
        )}
        {...props}
      >
        {volumeBands.map((volume, index) => {
          // Improved amplification with better stability and smaller heights
          const amplifiedVolume = volume > 0.01 ? volume ** 0.6 * 1.8 : 0;
          const heightPct = Math.min(
            maxHeight,
            Math.max(15, amplifiedVolume * 60 + 5),
          );
          const isHighlighted = highlightedIndices?.includes(index) ?? false;

          return (
            <Bar
              key={`bar-${index}-${volume}`}
              heightPct={heightPct}
              isHighlighted={isHighlighted}
              state={state}
            />
          );
        })}
      </div>
    );
  },
);

// Memoized Bar component to prevent unnecessary re-renders
const Bar = React.memo<{
  heightPct: number;
  isHighlighted: boolean;
  state?: AgentState;
}>(({ heightPct, isHighlighted, state }) => {
  const barRef = useRef<HTMLDivElement>(null);
  const targetHeightRef = useRef(heightPct);
  const currentHeightRef = useRef(heightPct);
  const animationFrameRef = useRef<number | null>(null);

  useEffect(() => {
    targetHeightRef.current = heightPct;

    const animateHeight = () => {
      const difference = targetHeightRef.current - currentHeightRef.current;

      // Apply smooth interpolation with decay
      if (Math.abs(difference) > 0.1) {
        currentHeightRef.current += difference * 0.15; // Smooth interpolation factor

        if (barRef.current) {
          barRef.current.style.height = `${Math.max(2, currentHeightRef.current)}%`;
        }

        animationFrameRef.current = requestAnimationFrame(animateHeight);
      } else {
        // Snap to target when close enough
        currentHeightRef.current = targetHeightRef.current;
        if (barRef.current) {
          barRef.current.style.height = `${Math.max(8, currentHeightRef.current)}%`;
        }
      }
    };

    animateHeight();

    return () => {
      if (animationFrameRef.current) {
        cancelAnimationFrame(animationFrameRef.current);
      }
    };
  }, [heightPct]);

  return (
    <div
      ref={barRef}
      data-highlighted={isHighlighted}
      data-state={state}
      className={cn(
        "max-w-[10px] min-w-[6px] flex-1 transition-colors duration-200",
        "bg-muted/30 rounded-full !bg-primary shadow-sm shadow-primary/20",
        state === "thinking" &&
          isHighlighted &&
          "animate-pulse !bg-blue-500/80",
      )}
    />
  );
});

Bar.displayName = "Bar";

// Wrap the main component with React.memo for prop comparison optimization
const BarVisualizer = React.memo(
  BarVisualizerComponent,
  (prevProps, nextProps) => {
    return (
      prevProps.state === nextProps.state &&
      prevProps.barCount === nextProps.barCount &&
      prevProps.mediaStream === nextProps.mediaStream &&
      prevProps.minHeight === nextProps.minHeight &&
      prevProps.maxHeight === nextProps.maxHeight &&
      prevProps.demo === nextProps.demo &&
      prevProps.centerAlign === nextProps.centerAlign &&
      prevProps.className === nextProps.className &&
      JSON.stringify(prevProps.style) === JSON.stringify(nextProps.style)
    );
  },
);

BarVisualizerComponent.displayName = "BarVisualizerComponent";
BarVisualizer.displayName = "BarVisualizer";

export { BarVisualizer };
