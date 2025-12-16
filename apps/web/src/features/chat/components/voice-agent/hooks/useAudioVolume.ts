import type { TrackReference } from "@livekit/components-react";
import { useEffect, useRef, useState } from "react";

/**
 * Hook to extract audio volume from a livekit track reference for use with the Orb component
 * Returns normalized volume values between 0 and 1
 */
export function useAudioVolume(audioTrack?: TrackReference) {
  const [inputVolume, setInputVolume] = useState(0);
  const [outputVolume, setOutputVolume] = useState(0);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const dataArrayRef = useRef<Uint8Array | null>(null);
  const animationFrameRef = useRef<number | undefined>(undefined);

  useEffect(() => {
    if (!audioTrack?.publication?.track) {
      setInputVolume(0);
      setOutputVolume(0);
      return;
    }

    const track = audioTrack.publication.track;

    // Create audio context and analyser
    const audioContext = new AudioContext();
    const source = audioContext.createMediaStreamSource(
      new MediaStream([track.mediaStreamTrack]),
    );
    const analyser = audioContext.createAnalyser();

    analyser.fftSize = 256;
    analyser.smoothingTimeConstant = 0.8;
    source.connect(analyser);

    const bufferLength = analyser.frequencyBinCount;
    const dataArray = new Uint8Array(bufferLength);

    analyserRef.current = analyser;
    dataArrayRef.current = dataArray;

    const updateVolume = () => {
      if (!analyserRef.current || !dataArrayRef.current) return;

      const frequencyData = new Uint8Array(
        analyserRef.current.frequencyBinCount,
      );
      analyserRef.current.getByteFrequencyData(frequencyData);

      // Calculate RMS (Root Mean Square) for volume
      let sum = 0;
      for (let i = 0; i < frequencyData.length; i++) {
        const value = frequencyData[i] / 255;
        sum += value * value;
      }

      const rms = Math.sqrt(sum / frequencyData.length);
      const normalizedVolume = Math.min(1, Math.max(0, rms * 2)); // Amplify and clamp

      // For simplicity, we'll use the same volume for both input and output
      // In a real scenario, you might want to distinguish between speaker/microphone tracks
      setInputVolume(normalizedVolume);
      setOutputVolume(normalizedVolume);

      animationFrameRef.current = requestAnimationFrame(updateVolume);
    };

    updateVolume();

    return () => {
      if (animationFrameRef.current) {
        cancelAnimationFrame(animationFrameRef.current);
      }
      audioContext.close();
    };
  }, [audioTrack]);

  return {
    getInputVolume: () => inputVolume,
    getOutputVolume: () => outputVolume,
    inputVolume,
    outputVolume,
  };
}
