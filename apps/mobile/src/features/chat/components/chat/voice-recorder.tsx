import { Audio } from "expo-av";
import * as Haptics from "expo-haptics";
import { Surface } from "heroui-native";
import { useCallback, useEffect, useRef, useState } from "react";
import { Animated, Easing } from "react-native";

export interface VoiceRecorderState {
  isRecording: boolean;
  isCancelling: boolean;
  elapsedMs: number;
  dragX: number;
}

export interface VoiceRecorderControls {
  startRecording: () => Promise<void>;
  stopAndSend: () => Promise<void>;
  cancelRecording: () => Promise<void>;
  updateDragX: (x: number) => void;
  state: VoiceRecorderState;
}

interface VoiceRecorderProps {
  onRecordingComplete: (uri: string, durationMs: number) => void;
  onCancel: () => void;
  onRecordingStart?: () => void;
}

const CANCEL_THRESHOLD = -80;

function _WaveformBar({ delay }: { delay: number }) {
  const heightAnim = useRef(new Animated.Value(4)).current;

  useEffect(() => {
    const loop = Animated.loop(
      Animated.sequence([
        Animated.timing(heightAnim, {
          toValue: 8 + Math.random() * 16,
          duration: 250 + Math.random() * 200,
          easing: Easing.inOut(Easing.ease),
          useNativeDriver: false,
          delay,
        }),
        Animated.timing(heightAnim, {
          toValue: 4,
          duration: 250 + Math.random() * 200,
          easing: Easing.inOut(Easing.ease),
          useNativeDriver: false,
        }),
      ]),
    );
    loop.start();
    return () => loop.stop();
  }, [heightAnim, delay]);

  return (
    <Animated.View
      style={{
        width: 3,
        borderRadius: 2,
        backgroundColor: "#ef4444",
        height: heightAnim,
        alignSelf: "center",
      }}
    />
  );
}

export function RecordingWaveform({ isCancelling }: { isCancelling: boolean }) {
  return (
    <Surface
      style={{
        flexDirection: "row",
        alignItems: "center",
        gap: 3,
        height: 28,
        backgroundColor: "transparent",
      }}
    >
      {[0, 60, 120, 180, 240, 180, 120, 60, 0].map((_delay, i) => (
        <Animated.View
          key={i}
          style={{
            width: 3,
            borderRadius: 2,
            backgroundColor: isCancelling ? "#52525b" : "#ef4444",
            height: 4 + (i % 3) * 8,
            alignSelf: "center",
          }}
        />
      ))}
    </Surface>
  );
}

export function useVoiceRecorder({
  onRecordingComplete,
  onCancel,
  onRecordingStart,
}: VoiceRecorderProps): VoiceRecorderControls {
  const [isRecording, setIsRecording] = useState(false);
  const [isCancelling, setIsCancelling] = useState(false);
  const [elapsedMs, setElapsedMs] = useState(0);
  const [dragX, setDragX] = useState(0);

  const recordingRef = useRef<Audio.Recording | null>(null);
  const startTimeRef = useRef<number>(0);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const cancelledRef = useRef(false);

  const stopTimer = useCallback(() => {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const startRecording = useCallback(async () => {
    try {
      const { granted } = await Audio.requestPermissionsAsync();
      if (!granted) return;

      await Audio.setAudioModeAsync({
        allowsRecordingIOS: true,
        playsInSilentModeIOS: true,
      });

      const { recording } = await Audio.Recording.createAsync(
        Audio.RecordingOptionsPresets.HIGH_QUALITY,
      );
      recordingRef.current = recording;
      cancelledRef.current = false;
      startTimeRef.current = Date.now();
      setIsRecording(true);
      setIsCancelling(false);
      setElapsedMs(0);
      setDragX(0);
      onRecordingStart?.();

      void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);

      timerRef.current = setInterval(() => {
        setElapsedMs(Date.now() - startTimeRef.current);
      }, 100);
    } catch {
      setIsRecording(false);
    }
  }, [onRecordingStart]);

  const stopAndSend = useCallback(async () => {
    stopTimer();
    const recording = recordingRef.current;
    if (!recording) return;
    recordingRef.current = null;

    try {
      await recording.stopAndUnloadAsync();
      if (cancelledRef.current) return;

      const uri = recording.getURI();
      if (uri) {
        const duration = Date.now() - startTimeRef.current;
        void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
        onRecordingComplete(uri, duration);
      }
    } catch {
      // silently ignore stop errors
    } finally {
      setIsRecording(false);
      setIsCancelling(false);
      setElapsedMs(0);
      setDragX(0);
    }
  }, [stopTimer, onRecordingComplete]);

  const cancelRecording = useCallback(async () => {
    stopTimer();
    cancelledRef.current = true;
    const recording = recordingRef.current;
    recordingRef.current = null;
    setIsRecording(false);
    setIsCancelling(false);
    setElapsedMs(0);
    setDragX(0);

    if (recording) {
      try {
        await recording.stopAndUnloadAsync();
      } catch {
        // silently ignore
      }
    }

    void Haptics.notificationAsync(Haptics.NotificationFeedbackType.Warning);
    onCancel();
  }, [stopTimer, onCancel]);

  const updateDragX = useCallback((x: number) => {
    const clamped = Math.min(0, x);
    setDragX(clamped);
    setIsCancelling(clamped < CANCEL_THRESHOLD);
  }, []);

  useEffect(() => {
    return () => {
      stopTimer();
      if (recordingRef.current) {
        recordingRef.current.stopAndUnloadAsync().catch(() => {});
      }
    };
  }, [stopTimer]);

  return {
    startRecording,
    stopAndSend,
    cancelRecording,
    updateDragX,
    state: { isRecording, isCancelling, elapsedMs, dragX },
  };
}

export const VOICE_CANCEL_THRESHOLD = CANCEL_THRESHOLD;
