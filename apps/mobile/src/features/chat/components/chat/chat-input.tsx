import { PressableFeedback } from "heroui-native";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  Animated,
  type GestureResponderEvent,
  PanResponder,
  Text,
  TextInput,
  View,
} from "react-native";
import { Call02Icon, PlusSignIcon, SentIcon } from "@/components/icons";
import { haptics } from "@/lib/haptics";
import {
  RecordingWaveform,
  useVoiceRecorder,
  VOICE_CANCEL_THRESHOLD,
} from "./voice-recorder";

interface ChatInputProps {
  placeholder?: string;
  onSubmit?: (value: string) => void;
  onAudioRecorded?: (uri: string, durationMs: number) => void;
  disabled?: boolean;
}

function formatElapsed(ms: number): string {
  const totalSec = Math.floor(ms / 1000);
  const min = Math.floor(totalSec / 60);
  const sec = totalSec % 60;
  return `${min}:${String(sec).padStart(2, "0")}`;
}

export function ChatInput({
  placeholder = "What can I do for you today?",
  onSubmit,
  onAudioRecorded,
  disabled,
}: ChatInputProps) {
  const [value, setValue] = useState("");
  const scaleAnim = useRef(new Animated.Value(0.9)).current;

  const canSubmit = value.trim().length > 0;

  const handleAudioRecorded = useCallback(
    (uri: string, durationMs: number) => {
      onAudioRecorded?.(uri, durationMs);
    },
    [onAudioRecorded],
  );

  const handleCancel = useCallback(() => {}, []);

  const { startRecording, stopAndSend, cancelRecording, updateDragX, state } =
    useVoiceRecorder({
      onRecordingComplete: handleAudioRecorded,
      onCancel: handleCancel,
    });

  const panResponder = useRef(
    PanResponder.create({
      onStartShouldSetPanResponder: () => true,
      onMoveShouldSetPanResponder: () => true,
      onPanResponderGrant: (_evt: GestureResponderEvent) => {
        void startRecording();
      },
      onPanResponderMove: (
        _evt: GestureResponderEvent,
        gestureState: { dx: number },
      ) => {
        updateDragX(gestureState.dx);
      },
      onPanResponderRelease: (
        _evt: GestureResponderEvent,
        gestureState: { dx: number },
      ) => {
        if (Math.min(0, gestureState.dx) < VOICE_CANCEL_THRESHOLD) {
          void cancelRecording();
        } else {
          void stopAndSend();
        }
      },
      onPanResponderTerminate: () => {
        void cancelRecording();
      },
    }),
  ).current;

  useEffect(() => {
    Animated.spring(scaleAnim, {
      toValue: canSubmit ? 1 : 0.9,
      useNativeDriver: true,
    }).start();
  }, [canSubmit, scaleAnim]);

  const handleSend = () => {
    if (!canSubmit) return;
    void haptics.medium();
    onSubmit?.(value.trim());
    setValue("");
  };

  const showMic = !canSubmit && !state.isRecording;

  return (
    <View className="flex-row items-end rounded-3xl bg-surface-2 px-3 py-2 border border-border/10 shadow-lg">
      {!state.isRecording && (
        <PressableFeedback onPress={() => {}}>
          <View className="h-10 w-10 items-center justify-center rounded-full">
            <PlusSignIcon size={20} color="#8e8e93" />
          </View>
        </PressableFeedback>
      )}

      {state.isRecording ? (
        <View
          style={{
            flex: 1,
            flexDirection: "row",
            alignItems: "center",
            gap: 8,
            paddingHorizontal: 4,
          }}
        >
          <View
            style={{
              width: 8,
              height: 8,
              borderRadius: 4,
              backgroundColor: state.isCancelling ? "#71717a" : "#ef4444",
            }}
          />
          <RecordingWaveform isCancelling={state.isCancelling} />
          <Text
            style={{
              fontSize: 13,
              color: state.isCancelling ? "#71717a" : "#e4e4e7",
              marginLeft: 4,
            }}
          >
            {formatElapsed(state.elapsedMs)}
          </Text>
          <Text
            style={{
              fontSize: 11,
              color: "#52525b",
              flex: 1,
              textAlign: "right",
            }}
          >
            {state.isCancelling ? "Release to cancel" : "Slide left to cancel"}
          </Text>
        </View>
      ) : (
        <TextInput
          value={value}
          onChangeText={setValue}
          placeholder={placeholder}
          placeholderTextColor="#666666"
          multiline
          editable={!disabled}
          className="flex-1 text-base leading-6 text-foreground px-2 py-2 max-h-32"
          style={{ textAlignVertical: "bottom" }}
        />
      )}

      {showMic ? (
        <View
          style={{
            height: 36,
            width: 36,
            borderRadius: 18,
            backgroundColor: "rgba(255,255,255,0.06)",
            alignItems: "center",
            justifyContent: "center",
            marginBottom: 2,
          }}
          {...panResponder.panHandlers}
        >
          <Call02Icon size={18} color="#8e8e93" />
        </View>
      ) : !state.isRecording ? (
        <Animated.View
          style={{
            transform: [{ scale: scaleAnim }],
            opacity: canSubmit ? 1 : 0.4,
          }}
          className="pb-0.5"
        >
          <PressableFeedback onPress={handleSend} isDisabled={!canSubmit}>
            <View
              className={`h-9 w-9 rounded-full items-center justify-center ${canSubmit ? "bg-accent" : "bg-surface-3"}`}
            >
              <SentIcon size={18} color={canSubmit ? "#000000" : "#666666"} />
            </View>
          </PressableFeedback>
        </Animated.View>
      ) : null}
    </View>
  );
}
